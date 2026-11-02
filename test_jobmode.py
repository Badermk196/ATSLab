"""
"With job description" mode: the job title typed by the user, the severity of missing skills, the skills kept from a
posting, abbreviations that are in the resume, one card for the job title, AI gap findings that follow the Lab's own
timeline, and the sentence under the score. No AI call is made here: saved AI reviews and saved job keywords only.

  py -3.12 -m unittest test_jobmode -v
"""

import io
import os
import re
import shutil
import tempfile
import unittest

os.environ["ATSLAB_AI_REVIEW"] = "0"
os.environ.pop("OPENROUTER_API_KEY", None)

from reportlab.pdfgen import canvas
from streamlit.testing.v1 import AppTest

import ATSLab_v3 as L
import cv_review as R
import cv_score as C
import dashboard as D
import test_dashboard as T

HERE = os.path.dirname(os.path.abspath(__file__))
CV = os.path.join(HERE, "testcvs", "Rowan_Elatrache_CV_single_column.pdf")
JOB = os.path.join(HERE, "testcvs", "OSN_Brand_Content_Marketing_Manager.txt")
JOB_KEYWORDS = os.path.join(HERE, "testcvs", "OSN_Brand_Content_Marketing_Manager_keywords_v3.json")
TITLE = "Brand & Content Marketing Manager"
mi = lambda y, m: y * 12 + m - 1                                     # month number, as the timeline uses


def saved_reviews_only(run):
    """Run `run()` with the AI reviewer on but answering from the saved reviews only (cv_reviews\\): no API call."""
    D.fresh_modules()                                                # the check reloads changed modules: do it first
    saved_key, real, ai_on = os.environ.get("OPENROUTER_API_KEY"), L.call_ai, D.AI_REVIEW
    os.environ["OPENROUTER_API_KEY"] = "saved-reviews-only"
    L.call_ai = lambda *a, **k: None
    D.AI_REVIEW = True
    try:
        return run()
    finally:
        L.call_ai, D.AI_REVIEW = real, ai_on
        if saved_key is None:
            os.environ.pop("OPENROUTER_API_KEY", None)
        else:
            os.environ["OPENROUTER_API_KEY"] = saved_key


_osn = {}


def osn():
    """Rowan's single-column resume against the OSN+ job: the real case these rules came from."""
    if "r" not in _osn:
        cache = tempfile.mkdtemp()
        with open(JOB, encoding="utf-8") as f:
            text = f.read()
        shutil.copy(JOB_KEYWORDS, D.job_file(text, cache)[:-4] + "_keywords_v3.json")
        with open(CV, "rb") as f:
            data = f.read()
        _osn["r"] = saved_reviews_only(lambda: D.run_check(data, "rowan.pdf", True, text, cache, cache, job_title=TITLE))
        shutil.rmtree(cache, ignore_errors=True)
    return _osn["r"]


