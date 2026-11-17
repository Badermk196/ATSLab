"""
Tests for "set an issue aside" on the Admin report (dashboard.set_aside_controls / view_with).

An issue the team sets aside must stop counting, the score must change by EXACTLY what that issue costs
(a 0.1 change stays 0.1: it is never rounded up or away), the parts must move with the score, and the
score must never go down. This feature changes no rule, weight, threshold, cap or gate.

  py -3.12 -m unittest test_set_aside -v
"""

import json
import os
import re
import shutil
import tempfile
import unittest

from streamlit.testing.v1 import AppTest

import cv_score as C
import dashboard as D

HERE = os.path.dirname(os.path.abspath(__file__))
ROLE = "Logistics Coordinator"
SKILLS = {"required_skills": ["Inventory Management", "Freight Forwarding", "Customs Clearance",
                              "Warehouse Operations", "SAP", "Shipment Tracking"],
          "preferred_skills": ["Microsoft Excel", "Incoterms", "Route Planning"]}

# A resume with the problems Bader saw in the report: no city, no LinkedIn, a past job written in the
# present tense, and a Skills section that holds a job title instead of skills.
CV = """Jane Doe
Logistics Coordinator | Freight Forwarding | Customs Clearance
jane.doe@mail.com | +971 50 123 4567
SUMMARY
Logistics Coordinator with seven years of experience in freight forwarding, customs clearance and
warehouse operations across the UAE and GCC, known for accurate shipment tracking, clear vendor
communication and steady improvement of inventory management processes in busy distribution centres,
using SAP, Microsoft Excel and Incoterms every day to keep goods moving on time.
EXPERIENCE
Logistics Coordinator | Jan 2021 - Present
Gulf Freight LLC | Dubai, UAE
- Coordinate 40+ weekly freight forwarding shipments across five GCC markets with zero customs penalties.
- Reduce warehouse operations costs by 18% through better inventory management and route planning.
- Manage customs clearance for 300 import files a year using SAP and Incoterms rules.
Logistics Assistant | Mar 2018 - Dec 2020
Desert Cargo FZE | Sharjah, UAE
- Build a Microsoft Excel shipment tracking dashboard used daily by 12 planners.
- Negotiate carrier rates that saved AED 250,000 in the first year.
- Train 6 new coordinators on inventory management and customs clearance steps.
EDUCATION
Bachelor of Science in Supply Chain Management, University of Dubai, 2017
SKILLS
Project Manager
"""


def fake_doc(text):
    rows = [{"page": 0, "text": l, "cells": [l]} for l in text.splitlines() if l.strip()]
    return {"strict": text, "modern": text, "rows": rows}


def seed(cache):
    """A saved role skill list: no AI call in these tests."""
    os.makedirs(cache, exist_ok=True)
    with open(C.role_skills_path(ROLE, cache), "w", encoding="utf-8") as f:
        json.dump({"role": ROLE, "prompt_version": C.ROLE_PROMPT_VERSION, "ai_runs": [SKILLS] * 3}, f)


