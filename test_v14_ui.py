"""
v1.4 (2026-10-31): the redesign of the Admin page and the User page ("1000Jobs ATS Lab Redesign", 7 pages).
No scoring change. Each test uses its own data folder; no AI calls.

Admin: the sidebar (views, "Needs review" count, the signed-in admin, sign out, version), History (filters, search,
label chips, export CSV, delete with confirmation), Needs review (rules from Settings, notes, "Reviewed by"),
Settings (days to keep files and the privacy note, daily limit, review rules, links, the name-and-email switch),
Activity log (who did what, filters, export). User: landing page and result never show hidden content.
Also: every text in lab_text.py, light and dark mode, an older database gets the new columns.

  py -3.12 -m unittest test_v14_ui -v
"""

import csv
import datetime as dt
import io
import os
import re
import shutil
import sqlite3
import tempfile
import tomllib
import unittest

os.environ["ATSLAB_AI_REVIEW"] = "0"
os.environ.pop("OPENROUTER_API_KEY", None)

from streamlit.testing.v1 import AppTest

import admin_page as A
import dashboard as D
import lab_pages as P
import lab_settings as S
import lab_store as H
import lab_text as T
import lab_ui as UI
import user_page as U
from test_app_pages import ADMINS, ENV_KEYS, HIDDEN, POINTS_RE, all_text, facts, result

HERE = os.path.dirname(os.path.abspath(__file__))


class Env(unittest.TestCase):
    """Its own data folder and admin accounts; the environment is put back afterwards."""
    def setUp(self):
        self.saved_env = {k: os.environ.get(k) for k in ENV_KEYS}
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        self.data = tempfile.mkdtemp()
        os.environ["ATSLAB_DATA_DIR"] = self.data
        os.environ["ATSLAB_ADMINS"] = ADMINS
        P._store.clear()
        self.store = P.store()

    def tearDown(self):
        P._store.clear()
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.data, ignore_errors=True)

    def add(self, candidate="Sam Lee", who=H.USER, score=80, label="Strong", f=None, when=None, pdf=b"%PDF-1",
            **extra):
        rec = dict(H.record_of(result(), who), candidate=candidate, score=score, label=label,
                   review_facts=f or facts(score=score), **extra)
        return self.store.add_check(rec, pdf, when=when)

    def admin(self, view, **state):
        at = AppTest.from_function(admin_app, default_timeout=200)
        at.session_state["admin"] = "Tester"
        at.session_state["admin_view"] = view
        for k, v in state.items():
            at.session_state[k] = v
        at.run()
        self.assertFalse(at.exception, at.exception)
        return at


def admin_app():
    import admin_page
    admin_page.admin()


def user_app():
    import user_page
    user_page.user()


# ---------------------------------------------------------------------------
# The store: notes, delete, the activity log, an older database
# ---------------------------------------------------------------------------
class TestStore(Env):
    def test_an_older_database_gets_the_new_columns_and_keeps_its_rows(self):
        folder = tempfile.mkdtemp()
        try:
            con = sqlite3.connect(os.path.join(folder, H.DB_NAME))
            con.executescript(H.SCHEMA.replace(",\n  review_note TEXT,\n  review_facts TEXT", "").split(
                "CREATE TABLE IF NOT EXISTS admin_log")[0])
            con.execute("INSERT INTO checks (created_at, checked_by, score, issues, review_reasons) VALUES "
                        "('2026-10-29 10:00:00', 'user', 40, '[]', '[\"No phone\"]')")
            con.commit()
            con.close()
            store = H.Store(folder)
            row = store.history()[0]
            self.assertEqual(row["review_reasons"], ["Score under 55", "No phone"])     # from its score and reasons
            store.mark_reviewed(row["id"], "Sara", "called them")
            self.assertEqual(store.get(row["id"])["review_note"], "called them")
            store.log("Sara", "review", "x")
            self.assertEqual(len(store.activity()), 1)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_delete_removes_the_report_and_the_file(self):
        cid = self.add()
        path = os.path.join(self.store.files, self.store.get(cid)["file_path"])
        self.assertTrue(os.path.exists(path))
        self.assertEqual(self.store.delete_check(cid)["id"], cid)
        self.assertIsNone(self.store.get(cid))
        self.assertFalse(os.path.exists(path))
        self.assertIsNone(self.store.delete_check(cid))                                  # twice: nothing to do

    def test_reviewed_by_when_and_the_note(self):
        cid = self.add(f=facts(score=40), score=40, label="Not ready")
        self.store.mark_reviewed(cid, "Sara", "  sent   a new template ")
        row = self.store.get(cid)
        self.assertEqual((row["reviewed_by"], row["review_note"]), ("Sara", "sent a new template"))
        self.assertTrue(row["reviewed_at"].startswith(str(dt.date.today())))
        self.assertEqual(self.store.needs_review(), [])


