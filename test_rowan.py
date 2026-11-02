"""
2026-10-25: errors found on a real resume (Rowan_Elatrache_CV.pdf: designed pages + a text version in one file).
Each fix is general (no rule for one person, file or template):

1. full month names in date ranges are read, and a resume with no 'Experience' heading still has its experience years
2. a file with a designed version and a text version: one note, the text version is scored
3. quotes: never just the name, 'Not found in your resume' when something is missing, never letter-spaced text
4. a name over two lines is one name
5. a UAE mobile number 05... is suggested as +971 5x ...
6. 'Few bullets show numbers' quotes bullets only
7. AI findings are Important at most; a gap covered by an education entry is not a gap

  py -3.12 -m unittest test_rowan -v
"""

import os

os.environ["ATSLAB_AI_REVIEW"] = "0"
import glob
import re
import shutil
import tempfile
import unittest

import ATSLab_v3 as L
import cv_layout as Y
import cv_review as R
import cv_score as C
import dashboard as D
import test_cv_score as T

HERE = os.path.dirname(os.path.abspath(__file__))
ROWAN = os.path.join(HERE, "testcvs", "Rowan_Elatrache_CV.pdf")
ROWAN_OLD = os.path.join(HERE, "weakcvs", "Rowan_Elatrache_Original_CV.pdf")
SPACED = re.compile(r"(?:(?:^|(?<=[^A-Za-z]))[A-Za-z] ){3,}[A-Za-z](?![A-Za-z])")
_cache = {}


def check(path):
    if path not in _cache:
        if not os.path.exists(path):
            raise unittest.SkipTest(f"{os.path.basename(path)} is not on this machine")
        with open(path, "rb") as f:
            _cache[path] = D.run_check(f.read(), os.path.basename(path), False, "")
    return _cache[path]


def all_quotes(r):
    out = []
    for c in D.issue_cards(r):
        cap, now, after = D.before_after(c, r)
        out += [(c["name"], q) for q in D.evidence(c, r) + now + [a[0] if isinstance(a, tuple) else a
                                                                  for a in (after or [])]]
    return out


class TestFullMonthNames(unittest.TestCase):
    def test_ranges_with_full_month_names(self):
        for text, months in (("September 2019 - August 2021", 24), ("January 2025 - Present", None),
                             ("Designer I Brand Lead January 2025 - Present", None),
                             ("Integrated Designer September 2019 - August 2021", 24),
                             ("April 2023 - August 2024", 17), ("Sept 2019 - Aug 2021", 24)):
            with self.subTest(text=text):
                got = L.find_ranges(text)
                self.assertEqual(len(got), 1, text)
                self.assertTrue(got[0]["month_format"], text)
                if months:
                    self.assertEqual(got[0]["end"] - got[0]["start"] + 1, months)

    def test_experience_years_without_an_experience_heading(self):
        text = """JANE DOE
jane.doe@mail.com | +971 50 123 4567
EXECUTIVE SUMMARY
A designer with eight years of experience in branding and campaigns.
EDUCATION
Bachelor of Arts in Design, University of Dubai September 2008 - June 2012
CAREER IMPACT AT A GLANCE
- 8+ years of experience: Delivered branding and campaigns for regional clients.
BLR WORLD (Dubai, U.A.E)
Brand Lead January 2021 - Present
- Led the brand team across five markets.
JAMES CONSULTANCY (Dubai, U.A.E)
Integrated Designer September 2015 - August 2019
- Built 12 identity systems for regional clients.
SELECT ACHIEVEMENTS
- Won a gold award for a rebrand.
LANGUAGES
English, Arabic"""
        doc = T.fake_doc(text)
        ana = C.analyse_cv(doc)
        self.assertEqual([s["kind"] for s in ana["sections"]].count("experience"), 1)
        self.assertEqual(len(ana["jobs"]), 2)
        self.assertGreater(L.experience_years(ana["jobs"]), 7)
        self.assertEqual(L.experience_years(L.analyse(doc)["jobs"]), L.experience_years(ana["jobs"]))
        exp = next(s for s in ana["sections"] if s["kind"] == "experience")
        self.assertEqual(exp["rows"][0]["text"], "BLR WORLD (Dubai, U.A.E)")      # the company line stays with its job
        self.assertEqual(ana["sections"][-1]["kind"], "languages")                 # achievements / languages stay out

    def test_a_resume_with_an_experience_heading_is_unchanged(self):
        doc = T.polished_cv()
        sections = L.analyse(doc)["sections"]
        self.assertIs(L.synthesize_experience(sections), sections)

    def test_the_rowan_file(self):
        r = check(ROWAN)
        self.assertGreater(r["experience_years"], 9)
        self.assertFalse([c for c in D.issue_cards(r) if re.search(r"\b0 years", " ".join(D.evidence(c, r)))])
        self.assertNotIn("about 0 years", " ".join(q for _, q in all_quotes(r)))


