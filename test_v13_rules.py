"""
v1.3 (2026-10-30), for every resume and every job. Tested on generated files and made-up postings (never one real
person or file).

1. Far too many pages: 3 times the page limit or more AND at least 4 pages -> the total is at most 75. A 2- or 3-page
   resume is never capped. Cutting the pages lifts the cap.
2. Glued words from a posting pasted without line breaks ('Software DeveloperLocation') are never a skill: the skill is
   split and only the real skills inside are kept.
3. A job with fewer than 10 skills: the missing places count as the meaning match, so one generic skill cannot count
   for too much.

  py -3.12 -m unittest test_v13_rules -v
"""

import os
import unittest

os.environ["ATSLAB_AI_REVIEW"] = "0"
os.environ.pop("OPENROUTER_API_KEY", None)

import ATSLab_v3 as L
import cv_score as C
from test_v12_rules import Files, resume_lines

TEN_YEARS = [("Logistics Manager", "Gulf Freight LLC", "Jan 2020 - Present"),
             ("Logistics Coordinator", "Desert Cargo FZE", "Jan 2014 - Dec 2019")]       # 10+ years: at most 3 pages
TWO_YEARS = [("Logistics Coordinator", "Gulf Freight LLC", "Mar 2024 - Present")]       # at most 1 page
CAP_TEXT = f"{C.PAGES_CAP_TIMES} times the page limit or more -> max {C.CAP_PAGES}"


class TestPageCap(Files):
    def issue(self, r, iid):
        return next((i for i in r["issues"] if i["id"] == iid), None)

    def test_the_cap_on_the_total(self):
        cc = {"C1": {"bullets": 5, "quant_share": 1.0}}
        parts = {"readability": 100.0, "content": 100.0, "structure": 100.0}
        limits = {"caps": {"total": None}, "pages_cap": C.CAP_PAGES}
        score, gates = C.total_from(parts, cc, limits=limits)
        self.assertEqual(score, C.CAP_PAGES)
        self.assertEqual(gates, [CAP_TEXT])
        self.assertAlmostEqual(C.total_from(parts, cc, limits=limits, pages_ok=True)[0], 100.0)   # cut: no cap
        self.assertAlmostEqual(C.total_from(parts, cc, limits=dict(limits, pages_cap=None))[0], 100.0)

    def test_fifteen_pages_scores_75_at_most_and_cutting_them_lifts_it(self):
        r = self.check(self.pdf("p15.pdf", resume_lines(TEN_YEARS, pages=15)))        # 15 pages, limit 3
        self.assertEqual(r["layout_limits"]["pages_cap"], C.CAP_PAGES)
        self.assertLessEqual(r["score"], C.CAP_PAGES)
        self.assertIn(CAP_TEXT, r["gates"])
        d11 = self.issue(r, "D11")
        self.assertEqual(d11["severity"], "Major")
        self.assertGreater(r["score"] + d11["points"], C.CAP_PAGES)        # the card shows what the cap costs
        self.assertGreaterEqual(r["_score_with"](["D11"]), r["score"])    # fixing it never lowers the score

    def test_four_pages_for_under_three_years_is_capped(self):
        r = self.check(self.pdf("p4_of_1.pdf", resume_lines(TWO_YEARS, pages=4)))      # 4 pages, limit 1
        self.assertEqual(r["layout_limits"]["pages_cap"], C.CAP_PAGES)
        self.assertLessEqual(r["score"], C.CAP_PAGES)

    def test_two_or_three_pages_are_never_capped(self):
        for pages in (2, 3):                                                            # 2 and 3 times the limit
            with self.subTest(pages=pages):
                r = self.check(self.pdf(f"p{pages}_of_1.pdf", resume_lines(TWO_YEARS, pages=pages)))
                self.assertIsNotNone(self.issue(r, "D11"))
                self.assertIsNone(r["layout_limits"]["pages_cap"])
                self.assertFalse(any("page limit" in g for g in r["gates"]))

    def test_under_three_times_is_not_capped(self):
        r = self.check(self.pdf("p8_of_3.pdf", resume_lines(TEN_YEARS, pages=8)))       # 8 pages, limit 3
        self.assertIsNotNone(self.issue(r, "D11"))
        self.assertIsNone(r["layout_limits"]["pages_cap"])

    def test_within_the_limit_is_not_capped(self):
        r = self.check(self.pdf("p3_of_3.pdf", resume_lines(TEN_YEARS, pages=3)))
        self.assertIsNone(self.issue(r, "D11"))
        self.assertIsNone(r["layout_limits"]["pages_cap"])