# ---------------------------------------------------------------------------
# "Needs review" rules (Settings)
# ---------------------------------------------------------------------------
class TestReviewRules(Env):
    def test_the_rules_decide_and_can_change(self):
        low = self.add("Low", score=50, f=facts(score=50))
        crit = self.add("Crit", f=facts(critical=["Template is hard for ATS to read"]))
        nophone = self.add("NoPhone", f=facts(no_phone=True))
        fine = self.add("Fine")
        ids = lambda rules=None: sorted(r["id"] for r in self.store.needs_review(rules))
        self.assertEqual(ids(), sorted([low, crit, nophone]))
        self.assertEqual(ids({"score": 45, "critical": True, "contact": True}), sorted([crit, nophone]))
        self.assertEqual(ids({"score": 55, "critical": False, "contact": False}), [low])
        self.assertEqual(ids({"score": 90, "critical": False, "contact": False}), sorted([low, crit, nophone, fine]))
        self.store.save_setting("review_contact", False, "Tester")
        self.assertEqual(P.review_rules(), {"score": 55, "critical": True, "contact": False})
        self.assertNotIn(nophone, [r["id"] for r in self.store.needs_review(P.review_rules())])

    def test_one_tag_per_critical_issue(self):
        reasons = H.reasons_for(facts(score=20, critical=["A is wrong", "B is wrong"]))
        self.assertEqual(A.reason_tags(reasons), ["Score under 55", "A is wrong", "B is wrong"])


