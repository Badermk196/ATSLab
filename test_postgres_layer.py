"""
The database layer (lab_db.py): the few SQLite/Postgres differences, and that the storage still works exactly as
before on a computer (the local SQLite file).

The last test in this file talks to the real Postgres database, and only runs when DATABASE_URL is set (on a
server, or on a computer that has it in .streamlit/secrets.toml). Without it, that test is skipped, so this file
is safe to run anywhere. It writes one settings row and removes it again: it never touches real data.
"""

import os
import tempfile
import unittest

import lab_db
import lab_store


class TestSqlTranslation(unittest.TestCase):
    """Only the differences the Lab really uses are translated; everything else must stay exactly as written."""

    def test_placeholders_become_percent_s(self):
        self.assertEqual(lab_db.pg_sql("SELECT * FROM checks WHERE id = ? AND score < ?"),
                         "SELECT * FROM checks WHERE id = %s AND score < %s")

    def test_two_argument_max_becomes_greatest(self):
        self.assertEqual(lab_db.pg_sql("SET n = MAX(0, n - 1)"), "SET n = GREATEST(0, n - 1)")

    def test_autoincrement_becomes_bigserial(self):
        self.assertEqual(lab_db.pg_sql("id INTEGER PRIMARY KEY AUTOINCREMENT,"),
                         "id BIGSERIAL PRIMARY KEY,")

    def test_begin_immediate_becomes_begin(self):
        self.assertEqual(lab_db.pg_sql("BEGIN IMMEDIATE"), "BEGIN")

    def test_ordinary_sql_is_left_alone(self):
        sql = ("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET "
               "value = excluded.value")
        self.assertEqual(lab_db.pg_sql(sql),
                         "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT(key) DO UPDATE SET "
                         "value = excluded.value")

    def test_the_schema_is_still_plain_sql_for_sqlite(self):
        """The schema must keep its SQLite spelling: the local file is the default on a computer."""
        self.assertIn("INTEGER PRIMARY KEY AUTOINCREMENT", lab_store.SCHEMA)
        self.assertNotIn("BIGSERIAL", lab_store.SCHEMA)


class TestRow(unittest.TestCase):
    """A Postgres row is read the same way as a SQLite row: by name and by position."""

    def setUp(self):
        self.row = lab_db.Row(["id", "score", "candidate"], (7, 71.5, "Test Person"))

    def test_by_name(self):
        self.assertEqual(self.row["score"], 71.5)

    def test_by_position(self):
        self.assertEqual(self.row[0], 7)
        self.assertEqual(self.row[2], "Test Person")

    def test_dict_and_keys(self):
        self.assertEqual(dict(self.row)["candidate"], "Test Person")
        self.assertEqual(self.row.keys(), ["id", "score", "candidate"])

    def test_get_returns_the_default_for_a_missing_column(self):
        self.assertIsNone(self.row.get("reviewed_by"))
        self.assertEqual(self.row.get("reviewed_by", "none"), "none")


