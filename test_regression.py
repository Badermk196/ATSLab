"""
Regression tests: the Lab works for any CV - good, bad and unusual.

  4 CV types: Mohamed's CV (strong), Tareq's CV (bad design), Jibran's original CV (clean but weak content),
  and a generated unusual CV (two columns + a table). Plus one test per fix: headers / footers, extra
  experience headings, shading vs text boxes, the job + education timeline, bullets only, role from the CV.

  py -3.12 -m unittest test_regression -v
No AI calls: the AI review is off, role skill lists are the saved ones (or written into a temporary folder).
"""

import io
import json
import os
import re
import shutil
import tempfile
import unittest

os.environ["ATSLAB_AI_REVIEW"] = "0"

from PIL import Image
from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import ATSLab_v3 as L
import cv_layout as Y
import cv_review as R
import cv_score as C
import dashboard as D
import test_cv_score as T

HERE = os.path.dirname(os.path.abspath(__file__))
MOHAMED = os.path.join(HERE, "testcvs", "MohamedShokry-original.pdf")
TAREQ = os.path.join(HERE, "CV4", "Tareq Al Masri CV JN26.pdf")
JIBRAN = os.path.join(HERE, "CV4", "jibran-original-cv.pdf")
W, H = A4
y = lambda top: H - top


def check(path):
    with open(path, "rb") as f:
        return D.run_check(f.read(), os.path.basename(path), False, "")


def need(path):
    if not os.path.exists(path):
        raise unittest.SkipTest(f"{path} is not on this machine")


# ---------------------------------------------------------------------------
# generated CVs
# ---------------------------------------------------------------------------
def make_unusual_cv(path):
    """Two columns (a plain left column) and a ruled table in the right column."""
    c = canvas.Canvas(path, pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(30, y(40), "Omar Nasser")
    c.setFont("Helvetica", 10)
    c.drawString(30, y(56), "Data Analyst")
    left = ["Contact", "omar.nasser@mail.com", "+971 50 765 4321", "Dubai, UAE", "Skills", "SQL", "Python", "Tableau",
            "Excel", "Power BI", "Statistics", "Languages", "English", "Arabic"]
    for i, t in enumerate(left):
        c.setFont("Helvetica-Bold" if t in ("Contact", "Skills", "Languages") else "Helvetica", 10)
        c.drawString(30, y(90 + 22 * i), t)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(230, y(90), "Experience")
    top = 112
    for title, dates in (("Data Analyst | Retail Group", "Jan 2022 - Present"),
                         ("Junior Analyst | Logistics Co", "Jun 2019 - Dec 2021")):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(230, y(top), f"{title} | {dates}")
        c.setFont("Helvetica", 10)
        for i in range(5):
            c.drawString(236, y(top + 16 + 14 * i), f"- Built {i + 3} weekly SQL reports used by {10 + i} managers.")
        top += 16 + 14 * 5 + 14
    c.setFont("Helvetica-Bold", 12)
    c.drawString(230, y(top + 10), "Projects")
    tx, ty, cw, rh = 230, top + 24, 110, 20                         # a 3 x 3 ruled table
    rows = [("Project", "Tool", "Result"), ("Churn model", "Python", "-12% churn"), ("Sales dash", "Tableau", "+8% sales")]
    for r_i, row in enumerate(rows):
        for c_i, cell in enumerate(row):
            c.rect(tx + c_i * cw, y(ty + (r_i + 1) * rh), cw, rh, stroke=1, fill=0)
            c.setFont("Helvetica", 9)
            c.drawString(tx + c_i * cw + 4, y(ty + (r_i + 1) * rh) + 6, cell)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(230, y(top + 120), "Education")
    c.setFont("Helvetica", 10)
    c.drawString(230, y(top + 136), "BSc Statistics, University of Sharjah, 2019")
    for i in range(10):
        c.drawString(230, y(top + 160 + 14 * i), f"Coursework and project note {i + 1} on data analysis and reporting.")
    c.showPage()
    c.save()


def make_paged_cv(path):
    """2 pages: footer 'Page | n', a page-2 header with '(continued)' and the contact line again, small footer
    text, and a title-case 'Additional Experience' section with a job in it."""
    c = canvas.Canvas(path, pagesize=A4)
    lines1 = [("Helvetica-Bold", 16, "LAYLA HASSAN"), ("Helvetica", 10, "Operations Manager"),
              ("Helvetica", 10, "layla.hassan@mail.com | +971 55 222 3344 | Dubai, UAE"),
              ("Helvetica-Bold", 12, "PROFESSIONAL EXPERIENCE"),
              ("Helvetica-Bold", 10, "Operations Manager | Gulf Logistics | Mar 2019 - Present")]
    lines1 += [("Helvetica", 10, f"- Cut delivery delays by {10 + i}% across {3 + i} warehouses in the UAE region.")
               for i in range(20)]
    top = 50
    for font, size, text in lines1:
        c.setFont(font, size)
        c.drawString(50, y(top), text)
        top += size + 10
    c.setFont("Helvetica", 7)
    c.drawString(500, 25, "Page | 1")
    c.showPage()
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y(30), "LAYLA HASSAN (continued)")
    c.setFont("Helvetica", 7)
    c.drawString(50, y(44), "PHONE: +971 55 222 3344 | EMAIL: layla.hassan@mail.com")
    lines2 = [("Helvetica-Bold", 12, "Additional Experience"),
              ("Helvetica-Bold", 10, "Shift Supervisor | Desert Freight | Jan 2016 - Feb 2019"),
              ("Helvetica", 10, "- Led a team of 12 loaders and cut loading time by 18% in two years."),
              ("Helvetica-Bold", 12, "EDUCATION"), ("Helvetica", 10, "BBA, University of Dubai, 2015"),
              ("Helvetica-Bold", 12, "SKILLS"), ("Helvetica", 10, "Logistics, SAP, Excel, Planning, Inventory, Lean")]
    top = 80
    for font, size, text in lines2:
        c.setFont(font, size)
        c.drawString(50, y(top), text)
        top += size + 10
    c.setFont("Helvetica", 7)
    c.drawString(500, 25, "Page | 2")
    c.showPage()
    c.save()