# ---------------------------------------------------------------------------
# History: filters, export, delete
# ---------------------------------------------------------------------------
class TestHistory(Env):
    def rows(self):
        day = lambda d: dt.datetime(2026, 10, d, 10, 0)
        self.add("Ana Gomez", score=92, label="Excellent", when=day(10))
        self.add("Ben Ode", who="Sara", score=60, label="Needs work", when=day(20), with_job=1,
                 job_title="Data Analyst")
        self.add("Cy Park", score=30, label="Not ready", when=day(28), f=facts(score=30))
        return self.store.history(rules=P.review_rules())

    def test_filters(self):
        rows = self.rows()
        names = lambda *a, **k: [r["candidate"] for r in A.filter_rows(rows, *a, **k)]
        self.assertEqual(names(), ["Cy Park", "Ben Ode", "Ana Gomez"])
        self.assertEqual(names("analyst"), ["Ben Ode"])                                  # search: the job title too
        self.assertEqual(names("SARA"), ["Ben Ode"])                                     # ... and who checked it
        self.assertEqual(names(label="Excellent"), ["Ana Gomez"])
        self.assertEqual(names(label=A.ADMIN_TEXT["all"]), ["Cy Park", "Ben Ode", "Ana Gomez"])
        self.assertEqual(names(job="with"), ["Ben Ode"])
        self.assertEqual(names(job="without"), ["Cy Park", "Ana Gomez"])
        self.assertEqual(names(dates=(dt.date(2026, 10, 15), dt.date(2026, 10, 28))), ["Cy Park", "Ben Ode"])
        self.assertEqual(names(dates=(dt.date(2026, 10, 20),)), ["Cy Park", "Ben Ode"])   # only a start day
        self.assertEqual(names(by=H.USER), ["Cy Park", "Ana Gomez"])
        self.assertEqual(names(by="Sara"), ["Ben Ode"])

    def test_export_csv_is_safe_in_a_spreadsheet(self):
        rows = self.rows()
        rows[0]["candidate"] = "=HYPERLINK(\"http://x\")"
        text = A.history_csv(rows).decode("utf-8-sig")
        table = list(csv.reader(io.StringIO(text)))
        self.assertEqual(table[0][:8], ["Date", "Candidate", "File", "Checked by", "Job", "Job title", "Score",
                                        "Label"])
        self.assertEqual(len(table), 4)
        self.assertTrue(table[1][1].startswith("'="))                                    # never run as a formula
        self.assertEqual(table[1][8], "Score under 55")
        self.assertEqual(A.safe_cell("+1"), "'+1")
        self.assertEqual(A.safe_cell("Sam"), "Sam")

    def test_the_view_cards_chips_table_and_export(self):
        self.rows()
        at = self.admin("history")
        text = all_text(at)
        for k in ("stat_checks", "stat_avg", "stat_user", "stat_review", "col_candidate", "col_review"):
            self.assertIn(A.ADMIN_TEXT[k], text)
        self.assertIn('<div class="v">3</div>', text)                                    # 3 checks
        self.assertIn('<div class="v">61</div>', text)                                   # average of 92, 60, 30
        chips = at.get("button_group")[0]
        self.assertEqual(list(chips.proto.options[i].content for i in range(len(chips.proto.options))),
                         ["All", "Excellent", "Needs work", "Not ready"])               # the labels in the history
        self.assertIn(A.ADMIN_TEXT["export"], [b.proto.label for b in at.get("download_button")])
        at.text_input(key="hist_search").set_value("park").run()
        self.assertIn("Cy Park", all_text(at))
        self.assertNotIn("Ana Gomez", all_text(at))

    def test_delete_asks_first_then_removes_and_logs(self):
        self.rows()
        cid = self.store.history()[0]["id"]
        at = self.admin("history")
        at.checkbox(key=f"sel_{cid}").check().run()
        at.button(key="hist_delete").click().run()
        self.assertIn(A.ADMIN_TEXT["confirm_title"].format(n=1, s=""), all_text(at))
        self.assertIsNotNone(self.store.get(cid))                                        # nothing deleted yet
        at.button(key="confirm_no").click().run()                                       # Cancel
        self.assertIsNotNone(self.store.get(cid))
        at.checkbox(key=f"sel_{cid}").check().run()
        at.button(key="hist_delete").click().run()
        at.button(key="confirm_yes").click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertIsNone(self.store.get(cid))
        self.assertEqual(len(self.store.history()), 2)
        log = self.store.activity()[0]
        self.assertEqual((log["admin"], log["kind"], log["target"]), ("Tester", "delete", "Cy Park"))

    def test_open_a_report_and_delete_it_there(self):
        cid = self.add("Dee Ray")
        at = self.admin("history", open_check=cid)
        self.assertIn(D.REPORT_TEXT["how_fix"], all_text(at))                            # the full report
        at.button(key="open_delete").click().run()
        at.button(key="confirm_yes").click().run()
        self.assertIsNone(self.store.get(cid))
        self.assertIn(A.ADMIN_TEXT["deleted"].format(n=1, s=""), all_text(at))

    def test_empty_states(self):
        at = self.admin("history")
        self.assertIn(A.ADMIN_TEXT["no_history"], all_text(at))
        self.add("Ana Gomez")
        at = self.admin("history")
        at.text_input(key="hist_search").set_value("nobody here").run()
        self.assertIn(A.ADMIN_TEXT["no_match"], all_text(at))


