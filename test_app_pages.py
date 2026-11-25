"""
Tests for the app with two pages (app.py): the Admin page (admin_page.py), the User page (user_page.py), the history
store (lab_store.py) and the settings (lab_settings.py). No AI calls. Each test class uses its own data folder.

  py -3.12 -m unittest test_app_pages -v
"""

import datetime as dt
import os
import re

os.environ["ATSLAB_AI_REVIEW"] = "0"      # no AI review (and no cost) in these tests
os.environ.pop("OPENROUTER_API_KEY", None)
import shutil
import tempfile
import unittest

from streamlit.testing.v1 import AppTest

import admin_page as A
import dashboard as D
import lab_settings as S
import lab_store as H
import test_dashboard as T
import user_page as U

HERE = os.path.dirname(os.path.abspath(__file__))
ADMINS = '{"Tester": "right-pass-1", "Sara": "other-pass-2"}'
ENV_KEYS = ("ATSLAB_ADMINS", "ATSLAB_DATA_DIR", "ATSLAB_FILE_DAYS", "ATSLAB_PREMIUM_URL", "ATSLAB_BOOKING_URL",
            "ATSLAB_COLLECT_LEADS", "ATSLAB_DAILY_CHECKS", "OPENROUTER_API_KEY")
_RESULTS = {}


def result(with_job=False):
    """A real result for Neda's resume (scored once per run; with a job: saved keywords, no AI)."""
    if with_job not in _RESULTS:
        cache = tempfile.mkdtemp()
        try:
            T.seed(cache)
            _RESULTS[with_job] = D.run_check(T.cv_bytes(), "Neda Sefati resume.pdf", with_job,
                                             T.job_text() if with_job else "", cache, cache,
                                             job_title="Delivery Lead" if with_job else None)
        finally:
            shutil.rmtree(cache, ignore_errors=True)
    return _RESULTS[with_job]


class Env(unittest.TestCase):
    """Each test: its own data folder and admin accounts; the environment is put back afterwards."""
    def setUp(self):
        self.saved_env = {k: os.environ.get(k) for k in ENV_KEYS}
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        self.data = tempfile.mkdtemp()
        os.environ["ATSLAB_DATA_DIR"] = self.data
        os.environ["ATSLAB_ADMINS"] = ADMINS
        self.store = H.Store(self.data)

    def tearDown(self):
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.data, ignore_errors=True)


def all_text(at):
    parts = [x.value for x in at.markdown if not x.value.startswith("<style")]
    parts += [x.value for x in at.caption] + [x.value for x in at.error]
    parts += [x.value for x in at.warning] + [x.value for x in at.info] + [x.value for x in at.success]
    parts += [x.label for x in at.button] + [x.label for x in at.expander] + [x.label for x in at.text_input]
    parts += [x.proto.label for x in at.get("link_button")]
    return "\n".join(str(p) for p in parts)


# ---------------------------------------------------------------------------
# Two pages, two links
# ---------------------------------------------------------------------------
class TestLinks(Env):
    def test_each_page_has_its_own_link(self):
        import app
        self.assertEqual([(link, page) for link, page, _ in app.LINKS], [("user", U.user), ("admin", A.admin)])

    def test_the_bare_address_opens_the_user_page(self):
        at = AppTest.from_file(os.path.join(HERE, "app.py"), default_timeout=120).run()
        self.assertFalse(at.exception, at.exception)
        text = all_text(at)
        self.assertIn(U.USER_TEXT["upload_title"], text)
        self.assertNotIn(A.ADMIN_TEXT["login_title"], text)

    def test_no_folder_of_this_computer_in_the_new_code(self):
        for name in ("app.py", "admin_page.py", "user_page.py", "lab_pages.py", "lab_settings.py", "lab_store.py"):
            with open(os.path.join(HERE, name), encoding="utf-8") as f:
                code = f.read()
            self.assertIsNone(re.search(r"[A-Za-z]:\\\\|ATSLab\\\\|Users\\\\", code), name)
            self.assertNotIn("right-pass", code)

    def test_the_data_folder_is_a_setting(self):
        self.assertEqual(S.data_dir(), self.data)
        os.environ.pop("ATSLAB_DATA_DIR")
        self.assertEqual(S.data_dir(), os.path.join(HERE, "data"))


