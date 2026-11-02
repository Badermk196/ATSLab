"""
Tests for column-aware reading (cv_layout.find_regions) and the "Template is hard for ATS to read" card.

The same resume content is drawn with reportlab in 7 layouts: single column, 2 / 3 / 4 columns, a left sidebar,
a right sidebar and a landscape page. Whatever the layout, the Lab must read every block in order (Content and
Structure checks and every quote use the column-by-column text); Readability keeps scoring what a strict ATS reads.
Real resumes in our folders with these layouts are checked too (skipped when not on this machine).

  py -3.12 -m unittest test_columns -v
"""

import os

os.environ["ATSLAB_AI_REVIEW"] = "0"      # no AI review (and no cost) in these tests
import re
import shutil
import tempfile
import textwrap
import unittest

from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

import ATSLab_v3 as L
import cv_layout as Y
import cv_score as C
import dashboard as D

HERE = os.path.dirname(os.path.abspath(__file__))
DL = os.path.expanduser("~/Downloads")

JOBS = [("Logistics Coordinator | Jan 2021 - Present", "Gulf Freight LLC | Dubai, UAE",
         ["Coordinated 40 weekly freight shipments across five GCC markets.",
          "Reduced warehouse costs by 18% through better route planning.",
          "Managed customs clearance for 300 import files a year."]),
        ("Logistics Assistant | Mar 2018 - Dec 2020", "Desert Cargo FZE | Sharjah, UAE",
         ["Built an Excel shipment tracker used daily by 12 planners.",
          "Negotiated carrier rates that saved AED 250,000 in one year.",
          "Trained 6 new coordinators on customs clearance steps."]),
        ("Warehouse Clerk | Jun 2016 - Feb 2018", "Port Cargo LLC | Dubai, UAE",
         ["Tracked 200 inbound containers a month with the port system.",
          "Filed 150 customs documents a month without errors."])]
BLOCKS = {
    "head": [("", ["Lina Haddad", "Logistics Coordinator | Freight Forwarding | Customs"])],
    "contact": [("CONTACT", ["lina.haddad@mail.com", "+971 50 123 4567", "Dubai, UAE", "linkedin.com/in/linahaddad"])],
    "summary": [("SUMMARY", ["Logistics Coordinator with eight years of experience in freight forwarding, customs "
                             "clearance and warehouse operations across the UAE and GCC, known for accurate shipment "
                             "tracking, clear vendor communication and steady cost savings in busy distribution "
                             "centres using SAP and Excel every day."])],
    "experience": [("EXPERIENCE", [x for t, co, bs in JOBS for x in [t, co] + ["- " + b for b in bs]])],
    # the same experience split over two columns (a section that continues in the next column)
    "experience_a": [("EXPERIENCE", [x for t, co, bs in JOBS[:2] for x in [t, co] + ["- " + b for b in bs]])],
    "experience_b": [("", [x for t, co, bs in JOBS[2:] for x in [t, co] + ["- " + b for b in bs]])],
    "education": [("EDUCATION", ["Bachelor of Science in Supply Chain Management", "University of Dubai, 2016"])],
    "skills": [("SKILLS", ["Inventory Management, Freight Forwarding, Customs Clearance",
                           "Warehouse Operations, SAP, Shipment Tracking",
                           "Microsoft Excel, Incoterms, Route Planning"])],
    "languages": [("LANGUAGES", ["English (fluent)", "Arabic (native)"])],
    "extra": [("ADDITIONAL INFORMATION", ["Visa: UAE residence visa", "UAE driving licence",
                                          "Notice period: 30 days"])],
}
# layout -> (page size, sidebar side or None, [(x0, x1, [blocks]) per column], blocks across the top)
LAYOUTS = {
    "single": (A4, None, [(50, 545, ["contact", "summary", "experience", "education", "skills", "languages", "extra"])],
               ["head"]),
    "two": (A4, None, [(40, 330, ["summary", "experience"]),
                       (360, 555, ["contact", "skills", "education", "languages", "extra"])], ["head"]),
    "three": (A4, None, [(25, 180, ["contact", "summary", "skills"]), (200, 420, ["experience"]),
                         (440, 575, ["education", "languages", "extra"])], ["head"]),
    "four": (landscape(A4), None, [(20, 200, ["contact", "skills", "languages"]),
                                   (220, 410, ["summary", "education", "extra"]), (430, 630, ["experience_a"]),
                                   (650, 830, ["experience_b"])], ["head"]),
    "left_sidebar": (A4, "left", [(20, 175, ["head", "contact", "skills", "languages", "extra"]),
                                  (215, 565, ["summary", "experience", "education"])], []),
    "right_sidebar": (A4, "right", [(30, 380, ["head", "summary", "experience", "education"]),
                                    (420, 575, ["contact", "skills", "languages", "extra"])], []),
    "landscape": (landscape(A4), None, [(30, 270, ["contact", "summary", "skills"]), (300, 560, ["experience"]),
                                        (590, 810, ["education", "languages", "extra"])], ["head"]),
}
EXPECTED_COLUMNS = {"single": 1, "two": 2, "three": 3, "four": 4, "left_sidebar": 2, "right_sidebar": 2,
                    "landscape": 3}