# ---------------------------------------------------------------------------
# Needs review: notes, the user's name and email, "Reviewed by"
# ---------------------------------------------------------------------------
class TestNeedsReview(Env):
    def test_card_note_and_mark_reviewed(self):
        cid = self.add("Ray Low", score=30, label="Not ready", f=facts(score=30, critical=["Template is hard"]),
                       lead_name="Ray Low", lead_email="ray@example.com")
        at = self.admin("review")
        text = all_text(at)
        for t in ("Ray Low", "ray@example.com", A.ADMIN_TEXT["why_flagged"], "Score under 55", "Template is hard",
                  A.ADMIN_TEXT["from_user"]):
            self.assertIn(t, text)
        at.text_area(key=f"note_{cid}").set_value("Called Ray, sent the new template").run()
        at.button(key=f"rev_{cid}").click().run()
        self.assertFalse(at.exception, at.exception)
        row = self.store.get(cid)
        self.assertEqual((row["reviewed_by"], row["review_note"]), ("Tester", "Called Ray, sent the new template"))
        self.assertIn(A.ADMIN_TEXT["no_review"], all_text(at))                           # the empty state
        log = self.store.activity()[0]
        self.assertEqual((log["kind"], log["target"]), ("review", "Ray Low"))
        self.assertIn("Called Ray", log["details"])
        hist = self.admin("history")
        self.assertIn(A.ADMIN_TEXT["tag_reviewed"].format(who="Tester"), all_text(hist))

    def test_the_subtitle_says_the_rules(self):
        self.store.save_setting("review_score", 70, "Tester")
        self.store.save_setting("review_critical", False, "Tester")
        at = self.admin("review")
        self.assertIn("a score under 70 or no email or no phone", all_text(at))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class TestSettingsPage(Env):
    def test_every_setting_is_on_the_page(self):
        at = self.admin("settings")
        keys = {w.key for w in list(at.number_input) + list(at.toggle) + list(at.text_input)}
        self.assertEqual(keys, {f"set_{k}" for k in S.SETTINGS})
        self.assertIn(A.ADMIN_TEXT["rules_title"], all_text(at))

    def test_save_logs_old_and_new_and_the_privacy_note_follows(self):
        at = self.admin("settings")
        at.number_input(key="set_file_days").set_value(14)
        at.number_input(key="set_review_score").set_value(70)
        at.toggle(key="set_review_contact").set_value(False)
        next(b for b in at.button if b.label == A.ADMIN_TEXT["save"]).click().run()
        self.assertIn(A.ADMIN_TEXT["settings_saved"], all_text(at))
        saved = self.store.saved_settings()
        self.assertEqual((S.get("file_days", saved), S.get("review_score", saved), S.get("review_contact", saved)),
                         (14, 70, False))
        details = {r["target"]: r["details"] for r in self.store.activity() if r["kind"] == "settings"}
        self.assertEqual(details[T.SETTINGS_TEXT["file_days"][0]], "30 days → 14 days")
        self.assertEqual(details[T.SETTINGS_TEXT["review_score"][0]], "55 → 70")
        self.assertEqual(details[T.SETTINGS_TEXT["review_contact"][0]], "on → off")
        user = AppTest.from_function(user_app, default_timeout=200).run()
        self.assertIn(U.USER_TEXT["privacy"].format(days=14), all_text(user))           # the privacy note updates

    def test_a_link_must_be_a_web_address(self):
        at = self.admin("settings")
        at.text_input(key="set_premium_url").set_value("javascript:alert(1)")
        next(b for b in at.button if b.label == A.ADMIN_TEXT["save"]).click().run()
        self.assertTrue(any("http" in e.value for e in at.error))
        self.assertNotIn("premium_url", self.store.saved_settings())
        self.assertEqual(S.get("premium_url", {"premium_url": "javascript:alert(1)"}), "https://1000jobs.club")

    def test_reset_to_the_server_settings(self):
        self.store.save_setting("daily_checks", 9, "Tester")
        at = self.admin("settings")
        next(b for b in at.button if b.label == A.ADMIN_TEXT["reset"]).click().run()
        self.assertEqual(self.store.saved_settings(), {})
        self.assertEqual(self.store.activity()[0]["details"], T.LOG_DETAILS["settings_reset"])


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------
class TestActivityLog(Env):
    def test_who_did_what_filters_and_export(self):
        now = H.now()
        self.store.log("Tester", "check", "Ana Gomez", "General check · score 92 · Excellent", when=now)
        self.store.log("Sara", "review", "Cy Park", "Note: called", when=now - dt.timedelta(days=3))
        self.store.log("Sara", "delete", "Old One", T.LOG_DETAILS["delete"], when=now - dt.timedelta(days=5))
        rows = self.store.activity()
        self.assertEqual([r["kind"] for r in A.filter_log(rows, kind="review")], ["review"])
        self.assertEqual([r["target"] for r in A.filter_log(rows, "deleted record")], ["Old One"])  # the action name
        self.assertEqual([r["admin"] for r in A.filter_log(rows, "sara")], ["Sara", "Sara"])
        self.assertEqual(len(A.filter_log(rows, dates=(now.date(),))), 1)
        table = list(csv.reader(io.StringIO(A.log_csv(rows).decode("utf-8-sig"))))
        self.assertEqual(table[0], ["When", "Admin", "Action", "Target", "Details"])
        self.assertEqual(table[1][2], T.LOG_KINDS["check"][1])
        at = self.admin("log")
        text = all_text(at)
        for t in ("Ana Gomez", "Cy Park", "Old One", T.LOG_KINDS["delete"][1], A.ADMIN_TEXT["stat_today"]):
            self.assertIn(t, text)
        A.log_export("Tester", "log", 3)
        self.assertEqual(self.store.activity()[0]["kind"], "export")

    def test_sign_in_and_checks_are_logged(self):
        at = AppTest.from_function(admin_app, default_timeout=200).run()
        at.text_input[0].set_value("Tester")
        at.text_input[1].set_value("right-pass-1")
        at.button[0].click().run()
        self.assertEqual(self.store.activity()[0]["kind"], "sign_in")
        A.saver("Tester")({"res": result(), "prev": None, "inputs": {"pdf": b"", "job_title": "", "client": False}})
        log = self.store.activity()[0]
        self.assertEqual((log["kind"], log["admin"]), ("check", "Tester"))
        self.assertIn(f"score {round(result()['score'])}", log["details"])

    def test_empty_log(self):
        self.assertIn(A.ADMIN_TEXT["no_log"], all_text(self.admin("log")))


