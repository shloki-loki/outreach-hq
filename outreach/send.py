"""The sender. It only ever sends messages Shlok approved on the website.

Safety properties:
- One sender at a time (the GitHub workflow is in a concurrency group; locally, the claim below).
- A message is claimed ("sending", with its Message-ID fixed) and published BEFORE the SMTP call.
  If the process dies mid-send the message stays "sending" and is never re-sent silently; the
  tracker later checks Gmail's Sent folder for that Message-ID and settles it.
- Daily caps, a sending window, a pause between sends, the do-not-email list and the limit on
  unverified guesses are all enforced here, whatever the website or an agent queued.
- In dry_run mode nothing is sent.
"""

from __future__ import annotations

import math
import random
import time
from pathlib import Path
from typing import Any

from . import mailbox, store
from .messages import suppressed
from .util import ROOT, load_config, now, now_iso, parse_iso, today

RESUME = ROOT / "assets" / "Shlok_Agrawal_Resume.pdf"
UNVERIFIED = ("guess", "catch-all", "none", None)


def _sent_today(messages: list[dict]) -> list[dict]:
    return [m for m in messages if (m.get("sent_at") or "").startswith(today()) and m.get("status") in ("sent", "replied", "bounced")]


def in_window(settings: dict) -> bool:
    current = now()
    cfg = settings["sending"]
    if current.strftime("%a").lower() not in cfg["send_days"]:
        return False
    return cfg["window_start"] <= current.strftime("%H:%M") <= cfg["window_end"]


def pick_next(settings: dict, sent_this_run: int) -> tuple[dict | None, str]:
    """Choose the next approved message that may go now. Returns (message, reason when none)."""
    cfg = settings["sending"]
    data, leads = store.load("messages"), store.load("leads")
    messages = data["messages"]
    queue = sorted((m for m in messages if m.get("status") == "approved"), key=lambda m: m.get("approved_at") or "")
    if not queue:
        return None, "nothing approved is waiting"
    if sent_this_run >= cfg["max_per_run"]:
        return None, f"run limit of {cfg['max_per_run']} reached; the rest go on the next run"
    done = _sent_today(messages)
    new_done = sum(1 for m in done if m.get("kind") == "cold")
    follow_done = len(done) - new_done
    guess_done = sum(1 for m in done if m.get("kind") == "cold" and m.get("email_status") in UNVERIFIED)
    guess_cap = cfg.get("unverified_per_day", 2)
    speculative_done = sum(1 for m in done if m.get("kind") == "cold" and m.get("speculative"))
    held = ""
    for message in queue:
        lead = store.find(leads["leads"], message["lead_id"]) or {}
        if suppressed(message["to"]):
            held = f"{message['id']}: {message['to']} is on the do-not-email list"
            _hold(message["id"], "skipped", held)
            continue
        if lead.get("replied_at") or lead.get("outcome") in ("rejected", "closed") or lead.get("stage") in ("rejected", "skipped"):
            held = f"{message['id']}: lead replied or closed since approval"
            _hold(message["id"], "skipped", held)
            continue
        contact = store.find(lead.get("contacts", []), message.get("contact_id")) or {}
        if contact.get("email", "").lower() == message["to"].lower() and contact.get("email_status"):
            message["email_status"] = contact["email_status"]  # the grade may have improved since drafting
        if message.get("kind") == "followup2" and settings.get("followups", {}).get("max_followups", 2) < 2:
            held = f"{message['id']}: only one follow-up per person (Shlok, 2026-11-27)"
            _hold(message["id"], "skipped", held)
            continue
        if message["email_status"] in ("bounced", "invalid"):
            held = f"{message['id']}: {message['to']} is now marked {message['email_status']}"
            _hold(message["id"], "skipped", held)
            continue
        if message.get("kind") == "cold":
            if new_done >= cfg["new_emails_per_day"]:
                held = f"daily cap of {cfg['new_emails_per_day']} new emails reached"
                continue
            if message.get("email_status") in UNVERIFIED and guess_done >= guess_cap:
                held = f"daily cap of {guess_cap} unverified addresses reached; verify the address to send more"
                continue
            if message.get("speculative") and speculative_done >= cfg.get("speculative_per_day", 6):
                held = f"daily cap of {cfg.get('speculative_per_day', 6)} speculative notes reached"
                continue
        elif follow_done >= cfg["followups_per_day"]:
            held = f"daily cap of {cfg['followups_per_day']} follow-ups reached"
            continue
        return message, ""
    return None, held or "nothing eligible"


def _hold(message_id: str, status: str, reason: str) -> None:
    def change() -> None:
        data = store.load("messages")
        message = store.find(data["messages"], message_id)
        if message and message.get("status") == "approved":
            message["status"], message["error"] = status, reason
            store.save("messages", data)
    store.transact(change, f"send: {message_id} {status}")


def claim(message_id: str, rfc_id: str, email_status: str | None = None) -> bool:
    """Atomically move approved -> sending. False if someone else got there first."""
    won = {"ok": False}

    def change() -> None:
        won["ok"] = False
        data = store.load("messages")
        message = store.find(data["messages"], message_id)
        if not message or message.get("status") != "approved":
            return
        message.update(status="sending", sending_at=now_iso(), message_id=rfc_id, error=None)
        if email_status:
            message["email_status"] = email_status
        store.save("messages", data)
        won["ok"] = True
    store.transact(change, f"send: claim {message_id}")
    return won["ok"]


