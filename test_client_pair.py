"""
The client comparison report must never mix the two files: the client's original resume and our 1000Jobs resume.

The real case this comes from (Sana, 2026-11-02): the form says the main upload is the 1000Jobs resume and
"Compare with a previous resume" is the client's own resume, but the two were uploaded the other way round. The
report then described the 1000Jobs resume as if it were the original: the "CAREER IMPACT AT A GLANCE" box heading,
the ** marks and the highlight boxes were shown as problems of the original, and "No city in the contact details"
was said about a resume whose original has "Dubai, United Arab Emirates".

The roles are now decided by the 1000Jobs marks a file carries (the highlight boxes, the watermark, "Select
Achievements", the ** marks), never by the upload slot alone. These tests use two generated resumes - an original
without those marks and a 1000Jobs one with them - and hold that line:
  * both upload orders give exactly the same report,
  * the header names the right file as the original,
  * an issue that only the 1000Jobs resume has is never shown,
  * every "Before" quote is text of the resume it is presented as.
No scoring is involved.

  py -3.12 -m unittest test_client_pair -v
"""

import io
import os

os.environ["ATSLAB_AI_REVIEW"] = "0"
os.environ.pop("OPENROUTER_API_KEY", None)
import re
import unittest

from reportlab.pdfgen import canvas
from streamlit.testing.v1 import AppTest

import admin_page as A
import dashboard as D
import lab_store as H
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
ORIGINAL = "Layla_Example_CV.pdf"                              # the client's own resume
OURS = "Layla_Example_Amazon_ACES.pdf"                         # the 1000Jobs resume
MARKS = ("CAREER IMPACT AT A GLANCE", "Select Achievements", "**", "Prepared with 1000Jobs")
_cache = {}