# ---------------------------------------------------------------------------
# Admin sign in
# ---------------------------------------------------------------------------
def admin_app():
    import admin_page
    admin_page.admin()


class TestAdminLogin(Env):
    def test_right_and_wrong_passwords(self):
        self.assertEqual(S.check_login("Tester", "right-pass-1"), "Tester")
        self.assertEqual(S.check_login(" tester ", "right-pass-1"), "Tester")           # the name: any case
        self.assertEqual(S.check_login("Sara", "other-pass-2"), "Sara")                  # several accounts
        self.assertIsNone(S.check_login("Tester", "other-pass-2"))                       # another admin's password
        self.assertIsNone(S.check_login("Tester", "RIGHT-PASS-1"))                       # the password: exact
        self.assertIsNone(S.check_login("Tester", ""))
        self.assertIsNone(S.check_login("Nobody", "right-pass-1"))

    def test_accounts_from_the_environment_in_two_forms_and_none(self):
        os.environ["ATSLAB_ADMINS"] = "Ali:pa:ss;Mona:x1"
        self.assertEqual(S.admin_accounts(), {"Ali": "pa:ss", "Mona": "x1"})
        os.environ.pop("ATSLAB_ADMINS")
        real = S._secrets
        S._secrets = lambda: {}
        try:
            self.assertEqual(S.admin_accounts(), {})
            self.assertIsNone(S.check_login("", ""))
            S._secrets = lambda: {"admins": {"Lina": "from-secrets"}}
            self.assertEqual(S.check_login("lina", "from-secrets"), "Lina")
        finally:
            S._secrets = real

    def test_sign_in_on_the_page(self):
        at = AppTest.from_function(admin_app, default_timeout=120).run()
        self.assertFalse(at.exception, at.exception)
        self.assertNotIn(D.REPORT_TEXT["upload_title"], all_text(at))                  # nothing before signing in
        at.text_input[0].set_value("Tester")
        at.text_input[1].set_value("wrong")
        at.button[0].click().run()
        self.assertIn(A.ADMIN_TEXT["wrong"], all_text(at))
        self.assertNotIn("admin", at.session_state)
        at.text_input[0].set_value("Tester")
        at.text_input[1].set_value("right-pass-1")
        at.button[0].click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(at.session_state["admin"], "Tester")
        self.assertIn(A.ADMIN_TEXT["signed_in"].format(name="Tester"), all_text(at))
        self.assertIn(A.ADMIN_TEXT["run"], [b.label for b in at.button])              # the check of a resume

    def test_too_many_wrong_tries_wait(self):
        for _ in range(A.MAX_TRIES):
            self.assertIsNone(A.sign_in("Tester", "wrong", "10.0.0.1", self.store))
        self.assertIsNone(A.sign_in("Tester", "right-pass-1", "10.0.0.1", self.store))   # locked for a minute
        self.store._run("UPDATE login_guard SET locked_until = 0")                       # the minute is over
        self.assertEqual(A.sign_in("Tester", "right-pass-1", "10.0.0.1", self.store), "Tester")

    def test_no_accounts_no_way_in(self):
        os.environ.pop("ATSLAB_ADMINS")
        real = S._secrets
        S._secrets = lambda: {}
        try:
            at = AppTest.from_function(admin_app, default_timeout=120).run()
            self.assertIn(A.ADMIN_TEXT["no_accounts"], all_text(at))
            self.assertFalse(at.text_input)
        finally:
            S._secrets = real

    def test_a_removed_account_is_signed_out(self):
        at = AppTest.from_function(admin_app, default_timeout=120)
        at.session_state["admin"] = "Gone"
        at.run()
        self.assertNotIn("admin", at.session_state)
        self.assertIn(A.ADMIN_TEXT["login_title"], all_text(at))