class TestTwoVersionsInOneFile(unittest.TestCase):
    """2026-10-26 (rule 1): the whole file is scored, as an ATS reads it; the note stays and changes no score."""

    def test_the_note_and_the_whole_file_is_scored(self):
        r = check(ROWAN)
        two = r["two_versions"]
        self.assertEqual(two["designed_pages"], [1, 2])
        self.assertEqual(two["start_page"], 3)
        self.assertTrue(r["notes"][0].startswith("This file has a designed version and a text version. "
                                                 "For online applications, upload only the text version."))
        for issue in ("columns side by side", "a page that is an image", "letter-spaced or broken headings"):
            self.assertIn(issue, r["notes"][0])
        self.assertEqual(r["layout"]["pages"], 8)                       # every page is scored
        self.assertTrue(r["layout_limits"]["landscape"] and r["layout_limits"]["columns"])
        self.assertLessEqual(r["score"], 40)                            # landscape + columns: at most 40
        self.assertEqual(r["layout_limits"]["image_pages"], 1)

    def test_the_designed_pages_count(self):
        r = check(ROWAN)
        tpl = next(i for i in r["issues"] if i["id"] == "TPL")
        self.assertEqual(tpl["severity"], "Critical")
        for reason in ("columns side by side", "a landscape page", "a page that is an image"):
            self.assertTrue([x for x in tpl["reasons"] if reason in x], tpl["reasons"])
        self.assertIn("T15", [i["id"] for i in r["issues"]])

    def test_the_note_is_in_the_report_once(self):
        r = check(ROWAN)
        doc = D.report_document(r, D.issue_cards(r))
        self.assertEqual(doc.count("This file has a designed version and a text version."), 1)
        self.assertIn('class="note vers"', doc)

    def test_normal_resumes_have_no_such_note(self):
        for p in (ROWAN_OLD, os.path.join(HERE, "strongcvs", "Jibran_Konkar_Resume.pdf"),
                  os.path.join(HERE, "testcvs", "MohamedShokry-original.pdf")):
            if os.path.exists(p):
                with self.subTest(cv=os.path.basename(p)):
                    self.assertIsNone(Y.find_text_version(p))

    def test_a_two_column_resume_is_not_two_versions(self):
        import test_columns as TC
        tmp = tempfile.mkdtemp()
        try:
            for name in ("two", "three", "left_sidebar", "landscape"):
                path = os.path.join(tmp, name + ".pdf")
                TC.make_layout_cv(path, name)
                self.assertIsNone(Y.find_text_version(path), name)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_bullet_column_is_not_a_text_column(self):
        # page 4 / 8 of the text version: a list of bullets and wrapped lines on a wide page is one column
        import pdfplumber
        if not os.path.exists(ROWAN):
            self.skipTest("no Rowan file")
        with pdfplumber.open(ROWAN) as pdf:
            counts = [Y.find_regions(p.extract_words(), p.width, p.height)[1] for p in pdf.pages]
        self.assertGreater(counts[0], 1)                                 # the designed page has columns
        self.assertEqual(counts[2:], [1] * 6)                           # the text pages have none


class TestQuotes(unittest.TestCase):
    def test_never_just_the_name_and_not_found_when_missing(self):
        r = check(ROWAN)
        names = {"rowan", "elatrache", "rowan elatrache"}
        for c in D.issue_cards(r):                 # the quotes of the card (the 'after the fix' example may show it)
            for q in D.evidence(c, r) + D.before_after(c, r)[1]:
                self.assertNotIn(re.sub(r"\W+", " ", q).strip().lower(), names, (c["name"], q))
        cards = {c["key"]: c for c in D.issue_cards(r)}
        checked = 0
        for key in ("uae_details", "location", "linkedin"):
            if key in cards:                                  # missing items: nothing to quote
                checked += 1
                self.assertEqual(D.evidence(cards[key], r), ["Not found in your resume"], key)
        self.assertGreaterEqual(checked, 1)

    def test_the_old_designed_file_never_quotes_the_name_or_broken_headings(self):
        r = check(ROWAN_OLD)
        for card, q in all_quotes(r):
            self.assertFalse(SPACED.search(q), (card, q))
            self.assertNotRegex(q, r"PROFI LE|I N FO|EDUCAT ION|CORE SKI LLS|E XPERI ENCE|L ANG UAGES")
        for c in D.issue_cards(r):
            for q in D.evidence(c, r) + D.before_after(c, r)[1]:
                self.assertNotIn(re.sub(r"\W+", " ", q).strip().upper(), ("ROWAN", "ROWAN ELATRACHE"), (c["name"], q))

    def test_broken_headings_are_put_back_together(self):
        for broken, fixed in (("PROFI LE", "PROFILE"), ("I N FO", "INFO"), ("CRE AT I VE SKI LLS", "CREATIVE SKILLS"),
                              ("ACCOM PLISH M EN T S", "ACCOMPLISHMENTS"), ("E XPERI ENCE", "EXPERIENCE"),
                              ("L ANG UAGES", "LANGUAGES"), ("EDUCAT ION", "EDUCATION")):
            self.assertEqual(Y.repair_heading(broken), fixed)
        for same in ("WORK EXPERIENCE", "ELATRACHE", "Profile", "CORE SKILLS", "ROWAN"):
            self.assertEqual(Y.repair_heading(same), same)

    def test_a_missing_item_is_never_quoted_with_the_name(self):
        r = T.Base()
        r.setUp()
        try:
            doc = T.changed(" | Dubai, UAE | ", " | ")
            res = r.score(doc)
        finally:
            r.tearDown()
        res["_doc"] = doc
        card = next(c for c in D.issue_cards(res) if c["key"] == "location")
        self.assertEqual(D.evidence(card, res), [D.NOT_FOUND])
        self.assertEqual(D.NOT_FOUND, "Not found in your resume")


