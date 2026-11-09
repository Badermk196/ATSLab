"""Generated resumes for the false alarms of 5 Nov 2026:

1. a one-column CV like a Google Docs / Word export (a SKILLS heading, "Bold label: items" lines, a hanging indent,
   a tab stop) must never be read as two columns - and a real two-column CV must still be;
2. a freelance job at a learning provider is a job; only a title that names a program is a course (one note, T17).
3. two files with similar names are never mixed: the text, the page count and the cache entry come from the uploaded
   file's own fingerprint (SHA-256 of its bytes).

  py -3.12 -m unittest test_column_and_course -v
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["ATSLAB_AI_REVIEW"] = "0"                     # no AI review (and no cost) in these tests
from reportlab.lib.pagesizes import A4                   # noqa: E402
from reportlab.pdfgen import canvas                      # noqa: E402

import cv_layout as Y                                    # noqa: E402
import cv_score as C                                     # noqa: E402
import ATSLab_v3 as L                                    # noqa: E402
import test_cv_layout as LAY                             # noqa: E402

W, H = A4
CONTACT = "sara.haddad@mail.com | +971 50 123 4567 | Dubai, UAE"


def one_column_docs_cv(path):
    """A one-column CV like a Google Docs / Word export where every line pairs a bold label with its items, the items
    starting at the same place (a tab stop), with hanging indent lines under a label. None of it is a column."""
    c = canvas.Canvas(path, pagesize=A4)
    y = lambda top: H - top
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y(48), "Sara Haddad")
    c.setFont("Helvetica", 10)
    c.drawString(50, y(70), "Data Analyst")
    pairs = [("Email:", "sara.haddad@mail.com"),
             ("Phone:", "+971 50 123 4567"),
             ("Profile:", "Data analyst with two years of experience in SQL, Python and Tableau reporting"),
             ("", "for retail and logistics teams in the UAE, building dashboards used every week."),
             ("Languages:", "Python, SQL, R, JavaScript, Looker"),
             ("Tools:", "Tableau, Power BI, Excel, Git, Airflow"),
             ("Methods:", "Regression, Forecasting, A/B testing, Data cleaning"),
             ("Databases:", "PostgreSQL, BigQuery, Snowflake"),
             ("Reporting:", "Dashboards, Monthly reviews, KPIs"),
             ("Certifications:", "Google Data Analytics, 2024"),
             ("Education:", "BSc Computer Science, University of Dubai, 2022"),
             ("Experience:", "Data Analyst, Retail Group, Dubai, Jan 2023 - Present"),
             ("", "Junior Data Analyst, Logistics Co, Dubai, Jan 2022 - Dec 2022"),
             ("Achievements:", "Cut report time from five days to one, built twelve dashboards")]
    top = 96
    for lab, val in pairs:
        if lab:
            c.setFont("Helvetica-Bold", 10)
            c.drawString(50, y(top), lab)                 # the label
        c.setFont("Helvetica", 10)
        c.drawString(140, y(top), val)                    # its items, always starting at the same place
        top += 15
    c.save()


def program_and_freelance_cv(path):
    """One column, with a real course under Experience and a freelance job at a learning provider."""
    c = canvas.Canvas(path, pagesize=A4)
    y = lambda top: H - top
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y(50), "Sara Haddad")
    c.setFont("Helvetica", 10)
    c.drawString(50, y(68), "Senior Programme Manager | Digital Transformation")
    c.drawString(50, y(84), CONTACT)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y(120), "SUMMARY")
    c.setFont("Helvetica", 10)
    c.drawString(50, y(140), "Senior programme manager with fifteen years in digital transformation and programme")
    c.drawString(50, y(154), "delivery across the UAE, KSA and Qatar, leading large teams and multi-country")
    c.drawString(50, y(168), "rollouts for telecom and retail clients, cutting cost and cycle time every year.")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y(210), "EXPERIENCE")
    c.setFont("Helvetica", 10)
    c.drawString(50, y(236), "AI Career Accelerator - Inner Circle | Be10X | Aug 2026 - Present")
    for i, t in enumerate(["- Completed 120 hours of applied AI coursework and delivered a capstone project.",
                           "- Worked in a cohort of 40 on model evaluation and deployment."]):
        c.drawString(50, y(252 + 14 * i), t)
    c.setFont("Helvetica", 10)
    c.drawString(50, y(300), "Freelance Data Consultant | Coursera | Jan 2025 - Present")
    for i, t in enumerate(["- Advised two teams on reporting pipelines and dashboard reviews.",
                           "- Cut manual reporting time by 30% across three business units.",
                           "- Built a shared SQL library used by 20 analysts every week."]):
        c.drawString(50, y(316 + 14 * i), t)
    c.drawString(50, y(370), "Senior Programme Manager | Amazon, Dubai, UAE | Jan 2021 - Dec 2024")
    for i, t in enumerate(["- Led a $7.5M programme across 14 clients in the UAE, KSA and Qatar.",
                           "- Cut delivery cycle time by 30% across three regions.",
                           "- Built a delivery dashboard used by 40 people every week."]):
        c.drawString(50, y(386 + 14 * i), t)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y(460), "EDUCATION")
    c.setFont("Helvetica", 10)
    c.drawString(50, y(480), "BSc Computer Science | University of Dubai | 2010")
    c.save()


def simple_cv(path, name, headline, pages=1):
    """A small one-column CV, `pages` pages long, with its own name on every page."""
    c = canvas.Canvas(path, pagesize=A4)
    y = lambda top: H - top
    for p in range(pages):
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, y(48 + 300 * p), name)
        c.setFont("Helvetica", 10)
        c.drawString(50, y(70 + 300 * p), headline)
        c.drawString(50, y(90 + 300 * p), CONTACT)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y(120 + 300 * p), "EXPERIENCE")
        c.setFont("Helvetica", 10)
        for i in range(6):
            c.drawString(50, y(145 + 15 * i + 300 * p), f"- Worked on reporting and delivery item {i} in Dubai.")
        c.showPage()
    c.save()


class TestOneColumnIsNotTwoColumns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.docs = os.path.join(cls.tmp, "docs_style.pdf")
        cls.docs_alt = os.path.join(cls.tmp, "docs_style_copy.pdf")
        cls.designed = os.path.join(cls.tmp, "two_column.pdf")
        one_column_docs_cv(cls.docs)
        one_column_docs_cv(cls.docs_alt)
        LAY.make_designed_cv(cls.designed)               # a real two-column CV with a sidebar

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_label_and_indent_layout_is_not_a_column(self):
        lay = Y.analyse_layout(self.docs)
        self.assertFalse(lay["columns_found"], lay.get("n_columns"))
        self.assertFalse(lay["findings"]["D4"]["found"])
        self.assertFalse(lay["findings"]["D3"]["found"])

    def test_the_fix_is_what_stops_it(self):
        """With the label / indent rule switched off, the same file is read as two columns: the test has teeth."""
        real = Y._label_or_indent_column
        Y._label_or_indent_column = lambda rows, x: False
        try:
            lay = Y.analyse_layout(self.docs_alt)            # a copy: a new key, so the file cache does not hide it
        finally:
            Y._label_or_indent_column = real
        self.assertTrue(lay["columns_found"], "the fixture does not exercise the rule")

    def test_no_template_card_and_no_page_format_card(self):
        r = C.score_cv(self.docs, None, None)
        ids = [i["id"] for i in r["issues"]]
        self.assertNotIn("TPL", ids)
        self.assertNotIn("T15", ids)
        self.assertNotIn("D4", ids)

    def test_a_real_two_column_cv_is_still_caught(self):
        lay = Y.analyse_layout(self.designed)
        self.assertTrue(lay["columns_found"])
        self.assertTrue(lay["findings"]["D4"]["found"])
        self.assertTrue(lay["findings"]["D3"]["found"])      # its sidebar too
        self.assertIn("TPL", [i["id"] for i in C.score_cv(self.designed, None, None)["issues"]])


class TestCourseAndFreelanceUnderExperience(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.cv = os.path.join(cls.tmp, "program.pdf")
        program_and_freelance_cv(cls.cv)
        cls.result = C.score_cv(cls.cv, None, None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_course_gets_the_note(self):
        note = next((i for i in self.result["issues"] if i["id"] == "T17"), None)
        self.assertIsNotNone(note, [i["id"] for i in self.result["issues"]])
        self.assertEqual(note["severity"], "Minor")
        self.assertIn("course or program", note["detail"])
        self.assertTrue(any("Accelerator" in e for e in note["evidence"]), note["evidence"])
        self.assertFalse(any("Coursera" in e for e in note["evidence"]), note["evidence"])

    def test_the_freelance_job_is_a_job(self):
        import ATSLab_v3 as L
        ana = C.analyse_cv(L.extract_cv(self.cv))
        self.assertEqual(len(ana["programs"]), 1, [j.get("title") for j in ana["programs"]])
        self.assertIn("Accelerator", ana["programs"][0].get("title") or "")
        titles = [j.get("title") or "" for j in ana["jobs"]]
        self.assertTrue(any("Coursera" in t for t in titles), titles)     # the freelance job is still a job
        self.assertTrue(any("Amazon" in t for t in titles), titles)

    def test_the_course_gets_no_location_or_date_card(self):
        for i in self.result["issues"]:
            if i["id"] in ("T16", "T4"):
                self.assertFalse(any("Accelerator" in e or "Be10X" in e for e in i["evidence"]), (i["id"], i["evidence"]))


class TestEachReportUsesItsOwnFile(unittest.TestCase):
    """Two files with similar names and different content: the text, the page count and the cache entry never mix."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.one = os.path.join(cls.tmp, "sara_cv_updated.pdf")
        cls.two = os.path.join(cls.tmp, "sara_cv_updated (1).pdf")
        simple_cv(cls.one, "Anna Ahmadi", "Data Analyst | SQL | Python", pages=1)
        simple_cv(cls.two, "Bilal Baker", "Programme Manager | Delivery | PMP", pages=2)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_text_and_the_page_count_come_from_the_file_itself(self):
        one, two = L.extract_cv(self.one), L.extract_cv(self.two)
        self.assertIn("Anna Ahmadi", one["modern"])
        self.assertNotIn("Bilal Baker", one["modern"])
        self.assertIn("Bilal Baker", two["modern"])
        self.assertNotIn("Anna Ahmadi", two["modern"])
        self.assertEqual(Y.analyse_layout(self.one)["pages"], 1)
        self.assertEqual(Y.analyse_layout(self.two)["pages"], 2)

    def test_a_changed_file_is_read_again(self):
        import cv_cache
        before = cv_cache.fingerprint(self.one)
        simple_cv(self.one, "Anna Ahmadi", "Data Analyst | SQL | Tableau | Looker", pages=1)
        self.assertNotEqual(before, cv_cache.fingerprint(self.one))
        self.assertIn("Looker", L.extract_cv(self.one)["modern"])

    def test_the_cache_key_is_the_content_not_the_name(self):
        import cv_cache
        twin = os.path.join(self.tmp, "another_name.pdf")
        shutil.copyfile(self.two, twin)
        self.assertEqual(cv_cache.fingerprint(self.two), cv_cache.fingerprint(twin))
        self.assertNotEqual(cv_cache.fingerprint(self.one), cv_cache.fingerprint(self.two))
        self.assertNotIn("Anna Ahmadi", L.extract_cv(twin)["modern"])     # same bytes, other name: same text


if __name__ == "__main__":
    unittest.main()
