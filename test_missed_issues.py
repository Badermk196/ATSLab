"""
Two things on the Admin page (no scoring is involved; v1.5 stays frozen):

1. "Please upload a resume first" although a resume was uploaded. Streamlit forgets an uploader's file whenever the
   page runs without drawing that uploader (ticking the client report switch, the calm "Checking..." page that
   replaces the form, another menu item). The Admin page now keeps the file for the session (slot_file) and a failed
   check goes back to the form with the message and the file still there.

2. Two kinds of feedback in "Report a bug": "The Lab got something wrong" (a Lab bug) and "The Lab missed a problem
   in the resume" (a missed issue). The Bug audit page shows two lists. An approved missed issue never changes a
   score: it is a request for a new check.

  py -3.12 -m unittest test_missed_issues -v
"""

import base64
import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ["ATSLAB_AI_REVIEW"] = "0"
os.environ.pop("OPENROUTER_API_KEY", None)

from streamlit.testing.v1 import AppTest

import admin_page as A
import lab_bugs as BG
import lab_store as H
import lab_text as T

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
PDF_BYTES = b"%PDF-1.4 a resume"
RESULT = {"score": 71.5, "label": "Good", "parts": {"readability": 80}, "issues": [], "target": "PM",
          "_doc": {"modern": "MY WHOLE RESUME TEXT"}}


# ---------------------------------------------------------------------------
# pages drawn alone (an AppTest page runs apart: it imports what it needs)
# ---------------------------------------------------------------------------
def form_page():
    import admin_page as A
    import dashboard as D
    import streamlit as st
    st.session_state["run_no"] = st.session_state.get("run_no", 0) + 1      # as admin_body does at every run
    out = A.check_form(D.WITHOUT_JOB)
    st.write(f"OUT [{out['name']}] {len(out['pdf'])}" if out else "OUT none")


def failed_check_page():
    """The whole Check page when the calm "Checking..." run has an empty file."""
    import admin_page as A
    A.check_view("Tester")


def error_page():
    import dashboard as D
    import streamlit as st
    st.session_state["check_error"] = "an old message"
    D.check_and_store({"pdf": b"", "name": "", "with_job": False, "text": "", "job_title": ""})
    st.write("ERR", st.session_state.get("check_error"))


def bugs_page():
    import admin_page as A
    A.bugs_view("Tester")


def report_page():
    import admin_page as A
    A.report_bug_control({"res": {"cv": "Swvl.pdf", "_uid": "u1"}}, "Tester")


def save_page():
    import admin_page as A
    import streamlit as st
    A.BG.ask_ai = lambda image, mime, words, result, **kw: {
        "explanation": "E", "fix": "F", "model": "m", "kind_seen": kw.get("kind")}
    bid = A.bug_save({"cv": "Swvl.pdf", "_uid": "u1", "score": 91.6}, "Tester", "no bullets", b"png", "image/png",
                     "missed")
    row = A.store().bug(bid)
    st.write(f"SAVED {row['kind']} {row['state']} {row['score']}")


def text_of(at):
    return " | ".join(str(m.value) for m in list(at.markdown) + list(at.caption) + list(at.info) + list(at.error))


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.old = os.environ.get("ATSLAB_DATA_DIR")
        os.environ["ATSLAB_DATA_DIR"] = self.folder
        os.environ["ATSLAB_LOCAL_DB"] = "1"
        self.addCleanup(self._tidy)

    def _tidy(self):
        if self.old is None:
            os.environ.pop("ATSLAB_DATA_DIR", None)
        else:
            os.environ["ATSLAB_DATA_DIR"] = self.old
        shutil.rmtree(self.folder, ignore_errors=True)

    def store(self):
        return A.store()


