"""
The last round before launch: a sign-in that lasts, a Clear button for every list, and a Resume Matcher that
works in a general check too.

Nothing here changes the score: the Lab's own numbers and rules are untouched.
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import lab_second as SO
import lab_store as H
import lab_text as T


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="atslab-launch-")
        self.store = H.Store(self.folder)

    def tearDown(self):
        self.store.close() if hasattr(self.store, "close") else None
        shutil.rmtree(self.folder, ignore_errors=True)

    def two_checks_and_a_log(self):
        for n, name in enumerate(("Sana Malik", "Ahmed Ali"), start=1):
            self.store.add_check({"created_at": H.now().strftime(H.TIME_FORMAT), "checked_by": "Bader",
                                  "candidate": name, "file_name": f"{name}.pdf", "score": 48, "label": "At risk",
                                  "with_job": 0, "parts": {}, "issues": [], "review_reasons": ["Score under 55"]},
                                 b"%PDF-1.4 fake" + bytes([n]))
        self.store.log("Bader", "check", "Sana Malik", "General check")


class TestClearButtons(StoreCase):
    """History, Needs review and the Activity log each get their own Clear button - and nothing else moves."""

    def test_clearing_the_history_removes_the_checks_and_their_files(self):
        self.two_checks_and_a_log()
        self.store.save_setting("file_days", 30, "Bader")
        gone = self.store.clear_checks()
        self.assertEqual(2, gone["checks"])
        self.assertEqual(2, gone["files"])
        self.assertEqual([], self.store.history())
        self.assertEqual([], self.store.needs_review())
        self.assertEqual(0, len(os.listdir(self.store.files)))
        self.assertEqual("30", self.store.saved_settings()["file_days"])    # the settings stay

    def test_clearing_the_history_keeps_the_activity_log(self):
        self.two_checks_and_a_log()
        self.store.clear_checks()
        self.assertEqual(1, len(self.store.activity()))

    def test_clearing_the_log_keeps_the_history(self):
        self.two_checks_and_a_log()
        self.assertEqual(1, self.store.clear_log())
        self.assertEqual([], self.store.activity())
        self.assertEqual(2, len(self.store.history()))

    def test_the_next_check_starts_at_one_again(self):
        self.two_checks_and_a_log()
        self.store.clear_checks()
        cid = self.store.add_check({"created_at": H.now().strftime(H.TIME_FORMAT), "checked_by": "Bader",
                                    "candidate": "New Person", "file_name": "New.pdf", "score": 70, "label": "Good",
                                    "with_job": 0, "parts": {}, "issues": [], "review_reasons": []})
        self.assertEqual(1, cid)

    def test_the_texts_the_page_needs_exist(self):
        for key in ("clear_history", "clear_history_ask", "clear_history_yes", "clear_history_done", "clear_review",
                    "clear_review_ask", "clear_review_yes", "clear_review_done", "clear_log", "clear_log_ask",
                    "clear_log_yes", "clear_log_done", "cancel"):
            self.assertIn(key, T.ADMIN_TEXT)
        for key in ("clear_history", "clear_log", "review_bulk"):
            self.assertIn(key, T.LOG_DETAILS)


class TestStayingSignedIn(StoreCase):
    """The password is typed once: a random token in the browser's cookie keeps the admin signed in."""

    def test_a_token_brings_the_admin_back(self):
        self.store.remember_admin("a" * 32, "Bader")
        self.assertEqual("Bader", self.store.admin_of_token("a" * 32))

    def test_an_unknown_token_says_nothing(self):
        self.assertIsNone(self.store.admin_of_token("b" * 32))
        self.assertIsNone(self.store.admin_of_token(""))
        self.assertIsNone(self.store.admin_of_token(None))

    def test_signing_out_forgets_the_token(self):
        self.store.remember_admin("c" * 32, "Bader")
        self.store.forget_token("c" * 32)
        self.assertIsNone(self.store.admin_of_token("c" * 32))

    def test_a_token_that_is_not_used_for_a_month_ends(self):
        self.store.remember_admin("d" * 32, "Bader")
        old = (H.now() - __import__("datetime").timedelta(days=31)).strftime(H.TIME_FORMAT)
        self.store._run("UPDATE admin_sessions SET seen_at = ? WHERE token = ?", (old, "d" * 32))
        self.assertIsNone(self.store.admin_of_token("d" * 32))
        self.assertEqual([], self.store._all("SELECT * FROM admin_sessions WHERE token = ?", ("d" * 32,)))

    def test_a_reset_of_the_data_keeps_the_sign_in(self):
        self.store.remember_admin("e" * 32, "Bader")
        self.two_checks_and_a_log()
        self.store.clear_data()
        self.assertEqual("Bader", self.store.admin_of_token("e" * 32))

    def test_sign_everywhere_out(self):
        self.store.remember_admin("f" * 32, "Bader")
        self.store.remember_admin("0" * 32, "Bader")
        self.assertEqual(2, self.store.forget_all_tokens())
        self.assertIsNone(self.store.admin_of_token("f" * 32))