GLUED_POSTING = """Job Title: Software DeveloperLocation: Pittsburgh, PADuration: 6+ Months
Responsibilities: build services with Spark and Kafka, write unit tests, review code with the team.
Requirements: 3+ years of experience with Java, Spring Boot, ScalaSpark and Kafka. Experience with JavaScript and
PostgreSQL. Knowledge of REST APIs and Docker. Familiarity with RESTful services and GitHub. Wiring DesignSchematic is
not needed. You will obtainProject Management experience in our team.
"""


class TestGluedSkills(unittest.TestCase):
    def test_glued_words_are_found_and_real_names_are_not(self):
        for word, parts in (("DeveloperLocation", ["Developer", "Location"]), ("PADuration", ["PA", "Duration"]),
                            ("JavaScriptNode", ["JavaScript", "Node"]), ("ScalaSpark", ["Scala", "Spark"]),
                            ("obtainProject", ["obtain", "Project"]), ("AWXTower", ["AWX", "Tower"])):
            self.assertEqual(L.glued_parts(word), parts, word)
        for word in ("JavaScript", "PowerShell", "GitHub", "LinkedIn", "DevOps", "PostgreSQL", "McKinsey", "OAuth",
                     "APIs", "KPIs", "RESTful", "iPhone", "IoT", "eCommerce", "XGBoost", "OpenId"):
            self.assertEqual(L.glued_parts(word), [word], word)
        self.assertIsNone(L.glued_skill_pieces("Power BI"))
        self.assertEqual(L.glued_skill_pieces("Software DeveloperLocation"), ["Software Developer", "Location"])

    def test_a_glued_skill_is_split_or_dropped(self):
        raw = {"title": "Software Developer", "required_skills": ["Java", "Spring Boot", "Kafka", "ScalaSpark",
                                                                  "Software DeveloperLocation", "PADuration",
                                                                  "obtainProject Management", "Docker", "PostgreSQL"],
               "preferred_skills": ["JavaScript", "GitHub", "REST APIs"], "soft_skills": []}
        kw = L.clean_keywords(raw, GLUED_POSTING)
        skills = kw["required_skills"] + kw["preferred_skills"]
        for s in skills:
            self.assertIsNone(L.glued_skill_pieces(s), s)                 # no glued word is ever a skill
        self.assertNotIn("Location", skills)
        self.assertNotIn("Duration", skills)
        self.assertIn("Spark", skills)                                      # a real tool inside 'ScalaSpark' is kept
        for s in ("Java", "Kafka", "Docker", "PostgreSQL", "JavaScript", "GitHub"):
            self.assertIn(s, skills)                                        # names written in camel case stay


class TestFewSkills(unittest.TestCase):
    def rec(self, term, found):
        return {"term": term, "type": "required", "times_in_job": 1, "weight": 3.0,
                "hits": [("exact", 1.0)] if found else []}

    def test_one_generic_hit_of_two_counts_little_when_the_meaning_is_far(self):
        prof = L.ATS_PROFILES["oracle"]
        recs = [self.rec("Accounting", True), self.rec("MPI", False)]
        old = L.keyword_checks(recs, prof)                                  # no meaning match: as before
        new = L.keyword_checks(recs, prof, m3=0.1)
        self.assertAlmostEqual(old["F1"]["score"], 0.5)
        self.assertAlmostEqual(new["F1"]["score"], (2 * 0.5 + 8 * 0.1) / 10)
        self.assertAlmostEqual(new["M1"]["score"], (2 * old["M1"]["score"] + 8 * 0.1) / 10)
        self.assertIn("only 2 job skills", new["F1"]["detail"])

    def test_ten_skills_or_more_are_not_changed(self):
        prof = L.ATS_PROFILES["oracle"]
        recs = [self.rec(f"Skill {k}", k < 4) for k in range(10)]
        self.assertEqual(L.keyword_checks(recs, prof)["F1"]["score"],
                         L.keyword_checks(recs, prof, m3=0.0)["F1"]["score"])

    def test_more_skills_found_never_lowers_the_score(self):
        prof = L.ATS_PROFILES["oracle"]
        for m3 in (0.0, 0.4, 1.0):
            a = L.keyword_checks([self.rec("A", False), self.rec("B", False), self.rec("C", True)], prof, m3)
            b = L.keyword_checks([self.rec("A", True), self.rec("B", False), self.rec("C", True)], prof, m3)
            self.assertGreaterEqual(b["F1"]["score"], a["F1"]["score"])
            self.assertGreaterEqual(b["M1"]["score"], a["M1"]["score"])


if __name__ == "__main__":
    unittest.main()
