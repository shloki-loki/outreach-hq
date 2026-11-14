"""The GitHub workers: live check, research, writing, people and the Apify sources.

The model and the network are replaced by fakes, so these tests check the gates around the model: what
is refused, what is stored, and that nothing weak reaches the approval queue.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

os.environ["OUTREACH_NO_GIT"] = "1"

from outreach import live, llm, messages, people, research, store, writer  # noqa: E402
from outreach.sources import apify  # noqa: E402
from outreach.util import HttpError  # noqa: E402

from tests.test_pipeline import GOOD_BODY, Base  # noqa: E402

POSTING = ("About Acme: Acme runs same-day dispatch for 2,000 grocery stores across Bengaluru. "
           "We are hiring a Founder's Office Associate to work with the CEO on planning, dispatch and inventory. "
           "You have 1-3 years of experience in operations or strategy, are comfortable with SQL and Excel, and "
           "have run a planning cycle end to end. ") * 3
SOURCE = "https://acme.com/blog/same-day"


def judged(**overrides) -> dict:
    payload = {"decision": "qualify", "research_score": 80, "reject_reason": "",
               "headline": "Founder's Office at a dispatch startup, asks 1-3 yrs; your S&OP and dispatch work maps directly.",
               "fit_notes": "Asks 1-3 yrs, SQL, planning. Matches sop and o2d. Missing nothing hard.",
               "matched_facts": ["sop", "o2d"],
               "pay": {"min_lpa": None, "max_lpa": None, "basis": "unknown", "stated": "", "source": ""},
               "pay_notes": "No figure found.", "culture_notes": "Glassdoor 4.1 (40 reviews).",
               "hook": "Acme runs same-day dispatch for 2,000 stores in Bengaluru", "hook_source": SOURCE,
               "company_domain": "acme.com", "company_url": "https://acme.com", "work_mode": "onsite"}
    payload.update(overrides)
    return payload


class FakeModel:
    """Answers each call in turn from a script; records the prompts it saw."""

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, llm.Reply):
            return answer
        return llm.Reply(text=json.dumps(answer), model=kwargs.get("model", "fake"))


EVIDENCE = llm.Reply(text=json.dumps({"what_they_do": "same-day dispatch", "pay_evidence": [
    {"site": "AmbitionBox", "title": "Associate", "range_lpa": "20-28", "sample": "9 salaries", "fixed_or_total": "fixed"}]}),
    model="fake", sources=[{"title": "acme.com", "url": SOURCE}])


class LiveCheckTest(Base):
    def test_only_clear_signals_close_a_posting(self):
        self.assertTrue(live.CLOSED_TEXT.search('<figcaption class="closed-job__flavor--closed">No longer accepting applications'))
        self.assertTrue(live.CLOSED_TEXT.search("This position has been filled."))
        self.assertFalse(live.CLOSED_TEXT.search("Applications accepted on an ongoing basis until the position is filled."))
        lead = self.add_lead(source="greenhouse", source_id="acme:1")
        with mock.patch.object(live, "http_json", side_effect=HttpError(404, "x")):
            self.assertTrue(live.probe(lead)[0])
        with mock.patch.object(live, "http_json", side_effect=HttpError(429, "x")):
            with self.assertRaises(live.Unknown):
                live.probe(lead)

    def test_closed_leads_go_to_the_bin_but_conversations_stay(self):
        lead = self.add_lead(source="greenhouse", source_id="acme:1")
        talking = self.add_lead(source="greenhouse", source_id="acme:2", title="Chief of Staff")
        data = store.load("leads")
        store.find(data["leads"], talking["id"])["replied_at"] = "2026-11-14T10:00:00+05:30"
        store.save("leads", data)
        with mock.patch.object(live, "http_json", side_effect=HttpError(404, "x")), mock.patch.object(live.store, "sync"):
            result = live.run()
        self.assertEqual(result["binned_ids"], [lead["id"]])
        stored = {l["id"]: l for l in store.load("leads")["leads"]}
        self.assertFalse(stored[lead["id"]]["open"])
        self.assertIn("no longer exists", stored[lead["id"]]["bin"]["reason"])
        self.assertNotEqual(stored[talking["id"]].get("open"), False)


class ResearchWorkerTest(Base):
    def setUp(self):
        super().setUp()
        patches = [mock.patch.object(research.store, "sync"), mock.patch.object(llm, "key", return_value="k"),
                   mock.patch.object(research, "pick_models", return_value={"research": "r", "judge": "j"}),
                   mock.patch.object(llm, "resolve", side_effect=lambda url: url),
                   mock.patch.object(live, "probe", return_value=(False, ""))]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def new_lead(self, **overrides):
        lead = self.add_lead(**overrides)
        data = store.load("leads")
        stored = store.find(data["leads"], lead["id"])
        stored["stage"], stored["jd"], stored["source_url"] = "new", POSTING, "https://acme.com/jobs/1"
        store.save("leads", data)
        return stored

    def test_a_sound_answer_is_stored_as_machine_research(self):
        lead = self.new_lead()
        model = FakeModel(EVIDENCE, judged())
        with mock.patch.object(llm, "generate", side_effect=model):
            result = research.run(limit=5)
        self.assertEqual(result["qualified"], 1, result)
        stored = store.find(store.load("leads")["leads"], lead["id"])
        self.assertEqual(stored["stage"], "qualified")
        self.assertEqual(stored["research"]["by"], "research-worker")
        self.assertEqual(stored["research"]["review"], "pending")
        self.assertNotIn("9343806463", model.prompts[1])   # contact details never reach the model
        self.assertNotIn("Beltech", model.prompts[1])

    def test_without_grounding_evidence_is_fetched_and_still_sourced(self):
        lead = self.new_lead()
        data = store.load("leads")
        store.find(data["leads"], lead["id"])["company_url"] = "https://acme.com"
        store.save("leads", data)
        site = b"<html><body>" + b"Acme runs same-day dispatch for D2C brands across 40 Indian cities. " * 6 + b"</body></html>"
        feed = (b"<rss><channel><item><title>Acme raises Series B</title><link>https://news.example.com/a</link>"
                b"<pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate><source url='https://x.com'>ET</source></item></channel></rss>")
        fetched = json.dumps({"what_they_do": "same-day dispatch", "recent_fact": {"fact": "raised Series B",
                                                                                  "url": "https://news.example.com/a"}})
        model = FakeModel(llm.Reply(text=fetched, model="j"), judged(hook_source="https://news.example.com/a"))
        get = lambda url, **kw: feed if "news.google.com" in url else site
        with mock.patch.object(research, "pick_models", return_value={"research": None, "judge": "j"}), \
                mock.patch.object(research, "http_get", side_effect=get), mock.patch.object(llm, "generate", side_effect=model):
            result = research.run(limit=5)
        self.assertEqual(result["qualified"], 1, result)
        stored = store.find(store.load("leads")["leads"], lead["id"])
        self.assertEqual([s["url"] for s in stored["research"]["sources"]], ["https://acme.com", "https://news.example.com/a"])
        self.assertIn("fetched", stored["research"]["evidence_model"])
        self.assertIn("[S2]", model.prompts[0])

    def test_a_key_without_grounding_falls_back_to_fetched_evidence(self):
        research._GROUNDING_OFF = False
        self.addCleanup(setattr, research, "_GROUNDING_OFF", False)
        calls = []
        def generate(prompt, **kw):
            calls.append(kw.get("search"))
            if kw.get("search"):
                raise llm.LlmError("Gemini HTTP 404: This model models/gemini-2.5-flash is no longer available to new users")
            return llm.Reply(text="{}", model="j")
        with mock.patch.object(llm, "generate", side_effect=generate), \
                mock.patch.object(research, "http_get", return_value=b"<rss><channel></channel></rss>"):
            evidence, sources = research.gather_evidence({"company": "Acme", "title": "x", "company_note": "AmbitionBox 4.1"},
                                                         {"research": "gemini-2.5-flash", "judge": "j"})
        self.assertEqual(calls, [True, None])
        self.assertTrue(research._GROUNDING_OFF)
        self.assertEqual(sources, [])

    def test_invented_source_and_seniority_are_caught_and_retried(self):
        self.new_lead()
        bad = judged(hook_source="https://made-up.example.com/news")
        model = FakeModel(EVIDENCE, bad, bad)
        with mock.patch.object(llm, "generate", side_effect=model):
            result = research.run(limit=5)
        self.assertEqual(result["left_for_a_person"], 1)
        self.assertIn("previous answer broke these rules", model.prompts[2])
        lead = store.load("leads")["leads"][0]
        self.assertEqual(lead["stage"], "new")
        self.assertIn("hook_source", lead["research_attempt"]["why"])

    def test_checks(self):
        lead = self.new_lead()
        evidence = json.loads(EVIDENCE.text)
        sources = [{"id": "S1", "url": SOURCE}]
        ok = research.check(judged(), lead, POSTING, "https://acme.com/jobs/1", evidence, sources)
        self.assertEqual(ok, [])
        senior = research.check(judged(), lead, "Requires 7+ years of experience in strategy.", "u", evidence, sources)
        self.assertTrue(any("stretch limit" in p for p in senior), senior)
        guessed = research.check(judged(pay={"min_lpa": 25, "max_lpa": 30, "basis": "estimate", "source": "industry norms"}),
                                 lead, POSTING, "u", evidence, sources)
        self.assertTrue(any("estimated pay" in p for p in guessed), guessed)
        sourced = research.check(judged(pay={"min_lpa": 20, "max_lpa": 28, "basis": "estimate",
                                             "source": "AmbitionBox, 9 salaries, fixed"}), lead, POSTING, "u", evidence, sources)
        self.assertEqual(sourced, [])
        no_facts = research.check(judged(matched_facts=["mba"]), lead, POSTING, "u", evidence, sources)
        self.assertTrue(any("do not exist" in p for p in no_facts))
        stated = research.check(judged(pay={"min_lpa": 30, "max_lpa": 40, "basis": "stated"}), lead, POSTING, "u", evidence, sources)
        self.assertTrue(any("states no figure" in p for p in stated))

    def test_no_posting_text_means_no_decision(self):
        lead = self.new_lead()
        data = store.load("leads")
        store.find(data["leads"], lead["id"]).update(jd="", source="linkedin_post")
        store.save("leads", data)
        with mock.patch.object(llm, "generate", side_effect=AssertionError("model must not be called")):
            result = research.run(limit=5)
        self.assertEqual(result["left_for_a_person"], 1)


class WriterTest(Base):
    def setUp(self):
        super().setUp()
        lead = self.add_lead()
        data = store.load("leads")
        self.lead = store.find(data["leads"], lead["id"])
        self.lead["research"].update(done=True, hook="Acme runs same-day dispatch for 2,000 stores in Bengaluru",
                                     hook_source=SOURCE, headline="x" * 40, fit_notes="fits")
        self.lead["jd"] = POSTING
        self.lead["score"]["total"] = 70   # under 80: the question play
        store.save("leads", data)
        for patch in (mock.patch.object(writer.store, "sync"), mock.patch.object(llm, "key", return_value="k"),
                      mock.patch.object(writer, "pick_models", return_value={"writer": "w", "judge": "j"})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_fact_check_catches_invented_numbers(self):
        self.assertEqual(writer.fact_check(GOOD_BODY, self.lead), [])
        inflated = GOOD_BODY.replace("came down to 14", "came down to 9")
        self.assertTrue(any("9" in p for p in writer.fact_check(inflated, self.lead)))

    def test_a_draft_passing_every_gate_is_queued_with_its_play(self):
        draft = {"subject": "dispatch lots at Acme", "body": GOOD_BODY, "promise": ""}
        critic = {"would_reply": 8, "reads_mass_produced": False, "unsupported_claims": [], "unclear": [], "fix": ""}
        with mock.patch.object(llm, "generate", side_effect=FakeModel(draft, critic)):
            result = writer.run(linkedin_limit=0)
        self.assertEqual(result["cold"], 1, result)
        message = store.load("messages")["messages"][0]
        self.assertEqual((message["status"], message["play"], message["created_by"]), ("draft", "question", "writer"))

    def test_a_weak_draft_never_reaches_the_queue(self):
        weak = {"subject": "Application for Founder's Office", "body": GOOD_BODY.replace("I'm interested", "I am excited"), "promise": ""}
        with mock.patch.object(llm, "generate", side_effect=FakeModel(weak, weak, weak)):
            result = writer.run(linkedin_limit=0)
        self.assertEqual((result["cold"], result["dropped"]), (0, 1))
        self.assertEqual(store.load("messages")["messages"], [])
        self.assertIn("could not produce", store.load("leads")["leads"][0]["notes"][-1]["text"])

    def test_critic_can_send_a_draft_back(self):
        draft = {"subject": "dispatch lots at Acme", "body": GOOD_BODY, "promise": ""}
        harsh = {"would_reply": 4, "reads_mass_produced": True, "unsupported_claims": [], "unclear": [], "fix": "be specific"}
        with mock.patch.object(llm, "generate", side_effect=FakeModel(draft, harsh, draft, harsh, draft, harsh)):
            result = writer.run(linkedin_limit=0)
        self.assertEqual(result["cold"], 0)

    def test_play_choice(self):
        self.assertEqual(writer.choose_play({"type": "company"}, {"role_type": "founder"}), "offer")
        self.assertEqual(writer.choose_play({"type": "job"}, {"role_type": "recruiter"}), "direct")
        self.assertEqual(writer.choose_play({"type": "job", "score": {"total": 85}}, {"role_type": "founder"}), "offer")
        self.assertEqual(writer.choose_play({"type": "job", "score": {"total": 70}}, {"role_type": "founder"}), "question")


class PeopleAndSourcesTest(Base):
    def test_people_are_picked_by_role(self):
        items = [
            {"firstName": "Ann", "lastName": "Co", "linkedinUrl": "u1", "currentPositions": [{"title": "Co-Founder", "companyName": "Acme"}]},
            {"firstName": "Bo", "lastName": "Fo", "linkedinUrl": "u2", "currentPositions": [{"title": "Director, Chief of Staff", "companyName": "Acme"}]},
            {"firstName": "Cy", "lastName": "Ta", "linkedinUrl": "u3", "currentPositions": [{"title": "Senior Manager Talent Acquisition", "companyName": "Acme"}]},
            {"firstName": "Di", "lastName": "En", "linkedinUrl": "u4", "currentPositions": [{"title": "Software Engineer", "companyName": "Acme"}]},
        ]
        picked = people.choose(items, "Acme")
        self.assertEqual([p["role_type"] for p in picked], ["hiring_manager", "founder", "recruiter"])
        self.assertEqual(people.company_url({"company_linkedin": "https://in.linkedin.com/company/gokwik"}),
                         "https://www.linkedin.com/company/gokwik")

    def test_apify_rows_become_jobs(self):
        naukri = apify.naukri_jobs([
            {"id": 1, "title": "Chief of Staff", "url": "https://naukri.com/j/1", "consultant": False, "createdDate": 1794655877165,
             "company": {"name": "Acme"}, "salary": {"label": "25-35 Lacs"}, "experience": {"text": "1-3 Yrs"},
             "locations": [{"label": "Bengaluru"}], "ambitionBox": {"companyInfo": {"AggregateRating": "4.1", "ReviewsCount": "50"}}},
            {"id": 2, "title": "Founder's Office", "consultant": True, "company": {"name": "Agency"}}])
        self.assertEqual(len(naukri), 1)
        self.assertEqual((naukri[0]["pay_text"], naukri[0]["posted_at"][:4]), ("25-35 Lacs", "2026"))
        cafe = apify.hiringcafe_jobs([{"objectID": "x", "apply_url": "https://acme.com/j", "is_expired": False,
                                       "job_information": {"title": "Chief of Staff to the CTO"},
                                       "v5_processed_job_data": {"company_name": "Exotel", "formatted_workplace_location": "Bengaluru",
                                                                 "listed_compensation_currency": "INR", "yearly_min_compensation": 2500000,
                                                                 "yearly_max_compensation": 3500000, "company_website": "exotel.com"}}])
        self.assertEqual((cafe[0]["pay_text"], cafe[0]["company_url"]), ("Rs 25.0-35.0 LPA", "https://exotel.com"))
        well = apify.wellfound_jobs([{"id": 9, "title": "Chief of Staff", "company_name": "Cube", "location_names": ["HSR Layout"],
                                      "years_experience_min": 2, "company_slug": "cube-fi", "remote": False}])
        self.assertEqual(well[0]["experience_text"], "2+ years")

    def test_apify_never_runs_past_the_monthly_cap(self):
        with mock.patch.object(apify, "token", return_value="t"), mock.patch.object(apify, "month_usage_usd", return_value=3.45), \
                mock.patch.object(apify, "http_get", side_effect=AssertionError("must not call Apify")):
            with self.assertRaises(apify.BudgetSpent):
                apify.run_actor("a/b", {}, max_usd=0.1)

    def test_paid_sources_are_quiet_without_a_token(self):
        with mock.patch.object(apify, "token", return_value=None):
            self.assertEqual(apify.naukri.fetch({"apify": {"naukri": {"keywords": ["x"], "locations": ["y"]}}}, {}), ([], []))


class ParseTest(unittest.TestCase):
    def test_json_is_found_inside_prose_and_fences(self):
        self.assertEqual(llm.parse_json('Sure:\n```json\n{"a": {"b": "}"}}\n```'), {"a": {"b": "}"}})
        self.assertEqual(llm.parse_json('x {"a": 1} y'), {"a": 1})
        with self.assertRaises(llm.LlmError):
            llm.parse_json("no json here")


if __name__ == "__main__":
    unittest.main()