def make_shading_cv(path, with_box=False, with_table=False):
    """A light grey band behind normal text (background shading); optionally a real box or a ruled table."""
    c = canvas.Canvas(path, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y(50), "Sam Lee")
    c.setFillColor(Color(0.94, 0.94, 0.94))
    for i in range(3):
        c.rect(40, y(110 + 14 * i), 520, 13, stroke=0, fill=1)
    c.setFillColor(Color(0, 0, 0))
    c.setFont("Helvetica", 10)
    for i, t in enumerate(["Customer Success | Account Management | Renewals", "Salesforce | Excel | Tableau",
                           "Team Leadership | Coaching | Escalations"]):
        c.drawString(50, y(107 + 14 * i), t)
    if with_box:
        c.rect(40, y(220), 520, 50, stroke=1, fill=0)
        c.drawString(50, y(190), "Key result: grew renewals by 20 percent in one year")
    if with_table:
        for r_i in range(3):
            for c_i in range(3):
                c.rect(40 + c_i * 170, y(260 + (r_i + 1) * 20), 170, 20, stroke=1, fill=0)
                c.drawString(46 + c_i * 170, y(260 + (r_i + 1) * 20) + 6, f"Cell {r_i}{c_i} text")
    c.showPage()
    c.save()


class Tmp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# the 4 CV types
# ---------------------------------------------------------------------------
class TestStrongCV(unittest.TestCase):
    """Mohamed's CV: a strong CV must not be pulled down by false or repeated issues."""

    @classmethod
    def setUpClass(cls):
        need(MOHAMED)
        cls.r = check(MOHAMED)
        cls.cards = D.issue_cards(cls.r)

    def test_score_in_the_original_cv_range(self):
        # a strong original, but it has no headline, a letter-spaced name and several other issues (2026-10-23)
        self.assertGreaterEqual(self.r["score"], 65, self.r["parts"])
        self.assertLessEqual(self.r["score"], 75, self.r["parts"])

    def test_no_footer_job_and_every_experience_section_read(self):
        jobs = L.ats_fields(self.r["_vdoc"], C.analyse_cv(self.r["_vdoc"]))["jobs"]
        self.assertFalse([j for j in jobs if re.search(r"\bpage\b", j["title"], re.I)])
        titles = " ".join(j["title"] for j in jobs)
        self.assertIn("Interpreter", titles)                    # from "Early Work Experience"
        self.assertEqual(len(jobs), 7)

    def test_no_gap(self):
        self.assertNotIn("timeline", self.r)                      # v1.1: no gap check at all
        self.assertFalse([c for c in self.cards if re.search(r"\bgap\b", c["name"], re.I)])

    def test_name_is_one_card_and_no_heading_critical(self):
        keys = [c["key"] for c in self.cards]
        self.assertEqual(keys.count("name_spacing"), 1)           # only the name is letter-spaced: its own card (v1.1)
        for gone in ("spaced_headings", "name", "template"):
            self.assertNotIn(gone, keys)
        self.assertEqual(keys.count("headline"), 1)               # no target title under the name: one card
        self.assertEqual([c["key"] for c in self.cards if c["tag"] == "Critical"], [])   # rule 4: a spaced name is Minor
        self.assertEqual(next(c for c in self.cards if c["key"] == "name_spacing")["tag"], "Minor")

    def test_shaded_competencies_are_not_a_text_box(self):
        self.assertFalse(self.r["layout"]["findings"]["D6"]["found"])
        self.assertNotIn("boxes", [c["key"] for c in self.cards])
        self.assertNotIn("skills_unreadable", [c["key"] for c in self.cards])

    def test_one_summary_card_role_from_cv_and_short_improve_list(self):
        self.assertLessEqual([c["key"] for c in self.cards].count("summary"), 1)
        self.assertEqual(self.r["role_source"], "cv")
        self.assertEqual(self.r["target"], "Head of Customer Success & Experience")
        items = D.improve_items(self.cards)
        self.assertLessEqual(len(items), D.MAX_IMPROVE)
        self.assertEqual(len(items), len({x["fix"] for x in items}))

    def test_fonts_ignore_the_header_and_footer(self):
        ev = " ".join(self.r["layout"]["findings"]["D7"]["evidence"])
        self.assertNotIn("PHONE NUMBER", ev)
        self.assertNotIn("Page |", ev)


