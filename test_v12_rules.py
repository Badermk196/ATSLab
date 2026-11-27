"""
v1.2 (2026-10-29): the pre-launch fixes, each tested on generated files (never one real person or file).

Before going live
 1. Daily check limit on the User page: `daily_checks` (3) per person per day, counted on the server by browser and by
    IP address; a check that ends with a message is given back; a friendly message when the limit is reached.
 2. Wrong admin passwords are counted on the server, per name and per IP address: a page reload resets nothing.
 3. No Streamlit file watcher (.streamlit/config.toml).
 4. At most 3 checks run at once; the others wait in a queue ("N people ahead of you"); a realistic time is shown.
 5. Real resumes are never in a Docker image or a code repository (.dockerignore, .gitignore).
 6. The local start listens on this computer only (Docker keeps all addresses).
 7. Clear messages: password-locked PDF, Word file, damaged file (no technical words), empty file.
 8. A file with no resume signs is not scored: "This doesn't look like a resume ...".
 9. A resume mostly not in English is not scored: "We currently check resumes in English ...".
Scoring
10. MM/YYYY dates are month + year dates and count toward the years of experience; when no job can be read, the page
    limit goes by the dates in the resume, and with no dates at all there is no page limit (never "about 0 years").
11. Too many pages: 1 page over the limit = Minor, 2 or more = Important (and never "Excellent").
Smaller
12. /favicon.png answers (Streamlit 1.58 + Starlette 1.x fix in streamlit_fix.py).
13. A PDF is parsed once per check (cv_cache.one_parse), whatever the number of readings.

  py -3.12 -m unittest test_v12_rules -v
"""

import fnmatch
import io
import os
import shutil
import tempfile
import threading
import time
import tomllib
import unittest
import zipfile

os.environ["ATSLAB_AI_REVIEW"] = "0"
os.environ.pop("OPENROUTER_API_KEY", None)

import pdfplumber
from reportlab.pdfgen import canvas
from streamlit.testing.v1 import AppTest

import admin_page as A
import ATSLab_v3 as L
import cv_cache as CC
import cv_score as C
import dashboard as D
import lab_pages as P
import lab_store as H
import user_page as U

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_KEYS = ("ATSLAB_ADMINS", "ATSLAB_DATA_DIR", "ATSLAB_DAILY_CHECKS")


# ---------------------------------------------------------------------------
# Generated files
# ---------------------------------------------------------------------------
def make_pdf(path, lines, encrypt=None):
    """A plain PDF of these lines; "<page>" starts a new page."""
    c = canvas.Canvas(path, pagesize=(595, 842), encrypt=encrypt)
    y = 790
    for text in lines:
        if text == "<page>" or y < 60:
            c.showPage()
            y = 790
            if text == "<page>":
                continue
        c.setFont("Helvetica", 10.5)
        c.drawString(50, y, text)
        y -= 14
    c.save()
    return path


def resume_lines(jobs, pages=1, header=True, sections=True):
    """A one-column resume: jobs = [(title, company, dates)]; pages: filled with more bullets until it has this many."""
    out = ["Omar Haddad", "Logistics Coordinator | Freight Forwarding | Customs Clearance",
           "omar.haddad@mail.com | +971 50 765 4321 | Dubai, UAE | linkedin.com/in/omar-haddad-example"] if header else \
        ["Omar Haddad", "Logistics Coordinator"]
    out += ["SUMMARY" if sections else "",
            "Logistics coordinator with experience in freight forwarding, customs clearance and warehouse operations",
            "across the UAE, working with carriers, brokers and warehouse teams to keep shipments on time.",
            "EXPERIENCE" if sections else ""]
    for k, (title, company, dates) in enumerate(jobs):
        out += [f"{title} | {company} | Dubai, UAE | {dates}" if dates else f"{title} | {company} | Dubai, UAE"]
        out += [f"- Coordinated {12 + k * 5 + b} weekly shipments across five GCC markets with zero customs penalties."
                for b in range(3)]
    for p in range(1, pages):
        out += ["<page>", "PROJECTS" if sections else ""]
        out += [f"- Project {p}.{b}: moved {b + 3} warehouse lanes to a new carrier and cut delivery time by {b + 2} days."
                for b in range(40)]
    out += ["EDUCATION" if sections else "", "Bachelor of Science in Supply Chain Management | University of Dubai | 2018",
            "SKILLS" if sections else "", "Freight Forwarding, Customs Clearance, Warehouse Operations, SAP, Microsoft Excel,"
            " Incoterms, Route Planning, Inventory Management"]
    return [l for l in out if l != ""]