# ---------------------------------------------------------------------------
# Sidebar and sign out
# ---------------------------------------------------------------------------
class TestSidebar(Env):
    def test_views_count_admin_version_sign_out(self):
        self.add("Low", score=40, f=facts(score=40))
        self.add("Low 2", score=41, f=facts(score=41))
        at = self.admin("check")
        labels = [b.label for b in at.sidebar.button]
        self.assertEqual(labels[:5], [label for label, _ in T.NAV.values()])
        text = all_text(at)
        self.assertIn('.st-key-nav_review button::after {content: "2"', "".join(m.value for m in at.markdown))
        self.assertIn(A.ADMIN_TEXT["version"].format(version=T.APP_VERSION), text)
        self.assertIn("ATS Lab v1.4", text)
        self.assertIn("Tester", text)
        at.sidebar.button(key="nav_settings").click().run()
        self.assertEqual(at.session_state["admin_view"], "settings")
        at.sidebar.button(key="sign_out").click().run()
        self.assertNotIn("admin", at.session_state)
        self.assertIn(A.ADMIN_TEXT["login_title"], all_text(at))

    def test_a_view_saved_by_its_old_name_still_opens(self):
        at = self.admin("Needs review")
        self.assertEqual(at.session_state["admin_view"], "review")

    def test_check_view_side_panels(self):
        self.add("Recent One", score=69, label="Needs work")
        at = self.admin("check")
        text = all_text(at)
        for t in (A.ADMIN_TEXT["shows_title"], A.ADMIN_TEXT["recent"], "Recent One", A.ADMIN_TEXT["role_label"],
                  A.ADMIN_TEXT["compare_sub"]):
            self.assertIn(t, text)
        self.assertIn(D.CLIENT_TEXT["checkbox"], [c.label for c in at.checkbox])
        at.button(key="see_all").click().run()
        self.assertEqual(at.session_state["admin_view"], "history")


# ---------------------------------------------------------------------------
# The User page never shows hidden or admin content
# ---------------------------------------------------------------------------
ADMIN_ONLY = ["Needs review", "Activity log", "Settings", "History", "Delete", "Export CSV", "Mark reviewed",
              "Reviewed by", "Sign out", A.ADMIN_TEXT["admin_badge"], "Check a resume"]