class TestNameOverTwoLines(unittest.TestCase):
    def rows(self, lines):
        return [{"page": 0, "text": t, "cells": [t], "x0": 40, "x1": 40 + 9 * len(t), "top": top, "bottom": top + size,
                 "font": "Bold", "size": size} for t, top, size in lines]

    def doc(self, lines):
        text = "\n".join(t for t, *_ in lines)
        return {"strict": text, "modern": text, "rows": self.rows(lines)}

    def test_two_one_word_lines_are_one_name(self):
        d = C.join_wrapped(self.doc([("ROWAN", 30, 24), ("ELATRACHE", 56, 24), ("rowan@mail.com | +971 50 123 4567", 90, 9),
                                     ("EXECUTIVE SUMMARY", 120, 10)]))
        self.assertEqual(d["rows"][0]["text"], "ROWAN ELATRACHE")
        self.assertEqual(d["modern"].splitlines()[0], "ROWAN ELATRACHE")
        ana = C.analyse_cv(d)
        self.assertEqual(ana["header"][0]["text"], "ROWAN ELATRACHE")
        self.assertNotIn("ELATRACHE", [s["title"] for s in ana["sections"]])

    def test_a_heading_after_the_name_is_not_joined_to_it(self):
        for heading in ("SUMMARY", "PROFILE", "EXPERIENCE", "CONTACT"):
            d = self.doc([("ROWAN", 30, 24), (heading, 56, 24), ("text of the section goes here", 90, 9)])
            self.assertIs(C.join_wrapped(d), d)

    def test_the_old_designed_file_shows_the_full_name(self):
        r = check(ROWAN_OLD)
        self.assertEqual(D.candidate_name(r), "Rowan Elatrache")
        self.assertEqual(D.report_file_name(r), f"1000Jobs ATS Lab - Rowan Elatrache - {L.TODAY.isoformat()}.pdf")
        self.assertIn("Rowan Elatrache", D.header_html(r))

    def test_the_banner_above_the_name_is_not_the_name(self):
        r = check(ROWAN)
        self.assertEqual(D.candidate_name(r), "Rowan Elatrache")
        self.assertNotIn("Applicant Tracking", D.header_html(r))
        banner = "Additional Detailed Information for (ATS) Applicant Tracking System Optimisation"
        self.assertEqual(len(C.drop_banner(self.doc([(banner, 10, 9), ("ROWAN ELATRACHE", 30, 20),
                                                     ("a@b.com", 60, 9)]))["rows"]), 2)


class TestUaeMobile(unittest.TestCase):
    def test_05_numbers_become_plus_971(self):
        for given, fixed in (("0505767221", "+971 50 576 7221"), ("0505017855", "+971 50 501 7855"),
                             ("050 576 7221", "+971 50 576 7221"), ("052-888-4433", "+971 52 888 4433"),
                             ("0585165848", "+971 58 516 5848")):
            self.assertEqual(D.phone_fixed(given), fixed)

    def test_other_numbers_keep_their_rule(self):
        self.assertEqual(D.phone_fixed("(+971) 585-516-848"), "+971 58 551 6848")
        self.assertTrue(D.phone_fixed("0412345678").startswith("+[country code]"))      # not a UAE mobile number
        self.assertTrue(D.phone_fixed("+44 7700 900123").startswith("+44 770"))

    def test_the_card_suggests_it(self):
        r = check(ROWAN_OLD)
        card = next(c for c in D.issue_cards(r) if c["key"] == "phone")
        after = D.before_after(card, r)[2]
        self.assertIn("+971 50 576 7221", after[0][0])
        self.assertNotIn("[country code]", after[0][0])