INVOICE = ["INVOICE No. INV-2026-0417", "Bright Office Supplies FZE, Jebel Ali Free Zone, Dubai",
           "Bill to: Example Trading LLC, Business Bay, Dubai", "Date: 12 Oct 2026     Due date: 11 Nov 2026",
           "Item                              Qty     Unit price (AED)     Amount (AED)",
           "A4 paper, 80 gsm (box of 5)        20            95.00             1,900.00",
           "Toner cartridge HP 26A              6           420.00             2,520.00",
           "Office chair, mesh                  4           650.00             2,600.00",
           "Subtotal 7,020.00    VAT 5% 351.00    Total due 7,371.00",
           "Bank: Example Bank, IBAN AE07 0331 2345 6789 0123 456. Please pay within thirty days of the invoice date.",
           "Thank you for your business. Questions about this invoice go to the accounts team of the seller."]
FRENCH = ["Claire Dubois", "Responsable logistique", "EXPÉRIENCE PROFESSIONNELLE",
          "Responsable logistique | Entreprise de transport | 01/2019 - 12/2024",
          "- Gestion des stocks et du développement des fournisseurs pour une entreprise de logistique à Dubaï.",
          "- Suivi des performances avec les équipes et analyse des données de livraison pour la direction.",
          "- Mise en place des procédures de contrôle des stocks dans les entrepôts de la région.",
          "FORMATION", "Diplôme en gestion de la chaîne logistique | Université de Lyon | 2018",
          "COMPÉTENCES", "Gestion de projet, négociation, gestion des stocks, analyse des données, SAP, Excel"]


def docx_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


