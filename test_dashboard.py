"""
Short tests for the dashboard (dashboard.py). Scoring is tested in test_ATSLab_v3.py and test_cv_score.py.
No AI calls: job keywords and role skills are copied into temporary folders.

  py -3.12 -m unittest test_dashboard -v
"""

import html
import json
import os
import re

os.environ["ATSLAB_AI_REVIEW"] = "0"      # no AI review (and no cost) in these tests
import shutil
import tempfile
import time
import unittest

from streamlit.testing.v1 import AppTest

import ATSLab_v3 as L
import cv_layout as Y
import cv_score as C
import dashboard as D

HERE = os.path.dirname(os.path.abspath(__file__))
NEDA = "NedaSefati_Creatio"
ROLE = "Delivery Lead"
ROLE_SKILLS = {"required_skills": ["Delivery Governance", "Portfolio Management", "Release Management", "Jira",
                                   "Stakeholder Management", "Risk Management"],
               "preferred_skills": ["Agile", "ServiceNow", "Power BI"]}


def cv_bytes(name=NEDA, folder="CV4"):
    with open(os.path.join(HERE, folder, name + ".pdf"), "rb") as f:
        return f.read()


def job_text(name=NEDA):
    with open(os.path.join(HERE, "JobDe", name + ".txt"), encoding="utf-8") as f:
        return f.read()


def seed(cache):
    """Saved job keywords (as if extracted before) and a saved role skill list: no AI call in tests."""
    os.makedirs(cache, exist_ok=True)
    shutil.copy(os.path.join(HERE, "JobDe", NEDA + "_keywords_v3.json"),
                D.job_file(job_text(), cache)[:-4] + "_keywords_v3.json")
    with open(C.role_skills_path(ROLE, cache), "w", encoding="utf-8") as f:
        json.dump({"role": ROLE, "prompt_version": C.ROLE_PROMPT_VERSION, "ai_runs": [ROLE_SKILLS] * 3}, f)


def page_text_without_quotes(at):
    """Page text with the quotes from the CV left out (a CV may itself say 'P1 incidents')."""
    import re
    text = re.sub(r'<div class="code[^"]*">.*?</div>', " ", page_text(at), flags=re.S)
    return re.sub(r'<div class="m">.*?</div>', " ", text, flags=re.S)      # subtitles quote counts from the CV


def page_text(at):
    """All visible text of a drawn page (headings, text, captions, messages, expander and button labels)."""
    parts = [x.value for x in at.title] + [x.value for x in at.subheader] + [x.value for x in at.markdown]
    parts += [x.value for x in at.caption] + [x.value for x in at.success] + [x.value for x in at.warning]
    parts += [x.value for x in at.error] + [x.label for x in at.expander] + [x.label for x in at.button]
    return "\n".join(str(p) for p in parts)


def results_page(with_job, with_previous):
    """A tiny app that draws the results for Neda's CV (AppTest cannot upload a file)."""
    import os
    import shutil
    import tempfile
    import dashboard as D
    import test_dashboard as T
    here = os.path.dirname(os.path.abspath(D.__file__))

    def read(folder):
        with open(os.path.join(here, folder, "NedaSefati_Creatio.pdf"), "rb") as f:
            return f.read()
    cache = tempfile.mkdtemp()
    T.seed(cache)
    text = T.job_text() if with_job else T.ROLE
    title = "Delivery Lead" if with_job else None
    res = D.run_check(read("CV4"), "neda.pdf", with_job, text, cache, cache, job_title=title)
    prev = D.run_check(read("CVS"), "neda_old.pdf", with_job, text, cache, cache, job_title=title)         if with_previous else None
    D.render(res, with_job, prev)
    shutil.rmtree(cache, ignore_errors=True)


def button(at, label):
    return next(b for b in at.button if b.label == label)


class TestDashboardLoads(unittest.TestCase):
    def test_page_loads_with_its_inputs(self):
        at = AppTest.from_file(os.path.join(HERE, "dashboard.py"), default_timeout=120).run()
        self.assertFalse(at.exception, at.exception)
        self.assertFalse(at.title)                                    # no big title: the top bar has the name
        self.assertIn(D.brand_html(), page_text(at))
        self.assertEqual(list(at.radio[0].options), [D.WITH_JOB, D.REPORT_TEXT["without"]])
        self.assertEqual(at.text_area[0].label, "Job description")
        self.assertEqual([b.label for b in at.button], [D.REPORT_TEXT["new"], "Check resume"])
        self.assertIn("Compare with a previous resume (optional)", [e.label for e in at.expander])
        at.radio[0].set_value(D.WITHOUT_JOB).run()
        self.assertFalse(at.text_input)                     # no target role: the 1000Jobs standard is the reference
        self.assertNotIn("Advanced", [e.label for e in at.expander])

    def test_check_without_a_cv_shows_a_message(self):
        at = AppTest.from_file(os.path.join(HERE, "dashboard.py"), default_timeout=120).run()
        button(at, "Check resume").click().run()
        self.assertFalse(at.exception)
        self.assertIn("upload a resume", at.error[0].value)


_REAL_MAKE_PDF = D.make_pdf


def setUpModule():
    """The pages in these tests never wait for a browser to print a PDF (test_report makes real PDFs)."""
    D.make_pdf = lambda html_doc, timeout=None: b"%PDF-1.4 " + b"0" * D.PDF_MIN_BYTES


def tearDownModule():
    D.make_pdf = _REAL_MAKE_PDF


