"""
Tests for the LeverParser card (lab_lever.py) and its place in the second-opinion framework.

What must always hold:
  - the card is registered once, runs only when the team presses its button, and can be switched off;
  - a missing or broken package shows a state on the card and never breaks the Lab;
  - the parse score is honest: a field the parser did not read is marked "missed" and costs points;
  - a phone number the parser invented (not in the resume text) is marked "unclear", never "read";
  - nothing here can change the ATS Lab score or the Job match.

No real resume is used: every text in this file is generated.

  py -3.12 -m unittest test_lever -v
"""

import unittest

import lab_lever as V
import lab_second as SO

# A generated resume that carries every field the card checks.
FULL_CV = """Sara Ahmed
Project Manager | Delivery | Governance
sara.ahmed@mail.com | +971 50 111 2222 | https://linkedin.com/in/saraahmed
Dubai, United Arab Emirates
SUMMARY
Project Manager with nine years of experience leading delivery, governance and reporting for large
programmes across the GCC, working with vendors, finance and engineering teams to keep plans on track.
EXPERIENCE
Project Manager | Acme Consulting | Jan 2019 - Present
- Lead a portfolio of eight programmes with a combined budget of 12 million dollars.
Delivery Lead | Beta Systems | Mar 2015 - Dec 2018
- Ran release planning and reporting for three product teams in Dubai.
EDUCATION
Bachelor of Science, Information Systems - University of Dubai, 2014
SKILLS
Project Management, Governance, Reporting, Stakeholder Management, Vendor Management, Budgeting
"""

# A generated resume that carries no email, no phone and no LinkedIn at all.
THIN_CV = """Omar Khalid
Marketing Assistant
SUMMARY
Marketing assistant with two years of experience in social media scheduling and simple campaign reporting.
EXPERIENCE
Marketing Assistant | Gamma Media | 2022 - 2024
- Scheduled posts and prepared weekly campaign reports for the team.
"""


class FakeContact:
    def __init__(self, name="", email="", phone="", linkedin="", github="", address=""):
        self.name, self.email, self.phone, self.linkedin = name, email, phone, linkedin
        self.github, self.address = github, address


class FakeJob:
    def __init__(self, title="", company="", start=None, end=None, location=""):
        self.title, self.company = title, company
        self.start_date, self.end_date, self.location = start, end, location


class FakeEdu:
    def __init__(self, degree="", institution="", year=None):
        self.degree, self.institution, self.graduation_date = degree, institution, year


class FakeSkill:
    def __init__(self, name=""):
        self.name = name


class FakeResume:
    """What the parser returns, built by hand: these tests check our own logic, not the library's quality."""

    def __init__(self, contact=None, jobs=None, education=None, skills=None):
        self.contact_info = contact or FakeContact()
        self.experience = jobs or []
        self.education = education or []
        self.skills = skills or []

    def get_years_experience(self):
        return None


def states(answer):
    return {f["key"]: f["state"] for f in answer["fields"]}


class TestRegistration(unittest.TestCase):
    def test_registered_once(self):
        self.assertIn("lever", SO.CHECKERS)
        self.assertIn("lever", SO.ORDER)
        self.assertEqual(SO.CHECKERS["lever"]["compares"], "none")

    def test_switch_exists(self):
        import lab_settings as P
        import lab_text as T
        self.assertIn("second_lever", P._TYPES)
        self.assertIn("second_lever", T.SETTINGS_TEXT)
        self.assertEqual(P._TYPES["second_lever"][1], True)

    def test_card_texts_exist(self):
        import lab_text as T
        for key in ("read_lever", "lever_jobs", "lever_education", "lever_skills", "lever_missed",
                    "lever_all_read", "lever_unclear", "lever_note", "lever_tag", "no_score_reference",
                    "unavailable_hint_lever"):
            self.assertIn(key, T.SECOND_TEXT, key)

    def test_admin_page_has_the_card(self):
        import admin_page
        self.assertEqual(admin_page.SECOND_SETTINGS["lever"], "second_lever")


