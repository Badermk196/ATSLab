"""
The Admin page's "Second opinion" section: two extra ATS checkers beside the Lab score.

Rules checked here:
  - the cards are empty until the team presses their button (nothing runs by itself),
  - the section never changes the ATS Lab score (the module only reads it),
  - every card state works: not checked, agrees, disagrees, needs a job description, switched off in Settings,
  - the labels are the Lab's six (84 shows Strong),
  - the section is on the Admin page only: the plain report never draws it.

The page tests use a small made-up result (no scoring, no model): they only test the section.

  py -3.12 -m unittest test_second_opinion -v
"""

import copy
import os
import unittest

os.environ["ATSLAB_AI_REVIEW"] = "0"      # no AI review (and no cost) in these tests

from streamlit.testing.v1 import AppTest
from unittest import mock

import admin_page as A
import cv_score as C
import lab_second as SO
import lab_settings as S
import lab_text as T
import ATSLab_v3 as L

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKED_AT = "2026-11-10 14:00:00"
JOB_TEXT = ("Sales Manager. You will lead stakeholder management, delivery governance, release management, "
            "risk management, agile delivery and reporting with Jira.")
RESUME_TEXT = ("Sample Candidate. Dubai, United Arab Emirates. Skills: stakeholder management, release "
               "management, agile delivery, reporting.")
FAKE_PDF = b"%PDF-1.4 sample"


def fake_result():
    """A small result with the keys the section reads (score, parts, _doc, layout): no scoring, no model."""
    return {"score": 84, "label": "Strong", "cv": "sample.pdf", "mode": "job", "target": "Sales Manager",
            "parts": {"readability": 88, "content": 80, "structure": 86, "job_match": 82},
            "_doc": {"modern": RESUME_TEXT, "rows": []},
            "layout": {"pages": 1, "columns_found": False, "n_columns": 1, "landscape": False, "findings": []}}


def page_text(at):
    parts = [x.value for x in at.markdown] + [x.value for x in at.caption] + [x.label for x in at.button]
    parts += [x.value for x in at.info] + [x.value for x in at.warning]
    return "\n".join(str(p) for p in parts)


def second_page(checker=None, score=None, on=True, job=True):
    """A tiny app that draws the section (AppTest cannot click through the whole Admin page)."""
    import streamlit as st

    import admin_page as A
    import lab_second as SO
    import test_second_opinion as T

    old = A.P.setting
    A.P.setting = lambda key, *a, **k: on          # deterministic: the test decides the switches
    try:
        res = T.fake_result()
        text = T.JOB_TEXT if job else ""
        saved = {"res": res, "inputs": {"pdf": T.FAKE_PDF, "text": text, "with_job": bool(text)}}
        if checker and score is not None:
            ref = SO.reference_of(res, checker)
            answer = {"state": SO.DONE, "score": ref if score == "ref" else score,
                      "pct": 71, "n_matched": 54, "total": 76,
                      "missing": ["governance", "stakeholder", "release"],
                      "matched": [], "keywords": [], "checked_at": T.CHECKED_AT}
            st.session_state[A.second_key(saved, checker)] = SO.finish(checker, res, answer)
        A.second_opinion(saved)
    finally:
        A.P.setting = old


class TestLabelsAndNumbers(unittest.TestCase):
    def test_the_six_labels(self):
        self.assertEqual([SO.label_for(s) for s in (95, 84, 75, 60, 45, 20)],
                         ["Excellent", "Strong", "Good", "Needs work", "At risk", "Not ready"])
        self.assertEqual(SO.label_for(84), "Strong", "84 is Strong, never Excellent")

    def test_the_difference_reads_plainly(self):
        self.assertEqual(SO.difference(81, 82)["text"], "Agrees · 1 point lower")
        self.assertTrue(SO.difference(88, 84)["agree"])
        self.assertEqual(SO.difference(90, 84)["word"], "Agrees")      # 6 points apart: still agrees
        self.assertEqual(SO.difference(70, 84)["text"], "Lower · 14 points lower")
        self.assertEqual(SO.difference(96, 84)["word"], "Higher")

    def test_each_checker_compares_with_the_right_lab_number(self):
        res = {"score": 84, "parts": {"job_match": 82}}
        self.assertEqual(SO.reference_of(res, "matcher"), 82)
        self.assertEqual(SO.reference_of(res, "checker2"), 84)
        self.assertEqual(SO.reference_text(res, "matcher"), "vs Lab Job match 82")
        self.assertEqual(SO.reference_text(res, "checker2"), "vs Lab score 84")

    def test_finish_adds_the_comparison_and_keeps_the_answer(self):
        res = {"score": 84, "parts": {"job_match": 82}}
        done = SO.finish("matcher", res, {"state": SO.DONE, "score": 81})
        self.assertEqual(done["reference"], 82)
        self.assertEqual(done["difference"], "Agrees · 1 point lower")
        self.assertTrue(done["agree"])
        self.assertEqual(SO.finish("matcher", res, {"state": SO.NEEDS_JOB}), {"state": SO.NEEDS_JOB})


