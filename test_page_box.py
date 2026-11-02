"""
Pages whose box does not start at (0, 0): a shifted mediabox / cropbox (top = -7.8, as some PDF makers write it) or a
page offset to the right. Every crop is clamped to the page's own area, so such a page is read exactly like the same
page with a normal box. A page that still cannot be read skips only its layout checks, with a short note.

  py -3.12 -m unittest test_page_box -v
"""

import io
import os

os.environ["ATSLAB_AI_REVIEW"] = "0"
os.environ.pop("OPENROUTER_API_KEY", None)
import unittest

import pdfplumber
from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfdoc
from reportlab.pdfgen import canvas

import cv_layout as Y
import dashboard as D

W, H = 595.5, 842.25
BOXES = {"normal": (0, 0, W, H),
         "shifted down (top -7.8)": (0, 7.83, W, H + 7.83),       # pdfplumber reads this page as top = -7.83
         "offset to the right": (40, 0, W + 40, H)}
JOBS = [("Operations Manager | Gulf Logistics | Dubai, UAE | Mar 2020 - Present",
         ["Cut delivery times by 18% across 40 routes by redesigning the dispatch plan.",
          "Led a team of 12 coordinators and raised on-time delivery to 96%.",
          "Saved AED 1.2M a year by renegotiating 8 carrier contracts."]),
        ("Operations Supervisor | Emirates Freight | Dubai, UAE | Jan 2016 - Feb 2020",
         ["Managed 300 daily shipments with a 99% accuracy rate.",
          "Trained 25 new staff on the warehouse system in 6 months.",
          "Reduced stock errors by 30% with weekly cycle counts."])]


def resume_pdf(box, sidebar=False):
    """A one-page resume drawn inside `box` (x0, y0, x1, y1 in PDF points), with that box as its mediabox and
    cropbox. sidebar: a colored left sidebar with its own column of text (a two-column page)."""
    x, y = box[0], box[1]
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(box[2] - box[0], box[3] - box[1]))
    c.setCropBox(box)
    left = x + (190 if sidebar else 50)
    if sidebar:
        c.setFillColor(Color(0.85, 0.9, 0.97))
        c.rect(x, y, 170, H, fill=1, stroke=0)
        c.setFillColor(Color(0, 0, 0))
        c.setFont("Helvetica-Bold", 11)
        c.drawString(x + 15, y + H - 120, "SKILLS")
        c.setFont("Helvetica", 10)
        for k, s in enumerate(("Fleet planning", "Warehouse systems", "SAP", "Team leadership", "Budgeting",
                               "Carrier contracts", "Route design", "Inventory control", "Reporting", "Excel")):
            c.drawString(x + 15, y + H - 140 - 16 * k, s)
    c.setFillColor(Color(0, 0, 0))
    top = y + H - 60
    c.setFont("Helvetica-Bold", 20)
    c.drawString(left, top, "Sami Haddad")
    c.setFont("Helvetica", 11)
    c.drawString(left, top - 20, "Operations Manager | Logistics | Supply Chain")
    c.drawString(left, top - 36, "Dubai, UAE | +971 50 123 4567 | sami.haddad@mail.com")
    yy = top - 70
    c.setFillColor(Color(0.92, 0.92, 0.92))                                # a light shading bar behind a heading
    c.rect(left - 4, yy - 4, 340, 16, fill=1, stroke=0)
    c.setFillColor(Color(0, 0, 0))
    for head, lines in (("SUMMARY", ["Operations manager with 9 years in logistics across the UAE, leading teams of",
                                     "up to 12 people and cutting delivery costs and times with clear processes."]),
                        ("EXPERIENCE", None), ("EDUCATION", ["Bachelor of Business Administration | University of "
                                                             "Sharjah | 2015"])):
        c.setFont("Helvetica-Bold", 12)
        c.drawString(left, yy, head)
        yy -= 18
        c.setFont("Helvetica", 10.5)
        if lines is None:
            for title, bullets in JOBS:
                c.setFont("Helvetica-Bold", 10.5)
                c.drawString(left, yy, title if not sidebar else title.split(" | ")[0])
                yy -= 15
                if sidebar:
                    c.setFont("Helvetica", 10.5)
                    c.drawString(left, yy, " | ".join(title.split(" | ")[1:]))
                    yy -= 15
                c.setFont("Helvetica", 10.5)
                for b in bullets:
                    c.drawString(left + 10, yy, "• " + (b if not sidebar else b[:60]))
                    yy -= 14
                yy -= 6
        else:
            for l in lines:
                c.drawString(left, yy, l if not sidebar else l[:62])
                yy -= 14
        yy -= 12
    real = pdfdoc.PDFPage.check_format
    def check_format(self, document):                  # reportlab always writes [0 0 w h]: write the box asked for
        self.MediaBox = pdfdoc.PDFArray(list(box))
        return real(self, document)
    pdfdoc.PDFPage.check_format = check_format
    try:
        c.showPage()
        c.save()
    finally:
        pdfdoc.PDFPage.check_format = real
    return buf.getvalue()


