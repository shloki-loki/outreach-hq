"""Failures seen in production: a hung inbox read, writes lost to a concurrent sync, keys in logs."""

from __future__ import annotations

import imaplib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

os.environ["OUTREACH_NO_GIT"] = "1"

from outreach import emailfinder, llm, mailbox, research, send, store  # noqa: E402
from outreach.util import ROOT, HttpError, redact  # noqa: E402


class ImapTimeout(unittest.TestCase):
    def test_a_silent_server_cannot_hang_any_imap_call(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen()
        self.addCleanup(server.close)
        connect, port = imaplib.IMAP4_SSL.__init__, server.getsockname()[1]

        def local(client, host="", _port=993, **options):
            self.assertEqual(options.get("timeout"), 0.5)  # fail here, rather than hang, if it is dropped again
            connect(client, "127.0.0.1", port, **options)

        box = mailbox.Mailbox("a@example.invalid", "x", "n")
        calls = (lambda: mailbox.scan_inbox(box, date(2026, 11, 1), set(), set()),
                 lambda: mailbox.in_sent_folder(box, "<x@example.invalid>"),
                 lambda: mailbox._imap(box))
        with mock.patch.object(mailbox, "IMAP_TIMEOUT", 0.5), mock.patch.object(imaplib.IMAP4_SSL, "__init__", local):
            for call in calls:
                started = time.monotonic()
                with self.assertRaises(OSError):
                    call()
                self.assertLess(time.monotonic() - started, 5)


class LockedSync(unittest.TestCase):
    def test_a_sync_from_another_process_cannot_undo_a_claim(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)

        def git(*args, cwd=base):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                                  cwd=cwd, capture_output=True, text=True, check=True).stdout

        git("init", "-q", "--bare", "origin.git")
        git("init", "-q", "-b", "data", "seed")
        (base / "seed/messages.json").write_text('{"messages": [{"id": "M1", "status": "approved"}]}')
        git("add", "-A", cwd=base / "seed")
        git("commit", "-qm", "seed", cwd=base / "seed")
        git("push", "-q", str(base / "origin.git"), "data", cwd=base / "seed")
        git("clone", "-q", "-b", "data", "origin.git", "data")

        env = {**os.environ, "OUTREACH_DATA_DIR": str(base / "data"), "OUTREACH_NO_GIT": "0"}
        save, others = store.save, []

        def save_then_race(name, value):
            save(name, value)
            other = subprocess.Popen([sys.executable, "-c", "from outreach import store; store.sync()"], cwd=ROOT, env=env)
            others.append(other)
            try:
                other.wait(3)  # without the lock it finishes here and wipes what was just saved
            except subprocess.TimeoutExpired:
                pass

        with mock.patch.dict(os.environ, {"OUTREACH_NO_GIT": "0"}), mock.patch.object(store, "DATA_DIR", base / "data"), \
                mock.patch.object(store, "save", save_then_race):
            self.assertTrue(send.claim("M1", "<x@example.invalid>"))
        for other in others:
            self.assertEqual(other.wait(30), 0)
        saved = json.loads(git("show", "data:messages.json", cwd=base / "origin.git"))["messages"][0]
        self.assertEqual(saved["status"], "sending")


class FetchRetry(unittest.TestCase):
    def test_a_failed_fetch_is_tried_three_times_and_then_raises(self):
        error = subprocess.CalledProcessError(128, "git")
        with mock.patch.object(store.time, "sleep"):
            with mock.patch.object(store, "_git", side_effect=[error, error, None]) as git:
                store._fetch()
                self.assertEqual(git.call_count, 3)
            with mock.patch.object(store, "_git", side_effect=error), self.assertRaises(subprocess.CalledProcessError):
                store._fetch()

    def test_no_answer_is_not_retried(self):
        with mock.patch.object(store, "_git", side_effect=store.StoreOffline("offline")) as git:
            with self.assertRaises(store.StoreOffline):
                store._fetch()
            self.assertEqual(git.call_count, 1)


class Secrets(unittest.TestCase):
    def test_keys_in_urls_are_masked(self):
        for param in ("key", "api_key", "apikey", "token"):
            text = str(HttpError(401, f"https://x.test/v?email=a%40b.in&{param}=FAKE123%23+note&mode=power"))
            self.assertNotIn("FAKE123", text)
            self.assertIn("mode=power", text)
        self.assertEqual(redact("monkey=banana"), "monkey=banana")
        self.assertEqual(redact("key=[masked]"), "key=[masked]")

    def test_issues_and_journal_never_store_a_key(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(store, "DATA_DIR", Path(folder) / "data"):
            store.open_issue("test", "failed", "see https://x.test/v?key=FAKE123")
            store.log_entry("test", "note", "failed", "see https://x.test/v?api_key=FAKE456")
            saved = "".join(p.read_text() for p in (Path(folder) / "data").glob("*.json"))
        self.assertNotIn("FAKE", saved)

    def test_a_comment_pasted_with_a_key_is_ignored(self):
        quota = emailfinder.Quota.__new__(emailfinder.Quota)
        quota.cfg = {"p": {"env": "TEST_PROVIDER_KEY"}}
        for raw, want in (("FAKE++++      # p: free credits", "FAKE++++"), ("      # p: free credits", None),
                          ("", None), ("FAKE", "FAKE"), ("FA#KE", "FA#KE")):
            with mock.patch.dict(os.environ, {"TEST_PROVIDER_KEY": raw}):
                self.assertEqual(quota.key("p"), want)


class ResearchFlag(unittest.TestCase):
    def ran_ok(self, errors: int, fine: int):
        outcomes = [llm.LlmError("Gemini HTTP 503")] * errors + [{"skip": "login wall"}] * fine
        with mock.patch.object(research.store, "sync"), mock.patch.object(llm, "key", return_value="k"), \
                mock.patch.object(research, "pick_models", return_value={}), \
                mock.patch.object(research, "queue", return_value=[{"id": f"L{i}"} for i in range(len(outcomes))]), \
                mock.patch.object(research, "research_one", side_effect=outcomes), \
                mock.patch.object(research, "_note_attempt"), mock.patch.object(research.store, "log_run") as log:
            research.run()
        return log.call_args[0][1], log.call_args[0][2]

    def test_a_few_busy_model_errors_do_not_fail_the_run_but_are_shown(self):
        ok, summary = self.ran_ok(2, 38)
        self.assertTrue(ok)
        self.assertIn("2 errors (first: Gemini HTTP 503)", summary)

    def test_many_errors_still_fail_the_run(self):
        self.assertFalse(self.ran_ok(10, 30)[0])
        self.assertFalse(self.ran_ok(3, 0)[0])


if __name__ == "__main__":
    unittest.main()
