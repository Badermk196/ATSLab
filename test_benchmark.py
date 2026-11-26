"""
Tests for the Benchmark (lab_benchmark.py, the Benchmark view and the History row on the Admin page).
No AI call, no model, no Node: the Lab and the two second opinions are replaced by small fakes.

  py -3.12 -m unittest test_benchmark -v
"""

import os

os.environ["ATSLAB_AI_REVIEW"] = "0"
os.environ.pop("OPENROUTER_API_KEY", None)
import shutil
import tempfile
import time
import unittest
from unittest import mock

import lab_benchmark as B
import lab_second as SO
import lab_store as H


def cells(lab, matcher, engine, why=""):
    def one(v):
        return {"score": v, "why": why if v is None else ""}
    return {"lab": one(lab), "matcher": one(matcher), "engine": one(engine)}


def job(title, orig, new):
    return {"title": title, "orig": cells(*orig), "new": cells(*new)}


TWO = {"name": "Sara Ali", "created": "2026-11-26 10:00:00",
       "jobs": [job("Delivery Lead", (46, 40, 34), (71, 85, 60)), job("PMO Manager", (52, 55, 60), (48, 70, 82))]}


class TestColoursAndFormat(unittest.TestCase):
    def test_score_colours(self):
        self.assertEqual([B.score_tone(v) for v in (0, 49, 50, 69, 70, 100, None)],
                         ["bad", "bad", "warn", "warn", "ok", "ok", ""])

    def test_change_colours(self):
        self.assertEqual([B.change_tone(v) for v in (11, -5, 0, None)], ["ok", "bad", "", ""])

    def test_whole_percentages_and_signed_changes(self):
        self.assertEqual((B.percent(46), B.percent(None)), ("46%", "Not available"))
        self.assertEqual((B.signed(11), B.signed(-5), B.signed(0), B.signed(None)), ("+11%", "-5%", "0%", "-"))


class TestTheTables(unittest.TestCase):
    def test_one_table_per_job_and_an_across_table_for_more_than_one(self):
        tables = B.tables(TWO)
        self.assertEqual([t["title"] for t in tables], ["Delivery Lead", "PMO Manager", "Across the 2 jobs"])
        self.assertEqual([len(B.tables({"jobs": [TWO["jobs"][0]]}))], [1])             # a single job: no across table

    def test_rows_are_the_three_checkers_and_a_bold_average(self):
        rows = B.tables(TWO)[0]["rows"]
        self.assertEqual([r["name"] for r in rows], ["ATS Lab", "Resume Matcher", "VeriWorkly", "Average"])
        self.assertEqual([r["bold"] for r in rows], [False, False, False, True])
        self.assertEqual((rows[0]["orig"], rows[0]["new"], rows[0]["change"]), (46, 71, 25))
        self.assertEqual((rows[3]["orig"], rows[3]["new"], rows[3]["change"]), (40, 72, 32))

    def test_across_the_jobs_is_the_average_of_each_checker_over_all_jobs(self):
        rows = B.tables(TWO)[2]["rows"]
        self.assertEqual((rows[0]["orig"], rows[0]["new"]), (49, 60))                   # (46+52)/2, (71+48)/2 = 59.5 -> 60
        self.assertEqual((rows[1]["orig"], rows[1]["new"]), (48, 78))
        self.assertEqual((rows[2]["orig"], rows[2]["new"]), (47, 71))
        self.assertEqual(rows[3]["name"], "Average")
        self.assertEqual(rows[3]["change"], rows[3]["new"] - rows[3]["orig"])

    def test_a_checker_that_is_not_available_shows_not_available_and_the_average_uses_the_others(self):
        data = {"jobs": [job("Delivery Lead", (46, 40, 34), (71, 85, None))]}
        data["jobs"][0]["new"]["engine"]["why"] = "installing"
        table = B.tables(data)[0]
        veri = table["rows"][2]
        self.assertEqual((veri["orig"], veri["new"], veri["change"]), (34, None, None))
        self.assertEqual((table["rows"][3]["orig"], table["rows"][3]["new"]), (43, 78))   # ATS Lab + Resume Matcher only
        self.assertEqual(len(table["notes"]), 1)
        self.assertIn("VeriWorkly was not available", table["notes"][0])
        self.assertIn("still setting up", table["notes"][0])
        self.assertIn("ATS Lab and Resume Matcher", table["notes"][0])
        html = B.table_html(table)
        self.assertIn("Not available", html)

    def test_every_checker_missing_gives_an_empty_average_not_a_crash(self):
        data = {"jobs": [job("X", (None, None, None), (None, None, None))]}
        rows = B.tables(data)[0]["rows"]
        self.assertEqual((rows[3]["orig"], rows[3]["new"], rows[3]["change"]), (None, None, None))
        self.assertEqual(B.overall(data), (None, None))

    def test_the_html_has_the_colours_the_header_and_the_bold_average(self):
        html = B.table_html(B.tables(TWO)[0])
        for head in ("Checker", "Original resume", "1000Jobs resume", "Change"):
            self.assertIn(f"<th>{head}</th>", html)
        self.assertIn('<td class="a-bad">46%</td>', html)       # under 50: red
        self.assertIn('<td class="a-warn">60%</td>', html)       # 50 to 69: yellow
        self.assertIn('<td class="a-ok">71%</td>', html)         # 70 and above: green
        self.assertIn('<td class="a-ok">+25%</td>', html)
        self.assertIn("<b>Average</b>", html)
        self.assertIn('<td class="a-bad">-4%</td>', B.table_html(B.tables(TWO)[1]))    # a negative change: red

    def test_the_text_of_a_benchmark_is_escaped(self):
        data = {"jobs": [job("<script>x</script> & $5", (50, 50, 50), (60, 60, 60))]}
        self.assertNotIn("<script>", B.all_tables_html(data))