def make_layout_cv(path, layout):
    size, sidebar, cols, top = LAYOUTS[layout]
    W, H = size
    c = canvas.Canvas(path, pagesize=size)
    if sidebar:
        c.setFillColor(Color(0.85, 0.89, 0.95))
        c.rect(0 if sidebar == "left" else W - 200, 0, 200, H, stroke=0, fill=1)
        c.setFillColor(Color(0, 0, 0))
    y0 = 40
    if top:                                                  # name + headline across the whole page
        c.setFont("Helvetica-Bold", 18)
        c.drawString(cols[0][0], H - 45, "Lina Haddad")
        c.setFont("Helvetica", 10)
        c.drawString(cols[0][0], H - 62, "Logistics Coordinator | Freight Forwarding | Customs")
        y0 = 95
    size_pt = 8 if len(cols) >= 4 else 9
    for x0, x1, names in cols:
        y = y0
        for name in names:
            for heading, lines in BLOCKS[name]:
                if heading:
                    c.setFont("Helvetica-Bold", 10)
                    c.drawString(x0, H - y, heading)
                    y += 15
                for line in lines:
                    font = "Helvetica-Bold" if line == "Lina Haddad" else "Helvetica"
                    fs = 15 if line == "Lina Haddad" else size_pt
                    c.setFont(font, fs)
                    width = int((x1 - x0) / (stringWidth("n", font, fs) * 1.02))
                    for k, part in enumerate(textwrap.wrap(line, width) or [""]):
                        c.drawString(x0 + (8 if k and line.startswith("- ") else 0), H - y, part)
                        y += fs + 3.5
                y += 9
    c.save()


class LayoutBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.r, cls.lay = {}, {}
        for name in LAYOUTS:
            path = os.path.join(cls.tmp, f"lina_{name}.pdf")
            make_layout_cv(path, name)
            cls.lay[name] = Y.analyse_layout(path)
            with open(path, "rb") as f:
                cls.r[name] = D.run_check(f.read(), f"lina_{name}.pdf", False, "")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


def lines_of(text):
    return [" ".join(l.split()) for l in text.splitlines() if l.strip()]


