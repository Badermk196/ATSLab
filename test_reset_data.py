"""
The clean start (reset_data.py and lab_store.Store.clear_data): empty History, Needs review (notes and
"Reviewed by"), Activity log and daily check counts, and no kept resume file - while the database structure,
the settings (links, days, limits, review rules) and the admin accounts stay.

No AI, no browser, no network: every test uses its own temporary folder.

  py -3.12 -m unittest test_reset_data -v
"""

import os
import shutil
import tempfile
import unittest

import lab_settings as S
import lab_store as H
import lab_text as T
import reset_data as R

PDF = b"%PDF-1.4 a small test resume"


def a_check(score=48, name="Sana Malik"):
    return {"checked_by": H.USER, "candidate": name, "score": score, "label": "At risk", "parts": {},
            "issues": [{"name": "No email", "severity": "Critical", "points": 5.0}],
            "review_reasons": ["No email"],
            "review_facts": {"score": score, "critical": [], "no_email": True, "no_phone": False}}


class ResetCase(unittest.TestCase):
    """A data folder with one check that needs review, a note, an activity line, a daily count and a kept file."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.saved_admins = os.environ.get("ATSLAB_ADMINS")
        self.store = H.Store(self.folder)

    def tearDown(self):
        if self.saved_admins is None:
            os.environ.pop("ATSLAB_ADMINS", None)
        else:
            os.environ["ATSLAB_ADMINS"] = self.saved_admins
        shutil.rmtree(self.folder, ignore_errors=True)

    def fill(self):
        cid = self.store.add_check(a_check(), PDF)
        self.store.mark_reviewed(cid, "Tester", "called them on Monday")
        self.store.log("Tester", "check", "Sana Malik",
                       T.LOG_DETAILS["check"].format(job="Media Director", score=48, label="At risk"))
        self.store.reserve_check(["browser:abc", "ip:local"], 3)
        self.store.login_failed(["Tester", "ip:local"], 5, 60)
        self.store.save_setting("file_days", 14, "Tester")
        self.store.save_setting("premium_url", "https://1000jobs.club/premium", "Tester")
        return cid


class TestCleanData(ResetCase):
    def test_the_clean_start_empties_the_app_and_keeps_the_settings(self):
        cid = self.fill()
        self.assertTrue(self.store.get(cid)["review_note"])
        self.assertTrue(os.path.exists(os.path.join(self.store.files, self.store.get(cid)["file_path"])))

        gone = self.store.clear_data()

        self.assertEqual(gone["checks"], 1)
        self.assertEqual(gone["files"], 1)
        self.assertEqual(self.store.history(), [])                       # History is empty
        self.assertEqual(self.store.needs_review(), [])                  # Needs review is empty
        self.assertEqual(self.store.activity(), [])                      # Activity log is empty
        self.assertEqual(self.store.checks_today(["browser:abc", "ip:local"]), 0)
        self.assertEqual(self.store.login_wait(["Tester", "ip:local"]), 0)
        self.assertEqual([n for n in os.listdir(self.store.files)], [])  # no kept resume file
        self.assertEqual(self.store.saved_settings(),
                         {"file_days": "14", "premium_url": "https://1000jobs.club/premium"})

    def test_the_database_structure_stays(self):
        self.fill()
        self.store.clear_data()
        con = self.store.db()
        try:
            tables = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            columns = {r["name"] for r in con.execute("PRAGMA table_info(checks)")}
        finally:
            con.close()
        self.assertLessEqual({"checks", "admin_log", "settings", "daily_checks", "login_guard"}, tables)
        self.assertLessEqual(set(H.COLUMNS), columns)

    def test_a_clean_start_makes_the_next_check_number_one_again(self):
        self.fill()
        self.store.clear_data()
        self.assertEqual(self.store.add_check(a_check(name="Omar Haddad"), PDF), 1)

    def test_clearing_twice_changes_nothing(self):
        self.fill()
        self.store.clear_data()
        gone = self.store.clear_data()
        self.assertEqual(gone["checks"], 0)
        self.assertEqual(gone["files"], 0)


class TestReset(ResetCase):
    def test_the_dry_run_says_what_would_go_and_changes_nothing(self):
        self.fill()
        out = R.reset(folder=self.folder, dry_run=True)
        self.assertFalse(out["done"])
        self.assertEqual(out["before"]["checks"], 1)
        self.assertEqual(out["before"]["notes"], 1)
        self.assertEqual(out["before"]["reviewed"], 1)
        self.assertEqual(out["before"]["activity"], 1)
        self.assertEqual(out["before"]["daily"], 2)
        self.assertEqual(out["before"]["sign_in"], 2)
        self.assertEqual(out["before"]["files"], 1)
        self.assertEqual(out["before"]["settings"], 2)
        self.assertEqual(self.store.history()[0]["candidate"], "Sana Malik")     # still there
        self.assertEqual(len(os.listdir(self.store.files)), 1)

    def test_the_reset_clears_the_app_data_of_the_folder(self):
        self.fill()
        out = R.reset(folder=self.folder)
        self.assertTrue(out["done"])
        self.assertEqual(out["removed"]["checks"], 1)
        self.assertEqual(out["after"]["checks"], 0)
        self.assertEqual(out["after"]["activity"], 0)
        self.assertEqual(out["after"]["daily"], 0)
        self.assertEqual(out["after"]["files"], 0)
        self.assertEqual(out["after"]["settings"], 2)                   # the settings were not touched

    def test_the_cache_folders_are_only_cleared_when_asked(self):
        caches = []
        for name in ("cv_reviews_test", "dashboard_jobs_test"):
            folder = os.path.join(self.folder, name)
            os.makedirs(folder)
            with open(os.path.join(folder, "a.json"), "w", encoding="utf-8") as f:
                f.write("{}")
            caches.append(folder)
        R.reset(folder=self.folder)                                     # no caches asked: they stay
        self.assertEqual([R.count_files(c) for c in caches], [1, 1])
        out = R.reset(folder=self.folder, caches=caches)
        self.assertEqual([R.count_files(c) for c in caches], [0, 0])
        self.assertEqual(out["before"]["caches"], {"cv_reviews_test": 1, "dashboard_jobs_test": 1})

    def test_the_reset_keeps_the_admin_accounts(self):
        os.environ["ATSLAB_ADMINS"] = '{"Tester": "a-password", "Sara": "another-one"}'
        before = S.admin_accounts()
        R.reset(folder=self.folder)
        self.assertEqual(S.admin_accounts(), before)
        self.assertEqual(sorted(before), ["Sara", "Tester"])


class TestCommandLine(ResetCase):
    def test_the_command_with_yes_clears_the_folder_without_asking(self):
        self.fill()
        self.assertEqual(R.main(["--yes", "--folder", self.folder]), 0)
        self.assertEqual(self.store.history(), [])
        self.assertEqual(self.store.activity(), [])
        self.assertEqual(self.store.saved_settings().get("file_days"), "14")

    def test_the_dry_run_command_keeps_everything(self):
        self.fill()
        self.assertEqual(R.main(["--dry-run", "--folder", self.folder]), 0)
        self.assertEqual(len(self.store.history()), 1)

    def test_caches_and_keep_caches_together_are_refused(self):
        with self.assertRaises(SystemExit):
            R.main(["--yes", "--caches", "--keep-caches", "--folder", self.folder])


if __name__ == "__main__":
    unittest.main()
