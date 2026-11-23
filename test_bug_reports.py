"""
Tests for the bug reports (lab_bugs.py) and the Bug audit page.

What must always hold:
  - the page is registered once, Admin only, and its menu entry carries the new-bug count;
  - the storage round trip works: report, screenshot, AI text, decision, fix checklist, cleanup;
  - a screenshot is only accepted when it is a real image of a sensible size;
  - a screenshot lives while the bug is open, then `bug_image_days` days after Fixed/Rejected, then it is
    deleted and only the text stays;
  - the AI receives the screenshot, the sentence and the Lab's own result text - never the resume;
  - the AI can never change the score, a weight, a threshold or the state of a bug by itself;
  - a fix may only reach a score after every checklist step is recorded.

No real resume and no real screenshot is used: every file in this test is generated, and the AI call is
faked (no network, no API key needed).

  py -3.12 -m unittest test_bug_reports -v
"""

import base64
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

import lab_bugs as BG
import lab_settings as S
import lab_store as H
import lab_text as T

PNG = b"\x89PNG\r\n\x1a\n" + b"generated-screenshot-bytes" * 20      # not a real image: only stored and read back
MIME = "image/png"

# The Lab's own result, exactly as the report page builds it. No resume text is in here.
RESULT = {"score": 71.5, "label": "Needs work", "parts": {"readable": 80, "findable": 60, "matched": 70},
          "target": "Senior Project Manager", "_uid": "abc123", "cv": "Generated_CV.pdf",
          "issues": [{"name": "No email", "severity": "Critical", "why": "The resume has no email address."},
                     {"name": "Dates missing", "severity": "Major", "why": "One job has no dates."}]}


class FakeResponse:
    def __init__(self, body, status=200):
        self.status_code, self._body = status, body

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeRequests:
    """A stand-in for the requests module: no network, and it records what was sent."""

    def __init__(self, body=None, status=200):
        self.body, self.status, self.sent = body, status, None

    def post(self, url, headers=None, json=None, timeout=None):
        self.sent = {"url": url, "json": json, "timeout": timeout}
        return FakeResponse(self.body, self.status)


