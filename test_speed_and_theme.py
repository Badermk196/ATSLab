"""
Tests for Phase 1 of the speed / look round: the version line, the sun / moon button, the ring number's colour, the
second-opinion cards (ATS Checker 3 and LeverParser hidden), and the speed helpers (kept reads, reused results, the
warm-up, the timing). No scoring is touched here. No AI call, no download: the tests never load the AI model.

  py -3.12 -m unittest test_speed_and_theme -v
"""

import os

os.environ["ATSLAB_AI_REVIEW"] = "0"
os.environ.pop("OPENROUTER_API_KEY", None)
import shutil
import tempfile
import unittest
from unittest import mock

from streamlit.testing.v1 import AppTest

import lab_reuse
import lab_second as SO
import lab_settings as S
import lab_store as H
import lab_timing as TM
import lab_ui as UI
import lab_version as V
import lab_warmup as W


class TestVersionLine(unittest.TestCase):
    def test_the_line_has_a_short_hash_and_a_date(self):
        text = V.line()
        self.assertTrue(text.startswith("Version: "))
        self.assertRegex(text, r"^Version: [0-9a-f]{7,}( · \d{4}-\d{2}-\d{2})?$|^Version: unknown")

    def test_without_git_the_line_says_unknown_and_never_raises(self):
        with mock.patch.object(V, "_CACHE", []), mock.patch.object(V, "_git", side_effect=OSError("no git")), \
                mock.patch.object(V, "_from_git_files", side_effect=OSError("no .git")):
            self.assertIn("unknown", V.line())


class TestRingNumber(unittest.TestCase):
    def test_a_dark_page_gets_white_and_a_light_page_dark(self):
        dark, light = UI.ring_css("dark"), UI.ring_css("light")
        self.assertIn("#FFFFFF", dark)
        self.assertNotIn("#111827", dark)
        self.assertIn("#111827", light)
        self.assertNotIn("#FFFFFF", light)
        for css in (dark, light):                           # a literal colour: never a theme variable
            self.assertNotIn("var(", css)
            self.assertIn(".a-ring .n", css)
            self.assertIn(".atsl-gauge text.gauge-num", css)

    def test_the_gauge_number_never_uses_the_badge_class(self):
        """The report's ".rp .num" is a 28px badge: a gauge number with class "num" shrank to 13px."""
        import dashboard as D
        svg = D.gauge(84, 170)
        self.assertIn('class="gauge-num"', svg)
        self.assertNotIn('class="num"', svg)
        self.assertIn('font-size="48"', svg)                          # 28% of the ring: about 48px at 170px
        for choice in ("light", "dark", None):
            self.assertIn("font-weight: 800 !important", UI.ring_css(choice))

    def test_an_old_saved_report_gets_the_big_number_when_it_is_opened(self):
        """Reports saved before the fix carry class="num" (tiny: the report's 28px badge) or no class at all."""
        import dashboard as D
        fresh = D.gauge(46, 205)
        variants = (fresh.replace('class="gauge-num" ', 'class="num" '),
                    fresh.replace('class="gauge-num" ', "").replace("var(--a-gauge-text, #0f172a)", "#0f172a"), fresh)
        for old_html in variants:
            row = H.decode({"report_body": old_html, "report_doc": "<html>" + old_html + "</html>",
                            "comparison_doc": None, "parts": ""})
            self.assertEqual(row["report_body"], fresh)
            self.assertIn(fresh, row["report_doc"])
            self.assertIsNone(row["comparison_doc"])

    def test_with_no_choice_the_browsers_dark_mode_gives_white(self):
        css = UI.ring_css(None)
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertLess(css.index("#111827"), css.index("#FFFFFF"))      # light first, white inside the dark media rule

    def test_the_ring_rule_is_the_last_rule_of_the_page(self):
        for choice in ("light", "dark", None):
            page = UI.css(UI.ADMIN, UI.USER, extra=".x {color: red;}", choice=choice)
            self.assertTrue(page.rstrip().endswith("</style>"))
            self.assertGreater(page.rindex(UI.RING_SELECTOR), page.rindex(".x {color: red;}"))

    def test_the_visitors_choice_switches_the_whole_palette(self):
        self.assertIn(UI.DARK_VARS, UI.theme_css("dark"))
        self.assertIn("color-scheme: dark", UI.theme_css("dark"))
        self.assertIn(UI.LIGHT_VARS, UI.theme_css("light"))
        self.assertNotIn(UI.DARK_VARS, UI.theme_css("light"))