def cv_pdf(ours):
    """The same person, one page: the client's own resume (plain, with her city) or our 1000Jobs resume (the
    highlight boxes, "Select Achievements", a ** mark, the watermark and month-year dates the original lacks)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    y = 800

    def line(text, bold=False, size=10.5, gap=14):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(50, y, text)
        y -= gap

    line("Layla Example, PMP", True, 20, 24)
    line("Senior Programme Manager | Programme Delivery", False, 11, 16)
    line("layla.example@mail.com | +971 50 123 4567 | Dubai, United Arab Emirates | linkedin.com/in/layla-example",
         False, 10, 24)
    if ours:
        line("CAREER IMPACT AT A GLANCE", True, 12, 16)
        line("$4.9M programme delivered | 14 clients | NPS up 42%", gap=22)
    line("PROFESSIONAL SUMMARY", True, 12, 16)
    if ours:
        line("Programme manager with 15 years of experience, delivering a **$4.9M flagship programme** for a", gap=12)
        line("national energy client and growing one engagement into a four-year programme.", gap=22)
    else:
        line("Programme manager with 15 years of experience delivering multi-year programmes for enterprise", gap=12)
        line("and government clients across the region, including national energy companies and banks.", gap=22)
    line("PROFESSIONAL EXPERIENCE", True, 12, 18)
    for title, company, dates in (("Programme Manager", "Example Energy", "Jan 2019 - Dec 2023" if ours
                                   else "2019 - 2023"),
                                  ("Client Partner", "Example Consulting", "Feb 2014 - Dec 2018" if ours
                                   else "2014 - 2018")):
        line(f"{title} | {company} | Dubai, UAE | {dates}", True)
        line("- Delivered a multi-year programme for a national energy client across the region.")
        line("- Led a team of 8 people and managed the programme governance and reporting.", gap=18)
    if ours:
        line("SELECT ACHIEVEMENTS", True, 12, 16)
        line("Grew a single engagement into a four-year programme; client NPS up 42%.", gap=22)
    line("EDUCATION", True, 12, 16)
    line("MBA | University of Example | 2011", gap=22)
    line("SKILLS", True, 12, 16)
    line("Programme management, governance, stakeholder management, risk management, reporting, budgeting")
    if ours:
        line("Prepared with 1000Jobs", gap=14)
    c.save()
    return buf.getvalue()


def check(which):
    """The parsed report of one of the two resumes (no AI review, no key: nothing is scored differently)."""
    if which not in _cache:
        ours = which == "ours"
        _cache[which] = D.run_check(cv_pdf(ours), OURS if ours else ORIGINAL, False, "")
    return _cache[which]


def titles(doc, cls):
    """The issue names shown in the blocks of this class ('imv' = Improved, 'ci' = Issues in the original resume)."""
    return [D.html.unescape(t) for t in re.findall(rf'<div class="{cls}">.*?<div class="t">(.*?)</div>', doc)]


def quote_lines(doc):
    """Every quote line shown in the report, as one flat list."""
    return [D.html.unescape(line) for block in re.findall(r'<div class="code now">(.*?)</div>', doc)
            for line in block.split("<br>")]


def resume_parts(line):
    """The pieces of a quote line that are resume text: the line itself and what stands before a "  (note)"."""
    return [p for p in (line, re.split(r"\s{2,}\(", line)[0]) if len(p.split()) >= 3]


class TestTheRolesAreNeverSwapped(unittest.TestCase):
    def test_the_1000jobs_marks_decide_the_roles(self):
        original, ours = check("original"), check("ours")
        self.assertEqual(D.looks_like_1000jobs(original), 0)
        self.assertGreaterEqual(D.looks_like_1000jobs(ours), 3)
        for main, previous, swapped in ((ours, original, False), (original, ours, True)):
            with self.subTest(main=main["cv"]):
                old, new, flag = D.client_pair(main, previous)
                self.assertIs(old, original)
                self.assertIs(new, ours)
                self.assertEqual(flag, swapped)
        # the roles never move again, whatever order the pair is handed in
        self.assertEqual(D.client_pair(original, ours)[:2], (original, ours))
        self.assertEqual(D.client_pair(ours, original)[:2], (original, ours))

    def test_both_upload_orders_give_the_same_report(self):
        original, ours = check("original"), check("ours")
        self.assertEqual(D.client_document(original, ours), D.client_document(ours, original))

    def test_the_header_names_the_right_files(self):
        doc = D.client_document(check("ours"), check("original"))                    # the swapped upload order
        self.assertIn(f"<dt>{D.CLIENT_TEXT['original_file']}</dt><dd>{ORIGINAL}</dd>", doc)
        self.assertIn(f"<dt>{D.CLIENT_TEXT['ours_file']}</dt><dd>{OURS}</dd>", doc)

    def test_no_mark_of_the_1000jobs_resume_is_ever_shown(self):
        original, ours = check("original"), check("ours")
        for first, second in ((original, ours), (ours, original)):
            with self.subTest(main=first["cv"]):
                doc = D.client_document(first, second)
                for mark in MARKS:
                    self.assertNotIn(mark, doc)

    def test_the_compared_section_shows_the_file_name_under_each_score(self):
        original, ours = check("original"), check("ours")
        doc = D.client_document(ours, original)
        blocks = re.findall(r'<div class="(old|ours)">.*?<div class="file">(.*?)</div>', doc, re.S)
        self.assertEqual(blocks, [("old", ORIGINAL), ("ours", OURS)])   # left = the user's own, right = ours

    def test_no_city_is_never_said_about_a_resume_that_has_one(self):
        original, ours = check("original"), check("ours")
        self.assertFalse(D.missing_item("location", original), "the generated original has a city")
        self.assertNotIn(D.ISSUES["location"]["name"], D.client_document(ours, original))

    def test_every_shown_issue_and_quote_belongs_to_the_original(self):
        original, ours = check("original"), check("ours")
        old_cards, new_cards = D.issue_cards(original), D.issue_cards(ours)
        only_new = [c["name"] for c in new_cards if c["name"] not in {x["name"] for x in old_cards}]
        self.assertTrue(only_new, "the 1000Jobs resume must have an issue of its own, or this test proves nothing")
        for first, second in ((original, ours), (ours, original)):
            with self.subTest(main=first["cv"]):
                doc = D.client_document(first, second)
                self.assertEqual(titles(doc, "ci"), [c["name"] for c in old_cards])
                improved = D.client_comparison(*D.client_pair(first, second)[:2])["improved"]
                self.assertEqual(titles(doc, "imv"), [c["name"] for c in improved])
                new_keys = {c["key"] for c in new_cards if not c.get("ai")}
                for c in improved:
                    self.assertNotIn(c["key"], new_keys)                            # fixed in the 1000Jobs resume
                    self.assertFalse(c.get("ai"))
                for n in only_new:
                    self.assertNotIn(D.esc(n), doc)
                mine, theirs = D.own_text(original), D.own_text(ours)
                self.assertTrue(quote_lines(doc))
                for line in quote_lines(doc):
                    keys = [D.quote_key(p) for p in resume_parts(line)]
                    self.assertFalse(any(k and k in theirs for k in keys) and not any(k and k in mine for k in keys),
                                     f"this quote is text of the 1000Jobs resume: {line!r}")


def client_page(which):
    """The Admin result page for the two resumes: 'swapped' = the 1000Jobs resume was uploaded as the previous one.
    (AppTest cannot upload a file, so the two resumes are generated and parsed again inside this page.)"""
    import importlib.util
    import os

    import dashboard as D
    here = os.path.dirname(os.path.abspath(D.__file__))
    spec = importlib.util.spec_from_file_location("client_pair_page", os.path.join(here, "test_client_pair.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    original, ours = mod.check("original"), mod.check("ours")
    main, previous = (original, ours) if which == "swapped" else (ours, original)
    D.render(main, False, previous, client=True)


class TestThePageSaysWhenTheFilesCameInSwapped(unittest.TestCase):
    def test_the_swapped_order_is_said_plainly(self):
        check("original")
        check("ours")
        at = AppTest.from_function(client_page, args=("swapped",), default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        self.assertTrue(any("the other way round" in str(c.value) for c in at.caption),
                        [str(c.value) for c in at.caption])

    def test_the_right_order_says_nothing_extra(self):
        check("original")
        check("ours")
        at = AppTest.from_function(client_page, args=("as-uploaded",), default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        self.assertFalse(any("the other way round" in str(c.value) for c in at.caption))


class FakeFile:
    """What Streamlit puts in a file_uploader: the file's bytes and its name."""

    def __init__(self, data, name):
        self._data, self.name = data, name

    def getvalue(self):
        return self._data