class Base(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()
        seed(self.cache)
        self.r = C.score_cv("jane.pdf", None, ROLE, doc=fake_doc(CV), role_cache=self.cache)

    def tearDown(self):
        shutil.rmtree(self.cache, ignore_errors=True)

    def some_issue(self, n=1):
        """The n issues that carry points on their own (so there is something worth setting aside)."""
        worth = [i for i in self.r["issues"] if i["points"] > 0 or i.get("part_points")]
        self.assertGreaterEqual(len(worth), n, "the test resume must produce issues to set aside")
        return worth[:n]


class TestPartsWith(Base):
    def test_nothing_fixed_is_the_result_itself(self):
        self.assertEqual(self.r["_parts_with"]([]), (self.r["parts"], self.r["score"]))

    def test_every_issue_carries_its_part_cost(self):
        for i in self.r["issues"]:
            self.assertIn(i["id"], self.r["_part_costs"])

    def test_setting_one_issue_aside_never_lowers_the_score(self):
        for i in self.r["issues"]:
            self.assertGreaterEqual(self.r["_parts_with"]([i["id"]])[1], self.r["score"])

    def test_setting_everything_aside_is_the_best_the_scorer_can_do(self):
        """Every card set aside must give exactly what the scorer itself promises for fixing them all (the same
        number as the report's 'can reach'). A check no card carries (here T8, folded into the skills card) can
        still hold a part down: that is the scorer's own rule and this feature must not paper over it."""
        ids = [i["id"] for i in self.r["issues"]]
        self.assertEqual(self.r["_parts_with"](ids)[1], self.r["_score_with"](ids))
        self.assertGreaterEqual(self.r["_parts_with"](ids)[1], self.r["score"])

    def test_the_parts_are_the_same_shape(self):
        parts, score = self.r["_parts_with"]([self.some_issue()[0]["id"]])
        self.assertEqual(set(parts), set(self.r["parts"]))
        for v in parts.values():
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 100.0)
        self.assertGreaterEqual(score, self.r["score"])


class TestViewWith(Base):
    def test_nothing_set_aside_leaves_the_result_alone(self):
        self.assertIs(D.view_with(self.r, set()), self.r)

    def test_the_issue_disappears_and_the_score_moves(self):
        issue = self.some_issue()[0]
        view = D.view_with(self.r, {issue["id"]})
        self.assertNotIn(issue["id"], [i["id"] for i in view["issues"]])
        self.assertEqual(view["score"], self.r["_parts_with"]([issue["id"]])[1])
        self.assertGreaterEqual(view["score"], self.r["score"])

    def test_a_small_change_is_not_rounded_up(self):
        """The scorer's own number keeps one decimal (71.1 stays 71.1, never 72), so setting an issue aside can
        never round a small change away. On the page the SCORE is printed as a whole number (fmt_score), while
        the points are printed with their decimal (fmt)."""
        for i in self.r["issues"]:
            view = D.view_with(self.r, {i["id"]})
            exact = self.r["_parts_with"]([i["id"]])[1]
            self.assertEqual(view["score"], exact)
            self.assertEqual(round(view["score"], 1), view["score"])
        self.assertEqual(D.fmt(71.1), "71.1")           # points keep their decimal
        self.assertEqual(D.fmt(71.0), "71")
        self.assertEqual(D.fmt(0.4), "0.4")
        self.assertEqual(D.fmt_score(79.9), "79")        # the score never shows a decimal
        self.assertEqual(D.fmt_score(79.0), "79")
        self.assertEqual(D.fmt_score(100), "100")

    def test_the_parts_move_with_the_score(self):
        issue = self.some_issue()[0]
        view = D.view_with(self.r, {issue["id"]})
        parts, score = self.r["_parts_with"]([issue["id"]])
        self.assertEqual(view["parts"], parts)
        self.assertEqual(view["score"], score)

    def test_the_label_follows_the_new_score(self):
        view = D.view_with(self.r, {i["id"] for i in self.r["issues"]})
        self.assertEqual(view["score"], self.r["_parts_with"]([i["id"] for i in self.r["issues"]])[1])
        self.assertEqual(view["issues"], [])
        self.assertEqual(view["label"], C.label_for(view["score"], view["parts"], view["issues"]))
        self.assertGreaterEqual(view["score"], self.r["score"])

    def test_can_reach_never_falls_below_the_score_shown(self):
        view = D.view_with(self.r, {i["id"] for i in self.r["issues"]})
        self.assertGreaterEqual(view["_score_with"]([]), view["score"])

    def test_the_explanation_still_adds_up(self):
        view = D.view_with(self.r, {self.some_issue()[0]["id"]})
        for part, e in view["part_explain"].items():
            self.assertAlmostEqual(e["loss"], round(100 - view["parts"][part], 1), delta=0.05)
            self.assertLessEqual(round(sum(x["points"] for x in e["items"]), 1), e["loss"] + 0.05)
            self.assertGreaterEqual(e["other"], -0.05)

    def test_the_other_cards_are_untouched(self):
        """Only the card the issue belongs to can change: every other card keeps its name and its +pts."""
        before = {c["key"]: c for c in D.issue_cards(self.r)}
        issue = self.some_issue()[0]
        owner = next(c for c in D.issue_cards(self.r) if issue["id"] in [i["id"] for i in c["issues"]])
        after = {c["key"]: c for c in D.issue_cards(D.view_with(self.r, {issue["id"]}))}
        self.assertEqual(set(after) - set(before), set())                  # no new card appears
        self.assertLessEqual(set(before) - set(after), {owner["key"]})     # only that card can go
        for k, c in after.items():
            if k != owner["key"]:
                self.assertEqual((c["name"], c["points"]), (before[k]["name"], before[k]["points"]))


