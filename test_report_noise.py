"""Three cards a real report showed that the team called noise (Riyaj Shaikh, 4 Nov 2026), locked in:

1. "Light or low-contrast text" (D8) - its evidence was ordinary resume text; the card is switched off.
2. "Abbreviations are never written in full" (C12) - one abbreviation alone is no longer a card; two or more are.
3. "Inconsistent contact information" (AI) - dropped when the CV already has a full email and a phone with a code.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cv_layout as Y                                        # noqa: E402
import cv_review as R                                        # noqa: E402
import cv_score as C                                         # noqa: E402
import test_cv_score as T                                    # noqa: E402

CV_TEXT = """Riyaj Shaikh
Senior Digital & AI Transformation Leader
+971-527045353 | riyajshaikh7@gmail.com | linkedin.com/in/riyajshaikh
SUMMARY
Fifteen years in AI products and digital transformation.
EXPERIENCE
Principal - Digital & AI | Jan 2024 - Present
MTN Group | Dubai, UAE
- Built an AI analytics platform using NLP and ML that saved USD 500K a year.
"""


class TestTheLowContrastCardIsOff(unittest.TestCase):
    def test_the_switch_is_off(self):
        self.assertFalse(Y.CONTRAST_CHECK)

    def test_the_check_is_still_there_to_switch_back_on(self):
        self.assertIn("D8", Y.DESIGN)


class TestOneAbbreviationIsNotACard(unittest.TestCase):
    def checks(self, text):
        doc = T.fake_doc(text)
        ana = C.analyse_cv(doc)
        bugs = [{"code": "B9", "found": 0}, {"code": "B13", "found": 0}]
        res = {"bugs": bugs, "experience_years": 15, "pages": 1}
        return C.content_checks(doc, ana, res, "Head of AI & Digital Excellence")["C12"]

    def test_one_abbreviation_alone_is_not_flagged(self):
        c = self.checks(CV_TEXT)                              # NLP is used, never written in full
        self.assertEqual(c["score"], 1.0, c)
        self.assertEqual(c["detail"], "never written in full: none", c)

    def test_two_abbreviations_are_still_flagged(self):
        text = CV_TEXT + "- Ran UAT for the platform in three regions before the SDLC release.\n"
        c = self.checks(text)
        self.assertLess(c["score"], 1.0, c)
        self.assertIn("NLP", c["detail"], c)
        self.assertIn("UAT", c["detail"], c)


class TestAFalseContactFinding(unittest.TestCase):
    def item(self, issue, why="The contact information is split and incomplete."):
        return {"issue": issue, "why": why, "fix": ""}

    def test_dropped_when_the_email_and_phone_are_both_there(self):
        self.assertTrue(R.false_contact(self.item("Inconsistent contact information"), [CV_TEXT]))

    def test_kept_when_the_phone_is_missing(self):
        text = CV_TEXT.replace("+971-527045353 | ", "")
        self.assertFalse(R.false_contact(self.item("Inconsistent contact information"), [text]))

    def test_kept_when_the_email_is_missing(self):
        text = CV_TEXT.replace("riyajshaikh7@gmail.com | ", "")
        self.assertFalse(R.false_contact(self.item("Inconsistent contact information"), [text]))

    def test_any_other_finding_is_untouched(self):
        self.assertFalse(R.false_contact(self.item("Bullets start with weak words",
                                                   "They describe a duty, not a result."), [CV_TEXT]))

    def test_clean_drops_it_from_the_kept_findings(self):
        raw = {"field": "AI", "findings": [{"issue": "Inconsistent contact information", "severity": "Important",
                                            "type": "unusual", "quote": "riyajshaikh7@gmail.com",
                                            "why": "The contact information is split and incomplete.",
                                            "fix": "Consolidate it."}]}
        kept, rejected = R.clean(raw, [CV_TEXT])
        self.assertEqual(kept, [])
        self.assertEqual([f["issue"] for f in rejected], ["Inconsistent contact information"])


if __name__ == "__main__":
    unittest.main()
