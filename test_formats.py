"""
Tests for common resume formats the Lab must read as standard ones (2026-10-22):
numbered section headings, a '|' headline under the name, 'Company | Feb 2025 to Present | City' job lines with the
title on the line above, and icon-font bullets. Each odd format is only a Minor note.

  py -3.12 -m unittest test_formats -v
"""

import os

os.environ["ATSLAB_AI_REVIEW"] = "0"      # no AI review (and no cost) in these tests
import unittest

import ATSLab_v3 as L
import cv_score as C
import dashboard as D
from test_cv_score import fake_doc

ICON = ""                            # a private-use (icon font) bullet, as Word's Symbol font exports it
RESUME = f"""JANE DOE
SUPPLY CHAIN & LOGISTICS | INVENTORY & VENDOR OPERATIONS
Dubai, UAE | +971 50 123 4567 | jane.doe@mail.com
linkedin.com/in/janedoe
01 PROFESSIONAL SUMMARY
Logistics Coordinator with eight years of UAE experience across retail and trading, managing 3PL carriers,
inventory allocation and vendor operations, sustaining 98% on-time delivery for 3,000 SKUs and keeping
stock accurate with Excel analysis and clear vendor communication every week.
02 CORE COMPETENCIES
Logistics: Order fulfillment, carrier management, freight coordination, reverse logistics
Inventory: Stock allocation, replenishment, cycle counts, SKU master data
03 PROFESSIONAL EXPERIENCE
Logistics Coordinator
Babygrow FZC | Feb 2025 to Present | Sharjah, UAE
{ICON} Managed 3PL carriers and freight vendors, sustaining a 98% on-time delivery rate.
{ICON} Audited POD records, recovering AED 150,000 a year in invoice variances.
Supply Chain Executive
Bohemian General Trading | Aug 2023 to Jan 2025 | Dubai, UAE
{ICON} Directed inventory operations across four sales channels, fulfilling 50 orders monthly.
{ICON} Reduced shrinkage by 20% through stock movement tracking and monthly counts.
04 EDUCATION
Bachelor of Commerce, University of Mumbai, 2015
05 SKILLS
Inventory Management, Freight Forwarding, Customs Clearance, Warehouse Operations, SAP, Excel, Incoterms, Route Planning
"""


class TestFormats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = C.score_cv("jane.pdf", None, None, doc=fake_doc(RESUME))
        cls.ana = C.analyse_cv(cls.r["_vdoc"])

    def test_numbered_headings_are_standard_sections(self):
        self.assertEqual([(s["title"], s["kind"]) for s in self.ana["sections"]],
                         [("PROFESSIONAL SUMMARY", "summary"), ("CORE COMPETENCIES", "competencies"),
                          ("PROFESSIONAL EXPERIENCE", "experience"), ("EDUCATION", "education"),
                          ("SKILLS", "skills")])
        self.assertEqual(self.r["structure_checks"]["T1"]["score"], 1)          # standard names
        t13 = self.r["structure_checks"]["T13"]
        self.assertEqual(t13["score"], 0)
        self.assertIn("01 PROFESSIONAL SUMMARY", t13["evidence"])
        card = next(i for i in self.r["issues"] if i["id"] == "T13")
        self.assertEqual(card["severity"], "Minor")
        self.assertGreaterEqual(self.r["content_checks"]["C4"]["words"], 30)             # the summary is found

    def test_pipe_headline_is_not_a_section(self):
        line = "SUPPLY CHAIN & LOGISTICS | INVENTORY & VENDOR OPERATIONS"
        self.assertFalse(L.is_heading(line))
        self.assertIn(line, [x["text"] for x in self.ana["header"]])
        self.assertTrue(L.is_heading("SKILLS | TOOLS"))                       # one-word parts: still a heading
        self.assertTrue(L.is_heading("PROFESSIONAL EXPERIENCE"))

    def test_company_dates_location_line(self):
        jobs = L.ats_fields(self.r["_vdoc"], self.ana)["jobs"]
        self.assertEqual([(j["title"], j["company"], j["dates"]) for j in jobs],
                         [("Logistics Coordinator", "Babygrow FZC", "Feb 2025 to Present"),
                          ("Supply Chain Executive", "Bohemian General Trading", "Aug 2023 to Jan 2025")])
        self.assertTrue(all(j["has_range"] and j["problem"] is None for j in self.ana["jobs"]))   # 'to' = '-'
        self.assertEqual(self.r["structure_checks"]["T4"]["score"], 1)          # title, company, location, dates
        self.assertGreater(L.experience_years(self.ana["jobs"]), 2)

    def test_icon_bullets_are_read_as_bullets(self):
        bullets = [t for t, b in C.experience_items(self.ana) if b]
        self.assertEqual(len(bullets), 4)
        self.assertTrue(bullets[0].startswith("Managed 3PL carriers"))
        self.assertNotIn(ICON, self.r["_vdoc"]["modern"])
        self.assertEqual(self.r["content_checks"]["C1"]["score"], 1)            # every bullet has a number
        t14 = self.r["structure_checks"]["T14"]
        self.assertEqual(t14["score"], 0)
        self.assertIn("use standard bullets", t14["detail"].lower())
        self.assertEqual(next(i for i in self.r["issues"] if i["id"] == "T14")["severity"], "Minor")
        self.assertEqual(D.ISSUES["icon_bullets"]["fix"], "Use standard bullets (• or -).")

    def test_plain_resume_is_unchanged(self):
        plain = RESUME.replace(ICON, "-")
        for k in range(1, 6):
            plain = plain.replace(f"0{k} ", "")
        doc = fake_doc(plain)
        same, notes = C.normalize_doc(doc)
        self.assertIs(same, doc)                                               # nothing to change: same document
        self.assertEqual(notes, {"icon_bullets": [], "numbered": []})
        r = C.score_cv("jane.pdf", None, None, doc=doc)
        self.assertEqual((r["structure_checks"]["T13"]["score"], r["structure_checks"]["T14"]["score"]), (1, 1))

    def test_real_resume(self):
        path = os.path.join(os.path.expanduser("~/Downloads"), "Jibran_Konkar_Resume.pdf")
        if not os.path.exists(path):
            self.skipTest("Jibran_Konkar_Resume.pdf is not on this machine")
        r = C.score_cv(path, None, None)
        ana = C.analyse_cv(r["_vdoc"])
        self.assertEqual([s["kind"] for s in ana["sections"]][:3], ["summary", "competencies", "experience"])
        self.assertEqual(len(ana["jobs"]), 6)
        self.assertEqual(r["structure_checks"]["T4"]["score"], 1)
        self.assertGreaterEqual(r["score"], 70)                               # was 42.9 when misread


if __name__ == "__main__":
    unittest.main()