def toggle_page(kind):
    import admin_page
    import lab_pages as P
    import user_page
    P.start_page(kind)
    (user_page.page if kind == "user" else admin_page.admin_body)()
    P.theme_toggle()


def user_app():
    import user_page
    user_page.user()


def admin_app():
    import admin_page
    admin_page.admin()


class TestThemeButton(unittest.TestCase):
    def open(self, kind, cookie=None):
        at = AppTest.from_function(toggle_page, args=(kind,), default_timeout=120)
        if cookie:
            at.session_state["atsl_theme"] = cookie
        return at.run()

    def css_of(self, at):
        return "".join(m.value for m in at.markdown if "--a-bg" in m.value)

    def test_the_button_is_on_both_pages_and_switches_the_choice(self):
        for kind in ("user", "admin"):
            at = self.open(kind, "light")
            self.assertFalse(at.exception, at.exception)
            self.assertIn("color-scheme: light", self.css_of(at))
            at.button(key="theme_btn").click().run()
            self.assertEqual(at.session_state["atsl_theme"], "dark")
            self.assertIn("color-scheme: dark", self.css_of(at))
            at.button(key="theme_btn").click().run()
            self.assertEqual(at.session_state["atsl_theme"], "light")

    def test_both_real_pages_draw_the_button_last(self):
        for app in (user_app, admin_app):
            at = AppTest.from_function(app, default_timeout=120).run()
            self.assertFalse(at.exception, at.exception)
            self.assertEqual(at.button[-1].key, "theme_btn")          # last: no other test's button index moves

    def test_the_choice_is_written_to_a_cookie_only_when_it_changes(self):
        at = self.open("user", "light")
        at.button(key="theme_btn").click().run()
        self.assertEqual(at.session_state["atsl_theme_cookie"], "dark")


class TestSecondOpinionCards(unittest.TestCase):
    def test_leverparser_is_off_by_default_and_its_code_stays(self):
        self.assertFalse(S.SETTINGS["second_lever"][1])
        with mock.patch.object(SO.E, "available", return_value=(True, "")):
            self.assertNotIn("lever", SO.visible_order())
            self.assertIn("lever", SO.visible_order(lever_on=True))
            self.assertIn("lever", SO.ORDER)                 # nothing was removed

    def test_ats_checker_3_needs_its_engine(self):
        with mock.patch.object(SO.E, "available", return_value=(False, "not_installed")):
            self.assertNotIn("engine", SO.visible_order(lever_on=True))

    def test_the_check_again_button_never_wraps(self):
        css = UI.BASE + UI.ADMIN
        self.assertIn('[class*="st-key-card-so-"] button {min-width: max-content; white-space: nowrap;', css)


class TestKeptReads(unittest.TestCase):
    """The Postgres read cache, tested on the local file with the cache switched on."""
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = H.Store(self.dir)
        self.store.cache_reads = True
        self.calls = []
        original = self.store._all
        self.store._all = lambda sql, args=(): (self.calls.append(sql), original(sql, args))[1]

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def reads(self):
        return len([c for c in self.calls if "FROM settings" in c])

    def test_a_second_read_is_served_from_memory(self):
        self.store.saved_settings()
        self.store.saved_settings()
        self.assertEqual(self.reads(), 1)

    def test_a_kept_answer_is_a_copy(self):
        self.store.saved_settings()
        self.store.saved_settings()["x"] = "changed"
        self.assertNotIn("x", self.store.saved_settings())

    def test_a_write_drops_the_kept_reads(self):
        self.assertEqual(self.store.saved_settings(), {})
        self.store.save_setting("file_days", 7, "Tester")
        self.assertEqual(self.store.saved_settings().get("file_days"), "7")

    def test_a_write_through_db_drops_them_too(self):
        self.assertEqual(self.store.new_bugs(), 0)
        self.store.add_bug({"who": "Tester", "kind": "wrong", "description": "d"})
        self.assertEqual(self.store.new_bugs(), 1)

    def test_a_cleanup_that_deletes_nothing_does_not_drop_the_kept_reads(self):
        self.store.saved_settings()
        self.store.cleanup_bug_images(30)
        self.store.saved_settings()
        self.assertEqual(self.reads(), 1)

    def test_an_old_answer_is_read_again(self):
        self.store.saved_settings()
        with mock.patch.object(H.time, "monotonic", return_value=H.time.monotonic() + H.READ_TTL + 1):
            self.store.saved_settings()
        self.assertEqual(self.reads(), 2)

    def test_a_computer_with_the_local_file_reads_every_time(self):
        self.store.cache_reads = False
        self.store.saved_settings()
        self.store.saved_settings()
        self.assertEqual(self.reads(), 2)