class TestTheMatcherInAGeneralCheck(unittest.TestCase):
    """Without a job description the Resume Matcher reads the skills the resume's own role expects."""

    def setUp(self):
        self.res = {"cv": "Sana Malik.pdf", "target": "Senior Program Manager", "mode": "role", "parts": {},
                    "_doc": {"modern": "Senior Program Manager. Program management, risk management, stakeholder "
                                       "management and budgeting for large programmes."}}

    def test_it_reads_the_role_skills_when_there_is_no_job(self):
        real = SO.role_words
        SO.role_words = lambda role, limit=40: ["program management", "risk management", "budgeting"]
        try:
            words, source, role = SO.matcher_words(self.res, "", self.res["target"])
        finally:
            SO.role_words = real
        self.assertEqual("role", source)
        self.assertEqual("Senior Program Manager", role)
        self.assertEqual(["program management", "risk management", "budgeting"], words)

    def test_it_reads_the_job_words_when_there_is_a_job(self):
        words, source, role = SO.matcher_words(self.res, "We need program management and budgeting skills.", None)
        self.assertEqual("job", source)
        self.assertEqual("", role)
        self.assertIn("budgeting", [w.lower() for w in words])

    def test_a_check_with_a_job_keeps_its_comparison(self):
        answer = SO.finish("matcher", {"parts": {"job_match": 70}, "score": 66},
                           {"state": SO.DONE, "score": 72, "source": "job"})
        self.assertEqual(70, answer["reference"])
        self.assertEqual("Agrees", answer["word"])

    def test_a_general_check_has_nothing_to_compare_with(self):
        answer = SO.finish("matcher", {"parts": {}, "score": 66},
                           {"state": SO.DONE, "score": 72, "source": "role"})
        self.assertIsNone(answer["reference"])
        self.assertIsNone(answer["agree"])
        self.assertEqual("", answer["difference"])

    def test_the_headline_only_counts_real_comparisons(self):
        answers = {"matcher": {"state": SO.DONE, "agree": None}, "checker2": {"state": SO.DONE, "agree": True}}
        self.assertEqual("1 of 1 checker agree with the Lab", SO.headline(answers))
        answers = {"matcher": {"state": SO.DONE, "agree": None}, "checker2": {"state": SO.DONE, "agree": None}}
        self.assertEqual("", SO.headline(answers))

    def test_a_role_that_cannot_be_read_says_needs_a_job_description(self):
        out = SO.run("matcher", {"cv": "x.pdf", "target": "", "mode": "role", "_doc": {"modern": "text"}}, "",
                     {"matcher": True, "checker2": True})
        self.assertEqual(SO.NEEDS_JOB, out["state"])


class TestTheExplanationLines(unittest.TestCase):
    """Every card says what it read, so the number is never a mystery."""

    def test_the_texts_exist(self):
        for key in ("read_job", "read_role", "read_checks", "weakest", "no_reference", "skills", "skills_line",
                    "missing_skills"):
            self.assertIn(key, T.SECOND_TEXT)

    def test_the_card_line_names_the_role_and_the_checks(self):
        import admin_page as A
        line = A.read_line("matcher", {"source": "role", "role": "Senior Program Manager"})
        self.assertIn("Senior Program Manager", line)
        line = A.read_line("matcher", {"source": "job"})
        self.assertIn("job description", line)
        line = A.read_line("checker2", {"checks": [{"name": "One column", "passed": True},
                                                   {"name": "Bullets", "passed": False}]})
        self.assertIn("1 of 2", line)


class TestTheReportDocumentIsBuiltOnce(unittest.TestCase):
    """A click on the page must not rebuild the report document (that was 0.6-0.8 s per click)."""

    def test_the_document_is_kept_for_the_session(self):
        import dashboard as D
        calls = []
        real = D.report_document
        D.report_document = lambda r, cards: (calls.append(1), "<html>report</html>")[1]
        try:
            cache = {}
            r = {"_uid": "abc123"}
            first = D.report_doc_of(r, [], cache)
            second = D.report_doc_of(r, [], cache)
        finally:
            D.report_document = real
        self.assertEqual(first, second)
        self.assertEqual(1, len(calls))

    def test_a_result_without_an_id_still_works(self):
        import dashboard as D
        calls = []
        real = D.report_document
        D.report_document = lambda r, cards: (calls.append(1), "<html>one</html>")[1]
        try:
            doc = D.report_doc_of({"cv": "x.pdf"}, [], {})
            again = D.report_doc_of({"cv": "x.pdf"}, [], {})
        finally:
            D.report_document = real
        self.assertEqual("<html>one</html>", doc)
        self.assertEqual(doc, again)
        self.assertEqual(2, len(calls))          # no id: built every time (never a stale report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
