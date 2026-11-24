import unittest

from outreach import inmail, messages


def lead(**extra):
    base = {"id": "L1", "type": "job", "stage": "qualified", "title": "Founder's Office - BizOps", "company": "Helium",
            "source_url": "https://in.linkedin.com/jobs/view/founders-office-at-helium-4012345678?trk=abc&otpToken=x"}
    base.update(extra)
    return base


class InMailTest(unittest.TestCase):
    def test_renders_and_passes_the_linkedin_check(self):
        note, problems = inmail.render(lead())
        self.assertEqual(problems, [])
        self.assertEqual(note["job_url"], "https://www.linkedin.com/jobs/view/4012345678/")
        self.assertNotIn("otpToken", note["body"])
        self.assertIn("Founder's Office - BizOps role at Helium", note["body"])
        self.assertTrue(note["body"].startswith("Hi {first_name},"))
        self.assertEqual(note["subject"], "Founder's Office")

    def test_only_the_posting_link_is_allowed(self):
        note, _ = inmail.render(lead())
        body = note["body"].replace("{first_name}", "Priya")
        self.assertEqual(messages.check_linkedin("inmail", body, to_name="Priya", subject="x", job_url=note["job_url"]), [])
        extra = body.replace("Shlok", "See https://example.com\n\nShlok")
        self.assertTrue(any("link" in p for p in messages.check_linkedin("inmail", extra, to_name="Priya", subject="x",
                                                                         job_url=note["job_url"])))
        self.assertTrue(any("link" in p for p in messages.check_linkedin("inmail", body, to_name="Priya", subject="x")))

    def test_names(self):
        self.assertEqual(inmail.company_name("Flipkart (Flipkart Minutes)"), "Flipkart")
        self.assertEqual(inmail.company_name("ExxonMobil India Careers"), "ExxonMobil India")
        self.assertEqual(inmail.role_name("Digital Product Manager [T500-30912]"), "Digital Product Manager")
        self.assertEqual(inmail.role_name("Business Analyst - Payments, Business Analyst - Payments"), "Business Analyst - Payments")
        self.assertEqual(inmail.subject_for(lead(title="Manager - Supply Planning", company="PepsiCo")), "Manager at PepsiCo")
        note, problems = inmail.render(lead(company="Undisclosed AI company"))
        self.assertEqual(problems, [])
        self.assertNotIn("Undisclosed", note["body"])

    def test_exxonmobil_is_not_a_placeholder(self):
        _, problems = inmail.render(lead(company="ExxonMobil", title="Supply Planner"))
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