class TestTheCheckers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = fake_result()

    def test_the_matcher_reads_the_job_words(self):
        out = SO.run_matcher(self.res, JOB_TEXT)
        self.assertEqual(out["total"], len(out["keywords"]))
        self.assertEqual(out["n_matched"] + len(out["missing"]), out["total"])
        self.assertEqual(out["score"], out["pct"])
        self.assertTrue(out["keywords"], "the job description has real words")
        self.assertIn("stakeholder", out["matched"])

    def test_a_skill_is_found_word_by_word(self):
        """The words of a skill need not sit together: "team leadership" is found in "Team of 12 ...
        leadership", and a skill with a word missing is still missing."""
        text = "Team of 12 across the region; leadership and coaching."
        self.assertFalse(L.contains("team leadership", text))            # not as a phrase
        self.assertTrue(SO.found("team leadership", text))               # but word by word
        self.assertFalse(SO.found("team leadership", "leadership only"))  # a word is missing
        self.assertTrue(SO.found("release management", "release management"))   # a phrase still counts

    def test_the_checker2_gives_a_general_score(self):
        out = SO.run_checker2(self.res)
        self.assertTrue(0 <= out["score"] <= 100)
        self.assertTrue(out["checks"], "the checker says what it looked at")

    def test_the_states(self):
        self.assertEqual(SO.run("matcher", self.res, "", {"matcher": True})["state"], SO.NEEDS_JOB)
        self.assertEqual(SO.run("matcher", self.res, JOB_TEXT, {"matcher": False})["state"], SO.OFF)
        self.assertEqual(SO.run("checker2", self.res, "", {"checker2": False})["state"], SO.OFF)
        self.assertEqual(SO.run("nope", self.res, JOB_TEXT, {})["state"], SO.FAILED)

    def test_a_wrong_ai_key_never_breaks_the_matcher_card(self):
        """The Lab's AI call stops the whole process when the key is wrong (sys.exit). The card must not: it
        falls through to the resume's own skills, exactly as it does when there is no key at all."""
        old = C.role_skills
        C.role_skills = lambda *a, **k: (_ for _ in ()).throw(SystemExit("the AI service is busy"))
        self.addCleanup(setattr, C, "role_skills", old)
        res = dict(self.res, _doc={"modern": "Sample Candidate. Dubai.\nSKILLS\nstakeholder management, "
                                            "release management, reporting"})
        words, source, named = SO.matcher_words(res, "", "Sales Manager")
        self.assertEqual(source, "skills")
        self.assertTrue(words)
        self.assertEqual(SO.run("matcher", res, "", {"matcher": True})["state"], SO.DONE)

    def test_a_checker_that_stops_the_process_never_kills_the_page(self):
        old = SO.run_matcher
        SO.run_matcher = lambda *a, **k: (_ for _ in ()).throw(SystemExit("the AI service is busy"))
        self.addCleanup(setattr, SO, "run_matcher", old)
        self.assertEqual(SO.run("matcher", self.res, "", {"matcher": True})["state"], SO.FAILED)

    def test_a_broken_checker_never_breaks_the_lab(self):
        out = SO.run("checker2", {"layout": "not a dict"}, "", {})
        self.assertIn(out["state"], (SO.DONE, SO.FAILED))

    def test_the_section_never_changes_the_score(self):
        before = copy.deepcopy(self.res)
        SO.run("matcher", self.res, JOB_TEXT, {"matcher": True})
        SO.run("checker2", self.res, "", {"checker2": True})
        SO.finish("matcher", self.res, {"state": SO.DONE, "score": 10})
        self.assertEqual(self.res, before, "the checkers only read the Lab's numbers")

    def test_the_top_five_missing_keywords(self):
        answer = {"missing": ["a", "b", "c", "d", "e", "f", "g"]}
        self.assertEqual(SO.top_missing(answer), ["a", "b", "c", "d", "e"])

    def test_another_file_or_job_never_reuses_an_answer(self):
        one = {"inputs": {"pdf": b"pdf-one", "text": "a job description"}}
        self.assertNotEqual(A.second_key(one, "matcher"), A.second_key({"inputs": {"pdf": b"pdf-two",
                                                                                  "text": "a job description"}},
                                                                      "matcher"))
        self.assertNotEqual(A.second_key(one, "matcher"), A.second_key({"inputs": {"pdf": b"pdf-one", "text": ""}},
                                                                      "matcher"))
        self.assertEqual(A.second_key(one, "matcher"), A.second_key(one, "matcher"))