class TestUserPage(Env):
    def test_landing_page(self):
        at = AppTest.from_function(user_app, default_timeout=200).run()
        self.assertFalse(at.exception, at.exception)
        text = all_text(at)
        for t in (U.USER_TEXT["hero_pill"], U.USER_TEXT["ticks"][0], U.USER_TEXT["upload_title"],
                  U.USER_TEXT["privacy"].format(days=30), U.USER_TEXT["steps"][0][1]):
            self.assertIn(t, text)
        for t in ADMIN_ONLY:
            self.assertNotIn(t, text)
        self.assertFalse(at.sidebar.button)

    def test_result_page_shows_only_the_short_result(self):
        for with_job in (False, True):
            r = result(with_job)
            at = AppTest.from_function(user_app, default_timeout=200)
            at.session_state["u_result"] = r
            at.run()
            text = all_text(at)
            with self.subTest(with_job=with_job):
                for h in HIDDEN + ADMIN_ONLY:
                    self.assertNotIn(h, text, h)
                self.assertIsNone(POINTS_RE.search(text))
                self.assertIn(U.USER_TEXT["headline"][r["label"]], text)
                self.assertIn("can reach about", text)
                self.assertEqual(D.PART_NAMES["job_match"] in text, with_job)
                self.assertEqual(len(re.findall(r'class="u-issue"', text)), min(4, len(U.shown_issues(
                    D.issue_cards(r))[0])))
                self.assertFalse(at.get("download_button"))

    def test_the_locked_line_links_to_premium(self):
        os.environ["ATSLAB_PREMIUM_URL"] = "https://example.com/premium?a=1&b=2"
        at = AppTest.from_function(user_app, default_timeout=200)
        at.session_state["u_result"] = result()
        at.run()
        self.assertIn('href="https://example.com/premium?a=1&amp;b=2"', all_text(at))


# ---------------------------------------------------------------------------
# One style, light and dark, texts in one place
# ---------------------------------------------------------------------------
class TestStyleAndTexts(unittest.TestCase):
    def test_light_and_dark_mode(self):
        self.assertIn("@media (prefers-color-scheme: dark)", UI.PALETTE)
        light, dark = UI.PALETTE.split("@media (prefers-color-scheme: dark)")
        names = lambda part: set(re.findall(r"(--a-[a-z0-9-]+):", part))
        self.assertEqual(names(light), names(dark))                                      # every color has a dark one
        with open(os.path.join(HERE, ".streamlit", "config.toml"), "rb") as f:
            theme = tomllib.load(f)["theme"]
        self.assertIn("light", theme)
        self.assertIn("dark", theme)

    def test_no_hard_coded_colors_in_the_pages(self):
        for name in ("admin_page.py", "user_page.py"):
            with open(os.path.join(HERE, name), encoding="utf-8") as f:
                code = f.read()
            self.assertEqual(re.findall(r"(?<!&)#[0-9a-fA-F]{6}\b", code), [], name)    # colors live in lab_ui.py

    def test_texts_in_one_place(self):
        self.assertIs(A.ADMIN_TEXT, T.ADMIN_TEXT)
        self.assertIs(U.USER_TEXT, T.USER_TEXT)
        self.assertIs(P.QUEUE_TEXT, T.QUEUE_TEXT)
        for key in S.SETTINGS:
            self.assertEqual(S.SETTINGS[key][2], T.SETTINGS_TEXT[key][0])
        for name in ("admin_page.py", "user_page.py"):                     # no sentence written in the page code
            with open(os.path.join(HERE, name), encoding="utf-8") as f:
                code = f.read()
            calls = re.findall(r"st\.(?:button|markdown|caption|error|success|info|warning|text_input|text_area|"
                               r"toggle|checkbox|link_button|download_button)\(\s*\"([A-Z][a-z]+ [a-z]+[^\"]*)\"",
                               code)
            self.assertEqual(calls, [], name)

    def test_label_colors(self):
        self.assertIn("a-ok", UI.pill(92, "Excellent"))
        self.assertIn("a-warn", UI.pill(69, "Needs work"))
        self.assertIn("a-bad", UI.pill(19, "Not ready"))
        self.assertEqual(UI.initials("Mohamed Shokry"), "MS")
        self.assertEqual(UI.initials(""), "?")
        self.assertIn(">92</div>", UI.ring(92, "Excellent"))
        self.assertIn("&lt;b&gt;", UI.tag("<b>x</b>"))                                   # always escaped


if __name__ == "__main__":
    unittest.main()
