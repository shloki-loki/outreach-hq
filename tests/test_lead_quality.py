"""Lead quality rules from Shlok's review on 2026-11-23."""

import unittest

from outreach.rules import judge, ineligible
from outreach.sources.alerts import parse_alert
from outreach.util import load_config

TARGETING = load_config("targeting")


def job(title, description="", company="Acme", location="Bengaluru"):
    return {"source": "linkedin", "source_id": "1", "title": title, "company": company, "location": location,
            "description": description, "pay_text": "", "posted_at": None}


class Eligibility(unittest.TestCase):
    def test_graduate_program_is_dropped(self):
        verdict = judge(job("Associate Product Manager, University Graduate, 2027 Start", "Join our APM program."),
                        TARGETING)
        self.assertFalse(verdict.keep)
        self.assertIn("not open to him", verdict.reject_reason)

    def test_current_students_are_dropped(self):
        self.assertTrue(ineligible("Strategy Analyst", "Open to final year students graduating in 2027.", TARGETING))

    def test_edtech_wording_is_not_a_student_program(self):
        self.assertIsNone(ineligible("Founder's Office", "We help 2 million students learn coding.", TARGETING))


class Experience(unittest.TestCase):
    def test_more_than_three_years_is_dropped(self):
        verdict = judge(job("Chief of Staff", "Requirements: 8+ years of experience in executive roles."), TARGETING)
        self.assertFalse(verdict.keep)
        self.assertIn("8", verdict.reject_reason)

    def test_four_years_is_now_dropped(self):
        self.assertFalse(judge(job("Founder's Office Associate", "4+ years of experience."), TARGETING).keep)

    def test_not_stated_gets_no_bonus(self):
        verdict = judge(job("Founder's Office Associate", "Own special projects with the CEO."), TARGETING)
        self.assertTrue(verdict.keep)
        self.assertIn("Experience not stated (+0)", verdict.reasons)

    def test_senior_title_without_years_is_dropped(self):
        verdict = judge(job("Senior Manager, CEO's Office", "Work with the CEO on strategy."), TARGETING)
        self.assertFalse(verdict.keep)

    def test_senior_title_with_fitting_years_is_kept(self):
        self.assertTrue(judge(job("Senior Analyst, Strategy", "2+ years of experience."), TARGETING).keep)


ALERT = """Your job alert for Founder in Bengaluru
New jobs match your preferences.

Founder's Office - Associate
Zamp
Bengaluru
Actively recruiting
View job: https://www.linkedin.com/comm/jobs/view/4312345678/?trackingId=x&otpToken=SECRET

---------------------------------------------------------

Business Operations Analyst
PhonePe
Bengaluru
2 connections work here
View job: https://www.linkedin.com/comm/jobs/view/4398765432/?otpToken=SECRET2
"""


class Alerts(unittest.TestCase):
    def test_parses_jobs_and_drops_the_sign_in_token(self):
        jobs = parse_alert(ALERT)
        self.assertEqual([(j["title"], j["company"], j["location"]) for j in jobs],
                         [("Founder's Office - Associate", "Zamp", "Bengaluru"),
                          ("Business Operations Analyst", "PhonePe", "Bengaluru")])
        self.assertEqual(jobs[0]["url"], "https://www.linkedin.com/jobs/view/4312345678/")
        self.assertTrue(all("otpToken" not in j["url"] and "otpToken" not in j["apply_url"] for j in jobs))


if __name__ == "__main__":
    unittest.main()