class TestStayingSignedInOnThePage(Env):
    """An admin who signed in stays signed in after a refresh, a new tab or a new window (the cookie brings them back)
    until they press Sign out, change the password, or 30 days pass."""
    def page(self, cookie=None):
        from unittest import mock
        patch = mock.patch.object(A.P, "admin_token", return_value=cookie)
        patch.start()
        self.addCleanup(patch.stop)
        return AppTest.from_function(admin_app, default_timeout=120)

    def sign_in(self):
        at = self.page().run()
        at.text_input[0].set_value("Tester")
        at.text_input[1].set_value("right-pass-1")
        at.button[0].click().run()
        self.assertEqual(at.session_state["admin"], "Tester")
        return at

    def cookie_scripts(self, at):
        return [e.proto.body for e in at.get("html") if "atsl_admin" in e.proto.body]

    def test_signing_in_stores_only_a_hash_and_writes_the_cookie_in_the_page_that_stays(self):
        at = self.sign_in()
        token = at.session_state["admin_token"]
        rows = self.store._all("SELECT * FROM admin_sessions")
        self.assertEqual([self.store.token_hash(token)], [r["token_hash"] for r in rows])
        self.assertNotIn(token, " ".join(str(v) for v in rows[0].values()))
        scripts = self.cookie_scripts(at)
        self.assertEqual(1, len(scripts), scripts)
        self.assertIn(f"atsl_admin={token}", scripts[0])
        self.assertIn("Max-Age=2592000", scripts[0])                    # 30 days
        self.assertNotIn("right-pass-1", scripts[0])

    def test_a_refresh_new_tab_or_window_with_the_cookie_is_still_signed_in(self):
        token = self.sign_in().session_state["admin_token"]
        again = self.page(cookie=token).run()                            # a new session that sends the cookie
        self.assertFalse(again.exception, again.exception)
        self.assertEqual(again.session_state["admin"], "Tester")
        self.assertNotIn(A.ADMIN_TEXT["login_title"], all_text(again))
        self.assertEqual(1, len(self.cookie_scripts(again)))             # the cookie is renewed for 30 more days
        third = self.page(cookie=token).run()                            # and again, any number of times
        self.assertEqual(third.session_state["admin"], "Tester")

    def test_without_the_cookie_the_sign_in_page_shows(self):
        self.sign_in()
        other = self.page(cookie=None).run()                             # another browser
        self.assertNotIn("admin", other.session_state)
        self.assertIn(A.ADMIN_TEXT["login_title"], all_text(other))

    def test_sign_out_ends_it_for_good(self):
        at = self.sign_in()
        token = at.session_state["admin_token"]
        at.sidebar.button(key="sign_out").click().run()
        self.assertNotIn("admin", at.session_state)
        self.assertIn(A.ADMIN_TEXT["login_title"], all_text(at))
        self.assertEqual([], self.store._all("SELECT * FROM admin_sessions"))
        again = self.page(cookie=token).run()                            # the old cookie is still in the browser
        self.assertNotIn("admin", again.session_state)
        self.assertIn(A.ADMIN_TEXT["login_title"], all_text(again))
        self.assertTrue([e for e in again.get("html") if "Max-Age=0" in e.proto.body])     # and is deleted

    def test_a_changed_password_signs_the_admin_out(self):
        token = self.sign_in().session_state["admin_token"]
        os.environ["ATSLAB_ADMINS"] = '{"Tester": "brand-new-pass-9", "Sara": "other-pass-2"}'
        again = self.page(cookie=token).run()
        self.assertNotIn("admin", again.session_state)
        self.assertIn(A.ADMIN_TEXT["login_title"], all_text(again))

    def test_a_cookie_after_30_days_does_not_work(self):
        token = self.sign_in().session_state["admin_token"]
        old = (H.now() - dt.timedelta(minutes=1)).strftime(H.TIME_FORMAT)
        self.store._run("UPDATE admin_sessions SET expires_at = ?", (old,))
        again = self.page(cookie=token).run()
        self.assertNotIn("admin", again.session_state)


