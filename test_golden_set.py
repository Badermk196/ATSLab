"""The golden set as an automatic test.

Every future change is checked against 80 real resumes whose truth was read from the rendered pages and confirmed by
the team (golden_truth.json, 9 November 2026). Two levels:

  * layout truth - every resume in the set is measured and compared with the confirmed truth (fast, no scoring).
  * scoring gate - for a few resumes the whole score is run, to check that a layout card is shown only when the page
    confirms it, and that the checks below 90% accuracy never change the score.

Set ATSLAB_GOLDEN_FULL=1 to run the scoring gate over the whole set (slow).
"""

import json
import os
import unittest

import cv_score as C
import cv_vision as V

HERE = os.path.dirname(os.path.abspath(__file__))
TRUTH_FILE = os.path.join(HERE, "golden_truth.json")


def load_truth():
    if not os.path.isfile(TRUTH_FILE):
        return {}
    return json.load(open(TRUTH_FILE, encoding="utf-8"))["resumes"]


class TestGoldenLayoutTruth(unittest.TestCase):
    """What the page really shows must match the confirmed truth for every resume in the set."""

    def test_columns_name_and_headings(self):
        truth = load_truth()
        if not truth:
            self.skipTest("no golden_truth.json")
        pages = 0
        for rid, t in truth.items():
            if not os.path.isfile(t["path"]):
                continue
            got = V.page_layout(t["path"])
            if not got["ok"]:
                continue
            pages += 1
            self.assertEqual(bool(got["columns"]), not t["one_column"],
                             f"{t['name']}: columns should be {not t['one_column']} ({got.get('columns_detail')})")
            self.assertEqual(bool(got["name_spaced"]), bool(t["name_letters_spaced"]),
                             f"{t['name']}: letter-spaced name")
            self.assertEqual(bool(got["headings_spaced"]), bool(t["headings_letters_spaced"]),
                             f"{t['name']}: letter-spaced headings")
        self.assertGreater(pages, 40, "the golden set must be measured, not skipped")


class TestGoldenScoringGate(unittest.TestCase):
    """A layout card is shown only when the page confirms it; the checks below 90% never change the score."""

    @classmethod
    def setUpClass(cls):
        cls.truth = load_truth()
        if not cls.truth:
            raise unittest.SkipTest("no golden_truth.json")
        cls.two_col = [t for t in cls.truth.values() if not t["one_column"] and os.path.isfile(t["path"])]
        cls.one_col = [t for t in cls.truth.values() if t["one_column"] and os.path.isfile(t["path"])]
        if os.environ.get("ATSLAB_GOLDEN_FULL") == "1":
            cls.sample_two = cls.two_col
            cls.sample_one = cls.one_col
        else:
            cls.sample_two = cls.two_col
            cls.sample_one = cls.one_col[:2]

    @staticmethod
    def scored(result):
        return {i["id"] for i in result["issues"]}

    def test_column_card_only_when_the_page_shows_columns(self):
        for t in self.sample_two:
            with self.subTest(t["name"]):
                res = C.score_cv(t["path"])
                ids = self.scored(res)
                self.assertTrue(ids & {"D3", "D4", "T15", "TPL"} or "TPL" in ids,
                                f"{t['name']}: a two-column page must keep its layout card, got {sorted(ids)}")

    def test_no_column_card_on_a_one_column_page(self):
        for t in self.sample_one:
            with self.subTest(t["name"]):
                res = C.score_cv(t["path"])
                ids = self.scored(res)
                self.assertFalse(ids & {"D3", "D4", "T15", "TPL"},
                                 f"{t['name']}: one column, so no layout card, got {sorted(ids)}")

    def test_unreliable_checks_never_change_the_score(self):
        for t in (self.sample_one + self.sample_two)[:3]:
            with self.subTest(t["name"]):
                res = C.score_cv(t["path"])
                ids = self.scored(res)
                # 2026-11-09: the list itself is the contract - T6 (city) and T4C (date format) came back into the
                # score after the truth re-check, so the test reads the live list instead of fixed ids
                self.assertFalse(ids & set(C.UNRELIABLE_CHECKS),
                                 f"{t['name']}: checks under 90% must not be scored, got {sorted(ids)}")
                for c in C.UNRELIABLE_CHECKS:
                    check = (res.get("structure_checks") or {}).get(c)
                    if check and check.get("moved_to_verify"):
                        self.assertEqual(check["score"], 1.0,
                                         f"{t['name']}: {c} moved to verify must not lower the score")


if __name__ == "__main__":
    unittest.main(verbosity=2)
