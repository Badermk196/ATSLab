"""
The client comparison report: the client's original resume next to our 1000Jobs resume. It has exactly 3 sections
(Compared, Improved, Issues in the original resume) and "Why 1000Jobs", and never describes a problem of the
1000Jobs resume. The normal report (checkbox not ticked) stays as it was: the team sees every issue.

  py -3.12 -m unittest test_client_report -v
"""

import os

os.environ["ATSLAB_AI_REVIEW"] = "0"
os.environ.pop("OPENROUTER_API_KEY", None)
import re
import unittest

from streamlit.testing.v1 import AppTest

import ATSLab_v3 as L
import dashboard as D

HERE = os.path.dirname(os.path.abspath(__file__))
PAIRS = {"mohamed": ("testcvs/MohamedShokry-original.pdf", "testcvs/Mohamedshokry_Takeda.pdf"),
         "neda": ("CVS/NedaSefati_Creatio.pdf", "CV4/NedaSefati_Creatio.pdf")}
_cache = {}


def check(rel):
    if rel not in _cache:
        with open(os.path.join(HERE, rel), "rb") as f:
            _cache[rel] = D.run_check(f.read(), os.path.basename(rel), False, "")
    return _cache[rel]


def pair(name):
    old, new = PAIRS[name]
    return check(old), check(new)


# words that belong to the normal report only: they would describe or promise something about the 1000Jobs resume
NORMAL_ONLY = ("can reach", "Still not fixed", "Fixed since last version", "New in this version", "Top issues",
               "Biggest gain", "After top fixes", "issues found", "points lost", "pts", "What we'll fix",
               "How 1000Jobs will improve", "then this adds", "Other issues")


def titles(doc, cls):
    """The issue names shown in blocks of this class ('imv' = Improved, 'ci' = Issues in the original resume)."""
    return [D.html.unescape(t) for t in re.findall(rf'<div class="{cls}">.*?<div class="t">(.*?)</div>', doc)]


class TestClientReport(unittest.TestCase):
    def test_exactly_three_sections_then_why_1000jobs(self):
        for name in PAIRS:
            old, new = pair(name)
            doc = D.comparison_document(old, new)
            with self.subTest(pair=name):
                self.assertEqual(re.findall(r"<h2>(.*?)</h2>", doc),
                                 ["Compared", "Improved", "Issues in the original resume"])
                self.assertEqual(re.findall(r"<h3>(.*?)</h3>", doc), ["Why 1000Jobs"])
                self.assertGreater(doc.index("Why 1000Jobs"), doc.index("Issues in the original resume"))
                for t in D.IMPROVE_TEXT["why"]:
                    self.assertIn(D.esc(t), doc)

    def test_the_two_scores_side_by_side(self):
        old, new = pair("mohamed")
        doc = D.comparison_document(old, new)
        d = round(new["score"]) - round(old["score"])
        self.assertIn(f'Original resume: {D.fmt(old["score"])}', doc)
        self.assertIn(f'1000Jobs resume: {D.fmt(new["score"])}', doc)
        self.assertIn(f'({"+" if d >= 0 else "−"}{abs(d)})', doc)
        for p in ("readability", "content", "structure"):
            self.assertIn(f'<tr><td>{D.PART_NAMES[p]}</td><td>{D.fmt(old["parts"][p])}</td>'
                          f'<td>{D.fmt(new["parts"][p])}</td>', doc)

    def test_no_issue_of_the_1000jobs_resume_is_shown(self):
        for name in PAIRS:
            old, new = pair(name)
            doc = D.comparison_document(old, new)
            old_cards, new_cards = D.issue_cards(old), D.issue_cards(new)
            only_new = [c["name"] for c in new_cards if c["name"] not in {x["name"] for x in old_cards}]
            with self.subTest(pair=name):
                self.assertTrue(only_new, "this pair should have issues of the 1000Jobs resume to hide")
                for n in only_new:
                    self.assertNotIn(D.esc(n), doc)
                for w in NORMAL_ONLY:
                    self.assertNotIn(w, doc)
                # every issue shown is an issue of the ORIGINAL resume, with its quote from the original
                self.assertEqual(titles(doc, "ci"), [c["name"] for c in old_cards])
                new_keys = {c["key"] for c in new_cards if not c.get("ai")}
                improved = D.client_comparison(old, new)["improved"]
                self.assertEqual(titles(doc, "imv"), [c["name"] for c in improved])
                for c in improved:
                    self.assertNotIn(c["key"], new_keys)                       # fixed in the 1000Jobs resume
                    self.assertFalse(c.get("ai"))
                    self.assertTrue(D.short_quote(c, old))

    def test_each_original_issue_has_severity_quote_why_and_fix(self):
        old, new = pair("mohamed")
        doc = D.comparison_document(old, new)
        blocks = doc.split('<div class="ci">')[1:]
        self.assertEqual(len(blocks), len(D.issue_cards(old)))
        for b, c in zip(blocks, D.issue_cards(old)):
            with self.subTest(issue=c["name"]):
                self.assertIn(c["tag"], b)
                self.assertIn(D.CLIENT_TEXT["quote"], b)
                self.assertIn(D.esc(c["why"]), b)
                self.assertIn(D.esc(c["fix"]), b)

    def test_improved_lines_have_a_short_before_quote_and_what_changed(self):
        old, new = pair("mohamed")
        improved = D.client_comparison(old, new)["improved"]
        self.assertTrue(improved)
        for c in improved:
            q = D.short_quote(c, old)
            self.assertLessEqual(len(q), D.MAX_QUOTE_LINES)
            self.assertTrue(all(len(l) <= D.MAX_QUOTE_CHARS for l in q))
        doc = D.comparison_document(old, new)
        self.assertEqual(doc.count(f'<b>{D.CLIENT_TEXT["changed"]}:</b>'), len(improved))

    def test_pdf_file_name(self):
        old, new = pair("mohamed")
        self.assertEqual(D.report_file_name(new, "pdf", old),
                         f"1000Jobs ATS Lab - Mohamed Shokry - Comparison - {L.TODAY.isoformat()}.pdf")
        self.assertEqual(D.report_file_name(new), f"1000Jobs ATS Lab - Mohamed Shokry - {L.TODAY.isoformat()}.pdf")