# ---------------------------------------------------------------------------
# Secrets and settings
# ---------------------------------------------------------------------------
class TestSettings(Env):
    def test_defaults(self):
        self.assertEqual(S.get("file_days"), 30)
        self.assertIs(S.get("collect_leads"), False)                     # the name-and-email step: off by default
        self.assertTrue(S.get("premium_url").startswith("https://"))
        self.assertEqual(S.source("file_days"), "default")

    def test_environment_then_saved_by_an_admin(self):
        os.environ["ATSLAB_FILE_DAYS"] = "14"
        os.environ["ATSLAB_COLLECT_LEADS"] = "yes"
        self.assertEqual(S.get("file_days"), 14)
        self.assertIs(S.get("collect_leads"), True)
        self.assertEqual(S.source("file_days"), "server setting")
        self.store.save_setting("file_days", 7, "Tester")
        saved = self.store.saved_settings()
        self.assertEqual(S.get("file_days", saved), 7)                   # an admin's value wins
        self.assertEqual(S.source("file_days", saved), "saved here")
        self.store.clear_setting("file_days")
        self.assertEqual(S.get("file_days", self.store.saved_settings()), 14)

    def test_a_wrong_value_never_breaks_the_app(self):
        os.environ["ATSLAB_FILE_DAYS"] = "thirty"
        self.assertEqual(S.get("file_days"), 30)
        self.assertEqual(S.get("file_days", {"file_days": "0"}), 30)

    def test_the_ai_key_comes_from_the_secrets(self):
        real = S._secrets
        S._secrets = lambda: {"OPENROUTER_API_KEY": "test-key-not-real"}
        try:
            self.assertTrue(S.apply_api_key())
            self.assertEqual(os.environ["OPENROUTER_API_KEY"], "test-key-not-real")
        finally:
            S._secrets = real
            os.environ.pop("OPENROUTER_API_KEY", None)
        self.assertFalse(S.apply_api_key())

    def test_settings_view_saves(self):
        at = AppTest.from_function(admin_app, default_timeout=120)
        at.session_state["admin"] = "Tester"
        at.session_state["admin_view"] = "Settings"
        at.run()
        self.assertFalse(at.exception, at.exception)
        at.number_input(key="set_file_days").set_value(10)
        at.toggle(key="set_collect_leads").set_value(True)
        next(b for b in at.button if b.label == "Save settings").click().run()
        saved = H.Store(self.data).saved_settings()
        self.assertEqual(S.get("file_days", saved), 10)
        self.assertIs(S.get("collect_leads", saved), True)
        self.assertNotIn("premium_url", saved)                          # unchanged values are not saved


# ---------------------------------------------------------------------------
# History, "Needs review", the 30-day clean-up
# ---------------------------------------------------------------------------
def fake(score=80, email=True, phone=True):
    return {"score": score, "structure_checks": {"T7": {"score": float(email)},
                                                 "T3": {"detail": "+971 50 123 4567" if phone else "no phone number"}}}


def facts(score=80, critical=(), no_email=False, no_phone=False):
    """What the "Needs review" rules look at (saved with each check since v1.4)."""
    return {"score": score, "critical": list(critical), "no_email": no_email, "no_phone": no_phone}


