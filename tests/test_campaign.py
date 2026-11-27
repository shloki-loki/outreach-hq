import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from outreach import campaign, send, store
from outreach.util import load_config, now


def person(cid, name, email, role="founder", title="Co-Founder", status="verified"):
    return dict(id=cid, name=name, title=title, role_type=role, email=email, email_status=status)


def lead(i, contacts, **kw):
    base = dict(id=f"L{i:04d}", company=f"Co{i} Technologies Pvt Ltd", source="founder_reoutreach", type="company",
                stage="new", open=True, score={"total": 90 - i}, contacts=contacts)
    base.update(kw)
    return base


class CampaignTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for target in (patch.object(store, "DATA_DIR", Path(temp.name) / "data"), patch.object(store, "sync", lambda *a, **k: None)):
            target.start()
            self.addCleanup(target.stop)
        store.save("leads", {"leads": [
            lead(1, [person("C1", "Asha Rao", "asha@co1.com", title="Co-Founder & CTO"),
                     person("C2", "Dr. Vikram Shah", "vikram@co1.com", title="Co-Founder & CEO"),
                     person("C3", "Hr Team", "hr@co1.com", role="recruiter", title="Talent")]),
            lead(2, [person("C1", "Neha Jain", "neha@co2.com")], company="Co2 (YC W21)"),
            lead(3, [person("C1", "Gone Person", "gone@co3.com")]),                          # do-not-email
            lead(4, [person("C1", "Recent Person", "recent@co4.com")]),                      # emailed last week
            lead(5, [person("C1", "Guess Person", "guess@co5.com", status="guess")]),        # untrusted address
            lead(6, [person("C1", "Job Person", "job@co6.com")], source="linkedin", type="job"),
            lead(7, [person("C1", "Replied Person", "r@co7.com")], replied_at="2026-11-10T10:00:00+05:30"),
        ]})
        store.save("suppression", {"emails": {"gone@co3.com": {"reason": "already emailed"}}})
        store.save("messages", {"messages": [{"id": "M0001", "lead_id": "L0999", "contact_id": "C1", "to": "recent@co4.com",
                                              "kind": "cold", "status": "sent",
                                              "sent_at": (now() - timedelta(days=7)).isoformat()}]})

    def test_fills_name_and_company_and_passes_its_checks(self):
        self.assertEqual(campaign.company_name("Co2 (YC W21)"), "Co2")
        self.assertEqual(campaign.company_name("Acme Technologies Pvt Ltd"), "Acme Technologies")
        self.assertEqual(campaign.first_name("Dr. Vikram Shah"), "Vikram")
        template = campaign.load("founder-v2")
        subject, body = campaign.render(template, {"name": "Neha Jain"}, {"company": "Co2 (YC W21)"})
        self.assertEqual(subject, "Strategy and Ops role | Shlok Agrawal")
        self.assertTrue(body.startswith("Hi Neha,"))
        self.assertEqual(campaign.check(subject, body, "Neha", "Co2"), [])
        self.assertTrue(campaign.check(subject, body.replace("Co2", "{company}"), "Neha", "Co2"))

    def test_connection_failures_are_retried_next_run_but_bounces_are_not(self):
        data = store.load("messages")
        data["messages"] += [
            {"id": "M0002", "lead_id": "L0001", "contact_id": "C1", "to": "asha@co1.com", "kind": "cold",
             "status": "failed", "error": "TimeoutError: timed out"},
            {"id": "M0003", "lead_id": "L0002", "contact_id": "C1", "to": "neha@co2.com", "kind": "cold",
             "status": "failed", "error": "TimeoutError: timed out", "retries": 3},
            {"id": "M0004", "lead_id": "L0004", "contact_id": "C1", "to": "x@co4.com", "kind": "cold", "status": "bounced"},
            {"id": "M0005", "lead_id": "L0004", "contact_id": "C1", "to": "y@co4.com", "kind": "cold",
             "status": "failed", "error": "550 mailbox does not exist"}]
        store.save("messages", data)
        self.assertEqual(campaign.retry_failed(), {"retried": 1})
        by = {m["id"]: m for m in store.load("messages")["messages"]}
        self.assertEqual((by["M0002"]["status"], by["M0002"]["retries"], by["M0002"]["error"]), ("approved", 1, None))
        self.assertEqual(by["M0003"]["status"], "failed")
        self.assertEqual(by["M0004"]["status"], "bounced")
        self.assertEqual(by["M0005"]["status"], "failed")

    def test_only_one_founder_template_is_active(self):
        self.assertFalse(campaign.load("founder-v1").get("active"))
        active = [p.stem for p in (campaign.CONFIG_DIR / "templates").glob("*.toml")
                  if campaign.load(p.stem).get("active") and campaign.load(p.stem).get("audience") == "founders"]
        self.assertEqual(active, ["founder-v2"])

    def test_queue_targets_every_listed_address_round_robin_and_skips_the_unsafe(self):
        result = campaign.queue("founder-v2")
        messages = [m for m in store.load("messages")["messages"] if m.get("template") == "founder-v2"]
        self.assertEqual([m["to"] for m in messages],
                         ["vikram@co1.com", "neha@co2.com", "asha@co1.com", "hr@co1.com"])  # CEO first, round-robin
        self.assertEqual(result["queued"], 4)
        for m in messages:
            self.assertEqual((m["status"], m["kind"], m["play"]), ("approved", "cold", "template"))
            self.assertIn("approved_by", m)

    def test_daily_top_up_never_passes_per_day_and_stop_pulls_back(self):
        self.assertEqual(campaign.queue("founder-v2", limit=2)["queued"], 2)
        self.assertEqual(campaign.queue("founder-v2", limit=2)["queued"], 0)    # same day: no doubling
        self.assertEqual(campaign.queue("founder-v2", limit=3)["queued"], 1)
        self.assertEqual(campaign.stop("founder-v2")["pulled_back"], 3)
        self.assertFalse([m for m in store.load("messages")["messages"] if m.get("status") == "approved"])

    def test_dry_run_saves_nothing(self):
        self.assertEqual(campaign.queue("founder-v2", dry_run=True)["queued"], 4)
        self.assertEqual(len(store.load("messages")["messages"]), 1)

    def add_old(self, mid, to, status, error):
        data = store.load("messages")
        data["messages"].append({"id": mid, "lead_id": "L0001", "to": to, "kind": "cold", "status": status,
                                 "error": error, "template": "founder-v1", "sent_at": None,
                                 "created_at": now().isoformat()})
        store.save("messages", data)

    def order(self):
        return [m["to"] for m in store.load("messages")["messages"]
                if m.get("template") == "founder-v2" and m["status"] == "approved"]

    def test_never_sent_people_go_to_the_back_and_real_refusals_stay_out(self):
        self.add_old("M0101", "vikram@co1.com", "skipped", "campaign stopped")           # pulled back, never sent
        self.add_old("M0102", "neha@co2.com", "failed",
                     "SMTPServerDisconnected: Connection unexpectedly closed: [Errno 54] Connection reset by peer")
        self.add_old("M0103", "hr@co1.com", "failed", "SMTPRecipientsRefused: 550 5.1.1 no such user")
        campaign.queue("founder-v2")
        self.assertEqual(self.order(), ["asha@co1.com", "vikram@co1.com", "neha@co2.com"])  # both never-sent last; hr@ refused: out

    def test_requeue_reorders_the_day_without_doubling_it(self):
        self.assertEqual(campaign.queue("founder-v2", limit=2)["queued"], 2)
        self.assertEqual(self.order(), ["vikram@co1.com", "neha@co2.com"])
        self.add_old("M0101", "vikram@co1.com", "skipped", "campaign stopped")
        with patch.object(campaign, "load", lambda t: {**campaign.tomllib.load(open(
                campaign.CONFIG_DIR / "templates" / f"{t}.toml", "rb")), "per_day": 2}):
            result = campaign.requeue("founder-v2")
            self.assertEqual((result["pulled_back"], result["queued"]["queued"]), (2, 2))
            self.assertEqual(self.order(), ["neha@co2.com", "asha@co1.com"])          # vikram now waits at the back
            self.assertEqual(campaign.queue("founder-v2")["queued"], 0)              # same day: still no doubling

    def test_status_works_for_the_followup_template(self):
        self.assertEqual(campaign.status("followup-v1")["template"], "followup-v1")

    def test_sender_picks_them_up_within_the_founder_cap(self):
        campaign.queue("founder-v2")
        settings = load_config("settings")
        settings["sending"]["speculative_per_day"] = 60
        message, why = send.pick_next(settings, 0)
        self.assertEqual(message["to"], "vikram@co1.com", why)
        store.save("suppression", {"emails": {"vikram@co1.com": {"reason": "asked not to be emailed"}}})
        message, _ = send.pick_next(settings, 0)
        self.assertEqual(message["to"], "neha@co2.com")      # a newly blocked address is skipped at send time


