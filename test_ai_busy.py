"""The AI service is busy (429/5xx) or does not answer: the Lab asks the same model again, then the fallback model, and
the team sees one plain sentence - never the provider's own answer.

4 Nov 2026: a real check showed the whole OpenRouter answer in the Admin page
("Keyword extraction failed: ERROR from OpenRouter (503): {...\"provider_name\":\"Google AI Studio\"...}").
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ATSLab_v3 as V                                                    # noqa: E402
import dashboard as D                                                    # noqa: E402

GOOD = {"choices": [{"message": {"content": '{"title": "Head of AI & Digital Excellence", "hard_skills": ["Python"]}'}}]}
BUSY = {"error": {"code": 503, "message": "The service is currently unavailable.\nstatus: UNAVAILABLE",
                  "metadata": {"provider_name": "Google AI Studio"}}}
PRIMARY = "google/gemini-2.5-flash"


class FakeAnswer:
    """What requests.post gives back, with as much detail as the real one."""

    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body
        self.text = str(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("this answer has no JSON")
        return self._body


class TestTheAiIsAskedAgain(unittest.TestCase):
    def setUp(self):
        import requests
        self.calls = []
        self.old_post, self.old_wait = requests.post, V.AI_RETRY_WAIT
        V.AI_RETRY_WAIT = 0                     # no waiting in the tests
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        self.addCleanup(self.restore)

    def restore(self):
        import requests
        requests.post = self.old_post
        V.AI_RETRY_WAIT = self.old_wait
        os.environ.pop("OPENROUTER_API_KEY", None)

    def answers(self, *sequence):
        """A stand-in for requests.post: gives the answers in turn, then repeats the last one."""
        import requests

        def post(url, **kw):
            self.calls.append(kw["json"]["model"])
            return sequence[min(len(self.calls) - 1, len(sequence) - 1)]
        requests.post = post

    def test_a_busy_provider_is_asked_again_and_the_answer_is_used(self):
        self.answers(FakeAnswer(503, BUSY), FakeAnswer(503, BUSY), FakeAnswer(200, GOOD))
        out = V.call_ai("the job", PRIMARY)
        self.assertEqual(out["title"], "Head of AI & Digital Excellence")
        self.assertEqual(self.calls, [PRIMARY] * 3)                       # the same model, three tries

    def test_a_provider_that_stays_busy_ends_with_one_plain_sentence(self):
        self.answers(FakeAnswer(503, BUSY))
        with self.assertRaises(SystemExit) as caught:
            V.call_ai("the job", PRIMARY)
        msg = str(caught.exception)
        self.assertEqual(self.calls, [PRIMARY] * (V.AI_RETRIES + 1) + [V.AI_FALLBACK_MODEL] * (V.AI_RETRIES + 1))
        self.assertIn("busy", msg)
        for leak in ("provider_name", "Google AI Studio", "{", "metadata"):  # the provider's own answer stays out
            self.assertNotIn(leak, msg)

    def test_no_answer_at_all_is_asked_again_too(self):
        import requests

        def post(url, **kw):
            self.calls.append(kw["json"]["model"])
            raise requests.ConnectionError("no line")
        requests.post = post
        with self.assertRaises(SystemExit) as caught:
            V.call_ai("the job", PRIMARY)
        self.assertEqual(self.calls, [PRIMARY] * (V.AI_RETRIES + 1) + [V.AI_FALLBACK_MODEL] * (V.AI_RETRIES + 1))
        self.assertIn("no answer", str(caught.exception))

    def test_a_wrong_key_is_not_tried_again(self):
        self.answers(FakeAnswer(401, {"error": {"code": 401, "message": "No auth credentials found"}}))
        with self.assertRaises(SystemExit):
            V.call_ai("the job", PRIMARY)
        self.assertEqual(self.calls, [PRIMARY])                           # one try: another one cannot help

    def test_an_error_inside_a_good_answer_is_treated_as_busy(self):
        self.answers(FakeAnswer(200, {"error": {"code": 503, "message": "upstream is down"}}), FakeAnswer(200, GOOD))
        out = V.call_ai("the job", PRIMARY)
        self.assertEqual(out["title"], "Head of AI & Digital Excellence")
        self.assertEqual(len(self.calls), 2)


class TestTheMessageTheTeamSees(unittest.TestCase):
    def test_a_busy_ai_becomes_one_plain_sentence(self):
        msg = D.message_of_ai_error("ERROR: the AI service is busy or unreachable (503). Nothing was scored - try "
                                    "again in a minute.")
        self.assertEqual(msg, D.AI_BUSY_TEXT)
        for leak in ("provider_name", "Google AI Studio", "{", "metadata", "OpenRouter"):
            self.assertNotIn(leak, msg)

    def test_no_valid_keyword_answer_becomes_the_same_sentence(self):
        self.assertEqual(D.message_of_ai_error("ERROR: the AI gave no valid keyword answer."), D.AI_BUSY_TEXT)

    def test_any_other_lab_message_keeps_its_own_words(self):
        self.assertEqual(D.message_of_ai_error("ERROR: something else"), "Keyword extraction failed: ERROR: something else")


if __name__ == "__main__":
    unittest.main()
