"""The "To verify by the team" list: built by the scorer, shown on the admin page, never on the user page."""

import unittest

import cv_score as C
import dashboard as D


class TestVerifyList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = C.score_cv(r"C:\ATSLab\data\resumes\11_Riyaj_Shaikh_CV.pdf")

    def test_the_result_carries_the_list(self):
        self.assertIn("to_verify", self.r)
        for v in self.r["to_verify"]:
            self.assertTrue(v.get("id") and v.get("name") and v.get("why"),
                            "every entry says what it is and why it is not scored")

    def test_a_two_column_page_keeps_its_card_and_lists_no_layout_item(self):
        ids = {i["id"] for i in self.r["issues"]}
        self.assertIn("TPL", ids)                     # the layout card is kept: the page really has columns
        layout_ids = {"D3", "D4", "D12", "T15", "B1", "N1"}
        self.assertFalse(layout_ids & {v["id"] for v in self.r["to_verify"]},
                         "a layout problem the page confirms is scored, not sent for review")

    def test_unreliable_checks_are_listed_and_not_scored(self):
        ids = {i["id"] for i in self.r["issues"]}
        self.assertFalse(ids & set(C.UNRELIABLE_CHECKS),
                         "a check under 90% accuracy must never be scored")
        for v in self.r["to_verify"]:
            self.assertTrue(v.get("why"), "every entry on the team's list says why it is not scored")

    def test_the_two_rechecked_checks_are_scored_again(self):
        # 2026-11-09: after the truth re-check the city check (17 of 17 confirmed files right) and the date-format
        # check (4 of 4) reached the 90% bar and came back into the score
        self.assertNotIn("T6", C.UNRELIABLE_CHECKS)
        self.assertNotIn("T4C", C.UNRELIABLE_CHECKS)
        ids = {i["id"] for i in self.r["issues"]}
        self.assertIn("T6", ids, "this resume really has no city in the contact details")
        self.assertNotIn("T6", {v["id"] for v in self.r["to_verify"]})

    def test_the_user_page_text_has_no_verify_list(self):
        with open("dashboard.py", encoding="utf-8") as fh:
            source = fh.read()
        body = source[source.index("def render(r, with_job"):]
        self.assertNotIn("to_verify", body.split("def render_client")[0],
                         "the user report must not show the team's verify list")
        details = source[source.index("def show_details(r):"):source.index("def render(r, with_job")]
        self.assertIn("to_verify", details, "the admin details view shows it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
