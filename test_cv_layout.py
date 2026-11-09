"""
Tests for the design and layout checks (cv_layout.py) and how they feed the CV Score and the dashboard.
The test CVs are made here with reportlab: one with every design problem, one plain single-column CV.

  py -3.12 -m unittest test_cv_layout -v
"""

import io
import json
import os

os.environ["ATSLAB_AI_REVIEW"] = "0"      # no AI review (and no cost) in these tests
import shutil
import tempfile
import unittest

from PIL import Image
from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import cv_layout as Y
import cv_score as C

HERE = os.path.dirname(os.path.abspath(__file__))
ROLE = "Data Analyst"
SKILLS = {"required_skills": ["SQL", "Python", "Tableau", "Data Analysis", "Excel"],
          "preferred_skills": ["Power BI", "Statistics"]}
W, H = A4


def _img(size, color):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def make_designed_cv(path):
    """Photo, colored sidebar with contact details (with icons) and skills, two columns, a box, a colored panel,
    small text in 5 font families, light-grey text, 3 pages for 2 years of experience."""
    c = canvas.Canvas(path, pagesize=A4)
    y = lambda top: H - top                               # reportlab measures from the bottom
    # sidebar
    c.setFillColor(Color(0.80, 0.86, 0.94))
    c.rect(0, 0, 200, H, stroke=0, fill=1)
    c.drawImage(_img((120, 120), (150, 110, 90)), 40, y(160), 120, 120)        # photo
    c.setFillColor(Color(0, 0, 0))
    c.setFont("Helvetica-Bold", 16)
    c.drawString(30, y(190), "Sara Haddad")
    c.setFont("Helvetica", 8)
    c.drawString(30, y(205), "Data Analyst")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(30, y(240), "Profile")
    c.setFont("Helvetica", 7.5)
    for i, t in enumerate(["Analyst with two years of experience in", "reporting, dashboards and data cleaning",
                           "for retail and logistics teams in the UAE."]):
        c.drawString(30, y(255 + 11 * i), t)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(30, y(320), "Contact")
    c.setFont("Helvetica", 7.5)
    for i, t in enumerate(["+971 50 123 4567", "sara.haddad@mail.com", "Dubai, UAE"]):
        c.drawImage(_img((10, 10), (40, 40, 40)), 30, y(338 + 18 * i), 10, 10)  # icon
        c.drawString(46, y(336 + 18 * i), t)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(30, y(420), "Skills")
    c.setFont("Times-Roman", 7.5)
    for i, t in enumerate(["SQL", "Python", "Tableau", "Excel", "Statistics"]):
        c.drawString(36, y(438 + 12 * i), t)
    c.setFillColor(Color(0.93, 0.95, 0.98))               # light text on the colored sidebar: low contrast
    c.setFont("Helvetica", 7.5)
    c.drawString(30, y(520), "Hobbies: reading travel chess photography cooking")
    c.setFillColor(Color(0, 0, 0))
    # main column
    c.setFont("Helvetica-Bold", 13)
    c.drawString(230, y(40), "Work Experience")
    jobs = [("Senior / Data Analyst", "2023 - 2025", "Retail Group - Dubai, UAE"),
            ("Junior Data Analyst", "Jan 2022 - Dec 2022", "Logistics Co - Dubai, UAE")]
    top = 64
    for title, dates, company in jobs:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(230, y(top), title)
        c.drawString(480, y(top), dates)
        c.setFont("Courier", 7.5)
        c.drawString(230, y(top + 12), company)
        c.setFont("Helvetica", 7.5)
        for i in range(12):
            c.drawString(230, y(top + 26 + 11 * i), f"Responsible for weekly reporting and data checks for team {i}.")
        top += 26 + 11 * 12 + 18
    c.setStrokeColor(Color(0.2, 0.2, 0.2))                # a box with text in it
    c.rect(228, y(top + 46), 330, 46, stroke=1, fill=0)
    c.setFont("Courier-Bold", 8)
    c.drawString(236, y(top + 18), "Key result: cut report time from five days to one")
    c.drawString(236, y(top + 32), "Tools used: SQL Python Tableau")
    c.setFillColor(Color(1.0, 0.93, 0.70))                 # a colored panel with text
    c.rect(228, y(top + 130), 330, 70, stroke=0, fill=1)
    c.setFillColor(Color(0, 0, 0))
    c.setFont("Times-Bold", 8)
    c.drawString(236, y(top + 80), "Awards: Analyst of the year, Retail Group")
    c.setFont("ZapfDingbats", 8)
    c.drawString(236, y(top + 96), "4 4 4")
    c.showPage()
    for page in (2, 3):                                    # 3 pages for 2 years: too many
        c.setFont("Helvetica", 7.5)
        for i in range(30):
            c.drawString(50, y(60 + 14 * i), f"Page {page}: more project notes and details about reporting line {i}.")
        c.showPage()
    c.save()


