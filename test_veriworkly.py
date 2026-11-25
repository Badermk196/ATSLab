"""
Tests for the VeriWorkly card (the open-source @veriworkly/ats-engine) that replaced "ATS Checker 2" on the Admin page,
and for lab_node.py, which gives a server with no Node (Streamlit Cloud) its Node 24 (pip wheel) and installs the engine
once. No scoring is touched. No AI call, no download of the AI model; the one real engine run is skipped when the
engine is not installed on this computer.

  py -3.12 -m unittest test_veriworkly -v
"""

import os

os.environ["ATSLAB_AI_REVIEW"] = "0"
os.environ.pop("OPENROUTER_API_KEY", None)
import shutil
import tempfile
import unittest
from unittest import mock

import admin_page as A
import lab_node as N
import lab_second as SO
import lab_third as E
import test_second_opinion as T

HERE = os.path.dirname(os.path.abspath(__file__))
RESUME = ("Neda Sefati\nneda@example.com +971 50 123 4567\nDelivery Lead\n\nEXPERIENCE\nDelivery Lead, Creatio, "
          "Jan 2020 - Present\n- Led release management for 12 teams and cut incidents by 30%\n- Ran stakeholder "
          "reviews and risk management with Jira dashboards\n\nSKILLS\nJira, Agile, Release Management\n")
JOB = "Delivery Lead. Release management, stakeholder management, Jira, risk management, Agile."


def engine_report(score=88, job_match=None):
    """What E.run gives back (a finished answer)."""
    return {"state": E.DONE, "score": score, "job_match": job_match, "checks": [], "missing": ["Scrum"],
            "n_checks": 25, "n_total": 29, "weakest": [], "words": 120}


class TestTheComparison(unittest.TestCase):
    """VeriWorkly is compared with the right Lab number: Job match with a job description, the score without."""
    def setUp(self):
        self.res = T.fake_result()

    def run_engine(self, job, report):
        with mock.patch.object(SO.E, "run", return_value=report):
            return SO.finish("engine", self.res, SO.run("engine", self.res, job))

    def test_with_a_job_description_its_job_match_is_compared_with_the_labs_job_match(self):
        out = self.run_engine(JOB, engine_report(score=90, job_match=34))
        self.assertEqual((out["score"], out["readiness"], out["compares"]), (34, 90, "job_match"))
        self.assertEqual(out["reference"], round(self.res["parts"]["job_match"]))
        self.assertEqual(SO.reference_text(self.res, "engine", out), f"vs Lab Job match {out['reference']}")

    def test_without_a_job_description_its_readiness_is_compared_with_the_labs_score(self):
        out = self.run_engine("", engine_report(score=90))
        self.assertEqual((out["score"], out["compares"]), (90, "score"))
        self.assertEqual(out["reference"], round(self.res["score"]))
        self.assertEqual(SO.reference_text(self.res, "engine", out), f"vs Lab score {out['reference']}")

    def test_a_job_description_without_a_job_match_falls_back_to_the_overall_score(self):
        out = self.run_engine(JOB, engine_report(score=90, job_match=None))
        self.assertEqual((out["score"], out["compares"]), (90, "score"))

    def test_the_lab_number_is_never_changed(self):
        before = dict(self.res["parts"]), self.res["score"]
        self.run_engine(JOB, engine_report(job_match=34))
        self.assertEqual((self.res["parts"], self.res["score"]), before)


class TestTheCard(unittest.TestCase):
    def test_a_server_that_is_setting_up_says_so(self):
        text = A.unavailable_hint("engine", "VeriWorkly", "installing")
        self.assertIn("one-time install", text)

    def test_a_failed_setup_says_why(self):
        with mock.patch.object(A.LN, "status", return_value={"detail": "ENOTFOUND registry.npmjs.org"}):
            text = A.unavailable_hint("engine", "VeriWorkly", "npm_install_failed")
        self.assertIn("the npm install failed", text)
        self.assertIn("ENOTFOUND", text)
        self.assertIn("works normally", text)

    def test_the_card_is_drawn_when_the_engine_cannot_run(self):
        """VeriWorkly is not hidden when it is not installed: a problem is seen, not hidden."""
        with mock.patch.object(SO.E, "available", return_value=(False, "installing")):
            self.assertIn("engine", SO.visible_order())

    def test_pressing_the_button_on_a_server_that_is_setting_up_gives_an_unavailable_card(self):
        with mock.patch.object(SO.E, "available", return_value=(False, "installing")):
            out = SO.run("engine", T.fake_result(), JOB)
        self.assertEqual((out["state"], out["why"]), (E.UNAVAILABLE, "installing"))