class TestGeneratedLayouts(LayoutBase):
    def test_columns_detected(self):
        for name, n in EXPECTED_COLUMNS.items():
            with self.subTest(layout=name):
                lay = self.lay[name]
                self.assertEqual(lay["columns_found"], n > 1)
                self.assertEqual(lay["n_columns"], n)
                self.assertEqual(lay["landscape"], name in ("landscape", "four"))
        for name in ("left_sidebar", "right_sidebar"):
            self.assertTrue(self.lay[name]["findings"]["D3"]["found"], name)

    def test_every_block_is_read_in_order(self):
        """Column by column: each job's title, company and bullets follow each other; no block is mixed."""
        for name in LAYOUTS:
            with self.subTest(layout=name):
                text = lines_of(self.r[name]["_vdoc"]["modern"])
                flat = " ".join(text)                           # narrow columns wrap long lines
                for title, company, bullets in JOBS:
                    self.assertIn(f"{title} {company} - {bullets[0][:20]}", flat)
                for heading in ("EXPERIENCE", "EDUCATION", "SKILLS", "LANGUAGES"):
                    self.assertIn(heading, text)
                self.assertIn("SKILLS Inventory Management, Freight Forwarding,", flat)
                self.assertLess(flat.index("Logistics Coordinator | Jan"), flat.index("Warehouse Clerk | Jun"))

    def test_content_and_structure_read_the_columns(self):
        for name in LAYOUTS:
            with self.subTest(layout=name):
                r = self.r[name]
                ana = C.analyse_cv(r["_vdoc"])
                self.assertEqual(len(ana["jobs"]), 3)
                self.assertEqual(r["structure_checks"]["T4"]["score"], 1, r["structure_checks"]["T4"])
                self.assertEqual(r["structure_checks"]["T7"]["score"], 1)              # email
                self.assertEqual(r["structure_checks"]["T3"]["score"], 1)              # +971 phone
                self.assertEqual(r["structure_checks"]["T8"]["score"], 1)              # 9 skills
                self.assertEqual(r["content_checks"]["C15"]["score"], 1)               # headline
                self.assertEqual(r["content_checks"]["C1"]["score"], 1)                # numbers in bullets

    def test_one_template_card(self):
        for name in LAYOUTS:
            with self.subTest(layout=name):
                cards = D.issue_cards(self.r[name])
                tpl = [c for c in cards if c["key"] == "template"]
                if name == "single":
                    self.assertEqual(tpl, [])
                    continue
                self.assertEqual(len(tpl), 1)
                self.assertEqual(tpl[0]["severity"], "Critical")
                self.assertEqual(D.card_part(tpl[0]), "readability")
                self.assertEqual(tpl[0]["fix"], "Use a single-column, portrait template with normal headings.")
                reasons = tpl[0]["issues"][0]["reasons"]
                self.assertIn(f"{EXPECTED_COLUMNS[name]} columns side by side", reasons)
                if name in ("landscape", "four"):
                    self.assertIn("a landscape page", reasons)
                if "sidebar" in name:
                    self.assertIn("a sidebar", reasons)
                keys = {c["key"] for c in cards}               # template-only problems are inside the card
                for gone in ("columns", "sidebar", "reading_order", "sidebar_only", "name", "spaced_headings",
                             "landscape"):
                    self.assertNotIn(gone, keys)

    def test_can_reach_includes_the_template_fix(self):
        for name in LAYOUTS:
            if name == "single":
                continue
            r = self.r[name]
            cards = D.issue_cards(r)
            top = D.top_cards(cards)
            self.assertIn("template", [c["key"] for c in top], name)
            s = D.report_summary(r, cards)
            self.assertGreater(s["after"], r["score"], name)

    def test_quotes_are_never_mixed_columns(self):
        """Every quote shown on a card is a real line of the column-by-column reading (or the card's own
        summary line), never two columns run together."""
        for name in LAYOUTS:
            r = self.r[name]
            clean = set(lines_of(r["_vdoc"]["modern"]))
            for c in D.issue_cards(r):
                for q in D.evidence(c, r):
                    with self.subTest(layout=name, card=c["name"], quote=q):
                        heads = [h for h in ("SUMMARY", "EXPERIENCE", "EDUCATION", "SKILLS", "LANGUAGES", "CONTACT")
                                 if re.search(rf"\b{h}\b", q)]
                        self.assertLessEqual(len(heads), 1)

    def test_single_column_reads_exactly_as_before(self):
        lay = self.lay["single"]
        self.assertFalse(lay["columns_found"])
        r = self.r["single"]
        self.assertIs(r["_vdoc"], r["_doc"]) if r["_vdoc"] is r["_doc"] else \
            self.assertEqual(r["_vdoc"]["modern"], r["_doc"]["modern"])