class TestLocalStorage(unittest.TestCase):
    """No DATABASE_URL here: the Lab must keep using the local file and behave exactly as before."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = lab_store.Store(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def test_a_computer_uses_the_local_file(self):
        self.assertFalse(self.store.postgres)
        self.assertTrue(os.path.exists(os.path.join(self.folder.name, lab_store.DB_NAME)))

    def test_a_check_round_trip(self):
        rec = {"checked_by": "tester", "candidate": "Test Person", "file_name": "Test.pdf", "with_job": 1,
               "job_title": "Analyst", "score": 51.5, "label": "At risk", "parts": {"readable": 80},
               "issues": [{"id": "b1", "name": "Spaced headings"}], "review_reasons": ["score"],
               "review_facts": {"score": 51.5}}
        cid = self.store.add_check(rec, pdf_bytes=b"%PDF-1.4 test")
        self.assertTrue(cid)
        row = self.store.get(cid)
        self.assertEqual(row["candidate"], "Test Person")
        self.assertEqual(row["parts"], {"readable": 80})           # JSON came back as data, not as text
        self.assertEqual(row["issues"][0]["id"], "b1")
        self.assertEqual(self.store.file_of(cid), b"%PDF-1.4 test")
        self.assertEqual(len(self.store.history()), 1)
        self.assertEqual(len(self.store.needs_review()), 1)         # 51.5 is under the review limit of 55
        self.store.mark_reviewed(cid, "Bader", "looked at it")
        self.assertEqual(self.store.needs_review(), [])
        # a good score is not sent for review: the rule looks at the score, nothing else by default
        self.store.add_check({"checked_by": "tester", "candidate": "Good Person", "score": 84.5,
                              "review_facts": {"score": 84.5}})
        self.assertEqual(self.store.needs_review(), [])
        self.assertIsNotNone(self.store.delete_check(cid))
        self.assertEqual(len(self.store.history()), 1)

    def test_the_free_check_limit_is_counted_and_given_back(self):
        keys = ("browser-1", "ip-1")
        self.assertEqual(self.store.checks_today(keys), 0)
        self.assertTrue(self.store.reserve_check(keys, 3))
        self.assertTrue(self.store.reserve_check(keys, 3))
        self.assertEqual(self.store.checks_today(keys), 2)
        self.store.release_check(keys)                              # a check that ended with a message
        self.assertEqual(self.store.checks_today(keys), 1)
        self.assertTrue(self.store.reserve_check(keys, 3))
        self.assertTrue(self.store.reserve_check(keys, 3))
        self.assertFalse(self.store.reserve_check(keys, 3))          # three used: the limit is reached
        self.assertEqual(self.store.checks_today(keys), 3)

    def test_the_wrong_sign_in_counter(self):
        keys = ("Bader", "1.2.3.4")
        self.assertEqual(self.store.login_wait(keys), 0)
        self.store.login_failed(keys, 3, 60)
        self.store.login_failed(keys, 3, 60)
        self.store.login_failed(keys, 3, 60)
        self.assertGreater(self.store.login_wait(keys), 0)           # locked after three wrong tries
        self.store.login_ok(keys)
        self.assertEqual(self.store.login_wait(keys), 0)

    def test_the_activity_log_and_the_teaching_records(self):
        self.store.log("Bader", "check", target="Test Person", details="score 71.5")
        self.assertEqual(self.store.activity()[0]["kind"], "check")
        self.store.add_training("Bader", 1, "Test.pdf", "Analyst", 71.5,
                                {"name": "Spaced headings", "key": "b1", "issues": [{"id": "b1"}]},
                                "false alarm", note="not a real problem", evidence="E D U C A T I O N")
        counts = self.store.training_counts()
        self.assertEqual(counts[0]["issue_id"], "b1")
        self.assertEqual(counts[0]["times"], 1)
        self.assertEqual(self.store.clear_training(), 1)

    def test_the_settings_survive_and_can_be_cleared(self):
        self.store.save_setting("file_days", 30, "Bader")
        self.assertEqual(self.store.saved_settings()["file_days"], "30")
        self.store.clear_setting("file_days")
        self.assertNotIn("file_days", self.store.saved_settings())

    def test_staying_signed_in(self):
        self.store.remember_admin("token-1", "Bader")
        self.assertEqual(self.store.admin_of_token("token-1"), "Bader")
        self.store.forget_token("token-1")
        self.assertIsNone(self.store.admin_of_token("token-1"))

    def test_a_clean_start_empties_the_data_and_restarts_the_ids(self):
        self.store.add_check({"checked_by": "tester", "candidate": "Test Person", "score": 60}, pdf_bytes=b"x")
        self.store.log("Bader", "check")
        self.store.reserve_check(("browser-1",), 3)
        gone = self.store.clear_data()
        self.assertEqual(gone["checks"], 1)
        self.assertEqual(gone["admin_log"], 1)
        self.assertEqual(gone["files"], 1)                            # the kept resume file went with the row
        self.assertEqual(self.store.history(), [])
        self.assertEqual(self.store.activity(), [])
        self.assertEqual(self.store.checks_today(("browser-1",)), 0)
        self.assertEqual(self.store.add_check({"checked_by": "tester", "candidate": "Second"}), 1)


@unittest.skipUnless(lab_db.is_postgres(), "no DATABASE_URL: the local SQLite file is used")
class TestLivePostgres(unittest.TestCase):
    """The real database, when DATABASE_URL is set. One test row, removed again: real data is never touched."""

    def test_the_database_answers_and_the_tables_are_there(self):
        with tempfile.TemporaryDirectory() as folder:
            store = lab_store.Store(folder)                 # creates the tables if they are missing
            self.assertTrue(store.postgres)
            key = "test_postgres_layer"
            try:
                store.save_setting(key, "ok", "test")
                self.assertEqual(store.saved_settings().get(key), "ok")
            finally:
                store.clear_setting(key)
            self.assertNotIn(key, store.saved_settings())
            self.assertGreaterEqual(len(store.history(limit=1)), 0)   # a real query against the real database


if __name__ == "__main__":
    unittest.main()