class TestNodeForAServerWithNoNode(unittest.TestCase):
    def test_the_requirements_pin_the_node_wheel_and_the_engine(self):
        with open(os.path.join(HERE, "requirements.txt"), encoding="utf-8") as fh:
            self.assertRegex(fh.read(), r"(?m)^nodejs-wheel-binaries==24\.\d+\.\d+$")
        import json
        with open(os.path.join(HERE, "vendor", "ats-engine", "package.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["dependencies"], {"@veriworkly/ats-engine": "0.22.0"})
        self.assertTrue(os.path.isfile(os.path.join(HERE, "vendor", "ats-engine", "package-lock.json")))

    def test_npm_is_found_next_to_the_wheels_node(self):
        try:
            import nodejs_wheel          # noqa: F401
        except ImportError:
            self.skipTest("nodejs-wheel-binaries is not installed on this computer")
        self.assertTrue(os.path.isfile(N._npm_cli()))
        self.assertTrue(os.path.isfile(N.node_path()))
        self.assertGreaterEqual(N.node_version()[:2], N.MIN_NODE)

    def test_an_empty_folder_has_no_engine_command(self):
        folder = tempfile.mkdtemp()
        try:
            with mock.patch.object(N, "ENGINE_DIR", os.path.join(folder, "node_modules", "@veriworkly", "ats-engine")):
                self.assertIsNone(N.engine_script())
                self.assertIsNone(N.engine_command())
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_the_engine_script_is_read_from_its_package_json(self):
        folder = tempfile.mkdtemp()
        try:
            engine = os.path.join(folder, "node_modules", "@veriworkly", "ats-engine")
            os.makedirs(os.path.join(engine, "dist", "cli"))
            with open(os.path.join(engine, "package.json"), "w", encoding="utf-8") as fh:
                fh.write('{"bin": {"ats-engine": "./dist/cli/index.js"}}')
            with open(os.path.join(engine, "dist", "cli", "index.js"), "w", encoding="utf-8") as fh:
                fh.write("//")
            with mock.patch.object(N, "ENGINE_DIR", engine), mock.patch.object(N, "node_path", return_value="node"):
                self.assertEqual(N.engine_command(), ["node", os.path.join(engine, "dist", "cli", "index.js")])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_the_install_never_starts_inside_a_test_and_never_raises(self):
        with mock.patch.object(N, "engine_command", return_value=None):
            N.ensure()
        self.assertNotEqual(N.status()["state"], "installing")

    def test_a_missing_node_is_a_plain_reason_not_a_crash(self):
        with mock.patch.object(N, "node_version", return_value=None), \
                mock.patch.dict(N._STATE, {"state": "idle", "why": "", "seconds": None, "detail": ""}):
            N._install()
            self.assertEqual((N._STATE["state"], N._STATE["why"]), ("failed", "node_missing"))

    def test_a_node_that_is_too_old_is_a_plain_reason(self):
        with mock.patch.object(N, "node_version", return_value=(20, 18, 0)), \
                mock.patch.dict(N._STATE, {"state": "idle", "why": "", "seconds": None, "detail": ""}):
            N._install()
            self.assertEqual(N._STATE["why"], "node_too_old")

    def test_a_server_that_installed_the_command_itself_is_left_alone(self):
        with mock.patch.dict(os.environ, {"ATSLAB_ATS_ENGINE": "ats-engine"}), \
                mock.patch.object(N, "engine_command", return_value=None), \
                mock.patch.object(N, "_install") as install:
            N.ensure(background=False)
            install.assert_not_called()


@unittest.skipUnless(E.available()[0], "the engine is not installed on this computer")
class TestTheRealEngine(unittest.TestCase):
    """One real run through Node, the way the card runs it (the Lab's own text, no PDF)."""
    def test_it_scores_a_text_resume_with_and_without_a_job(self):
        plain = E.run(RESUME)
        self.assertEqual(plain["state"], E.DONE, plain)
        self.assertTrue(0 <= plain["score"] <= 100)
        with_job = E.run(RESUME, JOB)
        self.assertEqual(with_job["state"], E.DONE, with_job)
        self.assertIsNotNone(with_job["job_match"])


if __name__ == "__main__":
    unittest.main()