class TestFields(unittest.TestCase):
    def test_everything_read(self):
        resume = FakeResume(
            FakeContact("Sara Ahmed", "sara.ahmed@mail.com", "+971 50 111 2222",
                        "https://linkedin.com/in/saraahmed"),
            [FakeJob("Project Manager", "Acme Consulting", "Jan 2019", "Present")],
            [FakeEdu("Bachelor of Science", "University of Dubai", "2014")],
            [FakeSkill("Project Management")])
        answer = V.answer_of(resume, FULL_CV)
        self.assertEqual(answer["score"], 100)
        self.assertEqual(answer["missed"], [])
        self.assertEqual(states(answer)["phone"], V.READ)

    def test_nothing_read_is_all_missed(self):
        answer = V.answer_of(FakeResume(), FULL_CV)
        self.assertEqual(answer["score"], 0)
        for key in ("name", "email", "phone", "linkedin", "jobs", "job_dates", "education", "skills"):
            self.assertEqual(states(answer)[key], V.MISSED, key)

    def test_fields_the_resume_does_not_have_are_not_missed(self):
        answer = V.answer_of(FakeResume(), THIN_CV)          # no email, no phone, no LinkedIn in the text
        self.assertNotIn("Email", answer["missed"])
        self.assertNotIn("Phone", answer["missed"])
        self.assertNotIn("LinkedIn", answer["missed"])
        # the thin resume does have a job ("2022 - 2024"), so jobs and job dates are real misses
        self.assertIn("Jobs", answer["missed"])

    def test_invented_phone_is_unclear_not_read(self):
        """The parser sometimes adds a country code that is not in the resume: that is not a correct read."""
        resume = FakeResume(FakeContact("Sara Ahmed", phone="+1 971-50-999-8888"))
        answer = V.answer_of(resume, FULL_CV)                # the text has +971 50 111 2222, not 999
        self.assertEqual(states(answer)["phone"], V.UNCLEAR)
        self.assertEqual(answer["unclear"], ["Phone"])
        # the name was read (1) and the phone counts half (0.5): 100 * 1.5 / 8 = 19
        self.assertEqual(answer["score"], 19)

    def test_a_date_range_is_not_a_phone_number(self):
        self.assertFalse(V.expected("Worked at Gamma Media\n2022 - 2024\nDubai")["phone"])
        self.assertTrue(V.expected("Omar Khalid\n+971 50 123 4567\nDubai")["phone"])

    def test_job_dates_missed_when_the_parser_reads_no_dates(self):
        resume = FakeResume(FakeContact("Sara Ahmed"), [FakeJob("Project Manager", "Acme Consulting")])
        answer = V.answer_of(resume, FULL_CV)
        self.assertEqual(states(answer)["jobs"], V.READ)
        self.assertEqual(states(answer)["job_dates"], V.MISSED)

    def test_month_year_dates_count_as_job_dates(self):
        """A resume that writes "Jan 2019 - Present" has job dates: the check must not call them absent."""
        self.assertTrue(V.expected(FULL_CV)["job_dates"])
        self.assertTrue(V.expected("Worked at Acme\nMar 2015 - Dec 2018\nDubai")["job_dates"])

    def test_parse_label_is_not_the_ats_scale(self):
        self.assertEqual(V.parse_label(100), "Reads almost everything")
        self.assertEqual(V.parse_label(0), "Reads little")
        self.assertNotIn("Strong", V.parse_label(85))

    def test_long_fields_are_trimmed(self):
        job = FakeJob("A" * 200, "B" * 200)
        row = V.job_row(job)
        self.assertLessEqual(len(row["title"]), V.MAX_FIELD + 3)
        self.assertLessEqual(len(row["company"]), V.MAX_FIELD + 3)


class TestRun(unittest.TestCase):
    def test_unavailable_when_the_package_is_missing(self):
        saved = V._pyresume
        V._pyresume = None
        try:
            self.assertEqual(V.available(), (False, "not_installed"))
            self.assertEqual(V.run(FULL_CV), {"state": V.UNAVAILABLE, "why": "not_installed"})
            self.assertEqual(SO.run("lever", {"_doc": {"modern": FULL_CV}}),
                             {"state": SO.UNAVAILABLE, "why": "not_installed"})
        finally:
            V._pyresume = saved

    def test_no_text_is_never_a_score(self):
        self.assertEqual(V.run("")["state"], V.FAILED)
        self.assertEqual(V.run("")["why"], "no_text")
        self.assertEqual(SO.run("lever", {"_doc": {"modern": "too short"}})["why"], "no_text")

    def test_a_broken_parser_never_raises(self):
        class Boom:
            def parse_text(self, text):
                raise RuntimeError("broken")

        saved = V._PARSER
        V._PARSER = Boom()
        try:
            out = SO.run("lever", {"_doc": {"modern": FULL_CV}})
            self.assertEqual(out["state"], SO.FAILED)
            self.assertEqual(out["why"], "RuntimeError")
        finally:
            V._PARSER = saved

    def test_switched_off(self):
        self.assertEqual(SO.run("lever", {"_doc": {"modern": FULL_CV}}, settings={"lever": False}),
                         {"state": SO.OFF})

    @unittest.skipIf(not V.available()[0], "leverparser is not installed here")
    def test_real_parser_on_generated_text(self):
        first = V.run(FULL_CV)
        second = V.run(FULL_CV)
        self.assertEqual(first["state"], V.DONE)
        self.assertEqual(first["score"], second["score"])            # the same text always gives the same score
        self.assertGreaterEqual(first["score"], 0)
        self.assertLessEqual(first["score"], 100)
        self.assertIn("sara.ahmed@mail.com", str(first["fields"]))

    @unittest.skipIf(not V.available()[0], "leverparser is not installed here")
    def test_real_parser_never_raises_on_junk(self):
        out = V.run("X" * 200)
        self.assertIn(out["state"], (V.DONE, V.FAILED))


class TestNeverChangesTheLab(unittest.TestCase):
    def test_no_reference_and_no_agreement(self):
        res = {"score": 71.5, "parts": {"job_match": 60}}
        answer = SO.finish("lever", res, {"state": SO.DONE, "score": 88, "source": "lever"})
        self.assertIsNone(answer["reference"])
        self.assertIsNone(answer["agree"])
        self.assertEqual(answer["difference"], "")

    def test_excluded_from_the_agreement_headline(self):
        answers = {"lever": {"state": SO.DONE, "score": 88, "source": "lever", "agree": None}}
        self.assertEqual(SO.headline(answers), "")

    def test_the_result_is_not_touched(self):
        res = {"score": 71.5, "parts": {"job_match": 60}, "_doc": {"modern": FULL_CV}}
        before = repr(res)
        SO.run("lever", res)
        self.assertEqual(repr(res), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
