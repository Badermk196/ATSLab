"""
Tests for the AI reviewer (cv_review.py) and how its findings reach the CV Score and the dashboard.
The AI is replaced by a fake answer: no API calls, no cost.

  py -3.12 -m unittest test_cv_review -v
"""

import json
import os
import shutil
import tempfile
import unittest

os.environ["ATSLAB_AI_REVIEW"] = "0"      # the dashboard's own switch: these tests call the reviewer themselves

import ATSLab_v3 as L
import cv_review as R
import cv_score as C
import test_cv_score as T

CV = T.polished_cv(numbers=False)["modern"]
QUOTE_OK = "Coordinated weekly freight forwarding shipments across GCC markets without customs penalties."
ANSWER = {"field": "logistics coordination", "findings": [
    {"issue": "Bullets show duties, not results", "severity": "Major", "type": "content", "quote": QUOTE_OK,
     "why": "Recruiters cannot see the size of the work.", "fix": "Add how many shipments or markets, if you know."},
    {"issue": "Invented quote", "severity": "Critical", "type": "content",
     "quote": "Managed a fleet of 300 trucks across Saudi Arabia",
     "why": "x", "fix": "y"},                                                   # not in the CV -> rejected
    {"issue": "Shortened quote", "severity": "Major", "type": "content", "quote": "Coordinated weekly ... penalties",
     "why": "x", "fix": "y"},                                                   # paraphrased -> rejected
    {"issue": "Hobby line looks pasted from another CV", "severity": "Major", "type": "unusual",
     "quote": "Negotiated carrier rates that saved money for the logistics department.",
     "why": "It may not belong to this candidate.", "fix": "Check it."},
    {"issue": "Generic summary", "severity": "Major", "type": "content",
     "quote": "Known for accurate   shipment tracking, clear vendor communication",   # extra spaces: still found
     "why": "It sounds like many other CVs.", "fix": "Name one real result."},
]}


class FakeAI:
    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    def __call__(self, prompt, model):
        self.calls += 1
        self.prompt = prompt
        return self.answer


class Base(T.Base):
    def setUp(self):
        super().setUp()
        self.review_cache = tempfile.mkdtemp()
        self.real_ai = L.call_ai
        self.fake = FakeAI(ANSWER)
        L.call_ai = self.fake
        self.had_key = "OPENROUTER_API_KEY" in os.environ
        os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-used")

    def tearDown(self):
        L.call_ai = self.real_ai
        if not self.had_key:
            os.environ.pop("OPENROUTER_API_KEY", None)
        shutil.rmtree(self.review_cache, ignore_errors=True)
        super().tearDown()