class TestSeparatorAndLandscape(unittest.TestCase):
    def test_capital_i_separator(self):
        self.assertTrue(C.I_SEPARATOR_RE.search("Designer I Brand Lead, 2025 - Present"))
        self.assertTrue(C.I_SEPARATOR_RE.search("Graphic Design I Art Direction"))
        for ok in ("Software Engineer I", "Engineer I | Jan 2020 - Present", "Designer | Brand Lead"):
            self.assertFalse(C.I_SEPARATOR_RE.search(ok), ok)
        self.assertEqual(C.rule_severity("T12", {}, {}), "Minor")

    def test_unspace_heading(self):
        for spaced, word in (("E D U C AT I O N", "EDUCATION"), ("C R E AT I V E S K I L L S", "CREATIVE SKILLS"),
                             ("I N F O", "INFO"), ("P R O F I L E", "PROFILE")):
            self.assertEqual(Y.unspace_heading(spaced), word)
        self.assertEqual(Y.unspace_heading("Graphic Design I Art Direction"), "Graphic Design I Art Direction")


# real resumes with these layouts (whatever is on this machine)
REAL = {"Tareq (sidebar)": (os.path.join(HERE, "CV4", "Tareq Al Masri CV JN26.pdf"), 2, False),
        "Rowan (4 columns, landscape)": (os.path.join(DL, "Rowan_Elatrache_Original_CV.pdf"), 4, True)}


class TestRealLayouts(unittest.TestCase):
    def test_real_resumes(self):
        found = 0
        for name, (path, n, wide) in REAL.items():
            if not os.path.exists(path):
                continue
            found += 1
            with self.subTest(resume=name):
                with open(path, "rb") as f:
                    r = D.run_check(f.read(), os.path.basename(path), False, "")
                self.assertTrue(r["layout"]["columns_found"])
                self.assertEqual(r["layout"]["n_columns"], n)
                self.assertEqual(r["layout"]["landscape"], wide)
                cards = D.issue_cards(r)
                self.assertEqual([c["key"] for c in cards].count("template"), 1)
                ana = C.analyse_cv(r["_vdoc"])
                self.assertGreaterEqual(len(ana["jobs"]), 4)                  # the jobs are found in the columns
                for c in cards:
                    for q in D.evidence(c, r):
                        self.assertFalse(re.search(r"PROFILE.*LANGUAGES|PROFILE.*EXPERIENCE", q), (c["name"], q))
        if not found:
            self.skipTest("no real multi-column resume on this machine")

    def test_rowan_reads_like_the_page(self):
        path = REAL["Rowan (4 columns, landscape)"][0]
        if not os.path.exists(path):
            self.skipTest("Rowan's resume is not on this machine")
        r = C.score_cv(path, None, None)
        text = lines_of(r["_vdoc"]["modern"])
        self.assertEqual(text[0], "ROWAN ELATRACHE")                 # a name over two lines is one name
        self.assertIn("PROFILE", text)
        self.assertIn("EXPERIENCE", text)
        i = text.index("BLR World (Dubai, U.A.E)")
        self.assertTrue(text[i + 1].startswith("Designer I Brand Lead"))
        self.assertEqual(r["structure_checks"]["T12"]["score"], 0)                # 'Designer I Brand Lead'
        self.assertTrue(r["layout"]["findings"]["D12"]["found"])                  # landscape


if __name__ == "__main__":
    unittest.main()
