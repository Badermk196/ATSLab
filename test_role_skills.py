"""
Tests for the role skill lists (kept for later use; since 2026-10-20 they are NOT part of the CV Score: without
a job description there is no Role Fit). AI calls are replaced by fakes; the saved lists in
role_skills\\ (made with the current prompt) are used where they exist.

  py -3.12 -m unittest test_role_skills -v
"""

import json
import os

os.environ["ATSLAB_AI_REVIEW"] = "0"      # no AI review (and no cost) in these tests
import shutil
import tempfile
import unittest

import ATSLab_v3 as L
import cv_score as C

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = {   # field: (CV, target role)
    "media": ("CV4/Tareq Al Masri CV JN26.pdf", "Media Director"),
    "logistics": ("CV4/jibran-original-cv.pdf", "Logistics Coordinator"),
    "software": ("CV4/rashaadnmohammed_Cohere.pdf", "Software Engineering Intern"),
}
NOT_FOR_LEADERS = ("graphic design", "copywriting", "video editing")


def saved(role):
    path = C.role_skills_path(role)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if data.get("prompt_version") == C.ROLE_PROMPT_VERSION else None


def low(skills):
    return [s.lower() for s in skills["required_skills"] + skills["preferred_skills"]]


class TestRoleLists(unittest.TestCase):
    """The saved list for each role fits the exact title and its level."""

    def need(self, role):
        if not saved(role):
            self.skipTest(f"no saved list for {role} made with the current prompt")
        return C.role_skills(role)

    def test_media_director_is_a_leadership_media_list(self):
        sk = self.need("Media Director")
        skills = low(sk)
        self.assertIn("media planning", skills)
        self.assertTrue(any("media buying" in s for s in skills))
        self.assertTrue(any("budget" in s or "p&l" in s for s in skills))
        for wrong in NOT_FOR_LEADERS + ("sem",):
            self.assertNotIn(wrong, skills)
        self.assertIn("director", (sk["seniority"] or "").lower())

    def test_logistics_coordinator_is_hands_on_logistics(self):
        sk = self.need("Logistics Coordinator")
        skills = low(sk)
        self.assertTrue(sum(any(w in s for w in ("freight", "shipping", "customs", "inventory", "warehouse"))
                            for s in skills) >= 4)
        for wrong in NOT_FOR_LEADERS + ("p&l management",):
            self.assertNotIn(wrong, skills)

    def test_software_intern_is_entry_level_programming(self):
        sk = self.need("Software Engineering Intern")
        skills = low(sk)
        self.assertTrue({"python", "git"} <= set(skills) or {"java", "git"} <= set(skills))
        for wrong in ("team leadership", "p&l management", "budget management"):
            self.assertNotIn(wrong, skills)
        self.assertIn("intern", (sk["seniority"] or "").lower())


class TestFieldCheck(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()
        self.real_ai = L.call_ai
        self.prompts = []
        self.had_key = "OPENROUTER_API_KEY" in os.environ

    def tearDown(self):
        L.call_ai = self.real_ai
        if not self.had_key:
            os.environ.pop("OPENROUTER_API_KEY", None)
        shutil.rmtree(self.cache, ignore_errors=True)

    def cv(self, field):
        path, role = CASES[field]
        full = os.path.join(HERE, path)
        if not os.path.exists(full) or not saved(role):
            self.skipTest(f"{path} or the saved list for {role} is not on this machine")
        shutil.copy(C.role_skills_path(role), C.role_skills_path(role, self.cache))
        return full, role

    def fake_ai(self, answer):
        os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-used")   # the fake AI never uses it
        def call(prompt, model):
            self.prompts.append(prompt)
            return answer
        L.call_ai = call

    def test_no_role_fit_without_a_job(self):
        """Without a job description the CV is measured against the 1000jobs standard only: no Role Fit part,
        no role skill list asked from the AI, and the target role does not change the score."""
        path, role = self.cv("logistics")
        self.fake_ai(None)                                            # any AI call would show up in self.prompts
        r = C.score_cv(path, None, None, role_cache=self.cache)
        self.assertEqual(set(r["parts"]), {"readability", "content", "structure"})
        self.assertIsNone(r["role_skills"])
        self.assertFalse(any(i["id"] == "K" for i in r["issues"]))
        self.assertEqual(self.prompts, [])
        other = C.score_cv(path, None, "Media Director", role_cache=self.cache)
        self.assertEqual(other["score"], r["score"])

    def test_list_from_an_older_prompt_is_made_again(self):
        role = "Data Analyst"
        with open(C.role_skills_path(role, self.cache), "w", encoding="utf-8") as f:
            json.dump({"role": role, "ai_runs": [{"required_skills": ["Graphic Design"], "preferred_skills": []}] * 3}, f)
        self.fake_ai({"seniority": "mid-level", "field": "analytics", "core_skills": ["SQL", "Python", "Tableau"],
                      "common_skills": ["Excel"]})
        sk = C.role_skills(role, cache=self.cache)
        self.assertEqual(sk["required_skills"], ["SQL", "Python", "Tableau"])
        self.assertEqual(len(self.prompts), C.L.AI_RUNS)
        self.assertIn("JOB TITLE: Data Analyst", self.prompts[0])
        self.assertIn("EXACT level of seniority", self.prompts[0])


if __name__ == "__main__":
    unittest.main()
