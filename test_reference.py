"""
The reference set (reference_scores.json): real resumes and the score range each must stay in. They lock how the Lab
scores ANY resume. If a score leaves its range, fix the general rule (cv_score.py, "THE SCORING RULES"), never one
file. Scores are measured without the AI reviewer, so every run gives the same numbers.

Also checked here, on every reference resume: the layout limits (rule 3), the fixed severities (rule 4), "can reach"
(rule 5), clean quotes (rule 6), and that the points in each part's "Why this score" add up.

  py -3.12 -m unittest test_reference -v
"""

import glob
import json
import os

os.environ["ATSLAB_AI_REVIEW"] = "0"
os.environ.pop("OPENROUTER_API_KEY", None)
import re
import unittest

import cv_score as C
import dashboard as D

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "reference_scores.json"), encoding="utf-8") as f:
    REF = json.load(f)
_cache = {}


def check(rel):
    path = os.path.join(HERE, rel)
    if path not in _cache:
        with open(path, "rb") as f:
            _cache[path] = D.run_check(f.read(), os.path.basename(path), False, "")
    return _cache[path]


def set_files(s):
    return sorted(os.path.relpath(p, HERE).replace("\\", "/") for p in glob.glob(os.path.join(HERE, s["folder"], "*.pdf")))


ALL = list(dict.fromkeys([x["file"] for x in REF["resumes"]] + [p for s in REF["sets"] for p in set_files(s)]))


class TestReferenceFiles(unittest.TestCase):
    def test_every_reference_file_is_here(self):
        missing = [x["file"] for x in REF["resumes"] if not os.path.exists(os.path.join(HERE, x["file"]))]
        self.assertEqual(missing, [], "reference resumes missing from the Lab folders")
        for s in REF["sets"]:
            self.assertTrue(set_files(s), s["folder"])


class TestReferenceScores(unittest.TestCase):
    def test_each_reference_resume_stays_in_its_range(self):
        for x in REF["resumes"]:
            r = check(x["file"])
            lo, hi = x["range"]
            with self.subTest(resume=x["name"]):
                self.assertTrue(lo <= r["score"] <= hi, f'{x["name"]}: {r["score"]} not in {lo}-{hi} ({r["parts"]})')
                for part, top in x.get("max_parts", {}).items():
                    self.assertLessEqual(r["parts"][part], top, part)
                if x.get("content_above"):
                    other = next(y for y in REF["resumes"] if y["name"] == x["content_above"])
                    self.assertGreater(r["parts"]["content"], check(other["file"])["parts"]["content"])

    def test_the_strong_and_weak_sets(self):
        for s in REF["sets"]:
            for p in set_files(s):
                r = check(p)
                with self.subTest(set=s["name"], resume=os.path.basename(p)):
                    if "min" in s:
                        self.assertGreaterEqual(r["score"], s["min"], r["parts"])
                    if "max" in s:
                        self.assertLessEqual(r["score"], s["max"], r["parts"])