def check(data, name="resume.pdf"):
    return D.run_check(data, name, False, "")


class TestGeneratedPages(unittest.TestCase):
    def test_the_generated_pages_really_have_a_shifted_box(self):
        with pdfplumber.open(io.BytesIO(resume_pdf(BOXES["shifted down (top -7.8)"]))) as pdf:
            page = pdf.pages[0]
            self.assertAlmostEqual(page.bbox[1], -7.83, places=2)
            with self.assertRaises(ValueError):                         # what failed in the dashboard before
                page.crop((0, 0, page.width, page.height))
        with pdfplumber.open(io.BytesIO(resume_pdf(BOXES["offset to the right"]))) as pdf:
            self.assertEqual(pdf.pages[0].bbox[0], 40)

    def test_shifted_and_offset_pages_score_like_the_normal_page(self):
        for sidebar in (False, True):
            normal = check(resume_pdf(BOXES["normal"], sidebar))
            for name, box in BOXES.items():
                with self.subTest(page=name, sidebar=sidebar):
                    r = check(resume_pdf(box, sidebar))                 # no error
                    self.assertEqual(r["notes"], normal["notes"])        # no page skipped
                    self.assertEqual(r["score"], normal["score"])
                    self.assertEqual(r["parts"], normal["parts"])
                    found = lambda x: sorted(k for k, v in x["layout"]["findings"].items() if v["found"])
                    self.assertEqual(found(r), found(normal))
                    self.assertEqual(r["layout"]["n_columns"], normal["layout"]["n_columns"])
            self.assertEqual(normal["layout"]["n_columns"], 2 if sidebar else 1)

    def test_page_crop_never_fails(self):
        with pdfplumber.open(io.BytesIO(resume_pdf(BOXES["shifted down (top -7.8)"]))) as pdf:
            page = pdf.pages[0]
            for box in ((0, 0, page.width, page.height), (-50, -50, 2000, 2000), (100, 900, 50, 950)):
                crop = Y.page_crop(page, box)
                x0, top, x1, bottom = crop.bbox
                self.assertTrue(page.bbox[0] <= x0 <= x1 <= page.bbox[2] and page.bbox[1] <= top <= bottom <= page.bbox[3])
                crop.extract_text()

    def test_a_page_that_cannot_be_read_skips_only_its_layout_checks(self):
        D.fresh_modules()                                   # the check reloads changed modules: reload them first
        import cv_cache
        cv_cache.clear()                                    # this PDF was read before: read it again, with the patch
        real = Y.page_crop
        Y.page_crop = lambda page, box: (_ for _ in ()).throw(ValueError("a page that cannot be cropped"))
        try:
            r = check(resume_pdf(BOXES["shifted down (top -7.8)"]))
        finally:
            Y.page_crop = real
            cv_cache.clear()                                # never keep the reading made with the patch
        self.assertIn(Y.SKIPPED_NOTE.format(pages="1", s=""), r["notes"])
        self.assertGreater(r["score"], 0)                               # the check finished, every other part ran
        self.assertTrue(D.issue_cards(r) is not None)


if __name__ == "__main__":
    unittest.main()
