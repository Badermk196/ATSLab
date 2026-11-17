"""
2026-10-25: the PDF report. A clean report template (no buttons, switches or file chips; a header with the candidate,
the resume file, the date and how it was checked; every issue open), the "Download PDF" button, the file name, and
the fallback to the HTML report when the PDF cannot be made.

  py -3.12 -m unittest test_pdf -v
"""

import os

os.environ["ATSLAB_AI_REVIEW"] = "0"
import re
import unittest

from streamlit.testing.v1 import AppTest

import ATSLab_v3 as L
import dashboard as D
import test_dashboard as TD

HERE = os.path.dirname(os.path.abspath(__file__))
TODAY = L.TODAY.isoformat()


class Holder:
    pass


def mohamed():
    return TD.mohamed_result(Holder())


class TestFileName(unittest.TestCase):
    def fake(self, name, cv="Some Resume (final).pdf"):
        r = {"cv": cv}
        real = D.readable_name
        D.readable_name = lambda r_: (name, None)
        self.addCleanup(setattr, D, "readable_name", real)
        return r

    def test_name_found_titles_removed(self):
        for found, expected in (("MOHAMED SHOKRY, MBA", "Mohamed Shokry"), ("Dr. Jane Doe, PhD", "Jane Doe"),
                                ("Sam Lee, MSc, PMP", "Sam Lee"), ("NEDA SEFATI", "Neda Sefati"),
                                ("Tareq Al Masri", "Tareq Al Masri"), ("Jack Ma", "Jack Ma"),
                                ("Ali Hassan MBA", "Ali Hassan")):
            with self.subTest(found=found):
                r = self.fake(found)
                self.assertEqual(D.candidate_name(r), expected)
                self.assertEqual(D.report_file_name(r), f"1000Jobs ATS Lab - {expected} - {TODAY}.pdf")

    def test_no_name_uses_the_resume_file_name(self):
        r = self.fake(None, "Some Resume (final).pdf")
        self.assertIsNone(D.candidate_name(r))
        self.assertEqual(D.report_file_name(r), f"1000Jobs ATS Lab - Some Resume (final) - {TODAY}.pdf")
        self.assertEqual(D.report_file_name({"cv": "x.pdf"}), f"1000Jobs ATS Lab - x - {TODAY}.pdf")   # no data at all

    def test_unsafe_characters_never_reach_the_file_name(self):
        r = self.fake(None, 'a/b:c*d?"e<f>g|h.pdf')
        name = D.report_file_name(r)
        self.assertFalse(re.search(r'[<>:"/\\|?*]', name.replace(" - ", "")), name)
        self.assertTrue(name.endswith(f" - {TODAY}.pdf"))

    def test_mohamed_real_resume(self):
        r = mohamed()
        self.assertEqual(D.candidate_name(r), "Mohamed Shokry")
        self.assertEqual(D.report_file_name(r), f"1000Jobs ATS Lab - Mohamed Shokry - {TODAY}.pdf")
        self.assertEqual(D.report_file_name(r, "html"), f"1000Jobs ATS Lab - Mohamed Shokry - {TODAY}.html")


class TestReportTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = mohamed()
        cls.cards = D.issue_cards(cls.r)
        cls.doc = D.report_document(cls.r, cls.cards)

    def test_header_is_plain_text(self):
        h = D.header_html(self.r)
        for t in ("1000Jobs ATS Lab - Resume Report", "Mohamed Shokry", "mohamed.pdf",
                  L.TODAY.strftime("%d %B %Y").lstrip("0"), "Without a job description"):
            self.assertIn(t, h)
        for gone in ("<button", "<input", 'class="switch"', 'class="pill"', "KB", "With job description"):
            self.assertNotIn(gone, self.doc)

    def test_header_with_a_job(self):
        r = dict(self.r, mode="job", target="Customer Success Manager")
        h = D.header_html(r)
        self.assertIn("<dt>Target role</dt><dd>Customer Success Manager</dd>", h)      # the title the user typed
        self.assertIn("With a job description", h)
        self.assertNotIn("target role", h)
        self.assertNotIn("Target role", D.header_html(self.r))                           # none without a job

    def test_one_plain_sentence_under_the_score(self):
        sentence = re.search(r'<div class="plain">(.*?)</div>', self.doc, re.S).group(1)
        self.assertTrue(sentence.startswith("This resume scored "))
        self.assertIn("out of 100", sentence)
        self.assertIn("ATS", sentence)
        self.assertEqual(len(re.findall(r"\.(?!\d)", sentence)), 1)   # one sentence (a decimal score has a dot too)
        self.assertNotIn('class="plain"', D.score_html(self.r, self.cards))        # the dashboard page has none

    def test_every_issue_open_and_no_technical_details(self):
        self.assertEqual(self.doc.count('<details class="iss" open>'), len(self.cards))
        self.assertNotIn('<details class="iss">', self.doc)
        text = re.sub(r"<[^>]+>", " ", self.doc)
        for technical in ("What the ATS sees", "Show the full text", "Download", "Details"):
            self.assertNotIn(technical, text)

    def test_same_fonts_and_colors_as_the_dashboard(self):
        self.assertIn("Plus Jakarta Sans", self.doc)
        self.assertIn(D.FONT_URL, self.doc)
        for color in ("#0f172a", "#2563eb", "#b45309"):
            self.assertIn(color, D.REPORT_CSS)
        self.assertIn(D.REPORT_CSS, self.doc)                         # the very same stylesheet as the page