def settle(message_id: str, ok: bool, error: str = "") -> None:
    def change() -> None:
        data, leads = store.load("messages"), store.load("leads")
        message = store.find(data["messages"], message_id)
        if not message or message.get("status") != "sending":
            return
        lead = store.find(leads["leads"], message["lead_id"])
        if ok:
            message.update(status="sent", sent_at=now_iso(), error=None)
            if lead:
                lead["first_contacted_at"] = lead.get("first_contacted_at") or now_iso()
                lead["followup"] = {"due": False, "kind": None, "since": None}
                store.add_timeline(lead, "send-track", "sent", f"{message['kind']} email to {message['to_name'] or message['to']}")
        else:
            message.update(status="failed", error=error)
            if lead:
                store.add_timeline(lead, "send-track", "send_failed", error[:200])
        store.save("messages", data)
        store.save("leads", leads)
    store.transact(change, f"send: {message_id} {'sent' if ok else 'failed'}")


def compose_body(message: dict, settings: dict) -> str:
    """A cold email swaps its closing first-name line for the full signature; follow-ups stay short."""
    body = message["body"].rstrip()
    if message.get("kind") != "cold":
        return body + "\n"
    first = load_config("profile")["person"]["first_name"]
    lines = body.splitlines()
    if lines and lines[-1].strip() == first:
        lines = lines[:-1]
    return "\n".join(lines).rstrip() + "\n\n" + settings["signature"]["text"].strip() + "\n"


def run() -> dict[str, Any]:
    settings = load_config("settings")
    store.sync()
    summary: dict[str, Any] = {"mode": settings["mode"], "sent": [], "failed": [], "note": ""}
    waiting = [m for m in store.load("messages")["messages"] if m.get("status") == "approved"]
    if not waiting:
        summary["note"] = "nothing approved is waiting"
        return summary
    if settings["mode"] != "live":
        summary["note"] = (f"dry_run: {len(waiting)} approved email(s) would be sent. Nothing was sent. "
                           f"Set mode = \"live\" in config/settings.toml to send.")
        summary["would_send"] = [f"{m['id']} -> {m['to']} | {m['subject']}" for m in waiting]
        store.log_run("send-track/send", True, summary["note"])
        return summary
    if not in_window(settings):
        summary["note"] = f"outside the sending window; {len(waiting)} approved email(s) wait for the next run"
        store.log_run("send-track/send", True, summary["note"])
        return summary
    try:
        box = mailbox.from_env(load_config("profile")["person"]["name"])
    except mailbox.NotConfigured as exc:
        summary["note"] = str(exc)
        store.open_issue("send-track", "Gmail is not connected", "Approved emails are waiting but GMAIL_ADDRESS / "
                         "GMAIL_APP_PASSWORD are not set where the sender runs. See SETUP.md step 3.",
                         severity="error", key="gmail-not-configured")
        return summary

    while True:
        message, reason = pick_next(settings, len(summary["sent"]) + len(summary["failed"]))
        if not message:
            summary["note"] = reason
            break
        rfc_id = mailbox.new_message_id(box)
        if not claim(message["id"], rfc_id, message.get("email_status")):
            continue
        try:
            attachment: Path | None = RESUME if message.get("attach_resume") and RESUME.exists() else None
            mail = mailbox.build(box, message["to"], message["subject"], compose_body(message, settings),
                                 message_id=rfc_id, to_name=message.get("to_name") or "",
                                 in_reply_to=message.get("thread_parent"), attachment=attachment)
            mailbox.send(box, mail)
        except Exception as exc:  # the claim stays visible as a failure; never retried silently
            settle(message["id"], False, f"{type(exc).__name__}: {exc}")
            summary["failed"].append(message["id"])
            store.open_issue("send-track", f"Sending {message['id']} failed", f"{type(exc).__name__}: {exc}",
                             severity="error", key=f"send-failed:{message['id']}")
            if "auth" in str(exc).lower() or "535" in str(exc):
                break  # bad credentials: stop, do not hammer Gmail
            continue
        settle(message["id"], True)
        summary["sent"].append(f"{message['id']} -> {message['to']}")
        nxt, _ = pick_next(settings, len(summary["sent"]) + len(summary["failed"]))
        if nxt:
            time.sleep(random.uniform(settings["sending"]["gap_seconds_min"], settings["sending"]["gap_seconds_max"]))
    store.log_run("send-track/send", not summary["failed"],
                  f"sent {len(summary['sent'])}, failed {len(summary['failed'])}. {summary['note']}",
                  {"sent": len(summary["sent"]), "failed": len(summary["failed"])})
    return summary


def test_email() -> str:
    """Send one email to yourself to prove the Gmail connection works."""
    profile = load_config("profile")["person"]
    box = mailbox.from_env(profile["name"])
    mailbox.check_login(box)
    mail = mailbox.build(box, box.address, "Outreach HQ test email",
                         "This is a test from Outreach HQ. If you can read it, sending works.\n\n" +
                         load_config("settings")["signature"]["text"] + "\n", message_id=mailbox.new_message_id(box))
    mailbox.send(box, mail)
    return f"Test email sent to {box.address}. SMTP and IMAP logins both work."