class Files(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def pdf(self, name, lines, **kw):
        return make_pdf(os.path.join(self.dir, name), lines, **kw)

    def check(self, path, name=None):
        with open(path, "rb") as f:
            return D.run_check(f.read(), name or os.path.basename(path), False, "")


class Env(unittest.TestCase):
    """Its own data folder and admin accounts; the environment is put back afterwards."""
    def setUp(self):
        self.saved_env = {k: os.environ.get(k) for k in ENV_KEYS}
        self.data = tempfile.mkdtemp()
        os.environ["ATSLAB_DATA_DIR"] = self.data
        os.environ["ATSLAB_ADMINS"] = '{"Tester": "right-pass-1"}'
        os.environ.pop("ATSLAB_DAILY_CHECKS", None)
        self.store = H.Store(self.data)
        P._store.clear()

    def tearDown(self):
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        P._store.clear()
        shutil.rmtree(self.data, ignore_errors=True)


# ---------------------------------------------------------------------------
# 1. Daily check limit
# ---------------------------------------------------------------------------
def user_check_app(pdf, name):
    import lab_pages
    import user_page
    lab_pages.start_page()
    user_page.check({"pdf": pdf, "name": name, "title": "", "text": ""})


class TestDailyLimit(Env):
    def test_three_a_day_by_browser_or_by_ip(self):
        me, office_pc = ["browser:a", "ip:1.1.1.1"], ["browser:b", "ip:1.1.1.1"]
        for _ in range(3):
            self.assertTrue(self.store.reserve_check(me, 3))
        self.assertFalse(self.store.reserve_check(me, 3))                         # the 4th check today
        self.assertFalse(self.store.reserve_check(office_pc, 3))                  # same IP, other browser
        self.assertFalse(self.store.reserve_check(["browser:a", "ip:2.2.2.2"], 3))   # same browser, other IP
        self.assertTrue(self.store.reserve_check(["browser:c", "ip:3.3.3.3"], 3))    # someone else
        self.assertEqual(self.store.checks_today(me), 3)
        tomorrow = H.now() + H.dt.timedelta(days=1)
        self.assertFalse(self.store.reserve_check(me, 3, at=tomorrow))            # the 3 tries are for the visitor, not per day
        self.store.release_check(me)
        self.assertTrue(self.store.reserve_check(me, 3))                          # a check given back

    def test_the_limit_is_a_setting(self):
        self.assertEqual(P.S.get("daily_checks"), 3)
        os.environ["ATSLAB_DAILY_CHECKS"] = "5"
        self.assertEqual(P.S.get("daily_checks"), 5)

    def test_counted_on_the_server_across_sessions_with_a_friendly_message(self):
        os.environ["ATSLAB_DAILY_CHECKS"] = "1"
        empty = AppTest.from_function(user_check_app, args=(b"", "empty.pdf"), default_timeout=300).run()
        self.assertEqual(empty.error[0].value, D.CHECK_TEXT["empty"])
        self.assertEqual(self.store.checks_today(["ip:local"]), 0)               # a message: the check is given back
        from test_dashboard import cv_bytes
        first = AppTest.from_function(user_check_app, args=(cv_bytes(), "cv.pdf"), default_timeout=300).run()
        self.assertFalse(first.exception, first.exception)
        self.assertIn("u_result", first.session_state)
        again = AppTest.from_function(user_check_app, args=(cv_bytes(), "cv.pdf"), default_timeout=300).run()
        self.assertEqual(again.error[0].value, U.USER_TEXT["limit"].format(n=1))   # a new session: still counted
        self.assertNotIn("u_result", again.session_state)
        self.assertIn("Get Premium", [b.proto.label for b in again.get("link_button")])


# ---------------------------------------------------------------------------
# 2. Admin sign-in guard on the server
# ---------------------------------------------------------------------------
def admin_app():
    import admin_page
    admin_page.admin()


class TestAdminGuard(Env):
    def test_per_name_and_per_ip(self):
        for k in range(A.MAX_TRIES):                                      # one name, from different addresses
            self.assertIsNone(A.sign_in("Tester", "wrong", f"10.0.0.{k}", self.store))
        self.assertIsNone(A.sign_in("Tester", "right-pass-1", "10.9.9.9", self.store))
        self.assertGreater(self.store.login_wait(A.guard_keys("Tester", "10.9.9.9")), 50)
        for k in range(A.MAX_TRIES):                                      # many names, from one address
            self.assertIsNone(A.sign_in(f"guess{k}", "wrong", "10.1.1.1", self.store))
        self.assertGreater(self.store.login_wait(A.guard_keys("someone", "10.1.1.1")), 50)
        self.assertEqual(self.store.login_wait(A.guard_keys("other", "10.2.2.2")), 0)   # nobody else waits

    def test_a_right_sign_in_clears_the_count(self):
        for _ in range(A.MAX_TRIES - 1):
            A.sign_in("Tester", "wrong", "10.0.0.1", self.store)
        self.assertEqual(A.sign_in("Tester", "right-pass-1", "10.0.0.1", self.store), "Tester")
        A.sign_in("Tester", "wrong", "10.0.0.1", self.store)
        self.assertEqual(self.store.login_wait(A.guard_keys("Tester", "10.0.0.1")), 0)

    def test_a_reload_does_not_reset_the_wait(self):
        at = AppTest.from_function(admin_app, default_timeout=120).run()
        for _ in range(A.MAX_TRIES):
            at.text_input[0].set_value("Tester")
            at.text_input[1].set_value("wrong")
            at.button[0].click().run()
        self.assertIn(A.ADMIN_TEXT["locked"], [e.value for e in at.error])
        again = AppTest.from_function(admin_app, default_timeout=120).run()      # a reload: a new session
        again.text_input[0].set_value("Tester")
        again.text_input[1].set_value("right-pass-1")
        again.button[0].click().run()
        self.assertIn(A.ADMIN_TEXT["locked"], [e.value for e in again.error])
        self.assertNotIn("admin", again.session_state)


# ---------------------------------------------------------------------------
# 3, 5, 6. Server files
# ---------------------------------------------------------------------------
def ignored(name, patterns):
    return any(fnmatch.fnmatch(name + "/", p) or fnmatch.fnmatch(name, p.rstrip("/")) for p in patterns)


class TestServerFiles(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            return f.read()

    def test_no_file_watcher(self):
        with open(os.path.join(HERE, ".streamlit", "config.toml"), "rb") as f:
            self.assertEqual(tomllib.load(f)["server"]["fileWatcherType"], "none")

    def test_no_folder_with_resumes_goes_into_docker_or_git(self):
        for ignore in (".dockerignore", ".gitignore"):
            patterns = [l.strip() for l in self.read(ignore).splitlines() if l.strip() and not l.startswith("#")]
            for p in ("release-*/", "pretest_public/", "calib_*/", "nextsteps-resumes/", "data/"):
                self.assertIn(p, patterns, ignore)
            for name in os.listdir(HERE):                  # every folder that holds a PDF (a resume or a report)
                path = os.path.join(HERE, name)
                if os.path.isdir(path) and any(f.lower().endswith(".pdf") for _, _, fs in os.walk(path) for f in fs):
                    self.assertTrue(ignored(name, patterns), f"{name} is not in {ignore}")

    def test_local_start_on_this_computer_only_docker_on_all_addresses(self):
        bat = self.read("Start ATS Lab.bat")
        self.assertIn("--server.address 127.0.0.1", bat)
        self.assertIn("run_app.py", bat)
        docker = self.read("Dockerfile")
        self.assertIn('"--server.address=0.0.0.0"', docker)
        self.assertIn('"run_app.py"', docker)


# ---------------------------------------------------------------------------
# 4. The queue
# ---------------------------------------------------------------------------
class TestQueue(unittest.TestCase):
    def test_three_at_once_first_come_first_served(self):
        q = P.CheckQueue(3)
        tickets = [q.join() for _ in range(5)]
        self.assertEqual([q.try_start(t) for t in tickets], [True, True, True, False, False])
        self.assertEqual([q.ahead(t) for t in tickets[3:]], [0, 1])
        self.assertFalse(q.try_start(tickets[4]))                    # never before someone who came earlier
        q.done(tickets[0])
        self.assertFalse(q.try_start(tickets[4]))
        self.assertTrue(q.try_start(tickets[3]))
        q.leave(tickets[4])                                          # left the page while waiting
        self.assertEqual(q.waiting, [])

    def test_never_more_than_three_running(self):
        q, lock, now, peak = P.CheckQueue(3), threading.Lock(), [0], [0]

        def visitor():
            t = q.join()
            while not q.try_start(t):
                q.wait(0.01)
            with lock:
                now[0] += 1
                peak[0] = max(peak[0], now[0])
            time.sleep(0.05)
            with lock:
                now[0] -= 1
            q.done()
        threads = [threading.Thread(target=visitor) for _ in range(10)]
        [t.start() for t in threads]
        [t.join(10) for t in threads]
        self.assertEqual(peak[0], 3)
        self.assertEqual((q.running, q.waiting), (0, []))

    def test_a_visitor_never_reads_a_queue_position(self):
        self.assertFalse(hasattr(P, "queue_text"))
        self.assertNotIn("ahead", " ".join(P.QUEUE_TEXT.values()))
        self.assertEqual(P.MAX_RUNNING, 3)
        self.assertEqual(U.USER_TEXT["checking"], "Checking your resume… this usually takes under a minute")

    def test_a_waiting_visitor_who_left_is_dropped(self):
        now = [0.0]
        q = P.CheckQueue(1, clock=lambda: now[0])
        first, ghost, third = q.join(), q.join(), q.join()
        self.assertTrue(q.try_start(first))
        now[0] = 5
        self.assertFalse(q.try_start(third))                         # the third is still here, the ghost is not
        now[0] = P.STALE_WAIT + 6
        self.assertFalse(q.try_start(third))
        self.assertEqual(q.waiting, [third])                         # the ghost's place is gone
        self.assertEqual(q.ahead(third), 0)

    def test_a_check_that_hangs_gives_its_slot_back(self):
        now = [0.0]
        q = P.CheckQueue(1, clock=lambda: now[0])
        stuck, next_ = q.join(), q.join()
        self.assertTrue(q.try_start(stuck))
        now[0] = P.CHECK_TIMEOUT - 1
        self.assertFalse(q.try_start(next_))
        now[0] = P.CHECK_TIMEOUT + 1
        self.assertTrue(q.try_start(next_))
        q.done(stuck)                                                # the hung check ends late: nothing breaks
        self.assertEqual(q.running, 1)

    def test_done_is_safe_to_call_twice(self):
        q = P.CheckQueue(1)
        t = q.join()
        q.try_start(t)
        q.done(t)
        q.done(t)
        self.assertEqual((q.running, q.waiting), (0, []))

    def test_check_slot_frees_everything_when_the_check_fails_or_waits_too_long(self):
        q = P.CheckQueue(1)
        with self.assertRaises(RuntimeError):
            with P.check_slot(q):
                raise RuntimeError("the check crashed")
        self.assertEqual((q.running, q.waiting), (0, []))
        holder = q.join()
        q.try_start(holder)                                          # the only slot is taken
        old_timeout, P.QUEUE_TIMEOUT = P.QUEUE_TIMEOUT, 0.05
        try:
            with self.assertRaises(P.QueueTimeout):
                with P.check_slot(q):
                    pass
        finally:
            P.QUEUE_TIMEOUT = old_timeout
        self.assertEqual(q.waiting, [])                              # the one who gave up left no entry


# ---------------------------------------------------------------------------
# 7, 8, 9. Files that are not checked, with a clear message
# ---------------------------------------------------------------------------
class TestMessages(Files):
    def assert_message(self, data, name, key):
        with self.assertRaises(D.CheckError) as e:
            D.run_check(data, name, False, "")
        self.assertEqual(str(e.exception), D.CHECK_TEXT[key].format(name=name))
        return str(e.exception)

    def test_locked_word_damaged_empty(self):
        locked = self.pdf("locked.pdf", resume_lines([("Coordinator", "Gulf Freight", "Jan 2020 - Present")]),
                          encrypt="secret-1")
        with open(locked, "rb") as f:
            self.assert_message(f.read(), "locked.pdf", "locked")
        self.assertEqual(D.CHECK_TEXT["locked"], "This PDF is locked with a password. Save it without a password "
                                                 "and upload it again.")
        self.assert_message(docx_bytes(), "resume.docx", "word")
        self.assert_message(docx_bytes(), "renamed.pdf", "word")                  # a Word file renamed to .pdf
        self.assert_message(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64, "old.doc", "word")
        self.assertEqual(D.CHECK_TEXT["word"], "Please save your resume as a PDF and upload it again.")
        good = self.pdf("good.pdf", resume_lines([("Coordinator", "Gulf Freight", "Jan 2020 - Present")]))
        with open(good, "rb") as f:
            msg = self.assert_message(f.read()[:400], "cut.pdf", "damaged")
        for word in ("Pdfminer", "Exception", "Error", "PSEOF", "XRef"):
            self.assertNotIn(word, msg)
        self.assertEqual(self.assert_message(b"", "empty.pdf", "empty"), "This file is empty.")
        self.assert_message(b"", "", "no_file")
        self.assertIn("docx", D.UPLOAD_TYPES)                              # the upload box takes it, then explains

    def test_not_a_resume(self):
        self.assert_message(open(self.pdf("invoice.pdf", INVOICE), "rb").read(), "invoice.pdf", "not_resume")
        self.assertEqual(D.CHECK_TEXT["not_resume"],
                         "This doesn't look like a resume. Please upload your resume as a PDF.")
        doc = {"modern": "Senior Analyst\nWorked on budgets\nEXPERIENCE\nAnalyst | Bank", "strict": "", "rows": []}
        for text, sign in (("EXPERIENCE\nAnalyst at a bank\nEDUCATION\nBSc", "section"),
                           ("Analyst at a bank 03/2019 - 05/2023", "dates"), ("Analyst, ana.lyst@mail.com", "contact"),
                           ("Analyst, Mobile: 050 123 4567", "contact"), ("Analyst, +971 50 123 4567", "contact")):
            rows = [{"text": t, "cells": [t], "page": 0} for t in text.splitlines()]
            self.assertIn(sign, C.resume_signs(dict(doc, modern=text, rows=rows)), text)
        iban = "IBAN AE07 0331 2345 6789 0123 456"
        self.assertEqual(C.resume_signs({"modern": iban, "strict": "",
                                         "rows": [{"text": iban, "cells": [iban], "page": 0}]}), [])

    def test_a_resume_is_still_scored(self):
        r = self.check(self.pdf("resume.pdf", resume_lines([("Logistics Coordinator", "Gulf Freight LLC",
                                                             "Jan 2020 - Present")])))
        self.assertTrue(D.is_current(r))

    def test_not_english(self):
        self.assert_message(open(self.pdf("french.pdf", FRENCH), "rb").read(), "french.pdf", "not_english")
        self.assertEqual(D.CHECK_TEXT["not_english"],
                         "We currently check resumes in English. Please upload an English version.")
        arabic = ("سارة المنصوري مديرة موارد بشرية دبي الإمارات العربية المتحدة الخبرة العملية مديرة موارد بشرية "
                  "فنادق الخليج قادت توظيف أكثر من موظف سنويا في فنادق التعليم بكالوريوس إدارة الموارد البشرية")
        self.assertTrue(C.not_english(arabic))
        english = " ".join(resume_lines([("Logistics Coordinator", "Gulf Freight LLC", "Jan 2020 - Present")]))
        self.assertFalse(C.not_english(english))
        self.assertFalse(C.not_english(english + " Langues: français, español. Muhammad Al-Mansoori, José Müller."))
        self.assertFalse(C.not_english("Résumé"))                       # too little text to judge


# ---------------------------------------------------------------------------
# 10, 11. Dates and pages
# ---------------------------------------------------------------------------
class TestDatesAndPages(Files):
    def issue(self, r, iid):
        return next((i for i in r["issues"] if i["id"] == iid), None)

    def test_mm_yyyy_is_a_month_and_year_date(self):
        jobs = [("Logistics Manager", "Gulf Freight LLC", "01/2020 - Present"),
                ("Logistics Coordinator", "Desert Cargo FZE", "03/2014 - 12/2019")]
        r = self.check(self.pdf("mmyyyy.pdf", resume_lines(jobs)))
        ana = C.analyse_cv(r["_doc"])
        self.assertEqual([j["problem"] for j in ana["jobs"]], [None, None])         # month + year: no date problem
        self.assertTrue(all(j["month_format"] for j in ana["jobs"]))
        self.assertGreater(L.experience_years(ana["jobs"]), 12)
        self.assertFalse((r["structure_checks"]["T4"] or {}).get("date_problems"))
        self.assertIsNone(self.issue(r, "D11"))
        same = self.check(self.pdf("monyyyy.pdf", resume_lines([(t, c, d.replace("01/2020", "Jan 2020")
                                                                  .replace("03/2014", "Mar 2014")
                                                                  .replace("12/2019", "Dec 2019")) for t, c, d in jobs])))
        self.assertEqual(r["score"], same["score"])                                 # the same as "Mon YYYY"

    def test_no_job_read_the_pages_go_by_the_dates(self):
        # job lines the job reader does not know ('// dates' after a bullet): before 1.2, "2 pages for about 0 years"
        lines = resume_lines([], pages=2)
        at = lines.index("EDUCATION")
        lines[at:at] = ["- SENIOR DEVELOPER // 07/2016 - now", "- DEVELOPER // 01/2013 - 06/2016"]
        r = self.check(self.pdf("odd_jobs.pdf", lines))
        self.assertIsNone(self.issue(r, "D11"))                                     # ~13 years: 2 pages are fine
        self.assertEqual(C.years_from_dates("x 01/2013 - 06/2016 y 07/2016 - 12/2020"), 8.0)
        self.assertIsNone(C.years_from_dates("no dates at all"))

    def test_no_dates_at_all_no_page_limit(self):
        r = self.check(self.pdf("no_dates.pdf", resume_lines([("Logistics Coordinator", "Gulf Freight LLC", "")],
                                                             pages=4)))
        self.assertIsNone(self.issue(r, "D11"))

    def test_one_page_over_minor_two_or_more_important(self):
        two_years = [("Logistics Coordinator", "Gulf Freight LLC", "Mar 2024 - Present")]       # at most 1 page
        one_over = self.issue(self.check(self.pdf("p2.pdf", resume_lines(two_years, pages=2))), "D11")
        two_over = self.issue(self.check(self.pdf("p3.pdf", resume_lines(two_years, pages=3))), "D11")
        self.assertEqual(one_over["severity"], "Minor")
        self.assertEqual(two_over["severity"], "Major")
        self.assertIn("3 pages for about", two_over["detail"])
        self.assertIn("(at most 1)", two_over["detail"])
        self.assertEqual(C.rule_severity("D11", design={"D11": {"found": True, "over": 1}}), "Minor")
        self.assertEqual(C.rule_severity("D11", design={"D11": {"found": True, "over": 12}}), "Major")

    def test_under_a_year_never_about_0_years_and_the_card_says_the_same(self):
        r = self.check(self.pdf("new_starter.pdf", resume_lines([("Logistics Intern", "Gulf Freight LLC",
                                                                  "Jun 2026 - Present")], pages=2)))
        d11 = self.issue(r, "D11")
        self.assertIn("2 pages for less than a year of experience", d11["detail"])
        card = next(c for c in D.issue_cards(r) if c["key"] == "pages")
        text = " ".join(str(v) for v in card.values() if isinstance(v, (str, list)))
        self.assertIn("This resume has 2 pages for less than a year of experience.", text)
        self.assertNotIn("about 0 years", text)

    def test_far_too_many_pages_is_never_excellent(self):
        jobs = [("Logistics Manager", "Gulf Freight LLC", "Jan 2020 - Present"),
                ("Logistics Coordinator", "Desert Cargo FZE", "Jan 2014 - Dec 2019")]          # at most 3 pages
        r = self.check(self.pdf("p15.pdf", resume_lines(jobs, pages=15)))
        self.assertEqual(self.issue(r, "D11")["severity"], "Major")
        self.assertNotEqual(r["label"], "Excellent")


# ---------------------------------------------------------------------------
# 12. favicon, 13. one parse per check
# ---------------------------------------------------------------------------
class TestFaviconFix(unittest.TestCase):
    def test_a_png_answers_through_streamlits_gzip_layer(self):
        import streamlit_fix
        from starlette.applications import Starlette
        from starlette.responses import FileResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient
        from streamlit.web.server.starlette.starlette_gzip_middleware import SelectiveGZipMiddleware
        self.assertTrue(streamlit_fix.apply())
        png = os.path.join(os.path.dirname(__import__("streamlit").__file__), "static", "favicon.png")
        app = Starlette(routes=[Route("/favicon.png", lambda request: FileResponse(png, media_type="image/png"))])
        app.add_middleware(SelectiveGZipMiddleware, minimum_size=500)
        with TestClient(app) as client:
            for enc in ("gzip", "identity"):
                r = client.get("/favicon.png", headers={"Accept-Encoding": enc})
                self.assertEqual((r.status_code, r.headers["content-type"]), (200, "image/png"))
                self.assertEqual(r.content, open(png, "rb").read())


class TestOneParse(Files):
    def test_a_check_parses_the_pdf_once(self):
        path = self.pdf("once.pdf", resume_lines([("Logistics Coordinator", "Gulf Freight LLC", "Jan 2020 - Present")],
                                                 pages=2))
        opened, real = [], pdfplumber.open

        def counting(*a, **k):
            opened.append(a[0])
            return real(*a, **k)
        CC.clear()
        pdfplumber.open = counting
        try:
            r = self.check(path)
        finally:
            pdfplumber.open = real
        self.assertTrue(D.is_current(r))
        self.assertEqual(len(opened), 1)
        with CC.one_parse(path) as outer, CC.open_pdf(path) as inner, CC.one_parse(path) as nested:
            self.assertIs(outer, inner)
            self.assertIs(outer, nested)
        with CC.open_pdf(path) as alone:                       # outside a check: an ordinary open and close
            self.assertGreater(len(alone.pages), 1)


if __name__ == "__main__":
    unittest.main()