class TestBadDesignCV(unittest.TestCase):
    """Tareq's CV: the design problems must still be shown."""

    def test_design_issues_still_shown(self):
        need(TAREQ)
        r = check(TAREQ)
        keys = {c["key"] for c in D.issue_cards(r)}
        for k in ("template", "photo", "icons"):                  # sidebar, columns, order: one template card
            self.assertIn(k, keys)
        tpl = next(c for c in D.issue_cards(r) if c["key"] == "template")
        self.assertEqual(tpl["issues"][0]["reasons"], ["2 columns side by side", "a sidebar"])
        self.assertLess(r["score"], 60)
        self.assertTrue(all(D.evidence(c, r) for c in D.issue_cards(r)))


class TestWeakContentCV(unittest.TestCase):
    """Jibran's original CV: clean design, weaker content."""

    def test_clean_design_weak_content(self):
        need(JIBRAN)
        r = check(JIBRAN)
        self.assertFalse([k for k, v in r["layout"]["findings"].items() if v["found"]])
        self.assertGreaterEqual(r["parts"]["readability"], 85)
        self.assertLess(r["parts"]["content"], 85)
        self.assertIn("numbers", {c["key"] for c in D.issue_cards(r)})
        self.assertTrue(50 <= r["score"] < 80, r["score"])
        self.assertEqual(r["target"], "Logistics Coordinator")


