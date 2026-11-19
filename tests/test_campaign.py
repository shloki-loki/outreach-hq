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
        template = campaign.load("founder-v1")
        subject, body = campaign.render(template, {"name": "Neha Jain"}, {"company": "Co2 (YC W21)"})
        self.assertEqual(subject, "Ops and strategy help at Co2")
        self.assertTrue(body.startswith("Hi Neha,"))
        self.assertEqual(campaign.check(subject, body, "Neha", "Co2"), [])
        self.assertTrue(campaign.check(subject, body.replace("Co2", "{company}"), "Neha", "Co2"))

    def test_queue_targets_every_listed_address_round_robin_and_skips_the_unsafe(self):
        result = campaign.queue("founder-v1")
        messages = [m for m in store.load("messages")["messages"] if m.get("template") == "founder-v1"]
        self.assertEqual([m["to"] for m in messages],
                         ["vikram@co1.com", "neha@co2.com", "asha@co1.com", "hr@co1.com"])  # CEO first, round-robin
        self.assertEqual(result["queued"], 4)
        for m in messages:
            self.assertEqual((m["status"], m["kind"], m["play"]), ("approved", "cold", "template"))
            self.assertIn("approved_by", m)

    def test_daily_top_up_never_passes_per_day_and_stop_pulls_back(self):
        self.assertEqual(campaign.queue("founder-v1", limit=2)["queued"], 2)
        self.assertEqual(campaign.queue("founder-v1", limit=2)["queued"], 0)    # same day: no doubling
        self.assertEqual(campaign.queue("founder-v1", limit=3)["queued"], 1)
        self.assertEqual(campaign.stop("founder-v1")["pulled_back"], 3)
        self.assertFalse([m for m in store.load("messages")["messages"] if m.get("status") == "approved"])

    def test_dry_run_saves_nothing(self):
        self.assertEqual(campaign.queue("founder-v1", dry_run=True)["queued"], 4)
        self.assertEqual(len(store.load("messages")["messages"]), 1)

    def test_sender_picks_them_up_within_the_founder_cap(self):
        campaign.queue("founder-v1")
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

    def test_second_followup_after_first(self):
        self.activate("followup-v1")
        store.save("leads", {"leads": [lead(1, [person("C1", "Asha Rao", "a@co1.com")])]})
        store.save("suppression", {"emails": {}})
        store.save("messages", {"messages": [self.sent("M0001", "L0001", 30), self.sent("M0002", "L0001", 12, kind="followup1")]})
        campaign.queue_followups("followup-v1")
        follow = store.load("messages")["messages"][-1]
        self.assertEqual(follow["kind"], "followup2")
        self.assertIn("Co1 Technologies", follow["body"])

    def test_inactive_templates_queue_nothing(self):
        self.assertEqual(campaign.queue_followups("followup-v1")["queued"], 0)
        self.assertEqual(campaign.queue("job-apply-v1")["queued"], 0)

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