class TestPrinciples(unittest.TestCase):
    def each(self):
        for rel in ALL:
            yield rel, check(rel)

    def test_rule_1_the_whole_file_is_scored(self):
        r = check("testcvs/Rowan_Elatrache_CV.pdf")
        self.assertEqual(r["layout"]["pages"], 8)                         # every page, the designed ones too
        self.assertTrue(r["two_versions"])                               # the note is still there
        self.assertTrue(r["notes"][0].startswith("This file has a designed version and a text version. For online "
                                                 "applications, upload only the text version."))

    def test_rule_3_layout_limits(self):
        for rel, r in self.each():
            lim, p = r["layout_limits"], r["parts"]
            with self.subTest(resume=rel):
                for name in ("landscape", "columns"):
                    if lim[name]:
                        caps = C.LAYOUT_LIMITS[name]
                        self.assertLessEqual(p["readability"], caps["readability"])
                        self.assertLessEqual(p["structure"], caps["structure"])
                        self.assertLessEqual(r["score"], caps["total"])
                if lim["landscape"] and lim["columns"]:
                    self.assertLessEqual(r["score"], C.LAYOUT_LIMITS["both_total"])
                if lim["landscape"] or lim["columns"]:
                    self.assertIn("T15", [i["id"] for i in r["issues"]])  # the page format is a structure problem

    def test_rule_4_fixed_severity(self):
        important = {"C15", "C1", "T7", "B4", "R2", "B11", "R6", "R7"}
        for rel, r in self.each():
            for i in r["issues"]:
                with self.subTest(resume=rel, issue=i["id"]):
                    if i.get("ai"):
                        self.assertIn(i["severity"], ("Major", "Minor"))
                    elif i["id"] in C.LAYOUT_IDS:
                        self.assertEqual(i["severity"], "Critical")
                    elif i["id"] == "TPL":
                        self.assertEqual(i["severity"], "Critical" if r["layout_limits"]["active"] else "Minor")
                    elif i["id"] in important:
                        self.assertEqual(i["severity"], "Major")
                    elif i["id"] in ("T4", "T3"):
                        self.assertIn(i["severity"], ("Major", "Minor"))
                    elif i["id"] == "D11":                    # v1.2: 2 or more pages over the limit = Important
                        over = int(i["detail"].split()[0]) - int(i["detail"].rsplit("at most ", 1)[1].rstrip(")"))
                        self.assertEqual(i["severity"], "Major" if over >= C.PAGES_OVER_MAJOR else "Minor")
                    else:
                        self.assertEqual(i["severity"], "Minor", i["name"])
            self.assertLessEqual(len([i for i in r["issues"] if i.get("ai")]), 3)

    def test_rule_5_can_reach(self):
        for rel, r in self.each():
            cards = D.issue_cards(r)
            s = D.report_summary(r, cards)
            with self.subTest(resume=rel):
                self.assertLessEqual(s["after"], D.MAX_PROMISE)
                text = D.headline_sentence(s, "This resume")
                if r["layout_limits"]["active"] and s["n_layout"]:
                    self.assertIn("after moving to a single-column, portrait resume", text)
                else:
                    self.assertNotIn("single-column", text)

    def test_rule_6_clean_quotes(self):
        spaced = re.compile(r"(?:(?:^|(?<=[^A-Za-z]))[A-Za-z] ){3,}[A-Za-z](?![A-Za-z])")
        for rel, r in self.each():
            name = D.candidate_name(r)
            for c in D.issue_cards(r):
                for q in D.evidence(c, r) + D.before_after(c, r)[1]:
                    with self.subTest(resume=rel, card=c["name"]):
                        self.assertFalse(spaced.search(q), q)
                        if name:
                            self.assertNotEqual(re.sub(r"\W+", " ", q).strip().lower(), name.lower(), q)

    def test_why_this_score_adds_up(self):
        for rel, r in self.each():
            for part, e in r["part_explain"].items():
                with self.subTest(resume=rel, part=part):
                    total = sum(x["points"] for x in e["items"]) + e["other"]
                    self.assertAlmostEqual(total, e["loss"], delta=0.15)
                    self.assertAlmostEqual(e["loss"], 100 - r["parts"][part], delta=0.15)
                    if e["items"]:
                        self.assertLessEqual(abs(e["other"]), 0.5)     # every point lost is tied to an issue


# ---------------------------------------------------------------------------
# The dashboard path: every reference resume scored the way the dashboard does, WITH the AI reviewer (its saved
# answers in cv_reviews\, so no API call is made here), must stay in the same ranges. 2026-10-26.
# ---------------------------------------------------------------------------
import ATSLab_v3 as L

_dash = {}


def dashboard_check(rel):
    """The dashboard's own check (run_check) with the AI reviewer, from the saved reviews only."""
    path = os.path.join(HERE, rel)
    if path not in _dash:
        saved_key, real, ai_on = os.environ.get("OPENROUTER_API_KEY"), L.call_ai, D.AI_REVIEW
        os.environ["OPENROUTER_API_KEY"] = "saved-reviews-only"
        L.call_ai = lambda *a, **k: None                       # a review that is not saved is not made here
        D.AI_REVIEW = True                                     # the dashboard reviews every resume
        try:
            with open(path, "rb") as f:
                _dash[path] = D.run_check(f.read(), os.path.basename(path), False, "")
        finally:
            L.call_ai, D.AI_REVIEW = real, ai_on
            if saved_key is None:
                os.environ.pop("OPENROUTER_API_KEY", None)
            else:
                os.environ["OPENROUTER_API_KEY"] = saved_key
    return _dash[path]