class TestBulletsOnly(T.Base):
    def test_few_numbers_quotes_only_bullets(self):
        doc = T.polished_cv(numbers=False)
        r = self.score(doc)
        ev = r["content_checks"]["C1"]["evidence"]
        self.assertTrue(ev)
        text = doc["modern"]
        bullets = [l[2:] for l in text.splitlines() if l.startswith("- ")]
        for q in ev:
            self.assertIn(q, bullets)
            for banned in ("Logistics Coordinator with seven years", "Bachelor of Science", "University of Dubai"):
                self.assertNotIn(banned, q)

    def test_no_bullet_marks_never_quotes_summary_or_education(self):
        text = T.polished_cv(numbers=False)["modern"].replace("\n- ", "\n")
        doc = T.fake_doc(text)
        ana = C.analyse_cv(doc)
        for q in C.no_number_quotes(ana):
            self.assertNotIn("University of Dubai", q)
            self.assertNotIn("seven years of experience", q)
            self.assertNotRegex(q, r"\b(19|20)\d\d\b")


class FakeAI:
    def __init__(self, answer):
        self.answer = answer

    def __call__(self, prompt, model):
        return self.answer


class TestAiFindings(T.Base):
    QUOTE = "Coordinated weekly freight forwarding shipments across GCC markets without customs penalties."

    def finding(self, issue, severity="Critical", quote=None):
        return {"issue": issue, "severity": severity, "type": "content", "quote": quote or self.QUOTE,
                "why": "A recruiter would notice.", "fix": "Fix it."}

    def test_critical_becomes_important(self):
        kept, _ = R.clean({"findings": [self.finding("Dates look inconsistent")]}, [self.QUOTE])
        self.assertEqual([k["severity"] for k in kept], ["Major"])

    def test_no_ai_card_is_ever_critical(self):
        real, had_key = L.call_ai, os.environ.get("OPENROUTER_API_KEY")
        L.call_ai = FakeAI({"field": "logistics", "findings": [self.finding("Dates look inconsistent"),
                                                                self.finding("Vague role", "Major")]})
        os.environ["OPENROUTER_API_KEY"] = "test"
        cache = tempfile.mkdtemp()
        try:
            r = C.score_cv("jane.pdf", None, T.ROLE, doc=T.polished_cv(numbers=False), role_cache=self.cache,
                           review=True, review_cache=cache)
        finally:
            L.call_ai = real
            shutil.rmtree(cache, ignore_errors=True)
            if had_key is None:
                os.environ.pop("OPENROUTER_API_KEY", None)
        ai = [i for i in r["issues"] if i.get("ai")]
        self.assertEqual(len(ai), 2)
        self.assertNotIn("Critical", [i["severity"] for i in ai])

    def test_a_gap_covered_by_an_education_entry_is_not_a_gap(self):
        base = """JANE DOE
jane.doe@mail.com | +971 50 123 4567 | Dubai, UAE
SUMMARY
A designer with many years of experience in branding.
EXPERIENCE
Integrated Designer | Sep 2019 - Aug 2021
James Consultancy | Dubai, UAE
- Built 12 identity systems for regional clients.
Brand Creative Designer | Apr 2023 - Aug 2024
Virgin Media | London, UK
- Designed assets for 3 brands.
EDUCATION
{edu}
"""
        with_ma = C.timeline(C.analyse_cv(T.fake_doc(base.format(
            edu="Master of Arts in Graphic Branding, University of the Arts London, Sep 2021 - Feb 2023"))))
        without = C.timeline(C.analyse_cv(T.fake_doc(base.format(
            edu="Bachelor of Arts in Design, University of Dubai, Sep 2012 - Jun 2016"))))
        self.assertEqual(with_ma["gaps"], [])
        self.assertTrue(without["gaps"])                                  # the gap is real without the MA
        kept, rejected = R.clean({"findings": [self.finding("Unexplained employment gap", "Major")]}, [self.QUOTE])
        self.assertEqual((kept, len(rejected)), ([], 1))                  # v1.1: no gap finding is ever kept

    def test_a_degree_listed_under_another_heading_also_covers_its_months(self):
        text = """JANE DOE
jane.doe@mail.com | +971 50 123 4567 | Dubai, UAE
EXPERIENCE
Designer | Sep 2019 - Aug 2021
Studio One | Dubai, UAE
- Built 12 identity systems for regional clients.
UNIVERSITY OF THE ARTS LONDON
Master of Arts in Graphic Branding Sep 2021 - Feb 2023
- Explored brand strategy through research.
Designer | Apr 2023 - Aug 2024
Studio Two | London, UK
- Designed assets for 3 brands.
"""
        self.assertEqual(C.timeline(C.analyse_cv(T.fake_doc(text)))["gaps"], [])


if __name__ == "__main__":
    unittest.main()