if __name__ == "__main__":
    unittest.main()


class FollowupAndJobTemplateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for target in (patch.object(store, "DATA_DIR", Path(temp.name) / "data"), patch.object(store, "sync", lambda *a, **k: None)):
            target.start()
            self.addCleanup(target.stop)
        self.real_load = campaign.load

    def activate(self, template_id):
        template = dict(self.real_load(template_id), active=True)
        loader = patch.object(campaign, "load", lambda i: template if i == template_id else self.real_load(i))
        loader.start()
        self.addCleanup(loader.stop)

    def sent(self, mid, lead_id, days_ago, kind="cold", contact="C1", to="a@co1.com", **kw):
        return dict(id=mid, lead_id=lead_id, contact_id=contact, to=to, to_name="Asha Rao", kind=kind, subject="Ops at Co1",
                    status="sent", sent_at=(now() - timedelta(days=days_ago)).isoformat(), message_id=f"<{mid}@x>", **kw)

    def test_followups_queue_in_thread_and_stop_on_reply(self):
        self.activate("followup-v1")
        store.save("leads", {"leads": [lead(1, [person("C1", "Asha Rao", "a@co1.com")]),
                                       lead(2, [person("C1", "Ravi K", "r@co2.com")], replied_at="2026-11-18T10:00:00+05:30"),
                                       lead(3, [person("C1", "New One", "n@co3.com")])]})
        store.save("suppression", {"emails": {}})
        store.save("messages", {"messages": [self.sent("M0001", "L0001", 9), self.sent("M0002", "L0002", 9, to="r@co2.com"),
                                             self.sent("M0003", "L0003", 1, to="n@co3.com")]})
        result = campaign.queue_followups("followup-v1")
        self.assertEqual(result["queued"], 1)                         # replied lead and 1-day-old thread skipped
        follow = store.load("messages")["messages"][-1]
        self.assertEqual((follow["kind"], follow["thread_parent"], follow["status"]), ("followup1", "<M0001@x>", "approved"))
        self.assertTrue(follow["subject"].startswith("Re: ") and follow["body"].startswith("Hi Asha,"))
        self.assertEqual(campaign.queue_followups("followup-v1")["queued"], 0)   # already queued for that person

    def test_agent_followup_draft_is_replaced_but_his_edit_is_kept(self):
        self.activate("followup-v1")
        store.save("leads", {"leads": [lead(1, [person("C1", "Asha Rao", "a@co1.com")]),
                                       lead(2, [person("C1", "Ravi K", "r@co2.com")])]})
        store.save("suppression", {"emails": {}})
        draft = lambda mid, lid, to, **kw: dict(id=mid, lead_id=lid, contact_id="C1", to=to, kind="followup1", status="draft",
                                                created_by="follow-up", subject="Re: x", body="...", **kw)
        store.save("messages", {"messages": [self.sent("M0001", "L0001", 9), self.sent("M0002", "L0002", 9, to="r@co2.com"),
                                             draft("M0003", "L0001", "a@co1.com"),
                                             draft("M0004", "L0002", "r@co2.com", edited_by_shlok=True)]})
        self.assertEqual(campaign.queue_followups("followup-v1")["queued"], 1)
        by_id = {m["id"]: m for m in store.load("messages")["messages"]}
        self.assertEqual(by_id["M0003"]["status"], "skipped")
        self.assertEqual(by_id["M0004"]["status"], "draft")          # his edited draft stays for him
        self.assertEqual(by_id["M0005"]["lead_id"], "L0001")

    def test_nameless_contact_is_greeted_like_the_first_email(self):
        self.activate("followup-v1")
        store.save("leads", {"leads": [lead(1, [person("C1", "", "hello@co1.com")]), lead(2, [person("C1", "", "jobs@co2.com")])]})
        store.save("suppression", {"emails": {}})
        first = self.sent("M0001", "L0001", 9, to="hello@co1.com", body="Hi Co1 team,\n\nText\n\nShlok\n")
        second = self.sent("M0002", "L0002", 9, to="jobs@co2.com", body="Hello team,\n\nText\n\nShlok\n")
        first["to_name"] = second["to_name"] = ""
        store.save("messages", {"messages": [first, second]})
        self.assertEqual(campaign.queue_followups("followup-v1")["queued"], 2)
        bodies = sorted(m["body"].splitlines()[0] for m in store.load("messages")["messages"] if m.get("template"))
        self.assertEqual(bodies, ["Hi Co1 team,", "Hi there,"])

    def test_only_one_followup(self):
        # Shlok, 2026-11-27: one follow-up per person, never a second.
        self.activate("followup-v1")
        store.save("leads", {"leads": [lead(1, [person("C1", "Asha Rao", "a@co1.com")])]})
        store.save("suppression", {"emails": {}})
        store.save("messages", {"messages": [self.sent("M0001", "L0001", 30), self.sent("M0002", "L0001", 12, kind="followup1")]})
        self.assertEqual(campaign.queue_followups("followup-v1")["queued"], 0)
        self.assertEqual(len(store.load("messages")["messages"]), 2)
        # A second follow-up approved before the change is skipped at send time, never sent.
        from outreach import send
        from outreach.util import load_config
        data = store.load("messages")
        data["messages"].append(dict(self.sent("M0003", "L0001", 0, kind="followup2"), status="approved",
                                     sent_at=None, approved_at="2026-11-27T09:00:00+05:30", email_status="valid"))
        store.save("messages", data)
        message, reason = send.pick_next(load_config("settings"), 0)
        self.assertIsNone(message)
        self.assertEqual(store.find(store.load("messages")["messages"], "M0003")["status"], "skipped")

    def test_inactive_templates_queue_nothing(self):
        for template_id in ("followup-v1", "job-apply-v1"):
            off = dict(self.real_load(template_id), active=False)
            with patch.object(campaign, "load", lambda i, off=off: off):
                runner = campaign.queue_followups if template_id.startswith("followup") else campaign.queue
                self.assertEqual(runner(template_id)["queued"], 0)

    def test_job_template_targets_qualified_unapplied_jobs_once(self):
        self.activate("job-apply-v1")
        job = lambda i, **kw: lead(i, kw.pop("contacts"), type="job", source="linkedin_post", stage=kw.pop("stage", "qualified"),
                                   title="Strategy & Ops (Founder's Office) | Bengaluru", **kw)
        store.save("leads", {"leads": [
            job(1, contacts=[person("C1", "", "careers@co1.com", role="recruiter")]),
            job(2, contacts=[person("C1", "Ravi K", "r@co2.com", role="hiring_manager")], applied_at="2026-11-18T10:00:00+05:30"),
            job(3, contacts=[person("C1", "Mia S", "m@co3.com", role="hiring_manager")], stage="rejected"),
            job(4, contacts=[person("C1", "Om P", "o@co4.com", role="hiring_manager")]),
        ]})
        store.save("suppression", {"emails": {}})
        store.save("messages", {"messages": [self.sent("M0001", "L0004", 2, to="other@co4.com", contact="C9")]})
        campaign.queue("job-apply-v1")
        queued = [m for m in store.load("messages")["messages"] if m.get("template") == "job-apply-v1"]
        self.assertEqual([m["to"] for m in queued], ["careers@co1.com"])     # applied, rejected, already emailed skipped
        self.assertTrue(queued[0]["body"].startswith("Hi there,"))
        self.assertEqual(queued[0]["subject"], "Application: Strategy & Ops (Founder's Office)")
        self.assertFalse(queued[0]["speculative"])


class VerifierRotationTest(unittest.TestCase):
    def test_most_quota_left_goes_first_and_used_up_ones_are_skipped(self):
        from outreach import emailfinder
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with patch.object(store, "DATA_DIR", Path(temp.name) / "data"), \
                patch.dict("os.environ", {"ZEROBOUNCE_API_KEY": "z", "MAILBOXVALIDATOR_API_KEY": "m"}, clear=False):
            quota = emailfinder.Quota()
            quota.usage[quota._bucket("mailboxvalidator")] = 290        # used up this month
            calls = []
            fake = [(name, (lambda n: lambda e, k: calls.append(n) or "valid")(name)) for name, _ in emailfinder.VERIFIERS]
            with patch.object(emailfinder, "VERIFIERS", fake):
                self.assertEqual(emailfinder.verify("a@b.com", quota), ("valid", "zerobounce"))
            self.assertEqual(calls, ["zerobounce"])