class TestReviewer(Base):
    def test_only_findings_quoted_from_the_cv_are_kept(self):
        rev = R.review_cv(CV, "Logistics Coordinator", cache=self.review_cache)
        kept = [f["issue"] for f in rev["findings"]]
        self.assertEqual(kept, ["Bullets show duties, not results", "Hobby line looks pasted from another CV",
                                "Generic summary"])
        self.assertEqual(sorted(f["issue"] for f in rev["rejected"]), ["Invented quote", "Shortened quote"])
        self.assertEqual(rev["field"], "logistics coordination")
        self.assertIn("EXACT words", self.fake.prompt)
        self.assertIn(f"Today's date is {L.TODAY.strftime('%d %B %Y')}", self.fake.prompt)   # no false "future" dates

    def test_saved_per_cv_and_never_reviewed_twice(self):
        R.review_cv(CV, "Logistics Coordinator", cache=self.review_cache)
        again = R.review_cv(CV, "Logistics Coordinator", cache=self.review_cache)
        self.assertEqual(self.fake.calls, 1)
        self.assertTrue(again["cached"])
        with open(R.cache_path(CV, "Logistics Coordinator", cache=self.review_cache), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual((saved["temperature"], saved["model"]), (0, "google/gemini-2.5-flash"))
        R.review_cv(CV + "\nNew line", "Logistics Coordinator", cache=self.review_cache)   # a changed CV: new review
        self.assertEqual(self.fake.calls, 2)

    def test_no_key_means_no_review(self):
        os.environ.pop("OPENROUTER_API_KEY", None)
        self.assertIsNone(R.review_cv(CV, "Logistics Coordinator", cache=self.review_cache))
        self.assertEqual(self.fake.calls, 0)


class TestFindingChecks(unittest.TestCase):
    """Facts the code can check are checked: a 'future date' claim about a past date is rejected."""

    CV_TEXT = "Logistics Coordinator\nBabygrow FZC - Sharjah, UAE Feb 2025 - Present\nCoordinated 40 weekly shipments."

    def item(self, issue, quote, why="It raises questions."):
        return {"issue": issue, "severity": "Critical", "type": "content", "quote": quote, "why": why, "fix": "x"}

    def test_false_future_date_is_rejected(self):
        kept, rejected = R.clean({"findings": [
            self.item("Future employment date", "Babygrow FZC - Sharjah, UAE Feb 2025 - Present")]}, [self.CV_TEXT])
        self.assertEqual(kept, [])
        self.assertEqual(len(rejected), 1)

    def test_real_future_date_is_kept(self):
        y = L.TODAY.year + 2
        text = f"Logistics Coordinator\nAcme LLC - Dubai, UAE Mar {y} - Present\nCoordinated 40 weekly shipments."
        kept, _ = R.clean({"findings": [self.item("Start date in the future", f"Acme LLC - Dubai, UAE Mar {y} - Present")]},
                          [text])
        self.assertEqual(len(kept), 1)

    def test_same_problem_twice_is_one_finding(self):
        kept, _ = R.clean({"findings": [self.item("Irrelevant education", "Babygrow FZC - Sharjah, UAE"),
                                        self.item("Irrelevant education", "Coordinated 40 weekly shipments.")]},
                          [self.CV_TEXT])
        self.assertEqual(len(kept), 1)


class TestQualityRules(unittest.TestCase):
    """Prompt rules (version 3), answered findings rejected, long quotes shortened for display."""

    def item(self, issue, quote):
        return {"issue": issue, "severity": "Major", "type": "content", "quote": quote, "why": "x.", "fix": "y."}

    def test_prompt_rules(self):
        p = R.review_prompt("Media Director")
        self.assertGreaterEqual(R.REVIEW_PROMPT_VERSION, 3)
        for rule in ("NEVER flag something the quoted text already answers",
                     "NEVER suggest removing real degrees, jobs, certifications",
                     "Skip nitpicks"):
            self.assertIn(rule, p)

    def test_already_answered_is_rejected(self):
        text = "Led a team of 5 -consisting of 3 planners & 2 operations."
        kept, rejected = R.clean({"findings": [self.item("Unclear team size", text)]}, [text])
        self.assertEqual((kept, len(rejected)), ([], 1))
        kept, _ = R.clean({"findings": [self.item("Vague team leadership claim", text)]}, [text])
        self.assertEqual(len(kept), 1)                            # a different point about the same line is kept

    def test_quote_over_several_lines(self):
        cv = "Alshaya Group - UAE Sep 2021 - Jun 2023\nManaged stock.\nAl Tayer Group - UAE Sep 2018 - Sep 2020"
        self.assertTrue(R.quote_in_cv("Alshaya Group - UAE Sep 2021 - Jun 2023\nAl Tayer Group - UAE Sep 2018 - Sep 2020",
                                      [cv]))
        self.assertFalse(R.quote_in_cv("Alshaya Group - UAE Sep 2021 - Jun 2023\nGodiva LLC - UAE Dec 2017", [cv]))

    def test_date_findings_are_confirmed_on_the_quoted_dates(self):
        cc = {k: {"score": 1.0} for k in ("C1", "C2", "C4", "C6")}
        ana = {"jobs": [{"intervals": [(2018 * 12, 2020 * 12 + 8)], "problem": None},
                        {"intervals": [(2021 * 12 + 8, 2023 * 12 + 5)], "problem": "year only"}]}
        f = lambda issue, quote: {"issue": issue, "why": "", "quote": quote}
        self.assertFalse(C.ai_confirmed(f("Inconsistent date format", "Apr 2024 to Feb 2026"), cc, ana))   # fine
        self.assertTrue(C.ai_confirmed(f("Inconsistent date format", "2021 - Current"), cc, ana))         # year only
        self.assertFalse(C.ai_confirmed(f("Unexplained employment gap", "Sep 2018 - Sep 2020"), cc, ana))  # v1.1: no gaps

    def test_long_quote_is_shortened_for_display(self):
        long = " ".join("word" + chr(97 + i % 26) + chr(97 + i // 26) for i in range(60))
        kept, _ = R.clean({"findings": [self.item("Vague responsibilities", long)]}, [long])
        self.assertEqual(kept[0]["quote_full"], long)
        self.assertEqual(len(kept[0]["quote"].split()), R.SHOW_QUOTE_WORDS + 1)   # 35 words + '…'


class TestSeverityAndBlocked(Base):
    """AI findings are Important at most unless a rule check confirms them; a fix held down by the
    no-numbers cap says what to fix first and what it adds then."""

    def answer(self, *findings):
        self.fake.answer = {"field": "logistics", "findings": list(findings)}

    def score(self, numbers=False):
        return C.score_cv("jane.pdf", None, T.ROLE, doc=T.polished_cv(numbers=numbers), role_cache=self.cache,
                          review=True, review_cache=self.review_cache)

    def test_unconfirmed_critical_becomes_important(self):
        self.answer({"issue": "Spelling mistakes in the summary", "severity": "Critical", "type": "content",
                     "quote": "Known for accurate shipment tracking, clear vendor communication", "why": "x.",
                     "fix": "y."})
        ai = [i for i in self.score()["issues"] if i.get("ai")][0]
        self.assertEqual(ai["severity"], "Major")
        self.assertFalse(ai["ai"]["confirmed"])

    def test_a_confirmed_finding_is_important_at_most(self):
        self.answer({"issue": "No measurable results", "severity": "Critical", "type": "content",
                     "quote": QUOTE_OK, "why": "x.", "fix": "y."})        # the bullet really has no number
        ai = [i for i in self.score()["issues"] if i.get("ai")][0]
        self.assertEqual(ai["severity"], "Major")                  # an AI finding is never Critical (2026-10-25)
        self.assertTrue(ai["ai"]["confirmed"])

    def test_blocked_fix_says_what_to_fix_first(self):
        import dashboard as D
        self.answer({"issue": "Spelling mistakes in the summary", "severity": "Critical", "type": "content",
                     "quote": "Known for accurate shipment tracking, clear vendor communication", "why": "x.",
                     "fix": "y."})
        r = self.score(numbers=False)                             # held at 70: no numbers in any bullet
        self.assertTrue(r["gates"])
        ai = [i for i in r["issues"] if i.get("ai")][0]
        self.assertEqual(ai["points"], 0)
        self.assertEqual(ai["blocked_by"], "numbers")
        self.assertGreaterEqual(ai["points_after"], 1)
        r["_doc"] = T.polished_cv(numbers=False)
        card = [c for c in D.issue_cards(r) if c.get("ai")][0]
        self.assertEqual(D.gain_text(card), f"Add numbers or results to your bullets first, then this adds about "
                                            f"+{card['points_after']:.0f}")
        free = self.score(numbers=True)                           # nothing holds it down: plain points, no note
        self.assertFalse(any(i.get("blocked_by") for i in free["issues"] if i.get("ai")))


class TestReviewInScore(Base):
    def score(self, doc, review=True):
        return C.score_cv("jane.pdf", None, T.ROLE, doc=doc, role_cache=self.cache, review=review,
                          review_cache=self.review_cache)

    def test_content_findings_feed_content_quality(self):
        doc = T.polished_cv(numbers=False)
        without = self.score(doc, review=False)
        with_ai = self.score(doc)
        self.assertIsNone(without["content_checks"]["C8"]["score"])
        self.assertAlmostEqual(with_ai["content_checks"]["C8"]["score"], 1 - 0.15 - 0.15)   # two Important findings
        self.assertAlmostEqual(with_ai["parts"]["content"], without["parts"]["content"] - 100 * C.AI_WEIGHT * 0.3,
                               places=0)                               # the review only takes points off
        ai = [i for i in with_ai["issues"] if i.get("ai")]
        self.assertEqual(sorted(i["name"] for i in ai), ["Bullets show duties, not results", "Generic summary"])
        major = next(i for i in ai if i["severity"] == "Major")
        self.assertEqual(major["evidence"], [QUOTE_OK])
        self.assertEqual(major["points"], 0)          # this CV is held at 70 (no numbers): fixing it alone adds 0
        free = self.score(T.polished_cv(numbers=True))                     # no cap: the summary finding is worth points
        summary = next(i for i in free["issues"] if i.get("ai") and i["name"] == "Generic summary")
        self.assertGreater(summary["points"], 0)

    def test_unusual_findings_are_not_scored(self):
        r = self.score(T.polished_cv(numbers=False))
        self.assertEqual([f["issue"] for f in r["ai_review"]["unusual"]], ["Hobby line looks pasted from another CV"])
        self.assertNotIn("Hobby line looks pasted from another CV", [i["name"] for i in r["issues"]])
        self.assertEqual(r["ai_review"]["rejected"], 2)


class TestReviewOnDashboard(Base):
    def test_ai_cards_in_the_same_style_and_new_problems_in_details(self):
        import dashboard as D
        from streamlit.testing.v1 import AppTest
        r = self.score_for_dashboard()
        all_cards = D.issue_cards(r)
        cards = [c for c in all_cards if c.get("ai")]
        self.assertEqual(len(cards), 2)                    # cards are never merged by a shared quote (2026-10-21)
        self.assertFalse([c for c in all_cards if c.get("also")])
        for c in cards:
            self.assertIn(c["tag"], D.SHOWN_SEVERITY.values())
            self.assertTrue(D.evidence(c, r))
            self.assertTrue(c["why"].endswith(".") and c["fix"].endswith("."))

        def page(res):
            import dashboard as D
            D.render(res)

        at = AppTest.from_function(page, args=(r,), default_timeout=120).run()
        self.assertFalse(at.exception, at.exception)
        text = "\n".join(m.value for m in at.markdown) + "\n".join(c.value for c in at.caption)
        self.assertIn("Bullets show duties, not results", text)
        self.assertIn("AI suggestion", text)
        self.assertIn("AI reviewer: Hobby line looks pasted from another CV", text)   # possible new problem
        self.assertIn("left out because their quote is not in the resume", text)

    def score_for_dashboard(self):
        r = C.score_cv("jane.pdf", None, T.ROLE, doc=T.polished_cv(numbers=False), role_cache=self.cache,
                       review=True, review_cache=self.review_cache)
        r["_doc"] = T.polished_cv(numbers=False)
        return r


class TestDegreeNeverIrrelevant(unittest.TestCase):
    def test_prompt_and_filter(self):
        self.assertEqual(R.REVIEW_PROMPT_VERSION, 8)
        self.assertIn("NEVER call a real degree", R.review_prompt())
        cv = "EDUCATION\nMaster of Applied Finance (Investing), Macquarie University, 2016\nLed 5 planners."
        raw = {"findings": [{"issue": "Irrelevant Master's degree", "severity": "Minor", "type": "content",
                             "quote": "Master of Applied Finance (Investing)", "why": "Not related to logistics.",
                             "fix": "Remove it."},
                            {"issue": "Degree not relevant to the role", "severity": "Minor", "type": "content",
                             "quote": "Master of Applied Finance (Investing), Macquarie University",
                             "why": "x.", "fix": "y."}]}
        kept, rejected = R.clean(raw, [cv])
        self.assertEqual(kept, [])
        self.assertEqual(len(rejected), 2)


class TestStricterReviewer(unittest.TestCase):
    """2026-10-23: at most 3 findings, only Important ones, no 'add a number' on a bullet that has numbers, no nitpicks."""

    LINES = [f"Delivered project number {n} for client {chr(65 + n)} on time and on budget in Dubai." for n in range(8)]
    CV_TEXT = "\n".join(LINES)

    def item(self, issue, quote, severity="Major", why="A recruiter would notice.", fix="Fix it."):
        return {"issue": issue, "severity": severity, "type": "content", "quote": quote, "why": why, "fix": fix}

    def test_at_most_three_findings_most_severe_first(self):
        raw = {"findings": [self.item(f"Problem {n}", self.LINES[n], "Major") for n in range(6)] +
                            [self.item("Worst problem", self.LINES[6], "Critical")]}
        kept, rejected = R.clean(raw, [self.CV_TEXT])
        self.assertEqual(len(kept), 3)
        self.assertEqual({k["severity"] for k in kept}, {"Major"})      # Critical is Important: never Critical
        self.assertEqual(len(rejected), 4)

    def test_only_important_findings(self):
        kept, rejected = R.clean({"findings": [self.item("Wording is plain", self.LINES[0], "Minor"),
                                               self.item("Real problem", self.LINES[1], "Major")]}, [self.CV_TEXT])
        self.assertEqual([k["issue"] for k in kept], ["Real problem"])
        self.assertEqual([k["issue"] for k in rejected], ["Wording is plain"])

    def test_no_more_context_or_number_on_a_bullet_with_numbers(self):
        has = "Cut order processing time from 30 to 20 days across four sales channels in the region."
        none = "Handled order processing for the sales channels in the region every day of the week."
        raw = {"findings": [self.item("Lacks context", has, why="More context would help.", fix="Add more context."),
                            self.item("Missing metric", has, why="No metric.", fix="Add a number."),
                            self.item("Missing result", none, why="No metric.", fix="Add a number.")]}
        kept, rejected = R.clean(raw, [has + "\n" + none])
        self.assertEqual([k["quote"] for k in kept], [none])        # a bullet with no number may still be asked
        self.assertEqual(len(rejected), 2)

    def test_summary_length_is_not_an_ai_finding(self):
        raw = {"findings": [self.item("Summary is too long", self.LINES[0], why="The summary is lengthy.")]}
        kept, rejected = R.clean(raw, [self.CV_TEXT])
        self.assertEqual((kept, len(rejected)), ([], 1))

    def test_prompt_asks_for_at_most_3(self):
        p = R.review_prompt()
        for rule in ("AT MOST 3", "report anything smaller than Major", "more context", "add a number"):
            self.assertIn(rule, p)


if __name__ == "__main__":
    unittest.main()
