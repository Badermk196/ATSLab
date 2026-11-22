"""
ATS Checker 3: the open-source VeriWorkly ats-engine, as the third card of the Admin page's
"Second opinion" section.

Rules checked here:
  - the engine is registered as a third checker and compared with the Lab's main score,
  - a failure (not installed, no Node, a timeout, a broken report) never breaks the Lab,
  - the engine's JSON report is read correctly (readiness, job match, failed checks, missing words),
  - the Lab's own score never changes when the engine runs,
  - the benchmark table shows the Lab and the cards side by side,
  - the licence is MIT and the licence text travels with the code,
  - nothing is sent anywhere: the engine runs as a local command on this machine.

The real command is only called when it is installed (otherwise those tests skip).
  py -3.12 -m unittest test_third_opinion -v
"""
import os
import unittest
from unittest import mock

os.environ["ATSLAB_AI_REVIEW"] = "0"      # no AI (and no cost) in these tests

import lab_second as SO
import lab_third as E
import lab_text as T

HERE = os.path.dirname(os.path.abspath(__file__))
RESUME = ("Sample Candidate\nDubai, United Arab Emirates\nsample@example.com | +971 50 000 0000\n"
          "SUMMARY\nSales manager with 12 years in stakeholder management and delivery governance.\n"
          "EXPERIENCE\nSales Manager, Acme FZE, Jan 2019 - Present\n"
          "- Led stakeholder management and release management across the region.\n"
          "SKILLS\nstakeholder management, release management, Jira, governance\n")
JOB = "Sales Manager. Stakeholder management, delivery governance, release management and Jira."
REPORT = {"readinessScore": 88, "jobMatchScore": 94, "checksPassed": 24, "checksTotal": 26,
          "wordCount": 61, "missingKeywords": ["lead", "governance"],
          "categories": {"parse": {"score": 100}, "contact": {"score": 90}},
          "failedChecks": [{"id": "ats-v2.format.length", "severity": "warning", "evidence": "61 words",
                            "scoreImpact": 10},
                           {"id": "ats-v2.structure.education", "severity": "warning", "evidence": "none",
                            "scoreImpact": 8}]}


def fake_result():
    """The keys the section reads. No scoring, no model."""
    return {"score": 84, "label": "Strong", "parts": {"job_match": 82},
            "_doc": {"modern": RESUME}, "layout": {"pages": 1, "n_columns": 1}}


