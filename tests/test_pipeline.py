"""Tests for the parts where a mistake costs something real: who gets filtered out, what an email
may say, and when (and whether) anything is sent. No network and no mailbox are touched.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import math
import os
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

os.environ["OUTREACH_NO_GIT"] = "1"

from outreach import emailfinder, importers, leads as lead_model, mailbox, messages, send, store, track  # noqa: E402
from outreach.rules import judge, parse_experience, parse_pay, pay_fit  # noqa: E402
from outreach.util import business_days_between, load_config, norm_company, now, word_match  # noqa: E402

TARGETING = load_config("targeting")

GOOD_BODY = """Hi Priya,

Acme's move into same-day dispatch is the kind of problem I spent the last year on. At Ola Electric I built a lotting algorithm for truck dispatches that cut Order-to-Delivery time from 32 to 14 days, and I ran S&OP planning with the COO.

I saw the Founder's Office opening and would like to be considered. Could we speak for 15 minutes this week, or could you point me to the right person?

Shlok
"""


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="outreach-test-"))
        self.patch = mock.patch.object(store, "DATA_DIR", self.dir)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def job(self, **overrides):
        base = {"source": "test", "source_id": "1", "company": "Acme", "title": "Founder's Office Associate",
                "location": "Bengaluru", "description": "0-2 years of experience in strategy.", "url": "https://acme.com/jobs/1"}
        base.update(overrides)
        return base

    def add_lead(self, **overrides) -> dict:
        job = self.job(**overrides)
        verdict = judge(job, TARGETING)
        data = store.load("leads")
        lead = lead_model.new_lead(job, verdict, store.next_id(data["leads"], "L"))
        lead["stage"] = "qualified"
        lead["contacts"] = [lead_model.new_contact({"name": "Priya Nair", "role_type": "hiring_manager",
                                                    "email": "priya.nair@acme.com", "email_status": "verified",
                                                    "confidence": 90}, "C1")]
        data["leads"].append(lead)
        store.save("leads", data)
        return lead


class RulesTest(Base):
    def test_target_roles_are_kept(self):
        for title in ("Founder's Office Associate", "Chief of Staff", "CEO's Office - Strategy & Operations",
                      "Strategy and Operations Analyst", "Entrepreneur in Residence", "Program Manager, BizOps"):
            self.assertTrue(judge(self.job(title=title), TARGETING).keep, title)

    def test_wrong_roles_are_dropped(self):
        for title in ("Software Engineer", "Founder's Office Intern", "Director of Strategy", "Inside Sales Executive",
                      "Head of Operations", "Backend Engineer - Strategy Team", "Telecaller"):
            self.assertFalse(judge(self.job(title=title), TARGETING).keep, title)

    def test_current_employer_is_never_a_lead(self):
        verdict = judge(self.job(company="Beltech AI"), TARGETING)
        self.assertFalse(verdict.keep)
        self.assertIn("exclude", verdict.reject_reason)

    def test_abroad_is_dropped_but_remote_india_is_kept(self):
        self.assertFalse(judge(self.job(location="San Francisco, CA"), TARGETING).keep)
        self.assertFalse(judge(self.job(location="Remote - US", description="US only"), TARGETING).keep)
        self.assertTrue(judge(self.job(location="Remote, India"), TARGETING).keep)
        self.assertEqual(judge(self.job(location="Bangalore, Karnataka"), TARGETING).location_bucket, "bengaluru")

    def test_bengaluru_scores_above_other_cities(self):
        blr = judge(self.job(location="Bengaluru"), TARGETING).score
        mumbai = judge(self.job(location="Mumbai"), TARGETING).score
        self.assertGreater(blr, mumbai)

    def test_experience_parsing(self):
        self.assertEqual(parse_experience("2-4 years of experience in consulting"), (2.0, 4.0))
        self.assertEqual(parse_experience("Minimum 5+ years experience"), (5.0, None))
        self.assertEqual(parse_experience("We were founded 8 years ago and have 5 years of runway"), (None, None))
        self.assertEqual(parse_experience(""), (None, None))

    def test_too_senior_is_dropped_and_stretch_is_flagged(self):
        self.assertFalse(judge(self.job(description="Requires 6+ years of experience"), TARGETING).keep)
        stretch = judge(self.job(description="3-5 years of experience"), TARGETING)
        self.assertTrue(stretch.keep)
        self.assertTrue(stretch.stretch)

    def test_pay_parsing(self):
        self.assertEqual(parse_pay("CTC: Rs 24-40 LPA")[:2], (24.0, 40.0))
        self.assertEqual(parse_pay("upto 30 LPA")[:2], (None, 30.0))
        self.assertEqual(parse_pay("Salary ₹18,00,000 - ₹22,00,000 per annum")[:2], (18.0, 22.0))
        self.assertEqual(parse_pay("36 Lacs")[:2], (36.0, 36.0))
        self.assertEqual(parse_pay("We serve 5-10 lakh users and raised Rs 50 lakh in funding"), (None, None, None))
        self.assertEqual(parse_pay("great team, great culture"), (None, None, None))

    def test_pay_floor(self):
        floor = TARGETING["pay"]["floor_lpa"]
        self.assertTrue(pay_fit(25, 35, floor).startswith("In range"))
        self.assertTrue(pay_fit(18, 27, floor).startswith("Possibly"))
        self.assertTrue(pay_fit(6, 9, floor).startswith("Below"))
        self.assertEqual(pay_fit(None, None, floor), "Unknown")
        below = judge(self.job(pay_text="Rs 6-9 LPA"), TARGETING)
        self.assertFalse(below.keep)
        self.assertIn("below", below.reject_reason)
        self.assertTrue(judge(self.job(pay_text="Rs 25-35 LPA"), TARGETING).pay.fit.startswith("In range"))

    def test_helpers(self):
        self.assertEqual(norm_company("Meesho (YC S15) Pvt. Ltd."), "meesho")
        self.assertEqual(norm_company("WealthQ (via DSL Consultancy)"), "wealthq")
        self.assertTrue(word_match("Ola", "Ola Electric"))
        self.assertFalse(word_match("Ola", "Motorola"))
        friday = now().replace(year=2026, month=11, day=13)
        self.assertEqual(business_days_between(friday, friday + timedelta(days=3)), 1)  # Fri -> Mon


class DraftRulesTest(Base):
    def check(self, body=GOOD_BODY, subject="Founder's Office at Acme", kind="cold"):
        return messages.check_draft(kind, subject, body, to_name="Priya Nair", company="Acme")

    def test_a_good_email_passes(self):
        self.assertEqual(self.check(), [])

    def test_current_employer_can_never_appear(self):
        problems = self.check(GOOD_BODY.replace("At Ola Electric", "At Beltech and Ola Electric"))
        self.assertTrue(any("Beltech" in p for p in problems), problems)

    def test_filler_buzzwords_pay_and_placeholders_are_refused(self):
        cases = {
            "I hope this email finds you well.": "filler",
            "I am passionate about operations.": "buzzword",
            "My expected CTC is 30 LPA.": "pay",
            "Excited to connect!": "exclamation",
            "I admire [Company] a lot.": "placeholder",
            "Read more at https://example.com today.": "link",
        }
        for extra, label in cases.items():
            body = GOOD_BODY.replace("I saw the Founder's Office opening", extra + " I saw the Founder's Office opening")
            problems = " | ".join(self.check(body))
            self.assertIn(label, problems, f"{extra!r} was not refused: {problems}")

    def test_length_greeting_signoff_and_company_are_enforced(self):
        self.assertTrue(any("words" in p for p in self.check("Hi Priya,\n\nPlease hire me at Acme.\n\nShlok\n")))
        self.assertTrue(any("Hi Priya" in p for p in self.check(GOOD_BODY.replace("Hi Priya,", "Hello there,"))))
        self.assertTrue(any("end with" in p for p in self.check(GOOD_BODY.replace("\nShlok\n", "\nRegards,\nShlok Agrawal\n"))))
        self.assertTrue(any("never names the company" in p for p in self.check(GOOD_BODY.replace("Acme's", "Your"), subject="Founder's Office role")))

    def test_applied_is_only_claimed_when_true(self):
        body = GOOD_BODY.replace("I saw the Founder's Office opening and would like to be considered.",
                                 "I have applied for the Founder's Office role.")
        self.assertTrue(any("not marked applied" in p for p in messages.check_draft(
            "cold", "Founder's Office at Acme", body, to_name="Priya Nair", company="Acme", applied=False)))
        self.assertEqual(messages.check_draft("cold", "Founder's Office at Acme", body, to_name="Priya Nair",
                                              company="Acme", applied=True), [])

    def test_speculative_note_cannot_pretend_there_is_an_opening(self):
        problems = messages.check_draft("cold", "Strategy help at Acme", GOOD_BODY, to_name="Priya Nair",
                                        company="Acme", speculative=True)
        self.assertTrue(any("no named opening" in p for p in problems), problems)
        honest = GOOD_BODY.replace("I saw the Founder's Office opening and would like to be considered. ",
                                   "I do not know if a Founder's Office hire is on your mind this quarter. ")
        self.assertEqual(messages.check_draft("cold", "Strategy help at Acme", honest, to_name="Priya Nair",
                                              company="Acme", speculative=True), [])

    def test_draft_needs_a_deliverable_address_and_respects_do_not_email(self):
        lead = self.add_lead()
        suppression = store.load("suppression")
        suppression["emails"]["priya.nair@acme.com"] = {"reason": "already emailed by the earlier founder pipeline"}
        store.save("suppression", suppression)
        with self.assertRaises(ValueError) as caught:
            messages.create_draft(lead["id"], "C1", "cold", "Founder's Office at Acme", GOOD_BODY)
        self.assertIn("do-not-email", str(caught.exception))

    def test_one_cold_email_per_person(self):
        lead = self.add_lead()
        messages.create_draft(lead["id"], "C1", "cold", "Founder's Office at Acme", GOOD_BODY)
        with self.assertRaises(ValueError) as caught:
            messages.create_draft(lead["id"], "C1", "cold", "Founder's Office at Acme", GOOD_BODY)
        self.assertIn("already has a cold email", str(caught.exception))

    def test_followup_needs_a_sent_cold_email(self):
        lead = self.add_lead()
        with self.assertRaises(ValueError) as caught:
            messages.create_draft(lead["id"], "C1", "followup1", "x",
                                  "Hi Priya,\n\nOne more thing on the Acme role: I also ran SAP MRP rollout from scratch, "
                                  "which may matter for your planning stack. Happy to share how.\n\nShlok\n")
        self.assertIn("no sent cold email", str(caught.exception))


class FakeBox:
    address = "me@gmail.com"
    password = "x"
    name = "Shlok Agrawal"


class SendTest(Base):
    def setUp(self) -> None:
        super().setUp()
        self.sent: list = []
        self.settings = load_config("settings")
        self.settings["mode"] = "live"
        patches = [
            mock.patch.object(send, "load_config", side_effect=lambda name: self.settings if name == "settings" else load_config(name)),
            mock.patch.object(send, "in_window", return_value=True),
            mock.patch.object(mailbox, "from_env", return_value=FakeBox()),
            mock.patch.object(mailbox, "send", side_effect=lambda box, mail: self.sent.append(mail)),
            mock.patch.object(send.time, "sleep"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def queue(self, count: int, status: str = "approved", email_status: str = "verified") -> list[dict]:
        made = []
        for index in range(count):
            lead = self.add_lead(company=f"Acme{index}", source_id=str(index))
            data = store.load("leads")
            stored = store.find(data["leads"], lead["id"])
            stored["contacts"][0]["email"] = f"priya.nair@acme{index}.com"
            stored["contacts"][0]["email_status"] = email_status
            store.save("leads", data)
            body = GOOD_BODY.replace("Acme's", f"Acme{index}'s")
            message = messages.create_draft(lead["id"], "C1", "cold", f"Founder's Office at Acme{index}", body,
                                            allow_unverified=True)
            data = store.load("messages")
            stored = store.find(data["messages"], message["id"])
            stored["status"] = status
            stored["approved_at"] = f"2026-11-12T10:{index:02d}:00+05:30"
            store.save("messages", data)
            made.append(stored)
        return made

    def statuses(self) -> list[str]:
        return [m["status"] for m in store.load("messages")["messages"]]

    def test_drafts_are_never_sent_without_approval(self):
        self.queue(3, status="draft")
        send.run()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.statuses(), ["draft"] * 3)

    def test_dry_run_sends_nothing(self):
        self.settings["mode"] = "dry_run"
        self.queue(2)
        result = send.run()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.statuses(), ["approved"] * 2)
        self.assertIn("dry_run", result["note"])

    def test_approved_emails_go_out_once_with_signature_and_thread_ids(self):
        self.queue(2)
        send.run()
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.statuses(), ["sent", "sent"])
        text = self.sent[0].get_content()
        self.assertIn("Portfolio: https://shlokagrawal-portfolio.vercel.app", text)
        self.assertNotIn("Beltech", text)
        self.assertEqual(text.count("Shlok Agrawal"), 1)
        stored = store.load("messages")["messages"][0]
        self.assertEqual(self.sent[0]["Message-ID"], stored["message_id"])
        send.run()  # a second run must not resend anything
        self.assertEqual(len(self.sent), 2)
        lead = store.load("leads")["leads"][0]
        self.assertTrue(lead["first_contacted_at"])

    def test_run_limit_and_daily_cap(self):
        self.settings["sending"] = dict(self.settings["sending"], max_per_run=6, new_emails_per_day=8)
        self.queue(10)
        send.run()
        self.assertEqual(len(self.sent), 6)
        send.run()
        self.assertEqual(len(self.sent), 8)  # daily cap of 8 new emails
        send.run()
        self.assertEqual(len(self.sent), 8)
        self.assertEqual(self.statuses().count("approved"), 2)

    def test_unverified_guesses_are_capped(self):
        self.queue(6, email_status="guess")
        send.run()
        self.assertEqual(len(self.sent), self.settings["sending"]["unverified_per_day"])

    def test_verifying_an_address_after_drafting_lifts_the_cap(self):
        self.queue(5, email_status="guess")
        data = store.load("leads")
        for lead in data["leads"]:
            lead["contacts"][0]["email_status"] = "verified"
        store.save("leads", data)
        send.run()
        self.assertEqual(len(self.sent), 5)

    def test_unverified_address_needs_an_explicit_exception_to_draft(self):
        lead = self.add_lead()
        data = store.load("leads")
        data["leads"][0]["contacts"][0]["email_status"] = "guess"
        store.save("leads", data)
        with self.assertRaises(ValueError) as caught:
            messages.create_draft(lead["id"], "C1", "cold", "Founder's Office at Acme", GOOD_BODY)
        self.assertIn("unverified", str(caught.exception))
        self.assertTrue(messages.create_draft(lead["id"], "C1", "cold", "Founder's Office at Acme", GOOD_BODY,
                                              allow_unverified=True)["id"])

    def test_speculative_notes_are_capped(self):
        self.settings["sending"] = dict(self.settings["sending"], speculative_per_day=2, max_per_run=6)
        made = self.queue(5)
        data = store.load("messages")
        for message in data["messages"]:
            message["speculative"] = True
        store.save("messages", data)
        send.run()
        self.assertEqual(len(self.sent), 2)

    def test_outside_window_nothing_goes(self):
        self.queue(1)
        with mock.patch.object(send, "in_window", return_value=False):
            send.run()
        self.assertEqual(self.sent, [])

    def test_smtp_failure_is_recorded_not_retried(self):
        self.queue(1)
        with mock.patch.object(mailbox, "send", side_effect=RuntimeError("connection reset")):
            send.run()
        message = store.load("messages")["messages"][0]
        self.assertEqual(message["status"], "failed")
        send.run()
        self.assertEqual(self.sent, [])  # failed stays failed until Shlok presses Retry

    def test_claim_is_exclusive(self):
        message = self.queue(1)[0]
        self.assertTrue(send.claim(message["id"], "<a@x>"))
        self.assertFalse(send.claim(message["id"], "<b@x>"))

    def test_reply_before_send_cancels_the_send(self):
        message = self.queue(1)[0]
        data = store.load("leads")
        data["leads"][0]["replied_at"] = "2026-11-12T09:00:00+05:30"
        store.save("leads", data)
        send.run()
        self.assertEqual(self.sent, [])
        self.assertEqual(store.find(store.load("messages")["messages"], message["id"])["status"], "skipped")


class TrackTest(Base):
    def sent_message(self, days_ago: int, kind: str = "cold") -> dict:
        lead = self.add_lead()
        data = store.load("messages")
        when = (now() - timedelta(days=days_ago)).replace(microsecond=0).isoformat()
        message = {"id": store.next_id(data["messages"], "M"), "lead_id": lead["id"], "contact_id": "C1",
                   "to": "priya.nair@acme.com", "to_name": "Priya Nair", "kind": kind, "subject": "Founder's Office at Acme",
                   "body": GOOD_BODY, "status": "sent", "sent_at": when, "created_at": when, "message_id": f"<{kind}@gmail.com>"}
        data["messages"].append(message)
        store.save("messages", data)
        return message

    def test_followup_becomes_due_after_four_business_days(self):
        self.sent_message(days_ago=1)
        track.scan(None)
        self.assertFalse(store.load("leads")["leads"][0]["followup"]["due"])
        data = store.load("messages")
        data["messages"][0]["sent_at"] = (now() - timedelta(days=8)).isoformat()
        store.save("messages", data)
        stats = track.scan(None)
        lead = store.load("leads")["leads"][0]
        self.assertTrue(lead["followup"]["due"])
        self.assertEqual(lead["followup"]["kind"], "followup1")
        self.assertEqual(stats["followups_due"], 1)

    def test_reply_stops_the_thread_and_drops_queued_followups(self):
        cold = self.sent_message(days_ago=8)
        data = store.load("messages")
        data["messages"].append(dict(cold, id="M0002", kind="followup1", status="draft", sent_at=None, message_id=None))
        store.save("messages", data)
        report = mailbox.InboxReport(replies=[mailbox.Reply(message_id=cold["message_id"], sender="priya.nair@acme.com",
                                                             subject="Re: Founder's Office at Acme", date="Thu, 12 Nov 2026",
                                                             snippet="Thanks Shlok, can you do Friday 4pm?")])
        with mock.patch.object(mailbox, "scan_inbox", return_value=report):
            stats = track.scan(FakeBox())
        stored = store.load("messages")["messages"]
        self.assertEqual(stats["replies"], 1)
        self.assertEqual(stored[0]["status"], "replied")
        self.assertEqual(stored[1]["status"], "skipped")
        lead = store.load("leads")["leads"][0]
        self.assertTrue(lead["replied_at"])
        self.assertFalse(lead["followup"]["due"])
        self.assertEqual(lead_model.display_status(lead, stored), "replied")

    def test_out_of_office_is_not_a_reply(self):
        cold = self.sent_message(days_ago=2)
        report = mailbox.InboxReport(replies=[mailbox.Reply(message_id=cold["message_id"], sender="priya.nair@acme.com",
                                                             subject="Automatic reply: Founder's Office", date="x",
                                                             snippet="I am out of office", auto=True)])
        with mock.patch.object(mailbox, "scan_inbox", return_value=report):
            stats = track.scan(FakeBox())
        self.assertEqual(stats["replies"], 0)
        self.assertEqual(store.load("messages")["messages"][0]["status"], "sent")

    def test_bounce_marks_address_dead_and_blocks_it(self):
        self.sent_message(days_ago=1)
        report = mailbox.InboxReport(bounced={"priya.nair@acme.com"})
        with mock.patch.object(mailbox, "scan_inbox", return_value=report):
            stats = track.scan(FakeBox())
        self.assertEqual(stats["bounces"], 1)
        self.assertEqual(store.load("messages")["messages"][0]["status"], "bounced")
        self.assertEqual(store.load("leads")["leads"][0]["contacts"][0]["email_status"], "bounced")
        self.assertIn("priya.nair@acme.com", store.load("suppression")["emails"])
        self.assertIn("first.last", store.load("domains")["domains"]["acme.com"]["bounced_patterns"])

    def test_interrupted_send_is_settled_from_the_sent_folder(self):
        message = self.sent_message(days_ago=0)
        data = store.load("messages")
        data["messages"][0].update(status="sending", sending_at=(now() - timedelta(minutes=30)).isoformat(), sent_at=None)
        store.save("messages", data)
        with mock.patch.object(mailbox, "scan_inbox", return_value=mailbox.InboxReport()), \
                mock.patch.object(mailbox, "in_sent_folder", return_value=False):
            track.scan(FakeBox())
        self.assertEqual(store.find(store.load("messages")["messages"], message["id"])["status"], "failed")


class EmailFinderTest(Base):
    def test_names_and_patterns(self):
        self.assertEqual(emailfinder.split_name("Dr. Anand Kumar Prajapati"), ("anand", "prajapati"))
        self.assertEqual(emailfinder.split_name("Shashwat D."), ("shashwat", ""))
        self.assertEqual(emailfinder.infer_pattern("priya.nair@acme.com", "priya", "nair"), "first.last")
        self.assertEqual(emailfinder.infer_pattern("pnair@acme.com", "priya", "nair"), "flast")
        self.assertEqual(emailfinder.domain_of("https://careers.acme.com/jobs/1"), "acme.com")
        self.assertIsNone(emailfinder.domain_of("https://boards.greenhouse.io/acme/jobs/1"))
        self.assertIsNone(emailfinder.domain_of("https://www.linkedin.com/jobs/view/1"))

    def test_bounced_patterns_are_not_guessed_again(self):
        options = emailfinder.candidates("priya", "nair", "acme.com", "employee", {"bounced_patterns": ["first.last"]})
        self.assertNotIn("priya.nair@acme.com", [email for email, _ in options])
        self.assertEqual(options[0][0], "priya@acme.com")

    def test_without_keys_the_result_is_an_honest_guess(self):
        with mock.patch.object(emailfinder, "mx_provider", return_value="google"), \
                mock.patch.object(emailfinder, "scrape_published", return_value={"generic": ["careers@acme.com"], "personal": []}), \
                mock.patch.dict(os.environ, {}, clear=False):
            for key in ("HUNTER_API_KEY", "QEV_API_KEY", "REOON_API_KEY", "APOLLO_API_KEY"):
                os.environ.pop(key, None)
            found = emailfinder.find_email("Priya Nair", "acme.com", "employee")
        self.assertEqual(found["email"], "priya.nair@acme.com")
        self.assertEqual(found["email_status"], "guess")
        self.assertLess(found["confidence"], 50)

    def test_a_verifier_confirms_and_the_pattern_is_remembered(self):
        with mock.patch.object(emailfinder, "mx_provider", return_value="google"), \
                mock.patch.object(emailfinder, "scrape_published", return_value={"generic": [], "personal": []}), \
                mock.patch.dict(os.environ, {"QEV_API_KEY": "k"}), \
                mock.patch.object(emailfinder, "VERIFIERS", [("quickemailverification",
                                  lambda email, key: "valid" if email == "priya@acme.com" else "invalid")]):
            for key in ("HUNTER_API_KEY", "APOLLO_API_KEY"):
                os.environ.pop(key, None)
            found = emailfinder.find_email("Priya Nair", "acme.com", "employee")
        self.assertEqual((found["email"], found["email_status"]), ("priya@acme.com", "verified"))
        self.assertEqual(store.load("domains")["domains"]["acme.com"]["pattern"], "first")
        self.assertEqual(store.load("quotas")["usage"][f"quickemailverification:{now().strftime('%Y-%m-%d')}"], 2)

    def test_no_mail_server_means_no_address(self):
        with mock.patch.object(emailfinder, "mx_provider", return_value=None):
            self.assertEqual(emailfinder.find_email("Priya Nair", "acme.com")["email"], "")


class ImportTest(Base):
    def test_connections_are_matched_to_leads(self):
        self.add_lead(company="Meesho")
        export = self.dir / "Connections.csv"
        export.write_text("Notes:\n\"When exporting your connection data...\"\n\n"
                          "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                          "Rahul,Verma,https://www.linkedin.com/in/rahul-verma,,Meesho,Product Manager,12 Aug 2025\n"
                          "Asha,Rao,https://www.linkedin.com/in/asha-rao,,Some Other Co,Analyst,01 Jan 2024\n", encoding="utf-8")
        result = importers.import_connections(str(export))
        self.assertEqual(result["connections"], 2)
        lead = store.load("leads")["leads"][0]
        self.assertEqual([r["name"] for r in lead["referrals"]], ["Rahul Verma"])
        self.assertEqual(importers.match_connections()["suggestions_added"], 0)  # idempotent


def _bump(directory: str, times: int) -> None:
    store.DATA_DIR = Path(directory)

    def change() -> None:
        data = store.load("runs")
        data["runs"].append({"pad": "x" * 20000})
        store.save("runs", data)
    for _ in range(times):
        store.transact(change, "bump")


class ConcurrentWriteTest(Base):
    def test_processes_writing_at_once_lose_nothing(self) -> None:
        import multiprocessing
        context = multiprocessing.get_context("fork")
        workers = [context.Process(target=_bump, args=(str(self.dir), 15)) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(60)
        self.assertEqual([worker.exitcode for worker in workers], [0, 0, 0, 0])
        self.assertEqual(len(store.load("runs")["runs"]), 60)
        self.assertEqual([p.name for p in self.dir.glob("*.tmp")] + [p.name for p in self.dir.glob(".*.tmp")], [])

    def test_lock_is_reentrant_within_a_process(self) -> None:
        def outer() -> str:
            store.log_run("test", True, "inner write while the lock is held")
            return "done"
        self.assertEqual(store.transact(outer, "outer"), "done")
        self.assertEqual(len(store.load("runs")["runs"]), 1)



class JournalTest(Base):
    def test_runs_issues_and_changes_all_reach_the_supervisor_log(self) -> None:
        store.log_run("lead-scout", True, "3 researched")
        store.log_run("follow-up/track", False, "inbox scan failed")
        store.open_issue("send-track", "Gmail refused the login", "535 from smtp.gmail.com")
        store.open_issue("send-track", "Gmail refused the login", "again")  # a repeat is counted, not logged twice
        store.log_entry("session", "update", "Verifier key added", "Reoon, 20 checks a day")
        entries = store.load("journal")["entries"]
        self.assertEqual([e["kind"] for e in entries], ["run", "failed", "issue", "update"])
        self.assertEqual(entries[2]["ref"], "I0001")
        self.assertEqual([e["id"] for e in entries], ["J0001", "J0002", "J0003", "J0004"])
        with self.assertRaises(ValueError):
            store.log_entry("session", "gossip", "x")



class TimeoutTest(Base):
    def test_a_timed_out_command_dies_with_the_helpers_it_started(self) -> None:
        import subprocess
        import time
        marker = self.dir / "still-running"
        # The shell starts a background helper that would write the marker after 3 s, as git starts
        # git-remote-https. The helper must be killed along with its parent.
        script = f"(sleep 3; touch '{marker}') & wait"
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            store._run(["sh", "-c", script], timeout=0.5)
        self.assertLess(time.monotonic() - started, 2.5)
        time.sleep(3.2)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