class TestHistory(Env):
    def test_why_a_resume_needs_review(self):
        ok = [{"name": "Weak openers", "severity": "Minor"}]
        crit = ok + [{"name": "Template is hard for ATS to read", "severity": "Critical"}]
        every = {"score": 55, "critical": True, "contact": True}
        self.assertEqual(H.review_reasons(fake(), ok), [])
        self.assertEqual(H.review_reasons(fake(55), ok), [])                            # 55 is not "under 55"
        self.assertEqual(H.review_reasons(fake(54.9), ok), ["Score under 55"])
        self.assertEqual(H.review_reasons(fake(), crit), [])                            # only a low score flags by default
        self.assertEqual(H.review_reasons(fake(), crit, every), ["Critical issue: Template is hard for ATS to read"])
        self.assertEqual(H.review_reasons(fake(email=False), ok), [])
        self.assertEqual(H.review_reasons(fake(email=False), ok, every), ["No email"])
        self.assertEqual(H.review_reasons(fake(phone=False), ok), [])
        self.assertEqual(H.review_reasons(fake(phone=False), ok, every), ["No phone"])

    def test_a_check_is_saved_and_opened_again(self):
        r = result()
        cid = self.store.add_check(H.record_of(r, "Tester"), T.cv_bytes())
        row = self.store.history()[0]
        self.assertEqual((row["id"], row["checked_by"], row["with_job"], row["score"], row["label"]),
                         (cid, "Tester", 0, r["score"], r["label"]))
        self.assertEqual(row["candidate"], D.candidate_name(r))
        self.assertNotIn("report_doc", row)                                             # the table stays light
        full = self.store.get(cid)
        self.assertIn(D.REPORT_TEXT["how_fix"], full["report_body"])                    # the full report, for the team
        self.assertTrue(full["report_doc"].startswith("<!doctype html>"))
        self.assertEqual(self.store.file_of(cid), T.cv_bytes())
        self.assertEqual([i["name"] for i in full["issues"]], [c["name"] for c in D.issue_cards(r)])

    def test_with_a_job_the_job_title_is_kept(self):
        cid = self.store.add_check(H.record_of(result(True), H.USER, "Delivery Lead"))
        row = self.store.get(cid)
        self.assertEqual((row["with_job"], row["job_title"], row["checked_by"]), (1, "Delivery Lead", "user"))
        self.assertIsNone(self.store.file_of(cid))

    def test_needs_review_and_mark_reviewed(self):
        good = dict(H.record_of(result(), "Tester"), review_reasons=[], review_facts=facts())
        bad = dict(good, review_reasons=["Score under 55"], review_facts=facts(score=40), candidate="Weak One")
        self.store.add_check(good)
        bid = self.store.add_check(bad)
        self.assertEqual([r["id"] for r in self.store.needs_review()], [bid])
        self.store.mark_reviewed(bid, "Sara")
        self.assertEqual(self.store.needs_review(), [])
        self.assertEqual(self.store.get(bid)["reviewed_by"], "Sara")

    def test_history_and_review_views(self):
        rec = H.record_of(result(), H.USER)
        self.store.save_setting("review_contact", True, "Tester")      # the team switched the contact trigger on
        self.store.add_check(dict(rec, review_reasons=["No phone"], review_facts=facts(no_phone=True),
                                  candidate="Needs Look"))
        self.store.add_check(dict(rec, review_reasons=[], review_facts=facts(), candidate="All Good"))
        at = AppTest.from_function(admin_app, default_timeout=120)
        at.session_state["admin"] = "Tester"
        at.session_state["admin_view"] = "History"
        at.run()
        self.assertFalse(at.exception, at.exception)
        text = all_text(at)
        self.assertLess(text.index("All Good"), text.index("Needs Look"))              # newest first
        self.assertEqual(text.count(A.ADMIN_TEXT["source_user"] + "</span>"), 2)      # both from the User page
        for col in ("col_candidate", "col_date", "col_source", "col_job", "col_score", "col_review"):
            self.assertIn(A.ADMIN_TEXT[col], text)
        at.session_state["admin_view"] = "Needs review"
        at.run()
        self.assertIn("Needs Look", all_text(at))
        self.assertNotIn("All Good", all_text(at))
        next(b for b in at.button if b.label == A.ADMIN_TEXT["open"]).click().run()     # open the report
        self.assertFalse(at.exception, at.exception)
        self.assertIn(D.REPORT_TEXT["how_fix"], all_text(at))
        next(b for b in at.button if b.label == A.ADMIN_TEXT["reviewed"]).click().run()
        self.assertIn(A.ADMIN_TEXT["no_review"], all_text(at))

    def test_files_are_deleted_after_the_set_days_and_the_report_stays(self):
        now = H.now()
        old = self.store.add_check(H.record_of(result(), "Tester"), b"%PDF-old", when=now - dt.timedelta(days=31))
        new = self.store.add_check(H.record_of(result(), "Tester"), b"%PDF-new", when=now - dt.timedelta(days=29))
        orphan = os.path.join(self.store.files, "left_over.pdf")
        with open(orphan, "wb") as f:
            f.write(b"%PDF-x")
        os.utime(orphan, ((now - dt.timedelta(days=40)).timestamp(),) * 2)
        self.assertEqual(self.store.cleanup_files(30, at=now), 1)
        self.assertIsNone(self.store.file_of(old))
        self.assertEqual(self.store.file_of(new), b"%PDF-new")
        self.assertFalse(os.path.exists(orphan))
        self.assertEqual(len(os.listdir(self.store.files)), 1)
        row = self.store.get(old)
        self.assertTrue(row["file_deleted_at"])
        self.assertEqual(row["score"], result()["score"])                               # score and report stay
        self.assertTrue(row["report_body"])
        self.assertEqual(self.store.cleanup_files(10, at=now), 1)                       # the days are a setting
        self.assertIsNone(self.store.file_of(new))

    def test_the_cleanup_runs_when_a_page_opens(self):
        import lab_pages as P
        P._store.clear()
        store = P.store()
        cid = store.add_check(H.record_of(result(), H.USER), b"%PDF-1", when=H.now() - dt.timedelta(days=3))
        os.environ["ATSLAB_FILE_DAYS"] = "2"
        AppTest.from_function(admin_app, default_timeout=120).run()
        self.assertIsNone(store.file_of(cid))