def check_form_page():
    """The Admin page's upload card, drawn alone (nothing is checked: the form is what matters)."""
    import admin_page as A
    import dashboard as D
    A.check_form(D.WITHOUT_JOB)


def warning_page(which):
    """The Admin page's check of the two files before the report, drawn alone: `which` says what is in the slot of the
    user's own resume - 'their-own' (their resume) or 'ours-too' (a 1000Jobs resume in the wrong slot). The page says
    which way it went: BUILT (the two files go on) or HELD (a decision is needed first)."""
    import importlib.util
    import os

    import admin_page as A
    import dashboard as D
    import streamlit as st
    # this test module again (an AppTest page runs apart: its names are not here), for the two generated resumes
    spec = importlib.util.spec_from_file_location(
        "client_pair_sub", os.path.join(os.path.dirname(os.path.abspath(D.__file__)), "test_client_pair.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    user_file = mod.FakeFile(mod.cv_pdf(which == "ours-too"), "Layla_Example_CV.pdf")
    ours_file = mod.FakeFile(mod.cv_pdf(True), "Layla_Example_Amazon_Senior_Program_Manager_ACES.pdf")
    out = A.client_inputs(0, user_file, ours_file, False, D.WITHOUT_JOB, "", "")
    st.write("BUILT" if out else "HELD", (out or {}).get("name", ""), (out or {}).get("prev_name", ""))


class TestTheTwoSlotsAreClear(unittest.TestCase):
    def test_the_two_slots_have_their_own_names_and_hints(self):
        at = AppTest.from_function(check_form_page, default_timeout=300)
        at.session_state["client_0"] = True                 # the client comparison report is switched on
        at.run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual([u.label for u in at.get("file_uploader")],
                         [A.ADMIN_TEXT["slot_original"], A.ADMIN_TEXT["slot_ours"]])
        captions = " | ".join(str(c.value) for c in at.caption)
        for t in (A.ADMIN_TEXT["slot_original_hint"], A.ADMIN_TEXT["slot_ours_hint"], A.ADMIN_TEXT["pair_hint"]):
            self.assertIn(t, captions)
        self.assertIn(A.ADMIN_TEXT["swap"], [b.label for b in at.button])
        self.assertIn(A.ADMIN_TEXT["run"], [b.label for b in at.button])

    def test_without_the_client_report_the_form_is_as_before(self):
        at = AppTest.from_function(check_form_page, default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual([u.label for u in at.get("file_uploader")],
                         [A.ADMIN_TEXT["resume"], A.ADMIN_TEXT["previous"]])


class TestTheFilesAreCheckedBeforeTheReport(unittest.TestCase):
    def test_what_counts_as_a_1000jobs_resume(self):
        self.assertEqual(D.template_marks(cv_pdf(False), ORIGINAL), [])
        marks = D.template_marks(cv_pdf(True), ORIGINAL)                   # the text alone is enough
        self.assertTrue(any("Career Impact" in m for m in marks), marks)
        self.assertTrue(any("**" in m for m in marks), marks)
        self.assertTrue(D.name_looks_like_ours("Layla_Example_Amazon_Senior_Program_Manager_ACES.pdf"))
        self.assertFalse(D.name_looks_like_ours("Layla_Example_CV.pdf"))
        self.assertFalse(D.name_looks_like_ours("khalid_resume.pdf"))

    def test_a_1000jobs_file_in_the_users_slot_is_not_passed_silently(self):
        at = AppTest.from_function(warning_page, args=("ours-too",), default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        warns = [str(w.value) for w in at.warning]
        self.assertTrue(any("looks like a 1000Jobs resume" in w and "Layla_Example_CV.pdf" in w for w in warns), warns)
        self.assertTrue(any("BUILT" in str(m.value) for m in at.markdown) is False, "nothing goes on by itself")
        labels = [b.label for b in at.button]
        self.assertIn(A.ADMIN_TEXT["swap"], labels)
        self.assertIn(A.ADMIN_TEXT["roles_confirm"], labels)

    def test_a_normal_pair_goes_straight_on(self):
        at = AppTest.from_function(warning_page, args=("their-own",), default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual([str(w.value) for w in at.warning], [])
        self.assertTrue(any("BUILT" in str(m.value) for m in at.markdown))

    def test_continue_builds_the_report_with_the_two_files_as_they_are(self):
        at = AppTest.from_function(warning_page, args=("ours-too",), default_timeout=300).run()
        next(b for b in at.button if b.label == A.ADMIN_TEXT["roles_confirm"]).click().run()
        built = " ".join(str(m.value) for m in at.markdown)
        self.assertIn("BUILT", built)
        self.assertIn("Layla_Example_Amazon_Senior_Program_Manager_ACES.pdf", built)     # the 1000Jobs resume
        self.assertIn("Layla_Example_CV.pdf", built)                                     # the user's own resume

    def test_swap_asks_for_the_two_files_the_other_way_round(self):
        at = AppTest.from_function(warning_page, args=("ours-too",), default_timeout=300).run()
        next(b for b in at.button if b.label == A.ADMIN_TEXT["swap"]).click().run()
        self.assertTrue(at.session_state["swap_0"], "the Swap button must ask for the other way round")


HER_CV = os.path.join(os.environ.get("ATSLAB_DATA_DIR") or os.path.join(HERE, "data"), "resumes",
                      "1_Sana_Malik_CV.pdf")                                   # her own CV, as the app kept it
ACES = os.path.join(os.path.expanduser("~"), "OneDrive", "Documents", "Desktop",
                    "Sana_Malik_Amazon_Senior_Program_Manager_ACES.pdf")       # the 1000Jobs resume
NEVER = ("CAREER IMPACT AT A GLANCE", "**$4.9M", "$7.5M+ portfolio", "No city in the contact details",
         "Select Achievements")


def result_page(which):
    """The Admin page's result view (check_view) with a saved client comparison result, drawn alone."""
    import importlib.util
    import os

    import admin_page as A
    import dashboard as D
    import streamlit as st
    spec = importlib.util.spec_from_file_location(
        "client_pair_res", os.path.join(os.path.dirname(os.path.abspath(D.__file__)), "test_client_pair.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    her, ours = mod.check("original"), mod.check("ours")
    st.session_state["result"] = {"res": ours, "with_job": False, "prev": her, "swap": None,
                                  "inputs": {"client": True, "with_job": False, "job_title": ""}}
    A.check_view("Tester")


class TestTheReportAlwaysDraws(unittest.TestCase):
    """The bug the team saw after a check: the page showed the file and the "Check new resume" button and nothing
    else, because the report was drawn only when the With/General switch had been changed after the check."""

    def test_the_client_report_draws_when_the_switch_did_not_change(self):
        check("original")
        check("ours")
        at = AppTest.from_function(result_page, args=("client",), default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        page = " ".join(str(m.value) for m in at.markdown)
        self.assertIn(D.CLIENT_TEXT["compared"], page)
        self.assertIn(D.CLIENT_TEXT["improved"], page)
        self.assertIn(f'<div class="file">{ORIGINAL}</div>', page)      # her own resume under the left score
        self.assertIn(f'<div class="file">{OURS}</div>', page)          # the 1000Jobs resume under the right one
        for t in ("CAREER IMPACT AT A GLANCE", "**$4.9M", "No city in the contact details"):
            self.assertNotIn(t, page)


@unittest.skipUnless(os.path.isfile(HER_CV) and os.path.isfile(ACES), "Sana's two real files are not on this computer")
class TestTheRealPairTheTeamReported(unittest.TestCase):
    """The real pair from the team's report (2026-11-02): her own CV and the 1000Jobs resume, in the right slots.
    This is the exact case that came out with the two files the wrong way round."""

    @classmethod
    def setUpClass(cls):
        with open(HER_CV, "rb") as f:
            cls.her = D.run_check(f.read(), "Sana_Malik_CV.pdf", False, "")
        with open(ACES, "rb") as f:
            cls.ours = D.run_check(f.read(), os.path.basename(ACES), False, "")

    def test_the_header_names_her_own_cv_as_the_original(self):
        doc = D.client_document(self.ours, self.her)          # the main upload is the 1000Jobs resume
        self.assertIn(f"<dt>{D.CLIENT_TEXT['original_file']}</dt><dd>Sana_Malik_CV.pdf</dd>", doc)
        self.assertIn(f"<dt>{D.CLIENT_TEXT['ours_file']}</dt><dd>{os.path.basename(ACES)}</dd>", doc)

    def test_the_two_files_the_other_way_round_give_the_same_report(self):
        self.assertEqual(D.client_document(self.ours, self.her), D.client_document(self.her, self.ours))

    def test_nothing_of_the_1000jobs_resume_is_shown_as_hers(self):
        doc = D.client_document(self.her, self.ours)          # her CV uploaded as the main (the bug's upload order)
        for t in NEVER:
            self.assertNotIn(t, doc)
        self.assertIn(f"<dd>Sana_Malik_CV.pdf</dd>", doc)

    def test_the_saved_history_record_has_the_same_roles(self):
        rec = H.record_of(self.ours, "tester", None, self.her, True, None)     # what the History saves
        doc = rec["comparison_doc"]
        self.assertIn(f"<dt>{D.CLIENT_TEXT['original_file']}</dt><dd>Sana_Malik_CV.pdf</dd>", doc)
        for t in ("CAREER IMPACT AT A GLANCE", "**$4.9M", "No city in the contact details"):
            self.assertNotIn(t, doc)


if __name__ == "__main__":
    unittest.main()