class TestUnusualCV(Tmp):
    """A generated CV with two columns and a ruled table: detected, explained, no crash."""

    def test_columns_and_table(self):
        path = os.path.join(self.tmp, "unusual.pdf")
        make_unusual_cv(path)
        with open(C.role_skills_path("Data Analyst", self.tmp), "w", encoding="utf-8") as f:
            json.dump({"role": "Data Analyst", "prompt_version": C.ROLE_PROMPT_VERSION,
                       "ai_runs": [T.SKILLS] * 3}, f)
        with open(path, "rb") as f:
            r = D.run_check(f.read(), "unusual.pdf", False, "", self.tmp, self.tmp)
        self.assertEqual(r["target"], "Data Analyst")             # the headline names the role
        f_ = r["layout"]["findings"]
        self.assertTrue(f_["D4"]["found"])
        self.assertIn("Table", {b[5] for b in f_["D6"]["boxes"]})
        cards = D.issue_cards(r)
        self.assertTrue(cards and all(D.evidence(c, r) for c in cards))


# ---------------------------------------------------------------------------
# one test per fix
# ---------------------------------------------------------------------------
class TestHeadersAndFooters(Tmp):
    def test_running_lines_are_never_jobs_headings_dates_or_fonts(self):
        path = os.path.join(self.tmp, "paged.pdf")
        make_paged_cv(path)
        lay = Y.analyse_layout(path)
        run = {k: set(v) for k, v in lay["running"].items()}
        self.assertIn("page|1", run[0])
        self.assertTrue({"page|2", "laylahassan(continued)"} <= run[1])
        self.assertTrue(any("email" in k for k in run[1]))           # the contact line repeated on page 2
        self.assertFalse(lay["findings"]["D7"]["found"])              # small footer text is not a font problem
        doc = Y.extract_clean(path, lay["running"])
        self.assertNotIn("Page |", doc["modern"])
        self.assertNotIn("(continued)", doc["modern"])
        ana = C.analyse_cv(doc)
        titles = [j["title"] for j in ana["jobs"]]
        self.assertFalse([t for t in titles if "Page" in t])
        self.assertTrue(any("Shift Supervisor" in t for t in titles))  # "Additional Experience" read as jobs
        self.assertIn("experience", [s["kind"] for s in ana["sections"] if s["title"] == "Additional Experience"])

    def test_extra_experience_headings(self):
        for h in ("Early Work Experience", "Additional Experience", "Previous Experience", "Other Experience",
                  "EARLY CAREER EXPERIENCE", "Relevant Work Experience"):
            self.assertTrue(C.is_heading_cv(h), h)
        self.assertFalse(C.is_heading_cv("Experience with SQL and Python in a fast-paced team"))


class TestShading(Tmp):
    def test_light_shading_is_not_a_text_box(self):
        path = os.path.join(self.tmp, "shade.pdf")
        make_shading_cv(path)
        self.assertFalse(Y.analyse_layout(path)["findings"]["D6"]["found"])

    def test_real_box_and_table_still_count(self):
        for kind in ("box", "table"):
            path = os.path.join(self.tmp, f"shade_{kind}.pdf")
            make_shading_cv(path, with_box=kind == "box", with_table=kind == "table")
            f = Y.analyse_layout(path)["findings"]["D6"]
            self.assertTrue(f["found"], kind)
            self.assertIn("Table" if kind == "table" else "Box", {b[5] for b in f["boxes"]})