# ---------------------------------------------------------------------------
# The User page: what it shows, and what it never shows
# ---------------------------------------------------------------------------
def user_app():
    import user_page
    user_page.user()


def user_check_app(pdf):
    """The User page's check of one resume (AppTest cannot upload a file)."""
    import user_page
    import lab_pages
    lab_pages.start_page()
    if "u_result" not in __import__("streamlit").session_state:
        user_page.check({"pdf": pdf, "name": "my resume.pdf", "title": "", "text": ""})


HIDDEN = [D.REPORT_TEXT["how_fix"], "How to fix", D.REPORT_TEXT["now_ats"], "What the ATS", D.REPORT_TEXT["after_fix"],
          "Greenhouse", "Workday", "Oracle", D.REPORT_TEXT["ai"], "AI review", "AI reviewer",
          "Missing keywords", 'class="chip', D.REPORT_TEXT["download"], D.REPORT_TEXT["top_sub"], "<details",
          D.REPORT_TEXT["scale"].split("{")[0], "Details", D.IMPROVE_TEXT["title"]]
POINTS_RE = re.compile(r"\+\s?\d+(?:\.\d)?\s?(?:pts?|points?)\b|−\d|-\d+ \w+ points", re.I)


class TestUserPage(Env):
    def check_hidden(self, text, r):
        cards = D.issue_cards(r)
        for h in HIDDEN:
            self.assertNotIn(h, text, h)
        self.assertIsNone(POINTS_RE.search(text), POINTS_RE.search(text))
        for c in cards:
            if c["fix"] and len(c["fix"]) > 25:
                self.assertNotIn(D.esc(c["fix"]), text, c["key"])
        for k in r["v3"].get("keywords") or []:                     # no keyword list: a missing skill is never named
            if k["match"] == "missing" and len(k["term"]) > 3:
                self.assertNotIn(D.esc(k["term"]), text.replace(D.esc(r.get("target") or ""), ""), k["term"])

    def test_what_is_shown(self):
        for with_job in (False, True):
            r = result(with_job)
            cards = D.issue_cards(r)
            text = U.result_html(r, cards)
            with self.subTest(with_job=with_job):
                self.assertIn(f">{int(r['score'])}</div>", text)
                self.assertIn(D.esc(r["label"]), text)
                for p in r["parts"]:
                    self.assertIn(D.PART_NAMES[p], text)
                self.assertEqual("job_match" in r["parts"], with_job)
                self.assertIn("can reach about", text)
                shown, more = U.shown_issues(cards)
                self.assertTrue(1 <= len(shown) <= U.MAX_SHOWN)
                for c in shown:
                    self.assertIn(D.esc(c["name"]), text)
                    self.assertIn(D.esc(U.short_why(c)), text)
                self.assertIn(U.USER_TEXT["more"].format(n=more, s="s" if more != 1 else ""), text)
                for t in D.IMPROVE_TEXT["why"]:
                    self.assertIn(D.esc(t), U.cta_html())

    def test_what_is_never_shown(self):
        for with_job in (False, True):
            with self.subTest(with_job=with_job):
                self.check_hidden(U.result_html(result(with_job)) + U.cta_html(), result(with_job))

    def test_the_top_four_issues(self):
        card = lambda n, p, **k: dict({"name": n, "points": p, "key": n, "tag": "Minor", "why": "W."}, **k)
        shown, more = U.shown_issues([card("d", 1), card("a", 10), card("c", 3), card("b", 6), card("e", 0.5)])
        self.assertEqual(([c["name"] for c in shown], more), (["a", "b", "c", "d"], 1))  # biggest first, 4 at most
        cards = [card(str(i), 1) for i in range(12)]
        shown, more = U.shown_issues(cards)
        self.assertEqual((len(shown), more), (U.MAX_SHOWN, 8))
        self.assertEqual(U.MAX_SHOWN, 4)
        shown, more = U.shown_issues([card("ai", 50, ai=True), card("a", 2), card("b", 2)])
        self.assertEqual(([c["name"] for c in shown], more), (["a", "b"], 1))            # no AI finding shown
        shown, _ = U.shown_issues([card("x", 0.0, points_after=4)])
        self.assertEqual(len(shown), 1)                                                  # blocked: still named
        self.assertEqual(U.short_why({"why": "First line. Second line."}), "First line.")

    def test_the_page_with_a_result(self):
        os.environ["ATSLAB_PREMIUM_URL"] = "https://example.com/premium"
        os.environ["ATSLAB_BOOKING_URL"] = "https://example.com/book"
        for with_job in (False, True):
            at = AppTest.from_function(user_app, default_timeout=120)
            at.session_state["u_result"] = result(with_job)
            at.run()
            self.assertFalse(at.exception, at.exception)
            text = all_text(at)
            self.check_hidden(text, result(with_job))
            links = {b.proto.label: b.proto.url for b in at.get("link_button")}
            self.assertEqual(links, {"Get Premium": "https://example.com/premium",
                                     "Book a resume session": "https://example.com/book"})
            self.assertIn(U.USER_TEXT["privacy"].format(days=30), text)
            self.assertFalse(at.dataframe)                                               # no tables, no details
            self.assertFalse(at.expander)

    def test_upload_card_and_privacy_note(self):
        at = AppTest.from_function(user_app, default_timeout=120).run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual([t.label for t in at.text_input], [U.USER_TEXT["job_title"]])
        self.assertEqual([t.label for t in at.text_area], [U.USER_TEXT["job_text"]])
        self.assertIn(U.USER_TEXT["privacy"].format(days=30), all_text(at))
        at.button[0].click().run()
        self.assertIn("upload a resume", at.error[0].value)
        at.text_input[0].set_value("Delivery Lead")
        at.button[0].click().run()
        self.assertEqual(at.error[0].value, U.USER_TEXT["need_text"])

    def test_every_user_check_is_in_the_admin_history(self):
        import lab_pages as P
        P._store.clear()
        at = AppTest.from_function(user_check_app, args=(T.cv_bytes(),), default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        rows = P.store().history()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["checked_by"], rows[0]["file_name"], rows[0]["with_job"]),
                         ("user", "my resume.pdf", 0))
        self.assertEqual(rows[0]["id"], at.session_state["u_check_id"])
        self.assertEqual(P.store().file_of(rows[0]["id"]), T.cv_bytes())                # kept for the team

    def test_name_and_email_step_when_switched_on(self):
        import lab_pages as P
        P._store.clear()
        cid = P.store().add_check(H.record_of(result(), H.USER))
        at = AppTest.from_function(user_app, default_timeout=120)
        at.session_state["u_result"] = result()
        at.session_state["u_check_id"] = cid
        at.run()
        self.assertIn("can reach about", all_text(at))                                  # off by default: the result
        os.environ["ATSLAB_COLLECT_LEADS"] = "1"
        at.run()
        self.assertNotIn("can reach about", all_text(at))                               # on: the form first
        self.assertIn(U.USER_TEXT["lead_title"], all_text(at))
        at.text_input[0].set_value("Sam Lee")
        at.text_input[1].set_value("not-an-email")
        go = lambda: next(b for b in at.button if b.label == U.USER_TEXT["lead_go"])
        go().click().run()
        self.assertIn(U.USER_TEXT["lead_bad"], all_text(at))
        at.text_input[1].set_value("sam@example.com")
        go().click().run()
        self.assertIn("can reach about", all_text(at))
        row = P.store().get(cid)
        self.assertEqual((row["lead_name"], row["lead_email"]), ("Sam Lee", "sam@example.com"))


class TestAdminSavesItsChecks(Env):
    def test_an_admin_check_is_in_the_history(self):
        import lab_pages as P
        P._store.clear()
        r = result()
        A.saver("Tester")({"res": r, "prev": None, "inputs": {"pdf": T.cv_bytes(), "job_title": "", "client": False}})
        rows = P.store().history()
        self.assertEqual([(x["checked_by"], x["score"]) for x in rows], [("Tester", r["score"])])

    def test_a_client_comparison_keeps_its_report(self):
        import lab_pages as P
        P._store.clear()
        r = result()
        A.saver("Tester")({"res": r, "prev": r, "inputs": {"pdf": b"", "job_title": "", "client": True}})
        row = P.store().get(P.store().history()[0]["id"])
        self.assertIn(D.CLIENT_TEXT["improved"], row["comparison_doc"])
        self.assertEqual(row["compared_with"], r["cv"])


if __name__ == "__main__":
    unittest.main()