class TestDashboardPath(unittest.TestCase):
    def test_every_reference_resume_has_its_saved_ai_review(self):
        missing = [rel for rel in ALL if dashboard_check(rel)["ai_review"] is None]
        self.assertEqual(missing, [], "no saved AI review: check these files once in the dashboard (with the API key)")

    def test_each_reference_resume_stays_in_its_range_with_the_ai_reviewer(self):
        for x in REF["resumes"]:
            r = dashboard_check(x["file"])
            lo, hi = x["range"]
            with self.subTest(resume=x["name"]):
                self.assertTrue(lo <= r["score"] <= hi, f'{x["name"]}: {r["score"]} not in {lo}-{hi} ({r["parts"]})')
                for part, top in x.get("max_parts", {}).items():
                    self.assertLessEqual(r["parts"][part], top, part)
                if x.get("content_above"):
                    other = next(y for y in REF["resumes"] if y["name"] == x["content_above"])
                    self.assertGreater(r["parts"]["content"], dashboard_check(other["file"])["parts"]["content"])

    def test_the_sets_with_the_ai_reviewer(self):
        for s in REF["sets"]:
            for p in set_files(s):
                r = dashboard_check(p)
                with self.subTest(set=s["name"], resume=os.path.basename(p)):
                    if "min" in s:
                        self.assertGreaterEqual(r["score"], s["min"], r["parts"])
                    if "max" in s:
                        self.assertLessEqual(r["score"], s["max"], r["parts"])

    def test_ai_findings_stay_inside_the_layout_limit(self):
        for rel in ALL:
            r, plain = dashboard_check(rel), check(rel)
            cap = r["layout_limits"]["caps"]["total"]
            with self.subTest(resume=rel):
                self.assertLessEqual(len([i for i in r["issues"] if i.get("ai")]), 3)
                self.assertTrue(all(i["severity"] != "Critical" for i in r["issues"] if i.get("ai")))
                if cap is not None and plain["score"] >= cap:      # the rules alone reach the limit
                    self.assertEqual(r["score"], plain["score"])
                self.assertEqual(r["parts"]["readability"], plain["parts"]["readability"])   # same file, same reading
                self.assertEqual(r["parts"]["structure"], plain["parts"]["structure"])


class TestSameFileSameScore(unittest.TestCase):
    def test_a_running_dashboard_reloads_every_lab_module(self):
        for m in D.LAB_MODULES:
            m._lab_mtime = os.path.getmtime(m.__file__)
        self.assertFalse(D.fresh_modules())                       # nothing changed: nothing reloaded
        L._lab_mtime = 0                                          # as if ATSLab_v3.py changed on disk
        self.assertTrue(D.fresh_modules())
        self.assertEqual({m.__name__ for m in D.LAB_MODULES}, {"cv_cache", "ATSLab_v3", "cv_layout", "cv_review", "cv_score"})
        for m in D.LAB_MODULES:
            self.assertEqual(m._lab_mtime, os.path.getmtime(m.__file__))

    def test_two_versions_read_the_text_version_for_content_and_structure(self):
        r = check("testcvs/Rowan_Elatrache_CV.pdf")
        self.assertEqual(r["layout"]["pages"], 8)                          # the layout reads every page
        self.assertNotIn("PROFI LE", r["_vdoc"]["modern"])                 # the cards quote the text version
        self.assertIn("Designer I Brand Lead January 2025 - Present", r["_vdoc"]["modern"])
        quotes = " ".join(q for c in D.issue_cards(r) for q in D.evidence(c, r) + D.before_after(c, r)[1])
        self.assertNotIn("cut off", quotes)
        self.assertNotIn("Graphic Design I Art Direction", quotes)         # a sidebar line is never the headline
        self.assertGreater(r["experience_years"], 9)


if __name__ == "__main__":
    unittest.main()