class TestTimeline(unittest.TestCase):
    def ana(self, jobs, edu_rows):
        return {"jobs": [{"title": t, "intervals": [iv]} for t, iv in jobs],
                "sections": [{"title": "EDUCATION", "kind": "education",
                              "rows": [{"text": e, "cells": [e], "page": 0} for e in edu_rows]}]}

    def test_gaps_need_more_than_six_empty_months(self):
        m = lambda y_, mo: y_ * 12 + mo - 1
        five = self.ana([("A", (m(2008, 6), m(2009, 4))), ("B", (m(2009, 11), m(2010, 11)))], [])
        self.assertEqual(C.timeline(five)["gaps"], [])                       # May-Oct 2009: 6 empty months
        twelve = self.ana([("A", (m(2018, 9), m(2020, 9))), ("B", (m(2021, 9), m(2023, 6)))], [])
        self.assertEqual(len(C.timeline(twelve)["gaps"]), 1)
        studied = self.ana([("A", (m(2018, 9), m(2020, 9))), ("B", (m(2021, 9), m(2023, 6)))],
                           ["MSc Finance, University of Dubai, Sep 2020 - Aug 2021"])
        self.assertEqual(C.timeline(studied)["gaps"], [])                    # education fills the gap
        self.assertIn("education: MSc Finance, University of Dubai: Sep 2020 to Aug 2021",
                      C.timeline_text(C.timeline(studied)))                  # whole names, never cut mid-word

    def test_ai_gap_finding_is_always_dropped(self):
        text = "Al Tayer Group - UAE Sep 2018 - Sep 2020"
        item = {"issue": "Unexplained employment gap", "severity": "Major", "type": "content", "quote": text,
                "why": "There is a gap.", "fix": "Explain it."}
        kept, rejected = R.clean({"findings": [item]}, [text])          # v1.1: no gap check at all
        self.assertEqual((kept, len(rejected)), ([], 1))
        skills = dict(item, issue="Skills gap for the role", why="A skills gap for this role.")
        self.assertFalse(R.is_gap_finding(skills))                     # a skills gap is not an employment gap

    def test_prompt_has_the_timeline_and_the_rules(self):
        self.assertGreaterEqual(R.REVIEW_PROMPT_VERSION, 4)
        self.assertGreaterEqual(R.REVIEW_PROMPT_VERSION, 6)
        none = C.gap_summary({"items": [], "gaps": []})
        p = R.review_prompt("Data Analyst", none)
        for t in ("DATES CHECKED BY THE LAB", "no gaps of more than 6 months", "report a gap ONLY if it is listed",
                  "NEVER suggest inventing an explanation", "contact details repeated in a page header"):
            self.assertIn(t, p)
        m = lambda y_, mo: y_ * 12 + mo - 1
        self.assertIn("Oct 2020 to Aug 2021", C.gap_summary({"items": [], "gaps": [(m(2020, 10), m(2021, 8))]}))


class TestBulletsAndRole(unittest.TestCase):
    def test_job_intro_paragraphs_are_not_bullets(self):
        intro = ("Led customer success and experience across the Middle East, Africa and Eastern Europe, overseeing "
                 "a large portfolio of strategic institutions and the team responsible for adoption and retention.")
        doc = T.fake_doc("Jane Doe\nEXPERIENCE\nHead of Success | Acme | Jan 2020 - Present\n" + intro +
                         "\n- Grew renewals by 20% across 40 accounts in the region.\n"
                         "- Cut escalations by 15% with a new weekly review.\n")
        ana = C.analyse_cv(doc)
        items = C.experience_items(ana)
        self.assertTrue(any(not b for _, b in items))                # the intro is there, as a paragraph
        bullets = [t for t, b in items if b]
        self.assertEqual(bullets, ["Grew renewals by 20% across 40 accounts in the region.",
                                   "Cut escalations by 15% with a new weekly review."])

    def test_role_from_headline_or_latest_title(self):
        self.assertEqual(C.clean_role("Head of Customer Success & Experience, EMEA"),
                         "Head of Customer Success & Experience")
        self.assertEqual(C.clean_role("Field Marketing Manager - MENA - Dubai, UAE"), "Field Marketing Manager")
        doc = T.fake_doc("Jane Doe\njane@x.com +971 50 123 4567\nEXPERIENCE\n"
                         "Junior Planner | Acme | Jan 2015 - Dec 2017\n- Planned routes.\n"
                         "Logistics Coordinator | Beta | Jan 2018 - Present\n- Ran shipments.\n")
        self.assertEqual(C.detect_role(doc, C.analyse_cv(doc)), "Logistics Coordinator")   # the latest job
        doc2 = T.fake_doc("Jane Doe\nSupply Chain Analyst | SAP | Excel\njane@x.com\nEXPERIENCE\n"
                          "Logistics Coordinator | Beta | Jan 2018 - Present\n- Ran shipments.\n")
        self.assertEqual(C.detect_role(doc2, C.analyse_cv(doc2)), "Supply Chain Analyst")  # the headline


if __name__ == "__main__":
    unittest.main()