class TestNormalReportUnchanged(unittest.TestCase):
    def test_the_normal_report_still_shows_every_issue_of_the_1000jobs_resume(self):
        old, new = pair("mohamed")
        doc = D.report_document(new)
        for c in D.issue_cards(new):
            self.assertIn(D.esc(c["name"]), doc)
        self.assertIn("Top issues", doc)
        for t in (D.CLIENT_TEXT["report_title"], "Issues in the original resume", "Original resume:"):
            self.assertNotIn(t, doc)
        self.assertNotIn(D.CLIENT_CSS, doc)                             # same page as before, to the byte


def client_page(client):
    """The results page for Mohamed's original resume and his 1000Jobs resume (AppTest cannot upload a file)."""
    import os
    import dashboard as D
    here = os.path.dirname(os.path.abspath(D.__file__))

    def run(rel):
        with open(os.path.join(here, rel), "rb") as f:
            return D.run_check(f.read(), os.path.basename(rel), False, "")
    D.render(run("testcvs/Mohamedshokry_Takeda.pdf"), False, run("testcvs/MohamedShokry-original.pdf"), client=client)


_REAL_MAKE_PDF = D.make_pdf


def setUpModule():
    """The pages here never wait for a browser to print a PDF (test_report makes real PDFs)."""
    D.make_pdf = lambda html_doc, timeout=None: b"%PDF-1.4 " + b"0" * D.PDF_MIN_BYTES


def tearDownModule():
    D.make_pdf = _REAL_MAKE_PDF


def page_text(at):
    parts = [x.value for x in at.markdown] + [x.value for x in at.subheader] + [x.value for x in at.caption]
    parts += [x.label for x in at.expander] + [x.value for x in at.info]
    return "\n".join(str(p) for p in parts)


class TestPage(unittest.TestCase):
    def test_the_checkbox_is_in_compare_with_a_previous_resume(self):
        at = AppTest.from_file(os.path.join(HERE, "dashboard.py"), default_timeout=120).run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual([c.label for c in at.checkbox], [D.CLIENT_TEXT["checkbox"]])
        self.assertFalse(at.checkbox[0].value)                          # not ticked: the normal report

    def test_ticked_the_page_shows_only_the_client_report(self):
        at = AppTest.from_function(client_page, args=(True,), default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        text = page_text(at)
        self.assertEqual(re.findall(r"<h2>(.*?)</h2>", text), ["Compared", "Improved", "Issues in the original resume"])
        self.assertIn("Why 1000Jobs", text)
        for w in NORMAL_ONLY + ("Compared with the previous resume", "Details"):
            self.assertNotIn(w, text)
        self.assertEqual([b.label for b in at.get("download_button")], [D.REPORT_TEXT["download"]])

    def test_not_ticked_the_team_still_sees_everything(self):
        at = AppTest.from_function(client_page, args=(False,), default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        text = page_text(at)
        for t in ("Compared with the previous resume", "Still not fixed", "Top issues", "can reach", "Details"):
            self.assertIn(t, text)
        self.assertNotIn("Issues in the original resume", text)


if __name__ == "__main__":
    unittest.main()