class TestJobTitleField(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()
        T.seed(self.cache)

    def tearDown(self):
        shutil.rmtree(self.cache, ignore_errors=True)

    def test_a_job_title_is_required_with_a_job_description(self):
        for title in (None, "", "   "):
            with self.subTest(title=title):
                with self.assertRaisesRegex(D.CheckError, "target role"):
                    D.run_check(T.cv_bytes(), "neda.pdf", True, T.job_text(), self.cache, self.cache, job_title=title)
        r = D.run_check(T.cv_bytes(), "neda.pdf", False, "", self.cache, self.cache)      # no job: no title needed
        self.assertNotEqual(r["mode"], "job")

    def test_the_typed_title_is_used_not_the_one_in_the_posting(self):
        r = D.run_check(T.cv_bytes(), "neda.pdf", True, T.job_text(), self.cache, self.cache,
                        job_title="  Senior   Release Manager ")
        self.assertEqual(r["target"], "Senior Release Manager")                   # spaces tidied
        self.assertEqual(r["v3"]["job_title"], "Senior Release Manager")
        self.assertEqual(r["v3"]["title_source"], "user")
        f3 = r["v3"]["ats"]["oracle"]["checks"]["F3"]["detail"]
        self.assertIn("Senior Release Manager", f3)                               # the title check uses it
        self.assertNotIn("Delivery Lead", f3)                                     # the posting's own title is not used

    def test_the_title_is_in_the_report_header_and_the_sentence_names_the_job(self):
        r = D.run_check(T.cv_bytes(), "neda.pdf", True, T.job_text(), self.cache, self.cache, job_title="Delivery Lead")
        h = D.header_html(r)
        self.assertIn("<dt>Target role</dt><dd>Delivery Lead</dd>", h)
        self.assertIn("With a job description", h)
        self.assertNotIn("target role", h)
        doc = D.report_document(r)
        sentence = re.search(r'<div class="plain">(.*?)</div>', doc, re.S).group(1)
        self.assertEqual(sentence, "This resume scored %s out of 100: the score shows how easily an ATS can read this "
                                   "resume, how well it meets the 1000Jobs standard, and how well it matches this job."
                         % D.fmt(r["score"]))
        plain = D.run_check(T.cv_bytes(), "neda.pdf", False, "", self.cache, self.cache)
        self.assertNotIn("matches this job", re.search(r'<div class="plain">(.*?)</div>',
                                                       D.report_document(plain), re.S).group(1))
        self.assertNotIn("Target role", D.header_html(plain))


class TestUploadCard(unittest.TestCase):
    def test_the_title_field_is_next_to_the_job_description_and_only_with_a_job(self):
        at = AppTest.from_file(os.path.join(HERE, "dashboard.py"), default_timeout=120).run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual([t.label for t in at.text_input], ["Target role (job title)"])
        self.assertEqual([t.label for t in at.text_area], ["Job description"])
        at.radio[0].set_value(D.WITHOUT_JOB).run()
        self.assertFalse(at.text_input)


class TestSeverityOfMissingSkills(unittest.TestCase):
    kw = lambda self, *items: {"keywords": [{"term": t, "type": ty, "match": m} for t, ty, m in items]}

    def test_a_missing_required_skill_is_important_preferred_only_is_minor(self):
        both = self.kw(("CRM", "required", "missing"), ("Tableau", "preferred", "missing"))
        pref = self.kw(("CRM", "required", "exact"), ("Tableau", "preferred", "missing"))
        self.assertEqual(C.rule_severity("K", res=both), "Major")                 # "Major" is shown as Important
        self.assertEqual(C.rule_severity("K", res=pref), "Minor")

    def test_the_real_case(self):
        r = osn()
        card = next(c for c in D.issue_cards(r) if c["key"] == "skills_missing")
        self.assertEqual(card["tag"], "Important")
        self.assertEqual(sorted(r["missing_required"]), sorted(
            k["term"] for k in r["v3"]["keywords"] if k["match"] == "missing" and k["type"] == "required"))
        quotes = D.evidence(card, r)
        self.assertTrue(quotes[0].startswith("Required, not found in the resume: "), quotes)
        self.assertTrue(quotes[1].startswith("Preferred, not found: "), quotes)       # preferred skills apart


class TestSkillsKept(unittest.TestCase):
    JOB = ("About the role. The Brand Marketing Manager owns brand marketing and content marketing for the region. "
           "You will use CRM tools and project management methods to plan every campaign. Good brand judgement and "
           "creative evaluation are essential, and you will write clear messaging for each launch. Requirements: "
           "five years of experience in brand marketing, content marketing, CRM and project management. "
           "Responsibilities include campaign planning, budget tracking and reporting to the marketing director.")

    def test_searchable_skills_stay_and_qualities_go(self):
        raw = {"title": "Brand Marketing Manager", "preferred_skills": [], "soft_skills": [],
               "required_skills": ["Brand Marketing", "Content Marketing", "CRM", "Project Management",
                                   "Brand judgement", "Creative evaluation", "Messaging"]}
        kw = L.clean_keywords(raw, self.JOB)
        kept = [s.lower() for s in kw["required_skills"] + kw["preferred_skills"]]
        for skill in ("brand marketing", "content marketing", "crm", "project management"):
            self.assertIn(skill, kept)
        for gone in ("brand judgement", "creative evaluation", "messaging"):
            self.assertNotIn(gone, kept)
        why = {d["term"]: d["reason"] for d in kw["dropped"]}
        self.assertEqual(why["Brand judgement"], "a quality, not a searchable skill")
        self.assertEqual(why["Creative evaluation"], "a quality, not a searchable skill")
        self.assertIn("Messaging", why)

    def test_the_prompt_says_so(self):
        self.assertIn("brand judgement", L.KEYWORD_PROMPT)
        self.assertIn("Project Management", L.KEYWORD_PROMPT)

    def test_the_real_case_lists_none_of_them(self):
        r = osn()
        terms = [k["term"].lower() for k in r["v3"]["keywords"]]
        for t in ("brand marketing", "content marketing", "crm", "project management"):
            self.assertIn(t, terms)
        for gone in ("brand judgement", "creative evaluation", "messaging"):
            self.assertNotIn(gone, terms)


class TestAbbreviationsOnlyForTermsInTheResume(unittest.TestCase):
    def f2(self, resume_text, skills):
        doc = {"strict": resume_text, "modern": resume_text, "rows": []}
        kw = {"required_skills": skills, "preferred_skills": [], "title": "Manager"}
        return L.findable_static(doc, L.analyse(doc), kw, None, L.ATS_PROFILES["oracle"])["F2"]

    def test_a_skill_missing_from_the_resume_is_not_written_one_way(self):
        c = self.f2("Marketing Manager\nPlanned campaigns with Excel and Tableau.", ["CRM"])
        self.assertIsNone(c["score"])                                            # no card: it is a missing skill
        self.assertEqual(c["detail"], "no abbreviation term of this job is in the resume")

    def test_a_skill_in_the_resume_in_one_form_is_written_one_way(self):
        c = self.f2("Marketing Manager\nManaged the CRM and reporting.", ["CRM"])
        self.assertEqual(c["score"], 0.0)
        self.assertIn("0/1", c["detail"])

    def test_both_forms_pass_and_only_present_terms_count(self):
        text = "Managed the CRM (customer relationship management). Ran SEO audits."
        c = self.f2(text, ["CRM", "SEO", "KPI"])
        self.assertEqual(c["detail"], "1/2 written both ways")                   # KPI is not in the resume: not counted

    def test_the_real_case_has_no_abbreviation_card(self):
        r = osn()
        self.assertNotIn("Abbreviations are written only one way", [c["name"] for c in D.issue_cards(r)])
        self.assertIn("crm", [s.lower() for s in r["missing_skills"]])


class TestOneJobTitleCard(unittest.TestCase):
    def test_which_ai_findings_are_the_job_title_problem(self):
        yes = ("Job title mismatch with target role", "Role mismatch with target position",
               "Inconsistent job title for target role")
        no = ("Inconsistent job titles for the same role", "Unexplained employment gap", "Education listed as work experience",
              "Few results", "Target audience unclear")
        for n in yes:
            self.assertTrue(D.is_title_mismatch({"name": n}), n)
        for n in no:
            self.assertFalse(D.is_title_mismatch({"name": n}), n)

    def test_the_real_case_has_one_card_for_it(self):
        r = osn()
        cards = D.issue_cards(r)
        names = [c["name"] for c in cards]
        self.assertEqual(names.count("The job title is not near the top"), 1)
        self.assertEqual([n for n in names if D.is_title_mismatch({"name": n})], [])      # no second, AI card
        card = next(c for c in cards if c["key"] == "job_title")
        ai = [i for i in card["issues"] if i.get("ai")]
        self.assertTrue(ai, "the saved AI review has a job title finding")
        self.assertEqual(card["also"], [i["name"] for i in ai])                           # "Also covers: ..."
        self.assertEqual(D.card_part(card), "job_match")
        self.assertEqual(card["tag"], "Important")                                        # the AI finding is Important
        self.assertIsNotNone(r["ai_review"])


def resume_pdf(lines):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    y = 790
    for kind, text in lines:
        c.setFont("Helvetica-Bold" if kind == "h" else "Helvetica", 12 if kind == "h" else 10.5)
        c.drawString(50, y, text)
        y -= 18 if kind == "h" else 14
    c.save()
    return buf.getvalue()


MA_CV = [("h", "Sami Haddad"), ("t", "Marketing Lead | Dubai, UAE | +971 50 123 4567 | sami.haddad@mail.com"),
         ("h", "EXPERIENCE"),
         ("h", "Marketing Lead | Acme Media | Dubai, UAE | Mar 2023 - Present"),
         ("t", "- Grew subscribers by 40% across 6 markets with a new content plan."),
         ("h", "Marketing Executive | Beta Brands | Dubai, UAE | Jan 2018 - Aug 2021"),
         ("t", "- Launched 12 campaigns and cut cost per lead by 25%."),
         ("h", "Marketing Assistant | Gamma Retail | Dubai, UAE | Jan 2015 - Mar 2016"),
         ("t", "- Supported 30 events a year for 5 brands."),
         ("h", "EDUCATION"),
         ("t", "MA Brand Management | University of the Arts London | Sep 2021 - Feb 2023")]


class TestAiGapsFollowTheLabTimeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cv.pdf")
            with open(path, "wb") as f:
                f.write(resume_pdf(MA_CV))
            cls.doc = L.extract_cv(path)
        cls.ana = C.analyse_cv(cls.doc)
        cls.gaps = C.timeline(cls.ana)["gaps"]

    def finding(self, period, quote):
        return {"issue": "Unexplained employment gap", "severity": "Major", "type": "content", "quote": quote,
                "why": f"There is no job between {period}.", "fix": f"Explain the gap, {period}."}

    def test_a_degree_with_dates_covers_its_months(self):
        # the MA runs Sep 2021 - Feb 2023, so 2022 is covered; the only real gap is Apr 2016 - Dec 2017
        self.assertEqual(self.gaps, [(mi(2016, 4), mi(2017, 12))])

    def test_every_gap_finding_is_rejected(self):
        # v1.1: the Lab does not check gaps, so even a gap the timeline shows is never a card
        texts = [self.doc["modern"]]
        raw = {"findings": [
            self.finding("Jan 2022 and Dec 2022", "MA Brand Management | University of the Arts London | Sep 2021 - Feb 2023"),
            self.finding("Apr 2016 and Dec 2017", "Marketing Assistant | Gamma Retail | Dubai, UAE | Jan 2015 - Mar 2016")]}
        kept, rejected = R.clean(raw, texts)
        self.assertEqual(kept, [])
        self.assertEqual(len(rejected), 2)

    def test_the_real_case_has_no_gap_card(self):
        r = osn()
        self.assertNotIn("timeline", r)
        self.assertFalse([c for c in D.issue_cards(r) if c.get("ai") and R.is_gap_finding(
            {"issue": c["name"], "why": c["why"]})])


if __name__ == "__main__":
    unittest.main()