class TestResultsPage(unittest.TestCase):
    def draw(self, with_job, with_previous=False):
        at = AppTest.from_function(results_page, args=(with_job, with_previous), default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        return at

    def check_common(self, at):
        text = page_text(at)
        for t in ("Readability", "Content", "Structure", "<svg", "resume can reach", "After top fixes",
                  "issues found", D.IMPROVE_TEXT["title"], "Why 1000Jobs", "Top issues", "Why it hurts",
                  "How to fix it", *[D.esc(t) for t in D.IMPROVE_TEXT["why"]]):
            self.assertIn(t, text)
        self.assertNotIn("CV Score", text)
        self.assertNotIn("Visual view", [h.value for h in at.subheader])
        for gone in ("Role Fit", "Completeness"):
            self.assertNotIn(gone, text)
        self.assertEqual(text.count("Biggest gain"), 1)
        self.assertEqual(text.count('<details class="iss" open>'), 1)        # the first issue opens, the rest close
        self.assertIn("Details", [e.label for e in at.expander])
        self.assertEqual([b.label for b in at.get("download_button")], [D.REPORT_TEXT["download"]])
        self.assertFalse(at.get("link_button"))                     # internal tool: no booking button
        self.assertNotIn("Book a CV session", text)
        return text

    def test_with_job(self):
        at = self.draw(True)
        text = self.check_common(at)
        self.assertIn("<h2>Job Match</h2>", text)
        self.assertIn("Checked against the job", text)
        self.assertEqual(text.count('<div class="card part'), 4)                # 4 part cards with a job

    def test_without_job(self):
        at = self.draw(False)
        text = self.check_common(at)
        self.assertNotIn("Job Match", text)                    # 3 part cards only
        self.assertEqual(text.count('<div class="card part'), 3)
        self.assertIn("Checked against the 1000Jobs resume standard", text)
        self.assertFalse([h.value for h in at.subheader if h.value.startswith("Skills recruiters search for")])

    def test_previous_cv(self):
        at = self.draw(True, with_previous=True)
        self.assertIn("Compared with the previous resume", [h.value for h in at.subheader])
        text = page_text(at)
        for t in ("Fixed since last version", "Still not fixed", "Template is hard for ATS to read"):
            self.assertIn(t, text)

    def test_no_codes_anywhere(self):
        """No internal id (B1, R3, C1, P6, K...) written by the dashboard. A word from the CV itself
        (a skill like 'Primavera P6', 'P1 incidents') is the candidate's own text and may be shown."""
        import re
        cv_words = set()
        for folder in ("CV4", "CVS"):
            cv_words |= set(re.findall(r"\w+", L.extract_cv(os.path.join(HERE, folder, NEDA + ".pdf"))["modern"]))
        for with_job, prev in ((True, True), (False, False)):
            text = page_text_without_quotes(self.draw(with_job, prev))
            bad = [m for m in D.CODE_RE.finditer(text) if m.group() not in cv_words]
            with self.subTest(with_job=with_job):
                self.assertFalse(bad, bad and text[max(0, bad[0].start() - 60):bad[0].end() + 60])


class TestScoreAndCards(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()
        seed(self.cache)

    def tearDown(self):
        shutil.rmtree(self.cache, ignore_errors=True)

    def test_big_circle_is_the_cv_score_not_readability(self):
        r = D.run_check(cv_bytes(), "neda.pdf", False, ROLE, self.cache, self.cache)
        self.assertIn("score", r)
        self.assertEqual(set(r["parts"]), {"readability", "content", "structure"})
        self.assertTrue(set(r["parts"]) <= set(D.PART_NAMES))
        g = D.gauge(r["score"], 200, "Resume Score", r["label"])
        self.assertIn(f">{round(r['score'])}</text>", g)
        self.assertNotAlmostEqual(r["score"], r["parts"]["readability"], places=0)

    def test_every_issue_id_has_plain_texts(self):
        r = D.run_check(cv_bytes(), "neda.pdf", True, job_text(), self.cache, self.cache, job_title="Delivery Lead")
        ids = {b["code"] for b in L.BUGS} | {i for p in r["v3"]["ats"] for i in r["v3"]["ats"][p]["checks"]}
        ids |= set(C.CONTENT_WEIGHT) | set(C.STRUCT_WEIGHT) | {"K"}
        self.assertEqual(sorted(i for i in ids if i not in D.ISSUE_OF), [], "add these to ISSUES")
        for key, v in D.ISSUES.items():
            for field in ("name", "why", "fix", "we_fix"):
                self.assertTrue(v[field].strip(), (key, field))
                self.assertIsNone(D.CODE_RE.search(v[field]), (key, field))
            self.assertTrue(v["why"].endswith(".") and v["fix"].endswith(".") and v["we_fix"].endswith("."), key)

    def test_cards_sorted_tagged_and_quoted(self):
        r = D.run_check(cv_bytes(NEDA, "CVS"), "neda.pdf", False, ROLE, self.cache, self.cache)
        cards = D.issue_cards(r)
        self.assertTrue(cards)
        self.assertEqual([c["points"] for c in cards], sorted((c["points"] for c in cards), reverse=True))
        self.assertTrue(all(c["tag"] in D.SHOWN_SEVERITY.values() for c in cards))
        self.assertEqual(len({c["key"] for c in cards}), len(cards))            # one card per issue
        spaced = next(c for c in cards if c["key"] == "template")     # letter-spaced headings: the template card
        self.assertEqual(spaced["tag"], "Minor")                      # rule 4: only layout problems are Critical
        self.assertIn("letter-spaced headings", spaced["issues"][0]["reasons"])
        quotes = [c for c in cards if ISSUE_SHOW(c) == "quotes"]
        for c in quotes:
            if c["key"] in ("pages", "photo", "length"):       # a fact about the page, not a line to quote
                self.assertTrue(D.evidence(c, r))
                continue
            for q in D.evidence(c, r):
                m = re.search(r'"(.+?)"', q)                      # 'Text in a box: "..."' -> the quoted CV text
                q = m.group(1) if m else re.sub(r"^\(\d+ words\) ", "", q)
                cv_words = set(r["_doc"]["modern"].split()) | set(r["_vdoc"]["modern"].split())
                words = q.replace("…", " ").replace(" / ", " ").split()[:4]        # a long sentence is cut: '...'
                self.assertTrue(all(w in cv_words for w in words), (c["name"], q))


class TestEveryCardQuotes(unittest.TestCase):
    """Every issue card shows at least one real line from the CV (never 'nothing to show')."""

    CASES = [("CV4/Tareq Al Masri CV JN26.pdf", "Media Director"),
             ("CV4/jibran-original-cv.pdf", "Logistics Coordinator"),
             ("CVS/profile-user-2UXAuWAmUaH2A5vU-1790959538885-ynuipc.pdf", "Senior Product Manager"),
             ("CV4/rashaadnmohammed_Cohere.pdf", "Software Engineering Intern"),
             ("CVS/NedaSefati_Creatio.pdf", "Delivery Lead")]

    def test_each_card_has_a_quote(self):
        for path, role in self.CASES:
            full = os.path.join(HERE, path)
            if not os.path.exists(full) or not os.path.exists(C.role_skills_path(role)):
                continue                                   # a CV or a saved role list not present on this machine
            with open(full, "rb") as f:
                r = D.run_check(f.read(), os.path.basename(path), False, role)
            for c in D.issue_cards(r):
                ev = D.evidence(c, r)
                with self.subTest(cv=path, card=c["name"]):
                    self.assertTrue(ev and all(e.strip() for e in ev), c["name"])
                    if D.ISSUES[c["key"]]["show"] in ("dates", "job_lines"):
                        flat = " ".join(r["_vdoc"]["modern"].split())
                        self.assertIn(" ".join(ev[0].split("  (")[0].split()[:3]), flat)   # a real job line


class TestOldResults(unittest.TestCase):
    """A CV checked before the layout checks existed (old result or old module in memory) is recalculated,
    never 'KeyError: layout'."""

    def setUp(self):
        self.cache = tempfile.mkdtemp()
        seed(self.cache)

    def tearDown(self):
        shutil.rmtree(self.cache, ignore_errors=True)

    def old_result(self):
        r = D.run_check(cv_bytes(), "neda.pdf", False, ROLE, self.cache, self.cache)
        for k in ("layout", "version", "_pages", "_vdoc"):        # what a result looked like before the layout checks
            r.pop(k, None)
        return r

    def test_old_module_in_memory_is_reloaded(self):
        """The reported bug: the dashboard kept running while cv_score.py changed on disk."""
        old = self.old_result()
        real_version = C.SCORE_VERSION
        C.score_cv = lambda *a, **k: dict(old)                      # the old module: results without 'layout'
        C.SCORE_VERSION = "2026-10-15.before-layout"
        r = D.run_check(cv_bytes(), "neda.pdf", False, ROLE, self.cache, self.cache)
        self.assertEqual(C.SCORE_VERSION, real_version)            # reloaded from disk
        self.assertTrue(D.is_current(r))
        self.assertIn("layout", r)
        self.assertIsNotNone(r["layout"])

    def test_old_result_in_the_page_is_recalculated(self):
        old = self.old_result()
        self.assertFalse(D.is_current(old))
        at = AppTest.from_file(os.path.join(HERE, "dashboard.py"), default_timeout=300)
        at.session_state["result"] = {"res": old, "with_job": False, "prev": None,
                                      "inputs": {"pdf": cv_bytes(), "name": "neda.pdf", "with_job": False,
                                                 "text": ROLE, "prev_pdf": None, "prev_name": None}}
        at.run()
        self.assertFalse(at.exception, at.exception)
        self.assertFalse(at.error, [e.value for e in at.error])
        self.assertIn("calculated again", " ".join(i.value for i in at.info))
        self.assertIn("<h2>Top issues</h2>", page_text(at))
        self.assertTrue(D.is_current(at.session_state["result"]["res"]))

    def test_old_result_without_inputs_asks_to_check_again(self):
        at = AppTest.from_file(os.path.join(HERE, "dashboard.py"), default_timeout=300)
        at.session_state["result"] = (self.old_result(), False, None)   # the form used before this fix
        at.run()
        self.assertFalse(at.exception, at.exception)
        self.assertIn("Check resume", " ".join(i.value for i in at.info))
        self.assertNotIn("<h2>Top issues</h2>", page_text(at))

    def test_tareq_without_a_job_description(self):
        path = os.path.join(HERE, "CV4", "Tareq Al Masri CV JN26.pdf")
        if not os.path.exists(path) or not os.path.exists(C.role_skills_path("Media Director")):
            self.skipTest("Tareq's CV or the saved 'Media Director' skills are not on this machine")
        with open(path, "rb") as f:
            r = D.run_check(f.read(), "Tareq_Al_Masri_CV_JN26_1.pdf", False, "Media Director")
        self.assertTrue(D.is_current(r))
        self.assertTrue(r["layout"]["columns_found"])
        self.assertNotIn("_pages", r)                                # no page images: the Visual view is gone


def ISSUE_SHOW(card):
    return D.ISSUES[card["key"]]["show"]


class TestRunCheck(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()
        seed(self.cache)

    def tearDown(self):
        shutil.rmtree(self.cache, ignore_errors=True)

    def test_with_job_reuses_saved_keywords(self):
        text = job_text()
        path = D.job_file(text, self.cache)
        r = D.run_check(cv_bytes(), "neda.pdf", True, text, self.cache, self.cache, job_title="Delivery Lead")
        self.assertEqual(r["mode"], "job")
        self.assertTrue(os.path.exists(path))
        self.assertEqual(r["parts"]["job_match"], r["v3"]["headline"]["job_match"])
        self.assertEqual(set(r["parts"]), set(D.PART_NAMES))         # with a job: 4 parts
        self.assertEqual(D.job_file("  " + text.replace("\n", " \n ") + " ", self.cache), path)   # spaces ignored

    def test_clear_errors(self):
        with self.assertRaisesRegex(D.CheckError, "not a PDF"):
            D.run_check(b"hello", "cv.txt", False, "Analyst", self.cache, self.cache)
        with self.assertRaisesRegex(D.CheckError, "save your resume as a PDF"):          # v1.2: a Word file
            D.run_check(b"hello", "cv.docx", False, "Analyst", self.cache, self.cache)
        with self.assertRaisesRegex(D.CheckError, "empty"):
            D.run_check(cv_bytes(), "cv.pdf", True, "   ", self.cache, self.cache)
        with self.assertRaisesRegex(D.CheckError, "does not look like a job"):
            D.run_check(cv_bytes(), "cv.pdf", True, "<!DOCTYPE html><html><body>x</body></html>", self.cache)
        key = os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            with self.assertRaisesRegex(D.CheckError, "API key is missing"):
                D.run_check(cv_bytes(), "cv.pdf", True, job_text() + "\nNew line so this job is not cached.",
                            self.cache, self.cache, job_title="Delivery Lead")
            r = D.run_check(cv_bytes(), "cv.pdf", False, "", self.cache, self.cache)   # no job: no AI needed
            self.assertEqual(set(r["parts"]), {"readability", "content", "structure"})
        finally:
            if key is not None:
                os.environ["OPENROUTER_API_KEY"] = key


def mohamed_result(test):
    path = os.path.join(HERE, "testcvs", "MohamedShokry-original.pdf")
    if not os.path.exists(path):
        test.skipTest("Mohamed's original CV is not on this machine")
    with open(path, "rb") as f:
        return D.run_check(f.read(), "mohamed.pdf", False, "")


class TestImproveList(unittest.TestCase):
    def test_what_we_fix_is_tied_to_real_issues_at_most_four_no_repeats(self):
        r = mohamed_result(self)
        cards = D.issue_cards(r)
        items = D.improve_items(cards)
        self.assertEqual(D.MAX_IMPROVE, 4)
        self.assertEqual(len(items), D.MAX_IMPROVE)                # many issues: the 4 biggest
        self.assertEqual(len(items), len({x["fix"] for x in items}))
        names = [c["name"] for c in cards]
        for x in items:                                            # each line names an issue found in this resume
            self.assertIn(x["issue"], names)
            self.assertEqual(x["fix"], next(c["we_fix"] for c in cards if c["name"] == x["issue"]))
        self.assertEqual(items[0]["fix"], D.ISSUES["headline"]["we_fix"])     # the biggest gain comes first
        html_ = D.improve_html(cards)
        for t in D.IMPROVE_TEXT["why"]:
            self.assertIn(html.escape(t), html_)
        self.assertEqual(len(D.IMPROVE_TEXT["why"]), 3)
        self.assertIn(html.escape(D.IMPROVE_TEXT["nothing"]), D.improve_html([]))   # no issue: no generic fixes


class TestWhyScore(unittest.TestCase):
    """'Why <score>?' under each circle lists the issues of that part, and their points add up to the part's
    loss (100 - part score), from the scorer's own numbers."""

    def check(self, r):
        for part, value in r["parts"].items():
            with self.subTest(part=part):
                w = D.why_part(r, part)
                e = r["part_explain"][part]
                self.assertAlmostEqual(e["loss"], 100 - value, places=1)
                self.assertAlmostEqual(sum(x["points"] for x in e["items"]) + e["other"], e["loss"], places=1)
                self.assertAlmostEqual(sum(p for _, p in w["items"]) + w["other"], e["loss"], places=1)
                self.assertLessEqual(len(w["items"]), D.MAX_WHY_ISSUES)
                self.assertLessEqual(len(w["good"]), D.MAX_WHY_GOOD)
                pts = [p for _, p in w["items"]]
                self.assertEqual(pts, sorted(pts, reverse=True))
                own = {i["id"] for i in r["issues"] if i["part"] == part}
                self.assertTrue(all(x["id"] in own for x in e["items"]))      # only issues of this part
                self.assertTrue(all(i["part_points"] > 0 for i in r["issues"] if i["part"] == part
                                    and i["id"] in {x["id"] for x in e["items"]}))
                self.assertLess(abs(e["other"]), 2.5, e)                    # almost all the loss is explained
                self.assertIsNone(D.CODE_RE.search(D.part_card_html(r, part)))

    def test_mohamed(self):
        r = mohamed_result(self)
        self.check(r)
        w = D.why_part(r, "readability")
        names = [n for n, _ in w["items"]]
        self.assertIn(D.ISSUES["name_spacing"]["name"], names)        # only the name is letter-spaced (v1.1)
        self.assertNotIn(D.ISSUES["template"]["name"], names)
        self.assertIn("Name has letter spacing</span>", D.part_card_html(r, "readability"))
        self.assertAlmostEqual(sum(p for _, p in w["items"]) + w["other"], 100 - r["parts"]["readability"], delta=0.2)
        n1 = next(i for i in r["issues"] if i["id"] == "N1")
        self.assertEqual(n1["severity"], "Minor")
        self.assertNotIn("Abbreviations", " ".join(n for n, _ in w["items"]))     # a font issue keeps its own name
        c = D.why_part(r, "content")
        self.assertEqual(c["items"][0][0], D.ISSUES["headline"]["name"])

    def test_with_a_job_and_a_layout_cv(self):
        cache = tempfile.mkdtemp()
        try:
            seed(cache)
            r = D.run_check(cv_bytes(), "neda.pdf", True, job_text(), cache, cache, job_title="Delivery Lead")
            self.assertIn("job_match", r["part_explain"])
            self.check(r)
        finally:
            shutil.rmtree(cache, ignore_errors=True)
        tareq = os.path.join(HERE, "CV4", "Tareq Al Masri CV JN26.pdf")
        if os.path.exists(tareq):                                 # penalties above the cap: scaled, still add up
            with open(tareq, "rb") as f:
                self.check(D.run_check(f.read(), "tareq.pdf", False, ""))

    def test_perfect_part_and_blocked_line(self):
        issue = {"id": "C1", "part": "content", "name": "x", "points": 0.0, "blocked_by": "readability"}
        r = {"issues": [issue], "parts": {"content": 96.0, "structure": 100.0},
             "part_explain": {"content": {"loss": 4.0, "items": [{"id": "C1", "name": "x", "points": 4.0}],
                                          "other": 0.0},
                              "structure": {"loss": 0.0, "items": [], "other": 0.0}}}
        cards = [{"name": D.ISSUES["numbers"]["name"], "issues": [issue], "points": 0.0}]
        w = D.why_part(r, "content", cards)
        self.assertEqual(w["items"], [(D.ISSUES["numbers"]["name"], 4.0)])
        self.assertEqual(w["blocked"], "Fix the layout issues first: until then, fixes here add little to your "
                                       "Resume Score.")
        s = D.why_part(r, "structure", cards)
        self.assertEqual(len(s["good"]), 2)
        self.assertIn(D.REPORT_TEXT["perfect"], D.part_card_html(r, "structure", cards=cards))


EDGE = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                          r"C:\Program Files\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)


def tareq_result(test):
    path = os.path.join(HERE, "CV4", "Tareq Al Masri CV JN26.pdf")
    if not os.path.exists(path):
        test.skipTest("Tareq's CV is not on this machine")
    with open(path, "rb") as f:
        return D.run_check(f.read(), "Tareq Al Masri CV JN26.pdf", False, "")


class TestReport(unittest.TestCase):
    """The redesigned report: every number from the scorer, one points scale, counts from the resume, and a
    downloadable report that prints without cut or overlapping text."""

    @classmethod
    def setUpClass(cls):
        cls.r = mohamed_result(cls)
        cls.cards = D.issue_cards(cls.r)

    def test_score_card_numbers_come_from_the_scorer(self):
        r, cards = self.r, self.cards
        s = D.report_summary(r, cards)
        top = D.top_cards(cards)
        self.assertEqual(s["n_fix"], len(top))
        self.assertLessEqual(s["n_fix"], D.TOP_CARDS)
        self.assertEqual(s["after"], min(D.MAX_PROMISE, r["_score_with"]([i["id"] for c in top for i in c["issues"]])))
        self.assertGreater(s["after"], s["now"])
        self.assertAlmostEqual(s["available"], round(s["after"] - s["now"], 1), places=1)
        self.assertEqual((s["found"], s["important"]), (len(cards), sum(c["severity"] == "Major" for c in cards)))
        self.assertEqual(r["_score_with"]([]), r["score"])                       # nothing fixed: the same score
        self.assertEqual(r["_score_with"]([i["id"] for i in r["issues"]]), 100.0)  # everything fixed
        gains = {p: r["_score_with"]([i["id"] for i in r["issues"] if i["part"] == p]) for p in r["parts"]}
        self.assertEqual(s["best_part"], max(gains, key=gains.get))
        html_ = D.score_html(r, cards)
        self.assertIn(f"Mohamed's resume can reach about <b>{D.fmt(s['after'])}</b> by fixing {s['n_fix']} issues.",
                      html_)
        self.assertIn(f"After top fixes: about {D.fmt(s['after'])}", html_)
        self.assertEqual(D.parts_html(r, cards).count("Biggest gain"), 1)

    def test_one_points_scale(self):
        """+pts = Resume Score points (the same on the issue card, the part card and the fix list); the part card
        and the issue subtitle show the same part points."""
        r, cards = self.r, self.cards
        for n, c in enumerate(cards, 1):
            with self.subTest(card=c["name"]):
                h = D.issue_html(n, c, r)
                if c["points"] >= 0.1:
                    self.assertIn(f'+{D.fmt(c["points"])} pt', h)
                part = D.card_part(c)
                w = D.why_part(r, part, cards)
                row = dict(w["items"]).get(c["name"])
                if row is not None and D.part_points(c) >= 0.1:
                    self.assertEqual(D.fmt(row), D.fmt(D.part_points(c)))
                    self.assertIn(D.REPORT_TEXT["part_cost"].format(p=D.fmt(row), part=D.PART_NAMES[part]), h)
                    self.assertEqual(w["gains"][c["name"]], c["points"])
        for x in D.improve_items(cards):
            c = next(c for c in cards if c["name"] == x["issue"])
            self.assertEqual(x["points"], c["points"])

    def test_counts_come_from_the_resume(self):
        r, cards = self.r, self.cards
        text = r["_vdoc"]["modern"]
        labels = next(c for c in cards if c["key"] == "job_labels")
        n = sum(1 for l in text.splitlines() if l.strip() == "Key Accomplishments:")
        self.assertGreater(n, 0)
        self.assertEqual(D.count_note(labels, r), f'"Key Accomplishments:" appears {n} times')
        self.assertFalse([c for c in cards if c["key"] == "repeated_numbers"])    # $25M three times: not flagged now
        fake = {"_doc": {"modern": ""}, "content_checks": {"C9": {"detail": "same result repeated: $25M (4 times)"}}}
        self.assertIn('"$25M" used 4 times', D.count_note({"key": "repeated_numbers"}, fake))
        self.assertFalse([c for c in cards if c["key"] == "summary"])     # a summary under 150 words is not flagged
        phone = next(c for c in cards if c["key"] == "phone")
        self.assertEqual(D.count_note(phone, r), "(+971) 585-516-848 \u2192 +971 58 551 6848")

    def test_before_and_after(self):
        r, cards = self.r, self.cards
        head = next(c for c in cards if c["key"] == "headline")
        cap, now, after = D.before_after(head, r)
        self.assertEqual(cap, D.REPORT_TEXT["now_ats"])
        self.assertEqual(now, ["Not found in your resume"])          # no headline: never quote just the name
        self.assertEqual(after[0], ("MOHAMED SHOKRY, MBA", False))
        self.assertEqual(after[1], ("[Target title] | [Strength] | [Strength]", True))
        phone = next(c for c in cards if c["key"] == "phone")
        self.assertIn("+971 58 551 6848", D.before_after(phone, r)[2][0][0])
        labels = next(c for c in cards if c["key"] == "job_labels")
        _, now, after = D.before_after(labels, r)
        self.assertIn("Key Accomplishments:", now)
        self.assertNotIn("Key Accomplishments:", [l for l, _ in after])
        self.assertEqual(D.phone_fixed("(+971) 585-516-848"), "+971 58 551 6848")
        self.assertEqual(D.phone_fixed("0505017855"), "+971 50 501 7855")          # a UAE mobile number
        self.assertEqual(D.phone_fixed("0412345678"), "+[country code] 41 234 5678")
        self.assertEqual(D.month_placeholders("Ecommerce Lead 2019 - 2020"), "Ecommerce Lead [Mon] 2019 - [Mon] 2020")
        self.assertEqual(D.month_placeholders("Lead | Mar 2019 - 2020"), "Lead | Mar 2019 - [Mon] 2020")

    def test_names(self):
        self.assertEqual(D.readable_name(self.r), ("MOHAMED SHOKRY, MBA", "Mohamed"))
        self.assertEqual(D.readable_name(tareq_result(self))[1], "Tareq")       # not "Work" (a heading)
        for bad in ("Work Experience", "Senior Product Manager", "jane@mail.com", "PROFESSIONAL SUMMARY"):
            self.assertFalse(D.looks_like_name(bad), bad)
        for good in ("Tareq Al Masri", "NEDA SEFATI", "Shikha Sureka"):
            self.assertTrue(D.looks_like_name(good), good)

    def test_downloadable_report(self):
        doc = D.report_document(self.r, self.cards)
        self.assertTrue(doc.startswith("<!doctype html>"))
        self.assertEqual(doc.count('<details class="iss" open>'), len(self.cards))   # every issue open
        self.assertIn('<details class="more" open>', doc)
        for t in ("@media print", "break-inside: avoid", "@page"):
            self.assertIn(t, doc)
        self.assertNotIn("position: fixed", doc)

    def test_report_prints_without_overlap(self):
        """Print the report with the browser (Edge / Chrome, headless) and check every page of the PDF:
        no two words overlap, nothing runs off the page, every issue is in it."""
        if not EDGE:
            self.skipTest("no Edge or Chrome to print with")
        import subprocess
        import pdfplumber
        tmp = tempfile.mkdtemp()
        try:
            for r in (self.r, tareq_result(self)):
                cards = D.issue_cards(r)
                src, pdf = os.path.join(tmp, "report.html"), os.path.join(tmp, "report.pdf")
                with open(src, "w", encoding="utf-8") as f:
                    f.write(D.report_document(r, cards))
                subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                                f"--user-data-dir={os.path.join(tmp, 'profile')}", f"--print-to-pdf={pdf}",
                                "file:///" + src.replace("\\", "/")], check=True, timeout=180,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                text = ""
                with pdfplumber.open(pdf) as p:
                    for n, page in enumerate(p.pages, 1):
                        words = page.extract_words()
                        text += " ".join(w["text"] for w in words) + " "
                        for w in words:
                            self.assertTrue(0 <= w["x0"] and w["x1"] <= page.width + 0.5, (n, w["text"]))
                        for a in range(len(words)):
                            for b in range(a + 1, len(words)):
                                u, v = words[a], words[b]
                                dx = min(u["x1"], v["x1"]) - max(u["x0"], v["x0"])
                                dy = min(u["bottom"], v["bottom"]) - max(u["top"], v["top"])
                                self.assertFalse(dx > 1.5 and dy > 1.5, (r["cv"], n, u["text"], v["text"]))
                flat = re.sub(r"\s+", " ", text)
                for c in cards:
                    self.assertIn(" ".join(c["name"].split()[:3]), flat, c["name"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestTopBar(unittest.TestCase):
    """The slim top bar of the design: before a check the upload card shows; after a check it hides and the score
    card comes right under the bar; 'Check new resume' brings the upload card back."""

    @classmethod
    def setUpClass(cls):
        cls.r = mohamed_result(cls)
        with open(os.path.join(HERE, "testcvs", "MohamedShokry-original.pdf"), "rb") as f:
            cls.pdf = f.read()

    def page_with_result(self):
        at = AppTest.from_file(os.path.join(HERE, "dashboard.py"), default_timeout=300)
        at.session_state["result"] = {"res": self.r, "with_job": False, "prev": None,
                                      "inputs": {"pdf": self.pdf, "name": "mohamed.pdf", "with_job": False,
                                                 "text": "", "prev_pdf": None, "prev_name": None}}
        at.run()
        self.assertFalse(at.exception, at.exception)
        return at

    def test_before_a_check_the_upload_card_shows(self):
        at = AppTest.from_file(os.path.join(HERE, "dashboard.py"), default_timeout=120).run()
        self.assertEqual(len(at.get("file_uploader")), 2)              # the resume and the previous version
        self.assertNotIn('class="atsl-chip"', page_text(at))           # no file checked yet: no file chip
        self.assertEqual([t.label for t in at.text_area], ["Job description"])
        at.radio[0].set_value(D.WITHOUT_JOB).run()
        self.assertFalse(at.text_area)                                 # no job box without a job description

    def test_after_a_check_the_upload_card_hides(self):
        at = self.page_with_result()
        self.assertFalse(at.get("file_uploader"))
        self.assertEqual([b.label for b in at.button], [D.REPORT_TEXT["new"]])
        text = page_text(at)
        self.assertIn(D.file_chip_html(self.r), text)                  # name and size in the top bar
        self.assertIn("62.7 KB", text)
        self.assertEqual(at.radio[0].value, D.WITHOUT_JOB)             # the switch shows how it was checked
        blocks = [m.value for m in at.markdown]
        first = next(k for k, v in enumerate(blocks) if "class=\"rp\"" in v)
        self.assertIn("resume can reach", blocks[first])               # the score card comes first
        self.assertNotIn('class="hdr"', text)                          # no second file chip above the score card

    def test_check_new_resume_shows_the_upload_card_again(self):
        at = self.page_with_result()
        button(at, D.REPORT_TEXT["new"]).click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertNotIn("result", at.session_state)
        self.assertEqual(len(at.get("file_uploader")), 2)
        self.assertIn("Check resume", [b.label for b in at.button])
        self.assertNotIn("resume can reach", page_text(at))

    def test_switch_after_a_check_offers_to_check_again(self):
        at = self.page_with_result()
        at.radio[0].set_value(D.WITH_JOB).run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual([t.label for t in at.text_area], ["Job description"])
        self.assertIn(D.REPORT_TEXT["again"], [b.label for b in at.button])
        self.assertIn("resume can reach", page_text(at))                # the result stays until checked again

    def test_blue_not_red(self):
        self.assertIn(D.BLUE, D.CSS)
        for red in ("#ff4b4b", "#FF4B4B", "rgb(255, 75, 75)"):
            self.assertNotIn(red, D.CSS)
        # v1.4: the app's theme is the redesign's indigo (light and dark), never Streamlit's red
        import re
        import tomllib
        import lab_ui
        with open(os.path.join(HERE, ".streamlit", "config.toml"), "rb") as f:
            theme = tomllib.load(f)["theme"]
        light, dark = lab_ui.PALETTE.split("@media (prefers-color-scheme: dark)")
        pri = lambda part: re.search(r"--a-pri: (#[0-9a-f]{6})", part).group(1)
        self.assertEqual(theme["light"]["primaryColor"], pri(light))
        self.assertEqual(theme["dark"]["primaryColor"], pri(dark))
        self.assertNotIn("#ff4b4b", str(theme).lower())
        self.assertIn("Plus Jakarta Sans", D.CSS)


LAST_TEST = {"shikha": ("CVS", "profile-user-2UXAuWAmUaH2A5vU-1790959538885-ynuipc.pdf"),
             "jibran": ("CV4", "jibran-original-cv.pdf"), "tareq": ("CV4", "Tareq Al Masri CV JN26.pdf"),
             "marsh": ("testcvs", "TareqAlMasri_MarshMcLennan.pdf")}
MARSH_JOB = os.path.join(HERE, "dashboard_jobs", "job_44e0c222d5572771.txt")


class TestFixesOnRealResumes(unittest.TestCase):
    """The 2026-10-21 fixes on the resumes of the last test (an original Shikha, Jibran and Tareq, and a
    1000jobs-generated Tareq checked against the Marsh McLennan job)."""

    @classmethod
    def setUpClass(cls):
        cls.r = {}
        for key, (folder, name) in LAST_TEST.items():
            path = os.path.join(HERE, folder, name)
            if not os.path.exists(path):
                continue
            with_job = key == "marsh" and os.path.exists(MARSH_JOB)
            text = open(MARSH_JOB, encoding="utf-8").read() if with_job else ""
            with open(path, "rb") as f:
                cls.r[key] = D.run_check(f.read(), name, with_job, text, job_title="Media Director" if with_job else None)

    def each(self):
        if not self.r:
            self.skipTest("the resumes of the last test are not on this machine")
        return self.r.items()

    def test_never_promise_more_than_95(self):
        for key, r in self.each():
            s = D.report_summary(r, D.issue_cards(r))
            self.assertLessEqual(s["after"], 95, key)
            self.assertIn("can reach about", D.score_html(r, D.issue_cards(r)) if s["n_fix"] else "can reach about")
        r = dict(next(iter(self.r.values())), _score_with=lambda ids: 100.0)
        self.assertEqual(D.report_summary(r, D.issue_cards(r))["after"], 95)

    def test_if_fixed_never_more_than_it_costs(self):
        for key, r in self.each():
            for i in r["issues"]:
                if i["part_points"] > 0:
                    self.assertLessEqual(i["points"], i["part_points"], (key, i["name"]))
            for c in D.issue_cards(r):
                if D.part_points(c) > 0:
                    self.assertLessEqual(c["points"], D.part_points(c), (key, c["name"]))

    def test_cards_merge_only_the_same_cause(self):
        for key, r in self.each():
            cards = D.issue_cards(r)
            self.assertFalse([c for c in cards if c.get("also")], key)
            for c in cards:
                if c.get("ai"):
                    self.assertEqual(len(c["issues"]), 1)
                else:
                    self.assertEqual({D.ISSUE_OF[i["id"]] for i in c["issues"]}, {c["key"]}, (key, c["name"]))
        if "marsh" in self.r:
            keys = {c["key"] for c in D.issue_cards(self.r["marsh"])}
            for separate in ("repeated_numbers", "repeated", "glance_boxes"):
                self.assertIn(separate, keys)                    # each its own card, none merged into another

    def test_one_part_per_issue(self):
        owned = set(C.STANDARD_OWNS) | {"B4", "B11", "R12"}
        for key, r in self.each():
            for c in D.issue_cards(r):
                self.assertEqual(len({i["part"] for i in c["issues"]}), 1, (key, c["name"]))
            self.assertFalse([i["id"] for i in r["issues"] if i["id"] in owned], key)
        if "tareq" in self.r:                                     # the 60-word summary is not flagged any more
            t = self.r["tareq"]
            self.assertEqual(t["content_checks"]["C4"]["words"], 60)
            self.assertFalse([c for c in D.issue_cards(t) if c["key"] == "summary"])
            edu = [c for c in D.issue_cards(t) if c["key"] == "education_details"]
            self.assertLessEqual(len(edu), 1)
            self.assertTrue(all(D.card_part(c) == "structure" for c in edu))

    def test_same_issue_same_severity(self):
        bugs = {b["code"]: b["severity"] for b in L.BUGS}
        for key, r in self.each():
            for i in r["issues"]:
                if i.get("ai") or i["id"].startswith(("D", "N")) or i["id"] in bugs:
                    continue
                self.assertEqual(i["severity"], C.rule_severity(i["id"], r["content_checks"], r["structure_checks"],
                                                               r["v3"]), (key, i["id"]))

    def test_new_checks_on_real_resumes(self):
        for key in ("tareq", "marsh"):
            if key in self.r:
                t11 = self.r[key]["structure_checks"]["T11"]
                self.assertIn("Senior / Media Manager", " ".join(t11["evidence"]))
                self.assertEqual(self.r[key]["structure_checks"]["T10"]["score"], 0)   # UAE, no visa / notice line
        for key, r in self.each():
            self.assertEqual(r["content_checks"]["C16"]["score"], 1, key)   # no false alarm on these four

    def test_education_good_line(self):
        self.assertEqual(D.education_good({"structure_checks": {"T9": {"every_year": True}}}),
                         "Education lists degrees with school and year")
        self.assertIn("year hidden", D.education_good({"structure_checks": {"T9": {"year_hidden": True}}}))
        self.assertIsNone(D.education_good({"structure_checks": {"T9": {}}}))


class TestTempFiles(unittest.TestCase):
    """The uploaded PDF is a temp file in the dashboard's own folder; it is always closed and deleted, and a file
    Windows still holds never stops the check ([WinError 32])."""

    def ours(self):
        return set(os.listdir(D.TMP_DIR)) if os.path.isdir(D.TMP_DIR) else set()

    def test_check_the_same_resume_twice_in_a_row(self):
        before = self.ours()
        data = cv_bytes()
        cache = tempfile.mkdtemp()
        try:
            seed(cache)
            first = D.run_check(data, "neda.pdf", False, "", cache, cache)
            second = D.run_check(data, "neda.pdf", False, "", cache, cache)
        finally:
            shutil.rmtree(cache, ignore_errors=True)
        self.assertEqual(first["score"], second["score"])
        self.assertEqual(self.ours() - before, set())               # both temp files were deleted

    def test_every_pdf_handle_is_closed(self):
        """After the layout check (pdfplumber + page images) the file can be deleted at once."""
        src = os.path.join(HERE, "CV4", NEDA + ".pdf")
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        shutil.copy(src, path)
        Y.analyse_layout(path)
        L.extract_cv(path)
        os.remove(path)                                              # raises if anything still holds the file
        self.assertFalse(os.path.exists(path))

    def test_a_held_file_never_fails_the_check(self):
        real = os.remove
        calls = []

        def busy(path):
            calls.append(path)
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        fd, path = tempfile.mkstemp(suffix=".pdf", dir=self.tmp())
        os.close(fd)
        try:
            os.remove = busy
            self.assertFalse(D.safe_remove(path, tries=3, wait=0.01))          # no exception, file left
            self.assertEqual(len(calls), 3)                                    # tried again before giving up
            data = cv_bytes()
            cache = tempfile.mkdtemp()
            seed(cache)
            r = D.run_check(data, "neda.pdf", False, "", cache, cache)         # the check still completes
            self.assertIn("score", r)
        finally:
            os.remove = real
        self.assertTrue(os.path.exists(path))
        old = time.time() - D.TMP_MAX_AGE - 10
        os.utime(path, (old, old))
        self.assertGreaterEqual(D.clean_temp(folder=os.path.dirname(path)), 1)   # cleaned up later
        self.assertFalse(os.path.exists(path))
        D.clean_temp(max_age=0)                                                 # the run above left one too

    def test_retry_then_success(self):
        real = os.remove
        n = []

        def flaky(path):
            n.append(1)
            if len(n) < 3:
                raise PermissionError(32, "in use")
            real(path)
        fd, path = tempfile.mkstemp(suffix=".pdf", dir=self.tmp())
        os.close(fd)
        try:
            os.remove = flaky
            self.assertTrue(D.safe_remove(path, tries=5, wait=0.01))
        finally:
            os.remove = real
        self.assertFalse(os.path.exists(path))
        self.assertEqual(len(n), 3)

    def test_dedicated_folder_and_clean_on_start(self):
        self.assertEqual(os.path.basename(D.TMP_DIR), "atslab_dashboard")
        folder = self.tmp()
        fresh = os.path.join(folder, "fresh.pdf")
        open(fresh, "wb").close()
        self.assertEqual(D.clean_temp(folder=folder), 0)            # a file in use right now is kept
        self.assertTrue(os.path.exists(fresh))
        at = AppTest.from_file(os.path.join(HERE, "dashboard.py"), default_timeout=120).run()
        self.assertFalse(at.exception, at.exception)
        self.assertTrue(at.session_state["temp_cleaned"])

    def tmp(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        return folder


ILLEGAL = OSError(22, "Windows Error 0xc000001d")
ILLEGAL.winerror = -1073741795                  # STATUS_ILLEGAL_INSTRUCTION, as ctypes reports it


class TestNativeFaults(unittest.TestCase):
    """A library built for CPU instructions this computer lacks must never stop a check: the part that fails is
    skipped with a clear note and the check finishes."""

    def setUp(self):
        self.cache = tempfile.mkdtemp()
        seed(self.cache)
        self.addCleanup(shutil.rmtree, self.cache, True)

    def test_page_renderer_fault(self):
        import cv_cache
        D.fresh_modules()
        cv_cache.clear()                                   # this PDF was read before: read it again, with the fault
        real = Y.pypdfium2.PdfDocument

        def broken(*a, **k):
            raise ILLEGAL
        Y.pypdfium2.PdfDocument = broken
        try:
            r = D.run_check(cv_bytes(), "neda.pdf", False, "", self.cache, self.cache)
        finally:
            Y.pypdfium2.PdfDocument = real
            cv_cache.clear()                               # never keep the reading made with the fault
        self.assertIn("score", r)
        self.assertIn(Y.PageRenderer.NOTE, r["notes"])
        self.assertTrue(r["layout"]["columns_found"] is not None)     # the other layout checks still ran

    def test_meaning_model_cannot_run(self):
        saved, cached, model = list(L._EMBED_OK), dict(L._EMBED_CACHE), list(L._EMBEDDER)
        L._EMBED_OK[:] = [False]                                     # as if the probe process had crashed
        L._EMBEDDER.clear()
        L._EMBED_CACHE.clear()                                       # nothing computed earlier in this run
        try:
            r = D.run_check(cv_bytes(), "neda.pdf", True, job_text(), self.cache, self.cache, job_title="Delivery Lead")
        finally:
            L._EMBED_OK[:] = saved
            L._EMBED_CACHE.update(cached)
            L._EMBEDDER[:] = model
        self.assertIn(L.EMBED_NOTE, r["notes"])
        m3 = r["v3"]["ats"]["oracle"]["checks"]["M3"]
        self.assertIsNone(m3["score"])
        self.assertIn("skipped", m3["detail"])
        self.assertIn("job_match", r["parts"])                      # Job Match still scored from the keywords

    def test_unknown_native_fault_runs_safe_mode(self):
        real = C.score_cv
        calls = []

        def once_broken(*a, **k):
            calls.append(k.get("safe", False))
            if not k.get("safe"):
                raise ILLEGAL
            return real(*a, **k)
        C.score_cv = once_broken
        try:
            r = D.run_check(cv_bytes(), "neda.pdf", False, "", self.cache, self.cache)
        finally:
            C.score_cv = real
        self.assertEqual(calls, [False, True])
        self.assertIn(C.SAFE_NOTE, r["notes"])
        self.assertIsNone(r["layout"])
        self.assertTrue(D.is_native_fault(ILLEGAL))
        self.assertFalse(D.is_native_fault(PermissionError(32, "in use")))

    def test_notes_are_shown_on_the_page(self):
        def page():
            import dashboard as D2
            import test_dashboard as T
            import tempfile as tf
            cache = tf.mkdtemp()
            T.seed(cache)
            r = D2.run_check(T.cv_bytes(), "neda.pdf", False, "", cache, cache)
            r["notes"] = ["The page images could not be made on this computer, so the colour and contrast checks "
                          "were skipped; every other check ran."]
            D2.render(r)
        at = AppTest.from_function(page, default_timeout=300).run()
        self.assertFalse(at.exception, at.exception)
        self.assertIn("colour and contrast checks were skipped", " ".join(i.value for i in at.info))

    def test_requirements_pin_the_working_versions(self):
        import importlib.metadata as md
        with open(os.path.join(HERE, "requirements.txt"), encoding="utf-8") as f:
            pins = dict(l.strip().split("==", 1) for l in f if "==" in l and not l.lstrip().startswith("#"))
        for name in ("torch", "sentence-transformers", "numpy", "pypdfium2", "pdfplumber", "streamlit"):
            self.assertIn(name, pins)
            self.assertEqual(md.version(name), pins[name], name)        # what is installed is what is pinned


if __name__ == "__main__":
    unittest.main()