def ai_body(text):
    return {"choices": [{"message": {"content": text}}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.store = H.Store(self.folder)
        self.saved_key = os.environ.pop("OPENROUTER_API_KEY", None)
        self.saved_requests = sys.modules.get("requests")
        self.addCleanup(self._tidy)

    def _tidy(self):
        sys.modules.pop("requests", None)
        if self.saved_requests is not None:
            sys.modules["requests"] = self.saved_requests
        os.environ.pop("OPENROUTER_API_KEY", None)      # never leave a fake key behind for another test
        if self.saved_key is not None:
            os.environ["OPENROUTER_API_KEY"] = self.saved_key
        shutil.rmtree(self.folder, ignore_errors=True)

    def fake_requests(self, body=None, status=200):
        fake = FakeRequests(body, status)
        sys.modules["requests"] = fake
        return fake

    def add(self, description="The score looks wrong", with_image=True, score=71.5):
        return self.store.add_bug({"who": "Bader", "kind": "bug", "description": description,
                                   "check_id": "abc123", "cv": "Generated_CV.pdf",
                                   "target": "Senior Project Manager", "score": score,
                                   "report": BG.result_text(RESULT)},
                                  screenshot=PNG if with_image else None, mime=MIME if with_image else "")


class TestRegistration(Base):
    def test_menu_entry_and_order(self):
        self.assertEqual(T.NAV["bugs"][0], "Bug audit")
        self.assertEqual(list(T.NAV).index("bugs"), list(T.NAV).index("review") + 1)

    def test_the_view_is_in_the_dispatch(self):
        import admin_page as A
        self.assertTrue(callable(A.bugs_view))
        self.assertIn("bugs", A.VIEWS)
        self.assertIn('"bugs": bugs_view', io.open("admin_page.py", encoding="utf-8").read())

    def test_the_setting_exists(self):
        self.assertEqual(S.SETTINGS["bug_image_days"][1], 30)
        self.assertEqual(S.LIMITS["bug_image_days"], (1, 3650))
        self.assertIn("bug_image_days", T.SETTINGS_TEXT)

    def test_the_activity_log_knows_a_bug(self):
        self.assertIn("bug", T.LOG_KINDS)

    def test_every_text_the_page_uses_exists(self):
        page = io.open("admin_page.py", encoding="utf-8").read()
        keys = set()
        for piece in page.split('T.BUG_TEXT["')[1:]:
            key = piece.split('"')[0]
            if key and not key.endswith("_"):        # "state_" is built as T.BUG_TEXT["state_" + state]
                keys.add(key)
        missing = sorted(k for k in keys if k not in T.BUG_TEXT)
        self.assertEqual(missing, [])

    def test_the_menu_count(self):
        import admin_page as A
        self.assertEqual(A.nav_badge("bugs", 0), "")
        self.assertIn('content: "3"', A.nav_badge("bugs", 3))
        self.assertIn(".st-key-nav_bugs", A.nav_css("bugs", 0, 3))
        self.assertIn('content: "3"', A.nav_css("bugs", 0, 3))
        self.assertNotIn('content: "3"', A.nav_css("bugs", 0, 0))

    def test_the_checklist_matches_the_page(self):
        import admin_page as A
        self.assertEqual(sorted(A.BUG_STEP_COLUMNS), sorted(k for k, _ in BG.FIX_STEPS))


class TestImageRules(unittest.TestCase):
    def test_a_png_is_accepted(self):
        self.assertEqual(BG.allowed_image("image/png", 1000), (True, ""))

    def test_a_jpeg_is_accepted(self):
        self.assertEqual(BG.allowed_image("image/jpeg", 1000), (True, ""))

    def test_other_files_are_refused(self):
        self.assertEqual(BG.allowed_image("application/pdf", 1000), (False, "type"))
        self.assertEqual(BG.allowed_image("", 1000), (False, "type"))

    def test_an_empty_file_is_refused(self):
        self.assertEqual(BG.allowed_image("image/png", 0), (False, "empty"))

    def test_a_huge_file_is_refused(self):
        self.assertEqual(BG.allowed_image("image/png", BG.MAX_IMAGE_MB * 1024 * 1024 + 1), (False, "big"))
        self.assertEqual(BG.allowed_image("image/png", BG.MAX_IMAGE_MB * 1024 * 1024), (True, ""))


class TestStorage(Base):
    def test_the_round_trip(self):
        bid = self.add()
        self.assertTrue(bid)
        rows = self.store.bugs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["has_image"], 1)          # the list says an image exists...
        self.assertNotIn("screenshot", rows[0])            # ...but never carries it
        self.assertEqual(self.store.bug_image(bid), (PNG, MIME))
        self.assertIn("ATS Lab score: 71.5", self.store.bug(bid)["report"])
        self.assertEqual(self.store.new_bugs(), 1)

    def test_a_report_without_a_screenshot(self):
        bid = self.add(with_image=False)
        self.assertEqual(self.store.bugs()[0]["has_image"], 0)
        self.assertEqual(self.store.bug_image(bid), (None, ""))

    def test_the_ai_text_is_stored(self):
        bid = self.add()
        self.store.set_bug_ai(bid, {"model": BG.MODEL, "explanation": "Because the date rule reads the line.",
                                    "fix": "Read only the job's own date line."})
        row = self.store.bug(bid)
        self.assertEqual(row["ai_explanation"], "Because the date rule reads the line.")
        self.assertEqual(row["ai_fix"], "Read only the job's own date line.")
        self.assertEqual(row["ai_model"], BG.MODEL)
        self.assertEqual(row["ai_error"], "")

    def test_a_failed_ai_answer_is_stored_as_text(self):
        bid = self.add()
        self.store.set_bug_ai(bid, {"error": "http", "why": "status 429"})
        self.assertEqual(self.store.bug(bid)["ai_error"], "http")
        self.assertEqual(self.store.bug(bid)["ai_explanation"], "")

    def test_the_decision(self):
        bid = self.add()
        self.store.set_bug_state(bid, BG.APPROVED, "Bader", "Real bug")
        row = self.store.bug(bid)
        self.assertEqual(row["state"], BG.APPROVED)
        self.assertEqual(row["state_who"], "Bader")
        self.assertEqual(row["note"], "Real bug")
        self.assertTrue(row["state_when"])
        self.assertEqual(self.store.new_bugs(), 0)

    def test_the_fix_checklist(self):
        bid = self.add()
        self.assertFalse(BG.ready_for_score(self.store.bug(bid)))
        self.store.set_bug_step(bid, "fix")
        self.assertEqual([done for _, done in BG.checklist(self.store.bug(bid))], [True, False, False])
        self.assertFalse(BG.ready_for_score(self.store.bug(bid)))
        self.store.set_bug_step(bid, "golden")
        self.store.set_bug_step(bid, "reference")
        self.assertTrue(BG.ready_for_score(self.store.bug(bid)))

    def test_delete_and_clear(self):
        bid = self.add()
        self.store.delete_bug(bid)
        self.assertEqual(self.store.bugs(), [])
        self.add()
        self.add()
        self.store.clear_bugs()
        self.assertEqual(self.store.bugs(), [])
        self.assertEqual(self.store.new_bugs(), 0)

    def test_the_newest_is_first(self):
        first = self.add("First")
        second = self.add("Second")
        self.assertEqual([b["id"] for b in self.store.bugs()], [second, first])


class TestRetention(Base):
    def closed_days_ago(self, days):
        bid = self.add()
        when = H.now() - H.dt.timedelta(days=days)
        self.store.set_bug_state(bid, BG.FIXED, "Bader", when=when)
        return bid

    def test_an_open_bug_keeps_its_screenshot(self):
        bid = self.add()
        row = self.store.bug(bid)
        self.assertIsNone(BG.keep_until(row, 30))
        self.assertFalse(BG.image_due(row, 30))
        self.assertEqual(self.store.cleanup_bug_images(30), 0)
        self.assertEqual(self.store.bug_image(bid)[0], PNG)

    def test_the_delete_day_is_the_close_day_plus_the_setting(self):
        bid = self.closed_days_ago(10)
        row = self.store.bug(bid)
        self.assertTrue(BG.keep_until(row, 30))
        self.assertFalse(BG.image_due(row, 30))
        self.assertTrue(BG.image_due(row, 5))

    def test_the_screenshot_goes_and_the_text_stays(self):
        bid = self.closed_days_ago(40)
        self.assertEqual(self.store.cleanup_bug_images(30), 1)
        self.assertEqual(self.store.bug_image(bid), (None, ""))
        row = self.store.bug(bid)
        self.assertEqual(row["has_image"], 0)
        self.assertIn("The score looks wrong", row["description"])      # the text is still there
        self.assertIn("ATS Lab score: 71.5", row["report"])

    def test_the_setting_is_what_decides(self):
        bid = self.closed_days_ago(40)
        self.assertEqual(self.store.cleanup_bug_images(60), 0)
        self.assertEqual(self.store.bug_image(bid)[0], PNG)

    def test_a_rejected_bug_is_treated_the_same(self):
        bid = self.add()
        self.store.set_bug_state(bid, BG.REJECTED, "Bader", when=H.now() - H.dt.timedelta(days=31))
        self.assertEqual(self.store.cleanup_bug_images(30), 1)

    def test_an_approved_bug_keeps_its_screenshot(self):
        bid = self.add()
        self.store.set_bug_state(bid, BG.APPROVED, "Bader", when=H.now() - H.dt.timedelta(days=90))
        self.assertEqual(self.store.cleanup_bug_images(30), 0)


class TestResultText(unittest.TestCase):
    def test_it_carries_the_score_the_parts_and_the_issues(self):
        text = BG.result_text(RESULT)
        self.assertIn("ATS Lab score: 71.5 (Needs work)", text)
        self.assertIn("readable 80", text)
        self.assertIn("Senior Project Manager", text)
        self.assertIn("No email", text)

    def test_it_never_carries_the_resume(self):
        res = dict(RESULT, _doc={"modern": "MY WHOLE RESUME TEXT"})
        self.assertNotIn("MY WHOLE RESUME", BG.result_text(res))

    def test_an_empty_result_is_still_text(self):
        self.assertIn("ATS Lab score", BG.result_text({}))
        self.assertIn("No issues were listed.", BG.result_text({"score": 50}))

    def test_it_stays_short(self):
        many = [{"name": f"Issue {i}", "why": "x" * 300} for i in range(200)]
        self.assertLessEqual(len(BG.result_text(dict(RESULT, issues=many))), 6000)


class TestAiCall(Base):
    def test_no_key_is_a_plain_answer(self):
        answer = BG.ask_ai(PNG, MIME, "wrong score", BG.result_text(RESULT))
        self.assertEqual(answer["error"], "no_key")

    def test_no_screenshot_is_a_plain_answer(self):
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        self.assertEqual(BG.ask_ai(b"", MIME, "wrong score", "result")["error"], "no_image")

    def test_a_good_answer_is_parsed(self):
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        body = ai_body('```json\n{"explanation": "The date rule read the education year.", '
                       '"fix": "Read only the job line.", "area": "Scoring", "score_change_needed": false, '
                       '"lab_was_right": true}\n```')
        self.fake_requests(body)
        answer = BG.ask_ai(PNG, MIME, "wrong score", BG.result_text(RESULT))
        self.assertEqual(answer["explanation"], "The date rule read the education year.")
        self.assertEqual(answer["fix"], "Read only the job line.")
        self.assertEqual(answer["area"], "scoring")
        self.assertFalse(answer["score_change_needed"])
        self.assertTrue(answer["lab_was_right"])
        self.assertEqual(answer["model"], BG.MODEL)
        self.assertIn("seconds", answer)
        self.assertNotIn("error", answer)

    def test_the_resume_is_never_sent(self):
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        fake = self.fake_requests(ai_body('{"explanation": "x", "fix": "y"}'))
        res = dict(RESULT, _doc={"modern": "MY WHOLE RESUME TEXT"})
        BG.ask_ai(PNG, MIME, "The score looks wrong", BG.result_text(res))
        sent = json.dumps(fake.sent["json"])
        self.assertIn("ATS Lab score: 71.5", sent)              # the Lab's own result: yes
        self.assertIn("The score looks wrong", sent)            # the sentence: yes
        self.assertIn(base64.b64encode(PNG).decode("ascii"), sent)   # the screenshot: yes
        self.assertNotIn("MY WHOLE RESUME", sent)               # the resume: never
        self.assertEqual(fake.sent["json"]["messages"][0]["content"][1]["type"], "image_url")

    def test_a_broken_answer_is_not_a_crash(self):
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        self.fake_requests(ai_body("I am not JSON at all"))
        self.assertEqual(BG.ask_ai(PNG, MIME, "x", "y")["error"], "bad_answer")

    def test_a_bad_status_is_not_a_crash(self):
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        self.fake_requests(ai_body(None), status=500)
        answer = BG.ask_ai(PNG, MIME, "x", "y")
        self.assertEqual(answer["error"], "http")
        self.assertIn("500", answer["why"])

    def test_no_network_is_not_a_crash(self):
        os.environ["OPENROUTER_API_KEY"] = "test-key"

        class Boom:
            def post(self, *a, **k):
                raise OSError("no line")

        sys.modules["requests"] = Boom()
        answer = BG.ask_ai(PNG, MIME, "x", "y")
        self.assertEqual(answer["error"], "OSError")
        self.assertIn("could not be reached", answer["why"])

    def test_a_missing_requests_module_is_not_a_crash(self):
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        sys.modules["requests"] = None
        answer = BG.ask_ai(PNG, MIME, "x", "y")
        self.assertIn("error", answer)


class TestTheAiNeverChangesTheScore(Base):
    def test_the_module_does_not_import_any_scoring_code(self):
        source = io.open("lab_bugs.py", encoding="utf-8").read()
        for name in ("import cv_score", "import dashboard", "import ATSLab", "import cv_layout", "import lab_pages"):
            self.assertNotIn(name, source)

    def test_the_module_never_writes_a_score(self):
        source = io.open("lab_bugs.py", encoding="utf-8").read()
        self.assertNotIn("score =", source.replace("score_change_needed", "").replace("score_change", ""))
        self.assertNotIn("UPDATE", source)

    def test_the_answer_carries_no_score_to_apply(self):
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        self.fake_requests(ai_body('{"explanation": "x", "fix": "y", "score": 99}'))
        answer = BG.ask_ai(PNG, MIME, "x", "y")
        self.assertNotIn("score", answer)

    def test_storing_an_ai_answer_leaves_the_score_and_the_state_alone(self):
        bid = self.add(score=71.5)
        self.store.set_bug_ai(bid, {"model": BG.MODEL, "explanation": "x", "fix": "y"})
        row = self.store.bug(bid)
        self.assertEqual(row["score"], 71.5)
        self.assertEqual(row["state"], BG.NEW)
        self.assertEqual(row["fixed_ok"], 0)

    def test_a_report_never_touches_the_lab_result(self):
        res = {"score": 71.5, "parts": {"matched": 70}, "_doc": {"modern": "RESUME"}}
        before = repr(res)
        BG.result_text(res)
        BG.find(self.store.bugs(), None, "x")
        self.assertEqual(repr(res), before)


class TestFilters(Base):
    def test_the_state_filter(self):
        a = self.add("Alpha bug")
        b = self.add("Beta bug")
        self.store.set_bug_state(b, BG.REJECTED, "Bader")
        rows = self.store.bugs()
        self.assertEqual([x["id"] for x in BG.find(rows, BG.NEW)], [a])
        self.assertEqual([x["id"] for x in BG.find(rows, BG.REJECTED)], [b])
        self.assertEqual(len(BG.find(rows, None)), 2)

    def test_the_search_filter(self):
        self.add("Alpha bug")
        self.add("Beta bug")
        rows = self.store.bugs()
        self.assertEqual(len(BG.find(rows, None, "alpha")), 1)
        self.assertEqual(len(BG.find(rows, None, "Generated_CV")), 2)
        self.assertEqual(len(BG.find(rows, None, "nothing here")), 0)

    def test_an_empty_filter_shows_everything(self):
        self.add()
        self.assertEqual(len(BG.find(self.store.bugs(), None, "")), 1)

    def test_the_state_of_a_missing_or_odd_state(self):
        self.assertEqual(BG.state_of({}), BG.NEW)
        self.assertEqual(BG.state_of({"state": "nonsense"}), BG.NEW)
        self.assertEqual(BG.state_of({"state": BG.FIXED}), BG.FIXED)

    def test_the_summary(self):
        a = self.add()
        b = self.add()
        c = self.add()
        self.store.set_bug_state(a, BG.APPROVED, "Bader")
        self.store.set_bug_state(b, BG.FIXED, "Bader")
        self.store.set_bug_state(c, BG.REJECTED, "Bader")
        counts = BG.summary(self.store.bugs())
        self.assertEqual(counts[BG.NEW], 0)
        self.assertEqual(counts[BG.APPROVED], 1)
        self.assertEqual(counts[BG.FIXED], 1)
        self.assertEqual(counts[BG.REJECTED], 1)
        self.assertEqual(BG.new_count([]), 0)

    def test_a_bug_nobody_decided_counts_as_new(self):
        self.assertEqual(BG.new_count([{}, {"state": None}, {"state": BG.NEW}]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