def report_page():
    """A tiny app that draws the Admin report with the set-aside control on (AppTest cannot press a real button)."""
    import tempfile

    import cv_score as C
    import dashboard as D
    import test_set_aside as T

    cache = tempfile.mkdtemp()
    T.seed(cache)
    r = C.score_cv("jane.pdf", None, T.ROLE, doc=T.fake_doc(T.CV), role_cache=cache)
    D.render(r, False, None, set_aside=True)


def plain_report_page():
    """The same report without the set-aside control: every other report must look exactly as it did before."""
    import tempfile

    import cv_score as C
    import dashboard as D
    import test_set_aside as T

    cache = tempfile.mkdtemp()
    T.seed(cache)
    r = C.score_cv("jane.pdf", None, T.ROLE, doc=T.fake_doc(T.CV), role_cache=cache)
    D.render(r, False, None)


class TestTheControlOnThePage(unittest.TestCase):
    def test_pressing_x_changes_the_report(self):
        at = AppTest.from_function(report_page, default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        x = [b for b in at.button if b.label.startswith("✕")]
        self.assertTrue(x, "no set-aside button on the Admin report")
        before = "\n".join(str(m.value) for m in at.markdown)
        self.assertTrue(any("Set an issue aside" in e.label for e in at.expander))
        x[0].click().run()
        self.assertFalse(at.exception, at.exception)
        # The X now asks WHY first (the Lab's teaching signal): nothing is set aside until a reason is saved.
        self.assertTrue(at.radio, "the X must ask why before the issue stops counting")
        at.radio[0].set_value("false_alarm")
        at.run()
        next(b for b in at.button if b.label == D.TRAIN_TEXT["save"]).click().run()
        self.assertFalse(at.exception, at.exception)
        after = "\n".join(str(m.value) for m in at.markdown)
        self.assertNotEqual(before, after, "setting an issue aside changed nothing on the page")
        self.assertEqual(len([b for b in at.button if b.label.startswith("✕")]), len(x) - 1)
        self.assertTrue([b for b in at.button if b.label.startswith("↺")], "no way to put the issue back")

    def test_a_report_without_the_control_has_no_x_buttons(self):
        """Bader's rule 3: the X is for the team only. Every other report looks exactly as it did before."""
        at = AppTest.from_function(plain_report_page, default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual([b.label for b in at.button if b.label.startswith("✕")], [])
        self.assertFalse([e.label for e in at.expander if "Set an issue aside" in e.label])


# ---------------------------------------------------------------------------
# The X as the Lab's teaching signal: WHY an issue was set aside (manual training)
# ---------------------------------------------------------------------------
class TestTrainingTexts(unittest.TestCase):
    def test_the_texts_and_reasons_exist(self):
        """Guard (a real bug once): the X asks for a reason, so its texts and reasons must be defined, not empty."""
        for key in ("ask", "note", "save", "cancel", "saved", "log_title", "log_sub", "export", "failed"):
            self.assertTrue(D.TRAIN_TEXT.get(key), f"TRAIN_TEXT[{key!r}] is missing")
        self.assertTrue(D.TRAIN_REASONS)
        for code, label in D.TRAIN_REASONS.items():
            self.assertTrue(code and isinstance(label, str) and label.strip(), f"bad reason {code!r}")

    def test_the_log_counts_each_issue_and_names_the_reason(self):
        rows = [{"at": "2026-11-16 10:00", "issue_id": "T7", "issue_name": "No email", "reason": "false_alarm"},
                {"at": "2026-11-16 11:30", "issue_id": "T7", "issue_name": "No email", "reason": "false_alarm"},
                {"at": "2026-11-16 12:00", "issue_id": "T7", "issue_name": "No email", "reason": "lab_rule_wrong"}]
        table = D.training_table(rows)
        self.assertEqual(len(table), 1)
        self.assertEqual(table[0]["Times set aside"], 3)
        self.assertIn(D.TRAIN_REASONS["false_alarm"] + " x2", table[0]["Why"])
        self.assertIn(D.TRAIN_REASONS["lab_rule_wrong"] + " x1", table[0]["Why"])
        self.assertEqual(table[0]["Last time"], "2026-11-16 12:00")

    def test_the_csv_keeps_the_plain_reason(self):
        text = D.csv_text(D.training_table([{"at": "2026-11-16 10:00", "issue_id": "T7",
                                             "issue_name": "No email", "reason": "lab_rule_wrong"}]))
        self.assertIn(D.TRAIN_REASONS["lab_rule_wrong"], text)
        self.assertIn("No email", text)


SAVED = []


def training_report_page():
    """The Admin report with a fake trainer/training reader: the X must ask WHY, save the reason, and show the log."""
    import tempfile

    import cv_score as C
    import dashboard as D
    import test_set_aside as T

    cache = tempfile.mkdtemp()
    T.seed(cache)
    r = C.score_cv("jane.pdf", None, T.ROLE, doc=T.fake_doc(T.CV), role_cache=cache)

    def trainer(res, card, reason, note, evidence):
        T.SAVED.append({"card": card["name"], "reason": reason, "note": note, "evidence": evidence})

    def training():
        return [{"at": "2026-11-16 10:00", "issue_id": "T7", "issue_name": "No email",
                 "reason": "false_alarm", "cv": "jane.pdf"}]

    D.render(r, False, None, set_aside=True, trainer=trainer, training=training)


class TestTrainingOnThePage(unittest.TestCase):
    def test_x_asks_why_then_saves_the_reason(self):
        import test_set_aside as T
        T.SAVED.clear()
        at = AppTest.from_function(training_report_page, default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        x = [b for b in at.button if b.label.startswith("✕")]
        self.assertTrue(x, "no set-aside button on the Admin report")
        x[0].click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertTrue(at.radio, "the X must ask WHY before the issue is set aside")
        self.assertEqual(at.radio[0].label, D.TRAIN_TEXT["ask"])
        self.assertIsNone(at.radio[0].value, "no reason is chosen yet")
        # the log is shown, with its reason
        self.assertTrue(any(D.TRAIN_TEXT["log_title"] in str(m.value) for m in at.markdown))
        self.assertEqual(T.SAVED, [], "nothing is saved before a reason is chosen")
        at.radio[0].set_value("false_alarm")
        at.run()
        self.assertFalse(at.exception, at.exception)
        save = next(b for b in at.button if b.label == D.TRAIN_TEXT["save"])
        save.click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(len(T.SAVED), 1)
        self.assertEqual(T.SAVED[0]["reason"], "false_alarm")
        self.assertTrue(T.SAVED[0]["card"])
        self.assertTrue([b for b in at.button if b.label.startswith("↺")], "the issue was not set aside")

    def test_a_report_without_the_control_has_no_training_buttons(self):
        at = AppTest.from_function(plain_report_page, default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        self.assertFalse([b for b in at.button if b.label == D.TRAIN_TEXT["save"]])
        self.assertFalse(any(D.TRAIN_TEXT["log_title"] in str(m.value) for m in at.markdown))


if __name__ == "__main__":
    unittest.main()