class TestTheSettings(unittest.TestCase):
    def test_the_four_switches_exist_and_are_on_by_default(self):
        for key in ("second_matcher", "second_checker2", "second_engine", "second_lever"):
            self.assertIn(key, S.SETTINGS)
            self.assertIn(key, T.SETTINGS_TEXT)
            self.assertTrue(S.SETTINGS[key][1])
            self.assertFalse(S.get(key, {key: False}), "a saved off switch wins")

    def test_the_settings_view_shows_all_four_switches(self):
        with open(os.path.join(HERE, "admin_page.py"), encoding="utf-8") as fh:
            source = fh.read()
        view = source[source.index("def settings_view(who):"):]
        for key in ("second_matcher", "second_checker2", "second_engine", "second_lever"):
            self.assertIn(f'setting_row("{key}"', view)


class TestTheCards(unittest.TestCase):
    def test_ats_checker_3_is_hidden_when_the_engine_is_not_installed(self):
        """The card is not drawn at all when the open-source engine is missing on the server."""
        with mock.patch.object(SO.E, "available", return_value=(False, "not_installed")):
            self.assertNotIn("engine", SO.visible_order())
            self.assertIn("matcher", SO.visible_order())

    def test_ats_checker_3_comes_back_when_the_engine_is_installed(self):
        """Nothing to switch on: installing the engine makes the card appear by itself."""
        with mock.patch.object(SO.E, "available", return_value=(True, "")):
            self.assertIn("engine", SO.visible_order())

    def test_the_section_starts_empty_with_a_button_for_each_checker(self):
        at = AppTest.from_function(second_page, default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        body = page_text(at)
        self.assertIn("Second opinion", body)
        self.assertIn("4 extra ATS checkers", body)
        self.assertIn("Second opinions are for comparison only", body)
        self.assertIn("change the ATS Lab score.", body)
        self.assertIn("Not checked yet", body)
        self.assertIn("Check with Resume Matcher", [b.label for b in at.button])
        self.assertIn("Check with ATS Checker 2", [b.label for b in at.button])
        self.assertIn("Check with ATS Checker 3", [b.label for b in at.button])
        self.assertIn("Check with LeverParser", [b.label for b in at.button])

    def test_pressing_the_button_runs_the_checker(self):
        at = AppTest.from_function(second_page, default_timeout=300).run()
        next(b for b in at.button if b.label == "Check with Resume Matcher").click().run()
        self.assertFalse(at.exception, at.exception)
        body = page_text(at)
        self.assertIn("Keyword match", body)
        self.assertIn("Check again", [b.label for b in at.button])
        self.assertNotIn("Check with Resume Matcher", [b.label for b in at.button])

    def test_a_card_that_agrees(self):
        at = AppTest.from_function(second_page, args=("matcher", "ref"), default_timeout=300).run()
        body = page_text(at)
        self.assertIn("Agrees", body)
        self.assertIn("vs Lab Job match 82", body)
        self.assertTrue(any(lbl in body for lbl in
                            ("Excellent", "Strong", "Good", "Needs work", "At risk", "Not ready")),
                        "the card shows the Lab's label for its number")

    def test_a_card_that_disagrees_shows_its_missing_keywords(self):
        at = AppTest.from_function(second_page, args=("matcher", 40), default_timeout=300).run()
        body = page_text(at)
        self.assertIn("Lower", body)
        self.assertIn("Top missing keywords: governance, stakeholder, release", body)

    def test_the_needs_a_job_description_state(self):
        at = AppTest.from_function(second_page, args=(None, None, True, False), default_timeout=300).run()
        next(b for b in at.button if b.label == "Check with Resume Matcher").click().run()
        self.assertFalse(at.exception, at.exception)
        body = page_text(at)
        self.assertIn("Needs a job description", body)
        self.assertIn("Check again", [b.label for b in at.button])

    def test_the_switched_off_state(self):
        at = AppTest.from_function(second_page, args=(None, None, False), default_timeout=300).run()
        body = page_text(at)
        self.assertIn("Switched off in Settings", body)
        self.assertNotIn("Check with Resume Matcher", [b.label for b in at.button])

    def test_the_plain_report_never_draws_the_section(self):
        # the hook runs only when the caller passes it: the standalone dashboard and the user page never do
        with open(os.path.join(HERE, "dashboard.py"), encoding="utf-8") as fh:
            dash = fh.read()
        body = dash[dash.index("def render(r, with_job"):dash.index("def render_client")]
        self.assertIn("if after_score:", body, "the section is drawn only through the hook")
        self.assertNotIn("SECOND_TEXT", dash, "the report itself draws no second-opinion text")
        self.assertIn("render(saved[\"res\"], saved[\"with_job\"], saved[\"prev\"], client=", dash,
                      "the standalone dashboard draws the report without the hook")

    def test_only_the_admin_page_passes_the_hook(self):
        with open(os.path.join(HERE, "admin_page.py"), encoding="utf-8") as fh:
            admin = fh.read()
        self.assertIn("after_score=lambda: second_opinion(saved)", admin)
        with open(os.path.join(HERE, "user_page.py"), encoding="utf-8") as fh:
            user = fh.read()
        self.assertNotIn("second_opinion", user, "the user page never draws the section")
        self.assertNotIn("after_score", user)


class TestWorkingWithoutAJobDescription(unittest.TestCase):
    """The second opinion must work with and without a job description, and never answer 0 by accident."""

    RESUME = ("Sample Candidate\nDubai, United Arab Emirates\n"
              "SKILLS\nStakeholder management, release management, agile delivery, reporting\n"
              "EXPERIENCE\nRelease Manager 2020 - 2024\nRan release management and reporting for 4 teams.\n")

    def res(self, text=RESUME):
        return {"score": 46, "label": "At risk", "target": "Release Manager",
                "parts": {"job_match": 40}, "_doc": {"modern": text}}

    def test_with_a_job_description_it_reads_the_job(self):
        out = SO.run_matcher(self.res(), JOB_TEXT)
        self.assertEqual(out["source"], "job")
        self.assertGreater(out["score"], 0)

    def test_without_a_job_description_it_reads_the_resume_skills(self):
        """No job, no known role: the matcher measures the resume's own skills instead of refusing."""
        out = SO.run_matcher(self.res(), "")
        self.assertIn(out["source"], ("skills", "role"))
        self.assertNotIn("error", out)

    def test_the_skills_check_does_not_match_the_list_against_itself(self):
        """The skills list must be measured against the experience, not read back from itself."""
        text = ("Sample Candidate\nSKILLS\nStakeholder management, release management\n"
                "EXPERIENCE\nCashier 2019 - 2021\nHandled payments and stock.\n")
        out = SO.run_matcher(self.res(text), "")
        self.assertEqual(out["source"], "skills")
        self.assertLess(out["score"], 100, "a skill that only sits in the list is not demonstrated")

    def test_a_result_without_text_fails_cleanly(self):
        """A saved result may not keep the resume text: the card says so instead of showing 0."""
        out = SO.run("matcher", {"score": 46, "cv": "Someone_CV.pdf"}, "", {})
        self.assertEqual(out["state"], SO.FAILED)
        self.assertEqual(out["why"], "no_text")

    def test_the_file_name_is_never_used_as_resume_text(self):
        self.assertEqual(SO.text_of({"cv": "Sana_Malik_CV.pdf"}), "")
        self.assertEqual(SO.text_of({"cv": "Sana_Malik_CV.pdf", "_doc": {"modern": "real text here"}}),
                         "real text here")

    def test_checker2_also_reads_a_saved_result(self):
        """ATS Checker 2 used _doc only, so a saved result scored low for the wrong reason."""
        out = SO.run_checker2({"score": 46, "_doc": {"modern": self.RESUME}})
        self.assertGreater(out["score"], 0)
        self.assertTrue(out["checks"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