class TestTheRegistration(unittest.TestCase):
    def test_it_is_the_third_checker(self):
        self.assertIn("engine", SO.CHECKERS)
        self.assertEqual(list(SO.ORDER), ["matcher", "checker2", "engine"])

    def test_it_is_compared_with_the_lab_score(self):
        self.assertEqual(SO.CHECKERS["engine"]["compares"], "score")
        self.assertEqual(SO.reference_of(fake_result(), "engine"), 84)
        self.assertEqual(SO.reference_text(fake_result(), "engine"), "vs Lab score 84")

    def test_the_licence_is_mit_and_kept_beside_the_code(self):
        folder = os.path.join(HERE, "vendor", "ats-engine", "licence")
        with open(os.path.join(folder, "LICENSE"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("MIT License", text)
        self.assertTrue(os.path.isfile(os.path.join(folder, "NOTICE")))
        self.assertIn("MIT", E.VERSION)


class TestTheReport(unittest.TestCase):
    def test_the_json_is_read_after_a_banner(self):
        out = E._json_of('VeriWorkly banner\n{"readinessScore": 88}\n')
        self.assertEqual(out, {"readinessScore": 88})

    def test_a_broken_json_is_not_a_crash(self):
        self.assertIsNone(E._json_of("not json at all"))

    def test_the_answer_carries_the_numbers_the_card_shows(self):
        answer = E.answer_of(REPORT)
        self.assertEqual(answer["state"], E.DONE)
        self.assertEqual(answer["score"], 88)
        self.assertEqual(answer["job_match"], 94)
        self.assertEqual(answer["missing"], ["lead", "governance"])
        self.assertEqual([c["name"] for c in answer["checks"]],
                         ["ats-v2.format.length", "ats-v2.structure.education"])

    def test_a_report_without_a_score_is_a_failure(self):
        self.assertEqual(E.answer_of({"wordCount": 10})["state"], E.FAILED)


class TestFailureIsolation(unittest.TestCase):
    def test_no_text_is_a_clean_failure(self):
        self.assertEqual(E.run("too short")["state"], E.FAILED)

    def test_not_installed_is_a_clean_state(self):
        with mock.patch.object(E, "available", return_value=(False, "not_installed")):
            self.assertEqual(E.run(RESUME)["state"], E.UNAVAILABLE)

    def test_a_timeout_is_a_clean_failure(self):
        with mock.patch.object(E, "available", return_value=(True, "")), \
                mock.patch.object(E, "command", return_value=["ats-engine"]), \
                mock.patch.object(E, "_run", side_effect=__import__("subprocess").TimeoutExpired("x", 1)):
            self.assertEqual(E.run(RESUME)["state"], E.FAILED)

    def test_an_unknown_error_never_breaks_the_lab(self):
        with mock.patch.object(E, "available", return_value=(True, "")), \
                mock.patch.object(E, "command", return_value=["ats-engine"]), \
                mock.patch.object(E, "_run", side_effect=OSError("boom")):
            self.assertEqual(E.run(RESUME)["state"], E.FAILED)

    def test_the_section_never_raises(self):
        with mock.patch.object(E, "available", return_value=(False, "not_installed")):
            out = SO.run("engine", fake_result(), JOB, {"engine": True})
        self.assertEqual(out["state"], SO.UNAVAILABLE)

    def test_switched_off_in_settings(self):
        self.assertEqual(SO.run("engine", fake_result(), JOB, {"engine": False})["state"], SO.OFF)


class TestTheLabScoreIsUntouched(unittest.TestCase):
    def test_running_the_engine_does_not_change_the_result(self):
        res = fake_result()
        before = repr(res)
        SO.run("engine", res, JOB, {"engine": True})
        self.assertEqual(repr(res), before, "the checker only reads the Lab's numbers")

    def test_the_engine_is_not_compared_when_it_has_no_score(self):
        answer = SO.finish("engine", fake_result(), {"state": SO.FAILED})
        self.assertEqual(answer["state"], SO.FAILED)


class TestTheBenchmark(unittest.TestCase):
    def test_the_benchmark_shows_the_lab_and_the_cards(self):
        import admin_page as A
        saved = {"res": fake_result(), "inputs": {"pdf": b"pdf", "text": JOB}}
        answers = {"matcher": {"state": SO.DONE, "score": 80, "reference": 82, "word": "Agrees",
                               "difference": "Agrees · 2 points lower", "source": "job"},
                   "engine": {"state": SO.DONE, "score": 88, "reference": 84, "word": "Agrees",
                              "difference": "Agrees · 4 points higher", "source": "engine"}}
        html = []
        with mock.patch.object(A.st, "markdown", lambda *a, **k: html.append(a[0] if a else "")):
            A.benchmark(saved, answers)
        body = "\n".join(str(x) for x in html)
        self.assertIn(T.SECOND_TEXT["bench_title"], body)
        self.assertIn(T.SECOND_TEXT["bench_lab"], body)
        self.assertIn("Resume Matcher", body)
        self.assertIn("ATS Checker 3", body)
        self.assertNotIn("ATS Checker 2", body, "a card with no number is not in the table")

    def test_no_table_when_nothing_was_checked(self):
        import admin_page as A
        saved = {"res": fake_result(), "inputs": {}}
        html = []
        with mock.patch.object(A.st, "markdown", lambda *a, **k: html.append(a[0] if a else "")):
            A.benchmark(saved, {})
        self.assertEqual(html, [], "an empty table is not drawn")


class TestPrivacy(unittest.TestCase):
    def test_the_engine_sends_nothing(self):
        with open(os.path.join(HERE, "lab_third.py"), encoding="utf-8") as fh:
            source = fh.read()
        code = source.split('"""', 2)[-1]          # the docstring may name the project's address
        for word in ("requests", "urllib", "http://", "https://", "socket", "urlopen"):
            self.assertNotIn(word, code, "the engine runs as a local command only")

    def test_the_resume_goes_to_a_temporary_folder(self):
        with open(os.path.join(HERE, "lab_third.py"), encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("tempfile.mkdtemp", source)
        self.assertIn("shutil.rmtree", source)


@unittest.skipUnless(E.available()[0], "the open-source engine is not installed on this machine")
class TestTheRealEngine(unittest.TestCase):
    def test_it_reads_a_real_resume(self):
        out = E.run(RESUME, JOB)
        self.assertEqual(out["state"], E.DONE, out)
        self.assertIsInstance(out["score"], int)
        self.assertTrue(0 <= out["score"] <= 100)
        self.assertIsInstance(out.get("job_match"), int)

    def test_it_reads_a_resume_without_a_job(self):
        out = E.run(RESUME)
        self.assertEqual(out["state"], E.DONE, out)
        self.assertIsNone(out.get("job_match"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