class TestTheDownloads(unittest.TestCase):
    def test_a_png_and_a_pdf_are_made(self):
        png, pdf = B.png_bytes(TWO), B.pdf_bytes(TWO)
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_the_file_name_has_the_name_and_the_date(self):
        self.assertEqual(B.file_stem(TWO), "1000Jobs Benchmark - Sara Ali - 2026-11-26")

    def test_a_long_note_still_makes_a_picture(self):
        data = {"name": "X", "jobs": [job("A", (50, 50, 50), (60, 60, None))]}
        data["jobs"][0]["new"]["engine"]["why"] = "installing"
        self.assertTrue(B.png_bytes(data).startswith(b"\x89PNG"))


class TestRunning(unittest.TestCase):
    """The run asks the Lab and the checkers per job and per resume, reuses saved answers and never raises."""
    def setUp(self):
        B._ANSWERS.clear()
        self.calls = []

        def fake_check(pdf, filename, text, title):
            self.calls.append(("lab", filename, title))
            return {"parts": {"job_match": 50.4 if filename.startswith("orig") else 71.6}, "_doc": {"modern": filename},
                    "target": title}

        def fake_run(checker, res, job_text=""):
            self.calls.append((checker, res["_doc"]["modern"]))
            if checker == "engine" and res["_doc"]["modern"].startswith("orig"):
                return {"state": SO.UNAVAILABLE, "why": "installing"}
            return {"state": SO.DONE, "score": 40.4 if res["_doc"]["modern"].startswith("orig") else 80.6,
                    "compares": "job_match"}

        self.patches = [mock.patch.object(B, "check_resume", fake_check), mock.patch.object(SO, "run", fake_run),
                        mock.patch.object(SO, "text_of", lambda res: res["_doc"]["modern"])]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        self.inputs = {"name": "Sara Ali", "original": (b"%PDF-1", "orig.pdf"),
                       "jobs": [{"title": "Delivery Lead", "text": "JD one", "pdf": b"%PDF-2", "filename": "new1.pdf"},
                                {"title": "PMO Manager", "text": "JD two", "pdf": b"%PDF-3", "filename": "new2.pdf"}]}

    def test_the_numbers_for_both_resumes_and_both_jobs(self):
        data = B.run_benchmark(self.inputs)
        first = data["jobs"][0]
        self.assertEqual(first["orig"]["lab"]["score"], 50)
        self.assertEqual(first["new"]["lab"]["score"], 72)
        self.assertEqual(first["new"]["matcher"]["score"], 81)
        self.assertEqual(first["orig"]["engine"], {"score": None, "why": "installing"})
        self.assertEqual(first["new"]["engine"]["score"], 81)
        self.assertEqual(len(data["jobs"]), 2)

    def test_a_saved_answer_is_reused_for_the_same_resume_and_job(self):
        B.run_benchmark(self.inputs)
        before = len([c for c in self.calls if c[0] == "matcher"])
        B.run_benchmark(self.inputs)
        self.assertEqual(len([c for c in self.calls if c[0] == "matcher"]), before)       # no second matcher run
        self.assertTrue(any(c[0] == "engine" for c in self.calls))
        engine_orig = [c for c in self.calls if c[0] == "engine" and c[1].startswith("orig")]
        self.assertGreater(len(engine_orig), 2)                    # a failure (still setting up) is asked again

    def test_a_job_match_less_engine_answer_is_not_available(self):
        with mock.patch.object(SO, "run", return_value={"state": SO.DONE, "score": 90, "compares": "score"}):
            out = B.ask("engine", {"_doc": {"modern": "text"}}, "job")
        self.assertEqual((out["score"], out["why"]), (None, "no_job_match"))

    def test_a_resume_the_lab_cannot_read_gives_not_available_everywhere_and_no_crash(self):
        def broken(pdf, filename, text, title):
            raise RuntimeError("This file is not a PDF.")
        with mock.patch.object(B, "check_resume", broken):
            data = B.run_benchmark(self.inputs)
        self.assertEqual(data["jobs"][0]["orig"]["lab"]["score"], None)
        self.assertFalse(B.any_number(data))

    def test_progress_messages(self):
        seen = []
        B.run_benchmark(self.inputs, lambda done, total, message: seen.append((done, total, message)))
        self.assertEqual(seen[0], (0, 12, "Job 1 of 2 · original resume · ATS Lab"))
        self.assertEqual(seen[-1], (12, 12, "Done"))
        self.assertTrue(any("1000Jobs resume · VeriWorkly" in m for _d, _t, m in seen))

    def test_the_background_run_saves_once_and_can_be_followed(self):
        saved = []
        run_id = B.start(self.inputs, "Tester", lambda data: saved.append(data) or 7)
        for _ in range(100):
            info = B.progress(run_id)
            if info["state"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(info["state"], "done", info)
        self.assertEqual((len(saved), info["history_id"]), (1, 7))
        self.assertEqual(info["done"], info["total"])

    def test_a_run_where_nothing_answers_is_an_error_and_is_not_saved(self):
        saved = []
        with mock.patch.object(B, "check_resume", side_effect=RuntimeError("nope")):
            run_id = B.start(self.inputs, "Tester", lambda data: saved.append(data))
            for _ in range(100):
                info = B.progress(run_id)
                if info["state"] != "running":
                    break
                time.sleep(0.05)
        self.assertEqual(info["state"], "error")
        self.assertEqual(saved, [])


class TestTheHistory(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="atslab-bench-")
        self.store = H.Store(self.folder)

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_a_benchmark_is_saved_with_the_label_the_name_and_the_date(self):
        cid = self.store.add_benchmark(TWO, "Tester")
        row = self.store.get(cid)
        self.assertEqual((row["label"], row["candidate"], row["checked_by"]), ("Benchmark", "Sara Ali", "Tester"))
        self.assertRegex(row["created_at"], r"^\d{4}-\d{2}-\d{2} ")
        self.assertEqual(row["parts"]["benchmark"]["jobs"][0]["title"], "Delivery Lead")
        self.assertEqual(B.overall(row["parts"]["benchmark"]), B.overall(TWO))

    def test_it_is_in_the_history_but_never_needs_review(self):
        self.store.add_benchmark({"name": "Low", "jobs": [job("X", (5, 5, 5), (6, 6, 6))]}, "Tester")
        self.assertEqual(len(self.store.history()), 1)
        self.assertEqual(self.store.history()[0]["review_reasons"], [])
        self.assertEqual(self.store.needs_review(), [])

    def test_it_can_be_deleted_like_any_record(self):
        cid = self.store.add_benchmark(TWO, "Tester")
        self.assertIsNotNone(self.store.delete_check(cid))
        self.assertEqual(self.store.history(), [])


class TestThePage(unittest.TestCase):
    """The Benchmark view on the Admin page (signed in as a test admin, its own data folder)."""
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("ATSLAB_ADMINS", "ATSLAB_DATA_DIR")}
        self.data = tempfile.mkdtemp(prefix="atslab-benchpage-")
        os.environ["ATSLAB_DATA_DIR"] = self.data
        os.environ["ATSLAB_ADMINS"] = '{"Tester": "pass-1"}'

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        shutil.rmtree(self.data, ignore_errors=True)

    def page(self):
        from streamlit.testing.v1 import AppTest

        def app():
            import admin_page
            admin_page.admin()
        at = AppTest.from_function(app, default_timeout=120)
        at.session_state["admin"] = "Tester"
        at.session_state["admin_view"] = "benchmark"
        return at

    def text(self, at):
        return "\n".join([x.value for x in at.markdown] + [x.value for x in at.error] + [b.label for b in at.button])

    def test_the_menu_has_a_benchmark_item_and_the_form_opens(self):
        at = self.page().run()
        self.assertFalse(at.exception, at.exception)
        self.assertIn("Benchmark", [b.label for b in at.sidebar.button])
        text = self.text(at)
        self.assertIn("Run benchmark", text)
        self.assertIn("Job 1", text)
        self.assertNotIn("Job 2", text)

    def test_pressing_run_with_nothing_filled_says_what_is_missing(self):
        at = self.page().run()
        at.button(key="bm_run").click().run()
        text = self.text(at)
        self.assertIn("Add the user's original resume", text)
        self.assertIn("Job 1: add the job title.", text)
        self.assertIn("Job 1: add the job description.", text)
        self.assertIn("Job 1: add the 1000Jobs resume", text)

    def test_a_finished_run_shows_the_tables_and_the_downloads(self):
        run_id = "t" * 12
        B._RUNS[run_id] = {"state": "done", "done": 12, "total": 12, "message": "Done", "data": TWO, "error": "",
                           "history_id": 1}
        try:
            at = self.page()
            at.session_state["bench_run"] = run_id
            at.run()
            self.assertFalse(at.exception, at.exception)
            text = self.text(at)
            for needle in ("Across the 2 jobs", "Delivery Lead", "PMO Manager", "Saved in History", "New benchmark"):
                self.assertIn(needle, text)
            self.assertEqual(len(at.get("download_button")), 2)
        finally:
            B.forget(run_id)

    def test_a_failed_run_says_so_and_offers_a_new_one(self):
        run_id = "e" * 12
        B._RUNS[run_id] = {"state": "error", "done": 0, "total": 12, "message": "", "data": None,
                           "error": "No checker could read these resumes.", "history_id": None}
        try:
            at = self.page()
            at.session_state["bench_run"] = run_id
            at.run()
            self.assertIn("No checker could read these resumes.", self.text(at))
            self.assertIn("New benchmark", self.text(at))
        finally:
            B.forget(run_id)

    def test_a_saved_benchmark_opens_from_the_history_and_never_counts_as_a_score(self):
        store = H.Store(self.data)
        cid = store.add_benchmark(TWO, "Tester")
        at = self.page()
        at.session_state["admin_view"] = "history"
        at.run()
        self.assertFalse(at.exception, at.exception)
        text = self.text(at)
        self.assertIn("Sara Ali", text)
        self.assertIn("Benchmark", text)
        at.session_state["open_check"] = cid
        at.run()
        self.assertFalse(at.exception, at.exception)
        self.assertIn("Across the 2 jobs", self.text(at))


if __name__ == "__main__":
    unittest.main()