def make_plain_cv(path):
    """A clean single-column CV: no design problem at all."""
    c = canvas.Canvas(path, pagesize=A4)
    y = lambda top: H - top
    lines = [("Helvetica-Bold", 16, "Sara Haddad"), ("Helvetica", 10, "Data Analyst | SQL | Python | Tableau"),
             ("Helvetica", 10, "sara.haddad@mail.com | +971 50 123 4567 | Dubai, UAE | linkedin.com/in/sarahaddad"),
             ("Helvetica-Bold", 12, "SUMMARY"),
             ("Helvetica", 10, "Data Analyst with two years of experience in SQL, Python and Tableau reporting."),
             ("Helvetica-Bold", 12, "EXPERIENCE"),
             ("Helvetica-Bold", 10, "Data Analyst | Retail Group | Jan 2023 - Dec 2024")]
    lines += [("Helvetica", 10, f"- Built {i + 3} weekly SQL reports that cut manual work by {10 + i}% for the team.")
              for i in range(6)]
    lines += [("Helvetica-Bold", 12, "EDUCATION"), ("Helvetica", 10, "BSc Statistics, University of Sharjah, 2022"),
              ("Helvetica-Bold", 12, "SKILLS"), ("Helvetica", 10, "SQL, Python, Tableau, Excel, Power BI, Statistics")]
    top = 50
    for font, size, text in lines:
        c.setFont(font, size)
        c.drawString(50, y(top), text)
        top += size + 9
    c.showPage()
    c.save()


class LayoutBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.designed = os.path.join(cls.tmp, "designed.pdf")
        cls.plain = os.path.join(cls.tmp, "plain.pdf")
        make_designed_cv(cls.designed)
        make_plain_cv(cls.plain)
        cls.lay = Y.analyse_layout(cls.designed)
        cls.lay_plain = Y.analyse_layout(cls.plain)
        with open(C.role_skills_path(ROLE, cls.tmp), "w", encoding="utf-8") as f:
            json.dump({"role": ROLE, "prompt_version": C.ROLE_PROMPT_VERSION, "ai_runs": [SKILLS] * 3}, f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestDesignChecks(LayoutBase):
    def test_every_design_issue_is_detected(self):
        f = self.lay["findings"]
        for fid in ("D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9", "D10"):     # D8 is switched off: below
            with self.subTest(issue=fid, label=Y.DESIGN[fid][0]):
                self.assertTrue(f[fid]["found"], f[fid])
                self.assertTrue(f[fid]["evidence"], fid)
        r = C.score_cv(self.designed, None, ROLE, role_cache=self.tmp)
        self.assertTrue(r["layout"]["findings"]["D11"]["found"])               # 3 pages for 2 years

    def test_the_low_contrast_card_is_switched_off(self):
        """4 Nov 2026: the D8 card ("Light or low-contrast text") is off - a real report quoted ordinary resume text
        as hard to read. The rule is still here and still measures contrast: see Y.CONTRAST_CHECK."""
        self.assertFalse(Y.CONTRAST_CHECK)
        self.assertFalse(self.lay["findings"]["D8"]["found"])
        self.assertIn("D8", Y.DESIGN)                                          # the check can be switched back on
        self.assertGreater(Y.contrast((30, 30, 30), (255, 255, 255)), Y.LOW_CONTRAST)   # dark on white: fine
        self.assertLess(Y.contrast((200, 200, 200), (255, 255, 255)), Y.LOW_CONTRAST)   # light grey: unreadable

    def test_plain_cv_has_no_design_issue(self):
        found = [k for k, v in self.lay_plain["findings"].items() if v["found"]]
        self.assertEqual(found, [])
        self.assertFalse(self.lay_plain["columns_found"])

    def test_boxes_for_the_visual_view(self):
        f = self.lay["findings"]
        labels = {b[5] for fid in ("D1", "D3", "D4", "D5", "D6") for b in f[fid]["boxes"]}
        for want in ("Photo", "Sidebar", "Column 1", "Column 2", "Icon", "Box"):
            self.assertIn(want, labels)
        pngs = Y.render_pages(self.designed, f)
        self.assertEqual(len(pngs), 3)
        self.assertTrue(all(p[:8] == b"\x89PNG\r\n\x1a\n" for p in pngs))

    def test_reading_order(self):
        rd = self.lay["reading"]
        self.assertEqual(rd["ats_headings"][0], "Work Experience")            # top of the right column is read first
        self.assertEqual(rd["page_headings"][:3], ["Profile", "Contact", "Skills"])
        self.assertIn("Work Experience", rd["out_of_order"])
        self.assertGreaterEqual(rd["switches"], 4)

    def test_page_view_reads_column_by_column(self):
        text = self.lay["visual_doc"]["modern"]
        self.assertLess(text.index("Sara Haddad"), text.index("Work Experience"))
        self.assertIn("+971 50 123 4567\nsara.haddad@mail.com", text)       # contact lines stay together

    def test_contact_and_skills_only_in_sidebar(self):
        ev = " ".join(self.lay["findings"]["D9"]["evidence"])
        self.assertIn("sara.haddad@mail.com", ev)
        self.assertIn("Skills", ev)


class TestScoreWithDesign(LayoutBase):
    def test_design_counts_in_readability_with_the_right_severity(self):
        r = C.score_cv(self.designed, None, ROLE, role_cache=self.tmp)
        sev = {i["id"]: i["severity"] for i in r["issues"] if i["id"].startswith("D") or i["id"] == "TPL"}
        for fid in ("D3", "D4", "D10"):                    # sidebar, columns, reading order: inside the template card
            self.assertNotIn(fid, sev)
        self.assertEqual(sev["TPL"], "Critical")
        for fid in ("D1", "D5", "D2", "D7"):               # D8 (low contrast) is switched off since 4 Nov 2026
            self.assertEqual(sev[fid], "Minor", fid)
        self.assertNotIn("D8", sev)
        plain = C.score_cv(self.plain, None, ROLE, role_cache=self.tmp)
        self.assertGreater(plain["parts"]["readability"], r["parts"]["readability"] + 20)
        self.assertFalse([i for i in plain["issues"] if i["id"].startswith("D") or i["id"] == "TPL"])
        self.assertTrue(all(i["part"] == "readability" for i in r["issues"] if i["id"].startswith("D")
                            or i["id"] == "TPL"))

    def test_merged_title_and_year_only_dates_are_quoted(self):
        r = C.score_cv(self.designed, None, ROLE, role_cache=self.tmp)
        # 2026-11-09: year-only dates have their own check (T4C) since the job card was split
        p5 = " ".join(r["structure_checks"]["T4C"]["evidence"])
        self.assertIn("year only", p5)                                # year-only dates: the date lines are quoted
        t11 = " ".join(r["structure_checks"]["T11"]["evidence"])
        self.assertIn("Senior / Data Analyst", t11)                 # two titles in one: its own Minor check
        self.assertNotIn("two titles in one", p5)


class TestDashboardWithDesign(LayoutBase):
    def run_dash(self, path):
        import dashboard as D
        with open(path, "rb") as f:
            data = f.read()
        return D, D.run_check(data, os.path.basename(path), False, ROLE, self.tmp, self.tmp)

    def test_every_card_quotes_the_cv(self):
        D, r = self.run_dash(self.designed)
        cards = D.issue_cards(r)
        self.assertTrue(any(c["key"] == "photo" for c in cards))
        for c in cards:
            with self.subTest(card=c["name"]):
                self.assertTrue(D.evidence(c, r), c["name"])
        photo = next(c for c in cards if c["key"] == "photo")
        self.assertIn("photo version for direct emails", photo["fix"])
        # since 2026-11-09 the job-details check is right too seldom on the golden set (44%): it is not scored and
        # no longer shown as a card. What the rule found is kept for the team in the verify list.
        self.assertFalse([c for c in cards if c["key"] == "job_details"])
        t4 = (r.get("structure_checks") or {}).get("T4") or {}
        if t4.get("moved_to_verify"):
            self.assertIn("2023 - 2025", " ".join(t4.get("evidence") or []))
            self.assertIn("T4", [v["id"] for v in r["to_verify"]])

    def test_page_has_no_visual_view(self):
        import dashboard as D
        from streamlit.testing.v1 import AppTest

        def page(path, cache):
            import dashboard as D
            with open(path, "rb") as f:
                r = D.run_check(f.read(), "designed.pdf", False, "Data Analyst", cache, cache)
            D.render(r)

        at = AppTest.from_function(page, args=(self.designed, self.tmp), default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        self.assertNotIn("Visual view", [h.value for h in at.subheader])     # removed on 2026-10-20
        self.assertEqual(len(at.get("imgs")), 0)
        html_ = "\n".join(m.value for m in at.markdown)
        self.assertNotIn("out of order: on the page this is section", html_)
        self.assertIn("What the ATS sees", html_)                              # still under Details


if __name__ == "__main__":
    unittest.main()
