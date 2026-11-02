"""
2026-10-25: two scoring fixes (summary written as bullets, shading is not a template problem) and the PDF report
(clean template, "Download PDF", file name).

  py -3.12 -m unittest test_report -v
"""

import os

os.environ["ATSLAB_AI_REVIEW"] = "0"
import re
import shutil
import tempfile
import unittest

from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

import ATSLab_v3 as L
import cv_score as C
import dashboard as D
import test_cv_score as T
import test_columns as TC

HERE = os.path.dirname(os.path.abspath(__file__))


class TestSummaryBullets(T.Base):
    def with_summary(self, body):
        text = T.polished_cv()["modern"]
        summ = text.split("SUMMARY\n")[1].split("\nEXPERIENCE")[0]
        return T.fake_doc(text.replace(summ, body))

    def test_two_bullets_make_a_minor_card(self):
        doc = self.with_summary("- Logistics Coordinator with seven years of experience in freight forwarding.\n"
                                "- Known for accurate shipment tracking and clear vendor communication.")
        r = self.score(doc)
        card = next(i for i in r["issues"] if i["id"] == "C17")
        self.assertEqual(card["severity"], "Minor")
        self.assertGreater(card["points"], 0)
        self.assertEqual(r["content_checks"]["C17"]["score"], 0)
        r["_doc"] = doc
        c = next(c for c in D.issue_cards(r) if c["key"] == "summary_bullets")
        self.assertEqual(c["name"], "Summary is written as bullets")
        self.assertIn("one short paragraph", c["fix"])
        self.assertTrue(D.evidence(c, r))

    def test_one_bullet_or_a_paragraph_is_fine(self):
        one = self.with_summary("- Logistics Coordinator with seven years of experience in freight forwarding and "
                                "customs clearance across the UAE and GCC.")
        para = T.polished_cv()
        for doc in (one, para):
            r = self.score(doc)
            self.assertEqual(r["content_checks"]["C17"]["score"], 1)
            self.assertFalse([i for i in r["issues"] if i["id"] == "C17"])

    def test_weights_still_add_up(self):
        self.assertAlmostEqual(sum(C.CONTENT_WEIGHT.values()) + sum(C.RETIRED_WEIGHT.values()), 1.0)


def make_single_column(path, shading=True, strip=False):
    """One text column; gray bars behind the job lines and (optionally) a tall light strip along the left edge."""
    W, H = A4
    c = canvas.Canvas(path, pagesize=A4)
    if strip:
        c.setFillColor(Color(0.92, 0.94, 0.97))
        c.rect(0, 0, 0.2 * W, H, stroke=0, fill=1)
    y = 60
    lines = [("Lina Haddad", 16), ("Logistics Coordinator | Freight Forwarding | Customs", 10),
             ("lina.haddad@mail.com | +971 50 123 4567 | Dubai, UAE | linkedin.com/in/linahaddad", 9)]
    sections = [("SUMMARY", ["Logistics Coordinator with eight years of experience in freight forwarding and customs "
                             "clearance across the UAE and GCC, known for accurate shipment tracking."]),
                ("EXPERIENCE", [x for t, co, bs in TC.JOBS for x in [t, co] + ["- " + b for b in bs]]),
                ("EDUCATION", ["Bachelor of Science in Supply Chain Management, University of Dubai, 2016"]),
                ("SKILLS", ["Inventory Management, Freight Forwarding, Customs Clearance, SAP, Excel, Incoterms"])]
    x0 = 0.25 * W if strip else 50
    for text, size in lines:
        c.setFont("Helvetica-Bold" if size > 12 else "Helvetica", size)
        c.drawString(x0, H - y, text)
        y += size + 6
    y += 8
    for heading, body in sections:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x0, H - y, heading)
        y += 16
        for line in body:
            job = shading and ("|" in line and "-" in line and not line.startswith("- "))
            if job:
                c.setFillColor(Color(0.94, 0.94, 0.94))
                c.rect(x0 - 4, H - y - 3, W - x0 - 40, 13, stroke=0, fill=1)
                c.setFillColor(Color(0, 0, 0))
            c.setFont("Helvetica", 9)
            c.drawString(x0, H - y, line[:105])
            y += 13
        y += 8
    c.save()


class TestShadingIsNotATemplateProblem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.r = {}
        for name, kw in (("bars", dict(shading=True)), ("plain", dict(shading=False)),
                         ("strip", dict(shading=False, strip=True))):
            path = os.path.join(cls.tmp, f"{name}.pdf")
            make_single_column(path, **kw)
            with open(path, "rb") as f:
                cls.r[name] = D.run_check(f.read(), f"{name}.pdf", False, "")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def names(self, key):
        return [c["name"] for c in D.issue_cards(self.r[key])]

    def test_gray_bars_are_only_a_minor_shading_card(self):
        r = self.r["bars"]
        self.assertFalse(r["layout"]["columns_found"])
        cards = {c["name"]: c for c in D.issue_cards(r)}
        self.assertNotIn("Template is hard for ATS to read", cards)
        shade = cards["Colored backgrounds or shading"]
        self.assertEqual(shade["severity"], "Minor")
        self.assertTrue(any("Shading behind" in q for q in D.evidence(shade, r)))
        self.assertFalse([i for i in r["issues"] if i["id"] in ("TPL", "D3", "D4")])

    def test_no_shading_no_card(self):
        self.assertNotIn("Colored backgrounds or shading", self.names("plain"))
        self.assertNotIn("Template is hard for ATS to read", self.names("plain"))

    def test_a_light_strip_on_a_single_column_resume_is_not_a_sidebar(self):
        r = self.r["strip"]
        self.assertFalse(r["layout"]["columns_found"])
        self.assertNotIn("Template is hard for ATS to read", self.names("strip"))
        self.assertIn("Colored backgrounds or shading", self.names("strip"))
        self.assertFalse(r["layout"]["findings"]["D3"]["found"])

    def test_real_columns_sidebars_and_landscape_keep_the_template_card(self):
        tmp = tempfile.mkdtemp()
        try:
            for name in ("two", "three", "four", "left_sidebar", "right_sidebar", "landscape"):
                path = os.path.join(tmp, f"{name}.pdf")
                TC.make_layout_cv(path, name)
                with open(path, "rb") as f:
                    r = D.run_check(f.read(), f"{name}.pdf", False, "")
                with self.subTest(layout=name):
                    self.assertIn("Template is hard for ATS to read", [c["name"] for c in D.issue_cards(r)])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_letter_spaced_headings_keep_the_template_card_as_minor(self):
        text = T.polished_cv()["modern"]
        for word in ("EXPERIENCE", "EDUCATION", "SKILLS"):
            text = text.replace(word + chr(10), " ".join(word) + chr(10))
        base = T.Base()
        base.setUp()
        try:
            r = base.score(T.fake_doc(text))
        finally:
            base.tearDown()
        tpl = [i for i in r["issues"] if i["id"] == "TPL"]
        self.assertEqual([i["severity"] for i in tpl], ["Minor"])          # rule 4: only layout problems are Critical
        self.assertIn("letter-spaced headings", tpl[0]["reasons"])


if __name__ == "__main__":
    unittest.main()