# ---------------------------------------------------------------------------
# 1. the uploaded file is not lost
# ---------------------------------------------------------------------------
class TestTheUploadedFileIsKept(unittest.TestCase):
    def run_button(self, at):
        return next(b for b in at.button if b.label == A.ADMIN_TEXT["run"])

    def test_a_kept_file_is_used_when_the_check_runs(self):
        at = AppTest.from_function(form_page, default_timeout=300)
        at.session_state["kept_upload_0"] = ("cv.pdf", PDF_BYTES)
        at.run()
        self.assertFalse(at.exception, at.exception)
        self.assertIn("cv.pdf", text_of(at))                                  # the page says which file it uses
        self.run_button(at).click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertIn(f"OUT [cv.pdf] {len(PDF_BYTES)}", text_of(at))

    def test_the_file_survives_the_client_report_switch(self):
        at = AppTest.from_function(form_page, default_timeout=300)
        at.session_state["kept_upload_0"] = ("cv.pdf", PDF_BYTES)
        at.session_state["client_0"] = True                                   # the single uploader is not drawn
        at.run()
        self.assertFalse(at.exception, at.exception)
        at.session_state["client_0"] = False                                  # ... and is drawn again, empty
        at.run()
        self.run_button(at).click().run()
        self.assertIn(f"OUT [cv.pdf] {len(PDF_BYTES)}", text_of(at))

    def test_a_file_the_visitor_removed_is_not_used(self):
        at = AppTest.from_function(form_page, default_timeout=300)
        at.session_state["kept_upload_0"] = ("cv.pdf", PDF_BYTES)
        at.session_state["slot_state"] = {"upload_0": (4, True)}              # it held a file on the run before ...
        at.session_state["run_no"] = 4                                        # ... and now (run 5) it is empty: the X
        at.run()
        self.assertNotIn("kept_upload_0", at.session_state)
        self.run_button(at).click().run()
        self.assertIn("OUT [] 0", text_of(at))                                # no file: nothing is passed on

    def test_a_restored_file_stays_through_the_next_runs(self):
        """The first run after the file was lost draws an empty uploader: that is not the visitor pressing the X."""
        at = AppTest.from_function(form_page, default_timeout=300)
        at.session_state["kept_upload_0"] = ("cv.pdf", PDF_BYTES)
        at.run()
        at.run()
        at.run()
        self.assertEqual(at.session_state["kept_upload_0"], ("cv.pdf", PDF_BYTES))
        self.run_button(at).click().run()
        self.assertIn(f"OUT [cv.pdf] {len(PDF_BYTES)}", text_of(at))

    def test_a_new_check_starts_without_the_old_file(self):
        at = AppTest.from_function(form_page, default_timeout=300)
        at.session_state["kept_upload_0"] = ("cv.pdf", PDF_BYTES)
        at.session_state["upload_round"] = 1                                  # "New check" starts a new round
        at.run()
        self.assertNotIn("Using the file you added before", text_of(at))

    def test_a_failed_check_keeps_its_message(self):
        at = AppTest.from_function(error_page, default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        text = text_of(at)
        self.assertIn("ERR Please upload a resume first.", text)             # the new message replaced the old one
        self.assertNotIn("an old message", text)


class TestAFailedCheckGoesBackToTheForm(StoreCase):
    def test_the_message_and_the_file_are_on_the_form_after_a_failed_check(self):
        at = AppTest.from_function(failed_check_page, default_timeout=300)
        at.session_state["admin"] = "Tester"
        at.session_state["kept_upload_0"] = ("cv.pdf", PDF_BYTES)
        # the "Run check" press was made and the calm page is on: the check starts now and fails (no real file)
        at.session_state["pending_check"] = {"pdf": b"", "name": "", "with_job": False, "text": "", "job_title": ""}
        at.session_state["pending_ready"] = True
        at.run()
        self.assertFalse(at.exception, at.exception)
        self.assertTrue(at.get("file_uploader"), "the form is back")
        text = text_of(at)
        self.assertIn("Please upload a resume first.", text)
        self.assertIn("Using the file you added before: cv.pdf", text)
        self.assertNotIn("pending_check", at.session_state)


# ---------------------------------------------------------------------------
# 2. the two kinds of feedback
# ---------------------------------------------------------------------------
def ai_body(content):
    return {"choices": [{"message": {"content": content}}]}


class FakeResponse:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


class FakeRequests:
    def __init__(self, body):
        self.body, self.sent = body, {}

    def post(self, url, headers=None, json=None, timeout=None):
        self.sent = {"url": url, "json": json}
        return FakeResponse(self.body)


class TestTheKinds(unittest.TestCase):
    def test_the_kind_of_a_report(self):
        self.assertEqual(BG.kind_of({}), BG.KIND_BUG)
        self.assertEqual(BG.kind_of({"kind": "bug"}), BG.KIND_BUG)
        self.assertEqual(BG.kind_of({"kind": None}), BG.KIND_BUG)              # saved before there were two kinds
        self.assertEqual(BG.kind_of({"kind": "missed"}), BG.KIND_MISSED)
        self.assertEqual(BG.kind_of({"kind": "something else"}), BG.KIND_BUG)

    def test_the_lists_and_the_filters(self):
        bugs = [{"id": 1, "kind": "bug", "description": "score", "state": "new"},
                {"id": 2, "kind": "missed", "description": "no bullets under the current job", "state": "new"},
                {"id": 3, "kind": "missed", "description": "other", "state": "approved"},
                {"id": 4, "description": "old report", "state": "fixed"}]
        self.assertEqual([b["id"] for b in BG.of_kind(bugs, BG.KIND_BUG)], [1, 4])
        self.assertEqual([b["id"] for b in BG.of_kind(bugs, BG.KIND_MISSED)], [2, 3])
        self.assertEqual([b["id"] for b in BG.find(bugs, "approved", "", BG.KIND_MISSED)], [3])
        self.assertEqual([b["id"] for b in BG.find(bugs, None, "bullets")], [2])
        self.assertEqual(len(BG.find(bugs)), 4)                                # no kind: everything, as before
        self.assertEqual(BG.summary(bugs, BG.KIND_MISSED)[BG.NEW], 1)
        self.assertEqual(BG.summary(bugs)[BG.NEW], 2)

    def test_the_two_choices_are_worded_as_asked(self):
        self.assertEqual(T.BUG_TEXT["kind_bug"], "The Lab got something wrong")
        self.assertEqual(T.BUG_TEXT["kind_missed"], "The Lab missed a problem in the resume")
        self.assertEqual(T.BUG_TEXT["list_bug"], "Lab bugs")
        self.assertEqual(T.BUG_TEXT["list_missed"], "Missed issues")
        self.assertIn("does not change any score", T.BUG_TEXT["missed_approved"])


class TestAskingTheAiAboutAMissedIssue(unittest.TestCase):
    def setUp(self):
        self.saved = sys.modules.get("requests")
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        self.addCleanup(self._tidy)

    def _tidy(self):
        os.environ.pop("OPENROUTER_API_KEY", None)
        if self.saved is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = self.saved

    def test_the_answer_says_if_it_is_real_how_common_and_how_to_detect_it(self):
        fake = FakeRequests(ai_body('```json\n{"real_problem": true, "why": "A current role with no bullets shows '
                                    'no achievements.", "how_common": "Sometimes: promotions are stacked.", '
                                    '"how_to_detect": "A job with a Present date and no bullet lines before the next '
                                    'job.", "area": "Content"}\n```'))
        sys.modules["requests"] = fake
        answer = BG.ask_ai(PNG, "image/png", "The current role, Director at Swvl, has no bullets",
                           BG.result_text(RESULT), kind=BG.KIND_MISSED)
        self.assertNotIn("error", answer)
        self.assertTrue(answer["explanation"].startswith("Real resume problem: yes."))
        self.assertIn("How common: Sometimes", answer["explanation"])
        self.assertIn("no bullet lines", answer["fix"])
        self.assertEqual(answer["area"], "content")
        self.assertNotIn("score", answer)                                       # nothing to apply to a score
        self.assertFalse(answer["score_change_needed"])

    def test_not_a_real_problem_is_said_plainly(self):
        sys.modules["requests"] = FakeRequests(ai_body('{"real_problem": false, "why": "A style choice.", '
                                                       '"how_common": "Rare.", "how_to_detect": "-"}'))
        answer = BG.ask_ai(PNG, "image/png", "x", "y", kind=BG.KIND_MISSED)
        self.assertTrue(answer["explanation"].startswith("Real resume problem: probably not."))

    def test_the_prompt_is_the_missed_one_and_the_resume_is_never_sent(self):
        fake = FakeRequests(ai_body('{"real_problem": true, "why": "w", "how_common": "c", "how_to_detect": "d"}'))
        sys.modules["requests"] = fake
        BG.ask_ai(PNG, "image/png", "The current role has no bullets", BG.result_text(RESULT), kind=BG.KIND_MISSED)
        sent = json.dumps(fake.sent["json"])
        self.assertIn("MISSED a problem", sent)                                 # the missed-issue prompt
        self.assertIn("NO points", sent)                                        # a card first, never a score
        self.assertIn("The current role has no bullets", sent)                  # the sentence: yes
        self.assertIn("ATS Lab score: 71.5", sent)                              # the Lab's own result: yes
        self.assertIn(base64.b64encode(PNG).decode("ascii"), sent)              # the screenshot: yes
        self.assertNotIn("MY WHOLE RESUME", sent)                               # the resume: never

    def test_a_lab_bug_still_uses_the_old_prompt(self):
        fake = FakeRequests(ai_body('{"explanation": "x", "fix": "y"}'))
        sys.modules["requests"] = fake
        BG.ask_ai(PNG, "image/png", "wrong score", "result")                    # no kind: a Lab bug, as before
        sent = json.dumps(fake.sent["json"])
        self.assertNotIn("MISSED a problem", sent)
        self.assertIn("reported a problem", sent)


class TestTheReportBox(StoreCase):
    def test_the_box_offers_the_two_choices(self):
        at = AppTest.from_function(report_page, default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        radio = at.radio[0]
        self.assertEqual(list(radio.options), [T.BUG_TEXT["kind_bug"], T.BUG_TEXT["kind_missed"]])
        self.assertEqual(radio.value, T.BUG_TEXT["kind_bug"])                   # a Lab bug works as it always did
        self.assertEqual(at.text_input[0].label, T.BUG_TEXT["sentence"])
        self.assertEqual([b.label for b in at.button], [T.BUG_TEXT["send"]])

    def test_a_missed_issue_asks_what_the_lab_should_have_caught(self):
        at = AppTest.from_function(report_page, default_timeout=300).run()
        at.radio[0].set_value(T.BUG_TEXT["kind_missed"]).run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(at.text_input[0].label, T.BUG_TEXT["sentence_missed"])
        self.assertIn("Director at Swvl, has no bullets", at.text_input[0].placeholder)
        self.assertIn("never sent", text_of(at))
        self.assertEqual([b.label for b in at.button], [T.BUG_TEXT["send_missed"]])

    def test_a_missed_issue_is_saved_with_its_kind_and_leaves_the_score_alone(self):
        at = AppTest.from_function(save_page, default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        self.assertIn("SAVED missed new 91.6", text_of(at))                     # kind, state, the Lab's own score


class TestTheBugAuditPage(StoreCase):
    def seed(self):
        store = self.store()
        ids = {}
        for kind, words in (("bug", "The score looks wrong"), ("missed", "The current job has no bullets")):
            ids[kind] = store.add_bug({"who": "Bader", "kind": kind, "description": words, "cv": f"{kind}.pdf",
                                       "score": 91.6, "report": "ATS Lab score: 91.6",
                                       "ai_explanation": "E", "ai_fix": "F"}, screenshot=PNG, mime="image/png")
        return ids

    def test_two_separate_lists_each_with_approve_and_reject(self):
        ids = self.seed()
        at = AppTest.from_function(bugs_page, default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        text = text_of(at)
        self.assertIn(T.BUG_TEXT["list_bug"], text)
        self.assertIn(T.BUG_TEXT["list_missed"], text)
        self.assertLess(text.index(T.BUG_TEXT["list_bug"]), text.index(T.BUG_TEXT["list_missed"]))
        keys = {b.key for b in at.button}
        for bid in ids.values():
            self.assertIn(f"bug_yes_{bid}", keys)
            self.assertIn(f"bug_no_{bid}", keys)
        self.assertIn(f"bug_step_fix_{ids['bug']}", keys)                       # a Lab bug keeps its fix checklist
        self.assertNotIn(f"bug_step_fix_{ids['missed']}", keys)                 # a missed issue has none

    def test_an_approved_missed_issue_is_a_request_for_a_new_check_and_changes_no_score(self):
        ids = self.seed()
        at = AppTest.from_function(bugs_page, default_timeout=300).run()
        next(b for b in at.button if b.key == f"bug_yes_{ids['missed']}").click().run()
        self.assertFalse(at.exception, at.exception)
        row = self.store().bug(ids["missed"])
        self.assertEqual(row["state"], BG.APPROVED)
        self.assertEqual(row["score"], 91.6)                                    # nothing about the score moved
        self.assertEqual((row["fixed_ok"], row["golden_added"], row["reference_passed"]), (0, 0, 0))
        text = text_of(at)
        self.assertIn(T.BUG_TEXT["missed_approved"], text)
        self.assertIn(T.BUG_TEXT["missed_tag"], " ".join(e.label for e in at.expander))
        self.assertEqual(self.store().bug(ids["bug"])["state"], BG.NEW)         # the Lab bug was not touched

    def test_a_report_saved_before_the_two_kinds_is_a_lab_bug(self):
        store = self.store()
        bid = store.add_bug({"who": "Bader", "description": "old", "cv": "old.pdf"}, screenshot=None, mime="")
        at = AppTest.from_function(bugs_page, default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        self.assertIn(f"bug_yes_{bid}", {b.key for b in at.button})
        self.assertIn(T.BUG_TEXT["list_none_missed"], text_of(at))               # the other list says it is empty


if __name__ == "__main__":
    unittest.main()