@unittest.skipUnless(D.find_browser(), "no Edge or Chrome to print with")
class TestRealPdf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.r = mohamed()
        cls.cards = D.issue_cards(cls.r)
        cls.data = D.make_pdf(D.report_document(cls.r, cls.cards))
        cls.tmp = tempfile.mkdtemp()
        cls.path = os.path.join(cls.tmp, "report.pdf")
        with open(cls.path, "wb") as f:
            f.write(cls.data)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def pages(self):
        import pdfplumber
        with pdfplumber.open(self.path) as p:
            return [(page.width, page.height, page.extract_words()) for page in p.pages]

    def test_it_is_a_real_pdf_on_a4(self):
        self.assertEqual(self.data[:5], b"%PDF-")
        pages = self.pages()
        self.assertGreaterEqual(len(pages), 2)
        for w, h, _ in pages:
            self.assertAlmostEqual(w, 595, delta=3)
            self.assertAlmostEqual(h, 842, delta=3)

    def test_no_buttons_switches_or_file_chips(self):
        text = " ".join(w["text"] for _, _, words in self.pages() for w in words)
        for gone in ("Download", "Check new resume", "Check again", "KB", "Paste the job description"):
            self.assertNotIn(gone, text)
        flat = re.sub(r"\s+", " ", text)
        self.assertIn("1000Jobs ATS Lab - Resume Report", flat)
        for t in ("CANDIDATE", "RESUME FILE", "DATE", "CHECKED", "Mohamed Shokry", "mohamed.pdf",
                  L.TODAY.strftime("%d %B %Y").lstrip("0")):
            self.assertIn(t, flat)
        self.assertIn("Without a job description", flat)

    def test_no_overlapping_text_and_nothing_off_the_page(self):
        for n, (width, height, words) in enumerate(self.pages(), 1):
            for w in words:
                self.assertTrue(-0.5 <= w["x0"] and w["x1"] <= width + 0.5, (n, w["text"]))
                self.assertTrue(-0.5 <= w["top"] and w["bottom"] <= height + 0.5, (n, w["text"]))
            for a in range(len(words)):
                for b in range(a + 1, len(words)):
                    u, v = words[a], words[b]
                    dx = min(u["x1"], v["x1"]) - max(u["x0"], v["x0"])
                    dy = min(u["bottom"], v["bottom"]) - max(u["top"], v["top"])
                    self.assertFalse(dx > 1.5 and dy > 1.5, (n, u["text"], v["text"]))

    def test_every_issue_is_in_the_pdf_and_none_is_cut_between_pages(self):
        flat = re.sub(r"\s+", " ", " ".join(w["text"] for _, _, words in self.pages() for w in words))
        for c in self.cards:
            self.assertIn(" ".join(c["name"].split()[:3]), flat, c["name"])
        for t in ("Why it hurts", "How to fix it"):
            self.assertGreaterEqual(flat.count(t), len(self.cards))

    def test_the_header_is_on_the_first_page_with_the_score_text(self):
        words = " ".join(w["text"] for w in self.pages()[0][2])
        self.assertIn("Resume Report", words)
        self.assertIn("out of 100", words)


class TestDownloadButton(unittest.TestCase):
    """The page: 'Download PDF' with the PDF, or a clear message and the HTML report when the PDF cannot be made."""

    def page(self, make):
        def results_page():
            import dashboard as D2
            import test_dashboard as T2
            r = T2.mohamed_result(type("H", (), {})())
            D2.render(r)
        real = D.make_pdf
        D.make_pdf = make                          # the page runs in this process: it uses this PDF maker
        try:
            return AppTest.from_function(results_page, default_timeout=300).run()
        finally:
            D.make_pdf = real

    def test_download_pdf_button(self):
        at = self.page(lambda doc, timeout=None: b"%PDF-1.4 " + b"0" * 3000)
        self.assertFalse(at.exception, at.exception)
        self.assertEqual([b.label for b in at.get("download_button")], ["Download PDF"])
        self.assertFalse([w for w in at.warning if "PDF could not be created" in w.value])

    def test_when_the_pdf_cannot_be_made_a_clear_message_and_the_html_report(self):
        def broken(doc, timeout=None):
            raise D.PdfError("no Edge or Chrome browser found")
        at = self.page(broken)
        self.assertFalse(at.exception, at.exception)
        self.assertEqual([b.label for b in at.get("download_button")], ["Download HTML report"])
        msg = " ".join(w.value for w in at.warning)
        self.assertIn("The PDF could not be created on this computer (no Edge or Chrome browser found)", msg)
        self.assertIn("HTML report instead", msg)

    def test_an_unexpected_failure_is_also_caught(self):
        def broken(doc, timeout=None):
            raise RuntimeError("boom")
        at = self.page(broken)
        self.assertFalse(at.exception, at.exception)
        self.assertEqual([b.label for b in at.get("download_button")], ["Download HTML report"])

    def test_pdf_for_keeps_the_result_so_it_is_made_once(self):
        calls = []
        real = D.make_pdf
        D.make_pdf = lambda doc, timeout=None: calls.append(1) or b"%PDF-1.4 " + b"0" * 3000
        try:
            r = mohamed()
            cards = D.issue_cards(r)
            cache = {}
            first, second = D.pdf_for(r, cards, cache), D.pdf_for(r, cards, cache)
        finally:
            D.make_pdf = real
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)

    def test_a_bad_file_from_the_browser_is_not_a_pdf(self):
        self.assertTrue(D.PDF_MIN_BYTES > 0)
        real_find = D.find_browser
        D.find_browser = lambda: None
        try:
            with self.assertRaises(D.PdfError):
                D.make_pdf("<html></html>")
        finally:
            D.find_browser = real_find


if __name__ == "__main__":
    unittest.main()