class TestReusedResults(unittest.TestCase):
    def setUp(self):
        lab_reuse.clear()
        self.count = 0

    def check(self, pdf, filename, with_job, text, job_title=None):
        self.count += 1
        return {"score": 80 + self.count, "cv": filename, "v3": {"cv": filename}, "_uid": f"u{self.count}"}

    def run_it(self, pdf=b"%PDF-a", name="a.pdf", with_job=True, text="job", title="Title", version="v1", stamp=1):
        return lab_reuse.run(self.check, pdf, name, with_job, text, job_title=title, version=version, code_stamp=stamp)

    def test_the_same_file_and_job_is_scored_once(self):
        first, second = self.run_it(), self.run_it()
        self.assertEqual(self.count, 1)
        self.assertEqual(first["score"], second["score"])
        self.assertTrue(second["_reused"])
        self.assertNotEqual(first["_uid"], second["_uid"])           # one result, one id

    def test_a_copy_never_changes_the_saved_one(self):
        self.run_it()["score"] = 1
        self.assertEqual(self.run_it()["score"], 81)

    def test_another_file_job_title_mode_or_rules_is_a_new_check(self):
        self.run_it()
        for change in ({"pdf": b"%PDF-b"}, {"text": "other job"}, {"title": "Other"}, {"with_job": False},
                       {"version": "v2"}, {"stamp": 2}):
            before = self.count
            self.run_it(**change)
            self.assertEqual(self.count, before + 1, change)

    def test_the_same_file_under_another_name_gets_its_own_name(self):
        self.run_it()
        again = self.run_it(name="renamed.pdf")
        self.assertEqual((self.count, again["cv"], again["v3"]["cv"]), (1, "renamed.pdf", "renamed.pdf"))

    def test_a_failed_check_is_never_saved(self):
        def boom(*a, **k):
            raise ValueError("busy")
        with self.assertRaises(ValueError):
            lab_reuse.run(boom, b"%PDF-z", "z.pdf", True, "job", job_title="T", version="v1")
        self.assertEqual(self.run_it(pdf=b"%PDF-z")["score"], 81)

    def test_only_the_last_results_are_kept(self):
        for n in range(lab_reuse.MAX_ENTRIES + 3):
            self.run_it(pdf=b"%PDF-" + str(n).encode())
        self.assertLessEqual(len(lab_reuse._STORE), lab_reuse.MAX_ENTRIES)


class TestWarmupAndTiming(unittest.TestCase):
    def test_the_warm_up_never_starts_inside_a_test(self):
        self.assertFalse(W.start())
        self.assertFalse(W.status()["started"])

    def test_waiting_for_a_warm_up_that_never_started_returns_at_once(self):
        W.wait(timeout=0.01)

    def test_the_timing_counts_calls_and_seconds(self):
        TM.reset()
        with TM.span("pdf reading"):
            pass
        TM.add("database", 0.25)
        TM.add("database", 0.25)
        lines = TM.snapshot()
        self.assertEqual(lines["database"], (2, 0.5))
        self.assertEqual(lines["pdf reading"][0], 1)
        TM.reset()
        self.assertEqual(TM.snapshot(), {})


if __name__ == "__main__":
    unittest.main()
