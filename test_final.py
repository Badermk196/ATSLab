"""
The final fixes before version 1.0: job locations are a note, the caps on Minor issues and on "No headline", the
fingerprint cache, the model loaded once, the test runner, the stacked job fields, and the client comparison report.

  py -3.12 -m unittest test_final -v
"""

import importlib
import io
import os
import re
import shutil
import tempfile
import unittest

os.environ["ATSLAB_AI_REVIEW"] = "0"
os.environ.pop("OPENROUTER_API_KEY", None)

from reportlab.pdfgen import canvas
from streamlit.testing.v1 import AppTest

import ATSLab_v3 as L
import cv_cache
import cv_layout as Y
import cv_score as C
import dashboard as D
import test_dashboard as T

HERE = os.path.dirname(os.path.abspath(__file__))


def cv_pdf(locations):
    """A one-page resume with three jobs; each job line has its location only when `locations` is true."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    y = 790

    def line(text, bold=False, size=10.5, gap=14):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(50, y, text)
        y -= gap
    line("Sami Haddad", True, 20, 24)
    line("Marketing Manager | Brand Strategy | Content", False, 11, 16)
    line("Dubai, UAE | +971 50 123 4567 | sami.haddad@mail.com | linkedin.com/in/sami-haddad", False, 10, 24)
    line("SUMMARY", True, 12, 16)
    line("Marketing manager with 9 years of experience growing brands and leading teams of up to 12 people across", gap=12)
    line("the region, with a record of cutting cost per lead and raising subscriber growth every year.", gap=22)
    line("EXPERIENCE", True, 12, 18)
    for title, company, place, dates in (("Marketing Lead", "Acme Media", "Dubai, UAE", "Mar 2023 - Present"),
                                         ("Marketing Executive", "Beta Brands", "Abu Dhabi, UAE", "Jan 2018 - Aug 2021"),
                                         ("Marketing Assistant", "Gamma Retail", "Sharjah, UAE", "Jan 2015 - Dec 2017")):
        line(f"{title} | {company}" + (f" | {place}" if locations else "") + f" | {dates}", True)
        line("- Grew subscribers by 40% across 6 markets with a new content plan.")
        line("- Launched 12 campaigns and cut cost per lead by 25%.", gap=18)
    line("EDUCATION", True, 12, 16)
    line("BA Marketing | University of Sharjah | 2014")
    line("SKILLS", True, 12, 16)
    line("Brand Marketing, Content Marketing, CRM, Project Management, Google Analytics, SEO, Excel, Tableau")
    c.save()
    return buf.getvalue()


def check(data, name="cv.pdf"):
    return D.run_check(data, name, False, "")


class TestJobLocationIsOnlyANote(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.with_place, cls.without = check(cv_pdf(True)), check(cv_pdf(False))

    def test_title_company_and_dates_still_count_and_pass_without_a_location(self):
        for r in (self.with_place, self.without):
            t4 = r["structure_checks"]["T4"]
            self.assertEqual(t4["score"], 1.0, t4["detail"])
            self.assertEqual(t4["detail"], "3 of 3 jobs have title, company and Mon YYYY dates")
        names = [c["name"] for c in D.issue_cards(self.without)]
        self.assertNotIn("Some jobs miss a title, company or Mon YYYY dates", names)

    def test_a_missing_location_costs_at_most_one_point_and_is_minor(self):
        t16 = self.without["structure_checks"]["T16"]
        self.assertEqual(t16["score"], 0.0)
        self.assertEqual(self.with_place["structure_checks"]["T16"]["score"], 1.0)
        cost = self.with_place["parts"]["structure"] - self.without["parts"]["structure"]
        self.assertGreater(cost, 0)
        self.assertLessEqual(cost, 1.0)                                   # 0-1 points
        card = next(c for c in D.issue_cards(self.without) if c["key"] == "job_locations")
        self.assertEqual(card["tag"], "Minor")
        self.assertLessEqual(D.part_points(card), 1.0)
        self.assertIn("not required", card["why"])

    def test_title_company_and_dates_keep_their_weight(self):
        self.assertGreater(C.STRUCT_WEIGHT["T4"], 0.2)
        self.assertIn("T16", C.NOTE_ONLY)                                 # a note: never the extra penalty points
        self.assertAlmostEqual(sum(C.STRUCT_WEIGHT.values()), 1.0)

    def test_a_location_note_adds_no_standard_penalty(self):
        sc = {k: {"score": 1.0, "detail": "", "evidence": []} for k in C.STRUCT_WEIGHT}
        base = C.structure_part(sc)
        sc["T16"] = {"score": 0.0, "detail": "", "evidence": []}
        self.assertAlmostEqual(base - C.structure_part(sc), 100 * C.STRUCT_WEIGHT["T16"])   # 1 point, no 2-point penalty
        self.assertNotIn("T16", C.failed_standards(sc, C.STRUCT_WEIGHT))


class TestMinorIssuesAreCapped(unittest.TestCase):
    """v1.0 ships with no Minor cap (MINOR_CAP = None). The cap is an option: these tests switch it on to check it."""
    def setUp(self):
        self.real = C.MINOR_CAP
        C.MINOR_CAP = 10.0
        self.addCleanup(setattr, C, "MINOR_CAP", self.real)

    def test_v1_ships_without_a_minor_cap(self):
        C.MINOR_CAP = self.real
        self.assertIsNone(self.real)
        sc = self.ok(C.STRUCT_WEIGHT)
        for k in ("T3", "T5", "T6", "T8"):
            sc[k]["score"] = 0.0
        lost = sum(100 * C.STRUCT_WEIGHT[k] for k in ("T3", "T5", "T6", "T8")) + 4 * C.PART_PENALTY["Minor"]
        self.assertAlmostEqual(C.structure_part(sc), 100 - lost, places=6)

    def ok(self, weights):
        return {k: {"score": 1.0, "detail": "", "evidence": []} for k in weights}

    def test_minor_issues_of_a_part_cost_ten_points_together_at_most(self):
        sc = self.ok(C.STRUCT_WEIGHT)
        for k in ("T2", "T3", "T5", "T6", "T8", "T9", "T10", "T11"):     # eight Minor structure problems
            sc[k]["score"] = 0.0
        uncapped = 100 - sum(100 * C.STRUCT_WEIGHT[k] for k in ("T2", "T3", "T5", "T6", "T8", "T9", "T10", "T11"))
        self.assertLess(uncapped, 60)                                     # they would cost over 40 points
        self.assertAlmostEqual(C.structure_part(sc), 100 - C.MINOR_CAP, places=6)

    def test_a_few_minor_issues_cost_what_they_cost(self):
        sc = self.ok(C.STRUCT_WEIGHT)
        sc["T5"]["score"] = 0.0                                           # LinkedIn: 10 weight + 2 = 12 -> over the cap...
        self.assertAlmostEqual(C.structure_part(sc), 100 - C.MINOR_CAP, places=6)
        sc = self.ok(C.STRUCT_WEIGHT)
        sc["T10"]["score"] = 0.0                                          # visa: 2 weight + 2 = 4 points
        self.assertAlmostEqual(C.structure_part(sc), 96.0, places=6)

    def test_important_issues_are_not_capped_by_it(self):
        sc = self.ok(C.STRUCT_WEIGHT)
        for k in ("T3", "T5", "T6", "T10"):
            sc[k]["score"] = 0.0
        sc["T7"]["score"] = 0.0                                           # no email: Important, 10 + 12 points
        self.assertAlmostEqual(C.structure_part(sc), 100 - C.MINOR_CAP - 22, places=6)

    def test_content_is_capped_the_same_way(self):
        cc = {k: {"score": 1.0, "detail": "", "evidence": [], "quant_share": 1.0, "bullets": 5} for k in C.CONTENT_WEIGHT}
        for k in ("C5", "C6", "C7", "C9", "C10", "C11", "C12", "C13", "C14", "C16", "C17"):
            cc[k]["score"] = 0.0
        self.assertAlmostEqual(C.content_part(cc), 100 - C.MINOR_CAP, places=6)

    def test_every_part_explanation_still_adds_up(self):
        r = check(cv_pdf(False))
        for part, e in r["part_explain"].items():
            total = sum(x["points"] for x in e["items"]) + e["other"]
            self.assertAlmostEqual(total, e["loss"], delta=0.15, msg=part)
            self.assertAlmostEqual(e["loss"], 100 - r["parts"][part], delta=0.15, msg=part)


class TestNoHeadlineCostsTheTotalAtMostTwenty(unittest.TestCase):
    def setUp(self):
        self.cc = {k: {"score": 1.0, "detail": "", "evidence": [], "quant_share": 1.0, "bullets": 5} for k in C.CONTENT_WEIGHT}
        self.cc["C8"] = {"score": None}
        self.parts = lambda cc: {"readability": 100.0, "content": C.content_part(cc), "structure": 100.0}
        self.bad_cc = {**self.cc, "C15": {**self.cc["C15"], "score": 0.0}}

    def loss(self):
        good = C.total_from(self.parts(self.cc), self.cc)[0]
        return good - C.total_from(self.parts(self.bad_cc), self.bad_cc)[0]

    def test_the_cap_is_twenty_for_v1(self):
        self.assertEqual(C.HEADLINE_CAP, 20.0)
        self.assertLessEqual(self.loss(), C.HEADLINE_CAP + 1e-9)

    def test_a_lower_cap_limits_the_loss_exactly(self):
        real = C.HEADLINE_CAP
        C.HEADLINE_CAP = 5.0
        self.addCleanup(setattr, C, "HEADLINE_CAP", real)
        uncapped = C.weighted_geo(self.parts(self.cc)) - C.weighted_geo(self.parts(self.bad_cc))
        self.assertGreater(uncapped, 5.0)
        self.assertAlmostEqual(self.loss(), 5.0, places=6)

    def test_it_stays_important_and_the_part_still_pays(self):
        self.assertEqual(C.rule_severity("C15"), "Major")
        self.assertLess(C.content_part(self.bad_cc), C.content_part(self.cc) - 20)          # the part is not capped

    def test_a_good_headline_changes_nothing(self):
        p = self.parts(self.cc)
        self.assertAlmostEqual(C.total_from(p, self.cc)[0], C.weighted_geo(p), places=6)


class TestFingerprintCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.a, self.b = os.path.join(self.tmp, "a.pdf"), os.path.join(self.tmp, "renamed copy.pdf")
        data = cv_pdf(True)                                                # the same bytes under two names
        for p in (self.a, self.b):
            with open(p, "wb") as f:
                f.write(data)
        cv_cache.clear()

    def test_the_same_file_is_read_once_whatever_its_name(self):
        first = L.extract_cv(self.a)
        misses = cv_cache.STATS["misses"]
        second = L.extract_cv(self.b)
        self.assertEqual(cv_cache.STATS["misses"], misses)               # no new reading
        self.assertGreaterEqual(cv_cache.STATS["hits"], 1)
        self.assertEqual(first, second)

    def test_the_layout_is_analysed_once_and_a_copy_is_returned(self):
        one = Y.analyse_layout(self.a)
        misses = cv_cache.STATS["misses"]
        two = Y.analyse_layout(self.b)
        self.assertEqual(cv_cache.STATS["misses"], misses)
        self.assertEqual(one["pages"], two["pages"])
        two["findings"]["D4"]["found"] = True                            # a caller changes its copy ...
        two["visual_doc"]["rows"].clear()
        three = Y.analyse_layout(self.a)
        self.assertFalse(three["findings"]["D4"]["found"])               # ... the next caller is not affected
        self.assertTrue(three["visual_doc"]["rows"])

    def test_another_file_or_other_pages_are_another_reading(self):
        L.extract_cv(self.a)
        misses = cv_cache.STATS["misses"]
        L.extract_cv(self.a, pages={0})
        self.assertEqual(cv_cache.STATS["misses"], misses + 1)
        other = os.path.join(self.tmp, "other.pdf")
        with open(other, "wb") as f:
            f.write(cv_pdf(False))
        L.extract_cv(other)
        self.assertEqual(cv_cache.STATS["misses"], misses + 2)

    def test_a_cached_check_gives_the_same_score(self):
        with open(self.a, "rb") as f:
            data = f.read()
        cv_cache.clear()
        first = check(data)
        misses = cv_cache.STATS["misses"]
        second = check(data)
        self.assertEqual(cv_cache.STATS["misses"], misses)               # the second check read nothing again
        self.assertEqual((first["score"], first["parts"]), (second["score"], second["parts"]))

    def test_the_cache_can_be_switched_off(self):
        saved = cv_cache.ENABLED
        cv_cache.ENABLED = False
        try:
            cv_cache.clear()
            L.extract_cv(self.a)
            L.extract_cv(self.a)
            self.assertEqual(cv_cache.STATS, {"hits": 0, "misses": 0})
        finally:
            cv_cache.ENABLED = saved


class TestModelLoadedOnce(unittest.TestCase):
    def test_the_model_and_its_answers_survive_a_reload_of_the_lab(self):
        before = (id(L._EMBEDDER), id(L._EMBED_CACHE), id(L._EMBED_OK))
        L._EMBED_OK[:] = [True]
        importlib.reload(L)
        self.assertEqual((id(L._EMBEDDER), id(L._EMBED_CACHE), id(L._EMBED_OK)), before)
        self.assertEqual(list(L._EMBED_OK), [True])
        self.assertIs(L._EMBEDDER, cv_cache.shared("embedder", list))
        importlib.reload(Y)                                              # the modules that import it keep working
        importlib.reload(C)


class TestTestRunner(unittest.TestCase):
    def test_quick_leaves_out_only_the_two_slow_calibration_tests(self):
        import argparse
        import run_tests
        ns = lambda **k: argparse.Namespace(**{"quick": False, "full": False, "reference": False, "files": [], **k})
        full, quick = run_tests.modules(ns(full=True)), run_tests.modules(ns(quick=True))
        self.assertEqual(sorted(set(full) - set(quick)), ["test_reference", "test_strong"])
        self.assertEqual(run_tests.modules(ns(reference=True)), ["test_reference"])
        self.assertEqual(run_tests.modules(ns(files=["test_final.py"])), ["test_final"])
        self.assertIn("test_final", quick)


def flat(block):
    out = []
    for child in block.children.values():
        out.append(child)
        if hasattr(child, "children"):
            out += flat(child)
    return out


class TestJobFieldsAreStacked(unittest.TestCase):
    def test_target_role_then_job_description_one_under_the_other_full_width(self):
        at = AppTest.from_file(os.path.join(HERE, "dashboard.py"), default_timeout=120).run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual([t.label for t in at.text_input], ["Target role (job title)"])
        self.assertEqual([t.label for t in at.text_area], ["Job description"])
        order = [e.type for e in flat(at.main) if e.type in ("text_input", "text_area")]
        self.assertEqual(order, ["text_input", "text_area"])             # the role first, then the description
        for col in at.columns:                                           # neither field sits in a column
            self.assertFalse(col.text_input or col.text_area, "the fields must not be side by side")

    def test_the_check_again_card_stacks_them_too(self):
        src = open(os.path.join(HERE, "dashboard.py"), encoding="utf-8").read()
        card = src[src.index("def again_card"):src.index("def current_result")]
        self.assertNotIn("st.columns", card)
        self.assertLess(card.index("text_input"), card.index("text_area"))


class TestClientReportWithAJob(unittest.TestCase):
    def test_the_comparison_never_shows_a_problem_of_the_1000jobs_resume(self):
        cache = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cache, True)
        T.seed(cache)
        text = T.job_text()
        old = D.run_check(T.cv_bytes(T.NEDA, "CVS"), "old.pdf", True, text, cache, cache, job_title="Delivery Lead")
        new = D.run_check(T.cv_bytes(), "new.pdf", True, text, cache, cache, job_title="Delivery Lead")
        doc = D.comparison_document(old, new)
        self.assertEqual(re.findall(r"<h2>(.*?)</h2>", doc), ["Compared", "Improved", "Issues in the original resume"])
        self.assertIn("<dt>Target role</dt><dd>Delivery Lead</dd>", doc)
        only_new = [c["name"] for c in D.issue_cards(new) if c["name"] not in {x["name"] for x in D.issue_cards(old)}]
        for name in only_new:
            self.assertNotIn(D.esc(name), doc)
        for words in ("can reach", "Still not fixed", "New in this version", "points lost"):
            self.assertNotIn(words, doc)


if __name__ == "__main__":
    unittest.main()
