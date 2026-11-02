"""
v1.1 scoring rules (2026-10-29), each tested on generated resumes (never one real person or file):

1. Resume length: only a resume that is too short for the experience is flagged (Minor); a long one never is.
2. There is no "Some bullets are too long or too short" check (no card, no points).
3. There is no employment gap check: no Lab card and no AI gap finding, and no points taken.
4. The candidate's name is found when a credential or title follows it ("NAME, PMP®", "NAME, MBA", "Dr. ..."), also
   when it is letter-spaced; the report header and the PDF file name show it without the credential.
5. A letter-spaced name alone is the Minor card "Name has letter spacing", never "Template is hard for ATS to read".
6. A bullet is never joined with a job header line under it ("Title | Company, City, Mon YYYY - Mon YYYY"), and every
   bullet check (numbers, verbs, repeats, detail) reads the same, fixed bullets.

  py -3.12 -m unittest test_v11_rules -v
"""

import json
import os
import shutil
import tempfile
import unittest

os.environ["ATSLAB_AI_REVIEW"] = "0"
os.environ.pop("OPENROUTER_API_KEY", None)

from reportlab.pdfgen import canvas

import ATSLab_v3 as L
import cv_review as R
import cv_score as C
import dashboard as D
from test_cv_score import fake_doc, polished_cv, ROLE, SKILLS

TODAY = L.TODAY.isoformat()


class Base(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()
        with open(C.role_skills_path(ROLE, self.cache), "w", encoding="utf-8") as f:
            json.dump({"role": ROLE, "prompt_version": C.ROLE_PROMPT_VERSION, "ai_runs": [SKILLS] * 3}, f)
        self.addCleanup(shutil.rmtree, self.cache, True)

    def score(self, doc, **kw):
        return C.score_cv("resume.pdf", None, ROLE, doc=doc, role_cache=self.cache, **kw)


BULLET = "Coordinated {n} weekly freight shipments across five GCC markets with zero customs penalties."


def resume_text(jobs, bullets_per_job=3, name="Nadia Rahman", extra=""):
    """A plain resume: jobs = [(title, company, dates)], each with numbered bullets."""
    body = []
    for k, (title, company, dates) in enumerate(jobs):
        body.append(f"{title} | {dates}")
        body.append(f"{company} | Dubai, UAE")
        body += [f"- {BULLET.format(n=10 * k + b + 2)}" for b in range(bullets_per_job)]
    return (f"{name}\nLogistics Coordinator | Freight Forwarding | Customs Clearance\n"
            f"nadia.rahman@mail.com | +971 50 123 4567 | Dubai, UAE | linkedin.com/in/nadia-rahman\n"
            f"SUMMARY\nLogistics Coordinator with experience in freight forwarding, customs clearance and warehouse "
            f"operations across the UAE and GCC.{extra}\nEXPERIENCE\n" + "\n".join(body) +
            "\nEDUCATION\nBachelor of Science in Supply Chain Management, University of Dubai, 2012\n"
            "SKILLS\nInventory Management, Freight Forwarding, Customs Clearance, Warehouse Operations, SAP, "
            "Shipment Tracking, Microsoft Excel, Incoterms, Route Planning\n")


TWELVE_YEARS = [("Logistics Manager", "Gulf Freight LLC", "Jan 2020 - Present"),
                ("Logistics Coordinator", "Desert Cargo FZE", "Jan 2014 - Dec 2019")]
TWO_YEARS = [("Logistics Coordinator", "Gulf Freight LLC", "Jan 2024 - Present")]


def pdf_resume(path, name, name_space=0.0, heading_space=0.0, pages=1, bullets=3):
    """A generated one-column resume PDF. name_space / heading_space: letter spacing (pt) of the name / headings;
    pages: the jobs are spread so the resume fills this many pages."""
    c = canvas.Canvas(path, pagesize=(595, 842))
    y = 790

    def line(text, size=10.5, bold=False, space=0.0, gap=14):
        nonlocal y
        if y < 60:
            c.showPage()
            y = 790
        t = c.beginText(50, y)
        t.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        t.setCharSpace(space)
        t.textLine(text)
        c.drawText(t)
        y -= gap
    line(name, 22, True, name_space, 30)
    line("Project Manager | Construction Planning | Cost Control", 11, gap=16)
    line("Dubai, UAE | +971 50 123 4567 | pm.candidate@mail.com | linkedin.com/in/pm-candidate", 10, gap=24)
    line("SUMMARY", 12, True, heading_space, 16)
    line("Project manager with 12 years of experience delivering residential and commercial projects across the UAE,", gap=12)
    line("leading site teams of up to 40 people and keeping budgets and schedules on track.", gap=22)
    line("EXPERIENCE", 12, True, heading_space, 18)
    jobs = (("Senior Project Manager", "Northwind Builders", "Jan 2020 - Present"),
            ("Project Manager", "Harbor Construction", "Jan 2016 - Dec 2019"),
            ("Site Engineer", "Coastal Contracting", "Jan 2013 - Dec 2015"))
    for k, (title, company, dates) in enumerate(jobs):
        line(f"{title} | {company} | Dubai, UAE | {dates}", bold=True)
        for b in range(bullets):
            line(f"- Delivered {k * 10 + b + 3} projects worth AED {b + 2}M on time by tightening weekly cost reviews.")
        y -= 6
        if pages > 1 and k == 0:
            y = 40                                          # the next job starts on a new page
    line("EDUCATION", 12, True, heading_space, 16)
    line("Bachelor of Science in Civil Engineering | University of Sharjah | 2012")
    line("SKILLS", 12, True, heading_space, 16)
    line("Project Management, Cost Control, Scheduling, Primavera P6, AutoCAD, Contract Management, Risk Management, MS Project")
    c.save()


class PdfBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def check_pdf(self, file_name="resume.pdf", **kw):
        path = os.path.join(self.dir, file_name)
        pdf_resume(path, **kw)
        with open(path, "rb") as f:
            return D.run_check(f.read(), file_name, False, "")


# ---------------------------------------------------------------------------------------------------------------------
# 1. Resume length
# ---------------------------------------------------------------------------------------------------------------------
class TestResumeLength(Base):
    def test_rule(self):
        for words, years, pages, flagged in ((300, 9, 2, True),       # 8+ years in under 350 words
                                             (340, 8, None, True),
                                             (360, 12, 2, False),
                                             (600, 12, 1, True),       # 10+ years on one page
                                             (600, 9, 1, False),
                                             (300, 5, 1, False),       # under 8 years: a short resume is fine
                                             (2500, 2, 4, False),      # long: never flagged
                                             (1800, 15, 3, False)):
            with self.subTest(words=words, years=years, pages=pages):
                c7 = C.length_check(words, years, pages)
                self.assertEqual(c7["score"] < 1, flagged, c7["detail"])

    def test_short_for_the_experience_is_a_minor_card(self):
        r = self.score(fake_doc(resume_text(TWELVE_YEARS, bullets_per_job=1)))
        self.assertGreaterEqual(r["experience_years"], 10)
        c7 = r["content_checks"]["C7"]
        self.assertLess(c7["score"], 1, c7)
        issue = next(i for i in r["issues"] if i["id"] == "C7")
        self.assertEqual(issue["severity"], "Minor")
        card = next(c for c in D.issue_cards(r) if c["key"] == "length")
        self.assertEqual(card["name"], "Resume is short for your experience")
        self.assertEqual(card["tag"], "Minor")

    def test_a_long_resume_is_never_flagged(self):
        filler = " Known for clear vendor communication and steady improvement of inventory processes." * 80
        r = self.score(fake_doc(resume_text(TWO_YEARS, bullets_per_job=12, extra=filler)))
        self.assertGreater(len(r["_vdoc"]["modern"].split()), 900)
        self.assertLess(r["experience_years"], 3)
        self.assertEqual(r["content_checks"]["C7"]["score"], 1.0)
        self.assertNotIn("C7", [i["id"] for i in r["issues"]])


class TestResumeLengthPages(PdfBase):
    def test_one_page_for_ten_plus_years(self):
        one = self.check_pdf(name="Nadia Rahman")
        self.assertEqual(one["layout"]["pages"], 1)
        self.assertGreaterEqual(one["experience_years"], 10)
        self.assertLess(one["content_checks"]["C7"]["score"], 1)
        two = self.check_pdf(name="Nadia Rahman", pages=2, bullets=8)
        self.assertEqual(two["layout"]["pages"], 2)
        self.assertEqual(two["content_checks"]["C7"]["score"], 1.0, two["content_checks"]["C7"]["detail"])


# ---------------------------------------------------------------------------------------------------------------------
# 2. No bullet length check
# ---------------------------------------------------------------------------------------------------------------------
class TestNoBulletLengthCheck(Base):
    def test_gone_everywhere(self):
        self.assertNotIn("C3", C.CONTENT_WEIGHT)
        self.assertNotIn("C3", C.CONTENT_NAME)
        self.assertNotIn("bullet_length", D.ISSUES)
        self.assertAlmostEqual(sum(C.CONTENT_WEIGHT.values()) + sum(C.RETIRED_WEIGHT.values()), 1.0)

    def test_long_and_short_bullets_cost_nothing(self):
        long = ("Coordinated 40 weekly freight shipments across five GCC markets with zero customs penalties while "
                "also training new coordinators, rebuilding the tracking sheet, renegotiating carrier rates and "
                "reporting every week to the regional director on cost and service levels.")
        base = polished_cv()["modern"]
        b0 = "Coordinated 40+ weekly freight forwarding shipments across five GCC markets with zero customs penalties."
        changed = self.score(fake_doc(base.replace(b0, long)))
        plain = self.score(fake_doc(base))
        self.assertNotIn("C3", changed["content_checks"])
        self.assertFalse([i for i in changed["issues"] if i["id"] == "C3" or "bullets are too" in i["name"]])
        self.assertEqual(changed["parts"]["content"], plain["parts"]["content"])

    def test_every_check_at_full_marks_is_100(self):
        cc = {k: {"score": 1.0, "detail": "", "evidence": [], "quant_share": 1.0, "bullets": 5} for k in C.CONTENT_WEIGHT}
        self.assertAlmostEqual(C.content_part(cc), 100.0)


# ---------------------------------------------------------------------------------------------------------------------
# 3. No employment gap check
# ---------------------------------------------------------------------------------------------------------------------
GAP_JOBS = [("Logistics Manager", "Gulf Freight LLC", "Jan 2022 - Present"),
            ("Logistics Coordinator", "Desert Cargo FZE", "Jan 2014 - Dec 2017")]       # four empty years


def finding(issue, quote, why="A recruiter will ask about it.", type_="content"):
    return {"issue": issue, "severity": "Major", "type": type_, "quote": quote, "why": why, "fix": "State it."}


class TestNoGapCheck(Base):
    QUOTE = "Logistics Coordinator | Jan 2014 - Dec 2017"

    def test_the_ai_gap_findings_are_filtered_out(self):
        text = resume_text(GAP_JOBS)
        raw = {"findings": [finding("Unexplained employment gap", self.QUOTE),
                            finding("Career break not explained", self.QUOTE, "There is a break in employment."),
                            finding("Gap between roles", self.QUOTE, type_="unusual"),
                            finding("Vague role description", "Logistics Coordinator with experience in freight "
                                                              "forwarding")]}
        kept, rejected = R.clean(raw, [text])
        self.assertEqual([f["issue"] for f in kept], ["Vague role description"])
        self.assertEqual(len(rejected), 3)

    def test_no_gap_card_and_no_points(self):
        doc = fake_doc(resume_text(GAP_JOBS))
        plain = self.score(doc)
        self.assertNotIn("timeline", plain)
        self.assertFalse([i for i in plain["issues"] if "gap" in (i["name"] + i["detail"]).lower()])
        self.assertFalse(any(p.search("Unexplained employment gap") for p, _ in C.AI_TOPICS))
        # the AI reviewer reports only a gap: it is dropped, and Content is the same as without the review
        real, key = L.call_ai, os.environ.get("OPENROUTER_API_KEY")
        L.call_ai = lambda *a, **k: {"field": "logistics", "findings": [finding("Unexplained employment gap",
                                                                                self.QUOTE)]}
        os.environ["OPENROUTER_API_KEY"] = "test-only"
        reviews = tempfile.mkdtemp()
        try:
            r = self.score(doc, review=True, review_cache=reviews)
        finally:
            L.call_ai = real
            os.environ.pop("OPENROUTER_API_KEY", None)
            if key is not None:
                os.environ["OPENROUTER_API_KEY"] = key
            shutil.rmtree(reviews, ignore_errors=True)
        self.assertEqual(r["ai_review"]["findings"], [])
        self.assertEqual(r["content_checks"]["C8"]["score"], 1.0)
        self.assertEqual(r["score"], plain["score"])
        self.assertFalse(any("gap" in c["name"].lower() for c in D.issue_cards(r)))


# ---------------------------------------------------------------------------------------------------------------------
# 4. The name with a credential or title
# ---------------------------------------------------------------------------------------------------------------------
class TestNameWithCredential(PdfBase):
    def test_bare_name(self):
        for text, want in (("SARA KHAN, PMP®", "SARA KHAN"), ("OMAR FAROUK, MBA", "OMAR FAROUK"),
                           ("Dr. Layla Nasser", "Layla Nasser"), ("Dr. Layla Nasser, PhD, PMP®", "Layla Nasser"),
                           ("Karim Saleh MBA", "Karim Saleh"), ("Eng. Ali Hamdan, PE", "Ali Hamdan"),
                           ("Nadia Rahman", "Nadia Rahman"), ("Rana Aziz, CPA, CMA", "Rana Aziz")):
            with self.subTest(text=text):
                self.assertEqual(L.bare_name(text), want)

    def check_name(self, shown, expected, **kw):
        r = self.check_pdf(name=shown, **kw)
        self.assertEqual(D.candidate_name(r), expected)
        self.assertEqual(D.report_file_name(r), f"1000Jobs ATS Lab - {expected} - {TODAY}.pdf")
        head = D.header_html(r)
        self.assertIn(expected, head)
        for credential in ("PMP", "MBA", "PhD", "Dr."):
            self.assertNotIn(credential, head)
        return r

    def test_names_with_a_credential_or_title(self):
        for shown, expected in (("SARA KHAN, PMP®", "Sara Khan"), ("OMAR FAROUK, MBA", "Omar Farouk"),
                                ("Dr. Layla Nasser", "Layla Nasser"),
                                ("Dr. Layla Ahmed Al Nasser, PhD, PMP®", "Layla Ahmed Al Nasser")):
            with self.subTest(name=shown):
                r = self.check_name(shown, expected)
                self.assertEqual(r["v3"]["ats"]["oracle"]["checks"]["R1"]["score"], 100)   # the name is found

    def test_a_letter_spaced_name_with_a_credential(self):
        r = self.check_name("HANA YOUSEF, PMP®", "Hana Yousef", name_space=6)   # the file name does not help
        self.assertTrue(L.spaced_lines(r["_doc"]["strict"])[0].startswith("H A N A"))


# ---------------------------------------------------------------------------------------------------------------------
# 5. A letter-spaced name only
# ---------------------------------------------------------------------------------------------------------------------
class TestSpacedNameOnly(Base):
    def test_spaced_name_only_is_the_minor_name_card(self):
        r = self.score(polished_cv(spaced_name=True))
        ids = [i["id"] for i in r["issues"]]
        self.assertIn("N1", ids)
        self.assertNotIn("TPL", ids)
        self.assertEqual(next(i for i in r["issues"] if i["id"] == "N1")["severity"], "Minor")
        cards = D.issue_cards(r)
        self.assertIn("Name has letter spacing", [c["name"] for c in cards])
        self.assertNotIn(D.ISSUES["template"]["name"], [c["name"] for c in cards])
        self.assertEqual(next(c for c in cards if c["key"] == "name_spacing")["tag"], "Minor")

    def test_spaced_headings_are_still_the_template_card(self):
        text = polished_cv(spaced_name=True)["modern"].replace("\nSKILLS\n", "\nS K I L L S\n")
        r = self.score(fake_doc(text))
        self.assertIn("TPL", [i["id"] for i in r["issues"]])
        self.assertIn("letter-spaced headings", next(i for i in r["issues"] if i["id"] == "TPL")["reasons"])


class TestSpacedNameOnlyPdf(PdfBase):
    def test_in_a_real_pdf(self):
        r = self.check_pdf(name="Hana Yousef", name_space=6)
        names = [c["name"] for c in D.issue_cards(r)]
        self.assertIn("Name has letter spacing", names)
        self.assertNotIn(D.ISSUES["template"]["name"], names)
        spaced = self.check_pdf(name="Hana Yousef", name_space=6, heading_space=5)
        self.assertIn(D.ISSUES["template"]["name"], [c["name"] for c in D.issue_cards(spaced)])


# ---------------------------------------------------------------------------------------------------------------------
# 6. A bullet is never joined with a job header
# ---------------------------------------------------------------------------------------------------------------------
HEADERS = ("Senior Project Manager | Northwind Construction Company LLC, Dubai, United Arab Emirates, Jan 2018 - Dec 2022",
           "Project Manager | Northwind Builders, Dubai, Jan 2018 - Dec 2022",
           "Northwind Construction Company LLC, Dubai, United Arab Emirates | Senior Project Manager | Jan 2018 - Dec 2022",
           "Jan 2018 - Dec 2022 | Senior Project Manager, Northwind Construction Company LLC, Dubai, United Arab Emirates")


def bullet_doc(header, last="Reduced warehouse costs by 18% through better inventory management and route planning"):
    """Two jobs; the last bullet of the first job has no full stop and the second job's header comes right after."""
    return fake_doc(f"""Nadia Rahman
Project Manager | Construction Planning | Cost Control
nadia.rahman@mail.com | +971 50 123 4567 | Dubai, UAE | linkedin.com/in/nadia-rahman
SUMMARY
Project manager with 12 years of experience delivering residential and commercial projects across the UAE.
EXPERIENCE
Project Director | Harbor Construction, Dubai, Jan 2023 - Present
- Responsible for the site teams of a portfolio of residential projects
- {last}
{header}
- {last}
- Delivered 9 projects worth AED 120M on time by tightening weekly cost reviews.
EDUCATION
Bachelor of Science in Civil Engineering, University of Sharjah, 2012
SKILLS
Project Management, Cost Control, Scheduling, Primavera P6, AutoCAD, Contract Management, Risk Management
""")


class TestBulletsAndJobHeaders(Base):
    def test_a_job_header_is_never_part_of_a_bullet(self):
        last = "Reduced warehouse costs by 18% through better inventory management and route planning"
        for header in HEADERS:
            with self.subTest(header=header):
                ana = C.analyse_cv(bullet_doc(header))
                items = C.experience_items(ana)
                self.assertFalse([t for t, _ in items if "Northwind" in t or "Jan 2018" in t], items)
                self.assertEqual([t for t, _ in items].count(last), 2, items)

    def test_every_bullet_check_reads_the_fixed_bullets(self):
        r = self.score(bullet_doc(HEADERS[0]))
        cc = r["content_checks"]
        self.assertEqual(cc["C1"]["detail"], "3 of 4 bullets have a number or result")          # numbers
        self.assertEqual(cc["C11"]["evidence"], ["Responsible for the site teams of a portfolio of residential "
                                                 "projects"])                                    # verbs
        self.assertIn("1 repeated bullet", cc["C6"]["detail"])                                   # repeats
        self.assertTrue(cc["C18"]["detail"].startswith("4 bullets"), cc["C18"]["detail"])         # detail
        self.assertEqual(cc["C1"]["evidence"], ["Responsible for the site teams of a portfolio of residential "
                                                "projects"])
        quotes = [q for i in r["issues"] for q in i["evidence"]]
        self.assertFalse([q for q in quotes if "Northwind" in q], quotes)

    def test_a_wrapped_bullet_is_still_one_bullet(self):
        doc = bullet_doc(HEADERS[0]).copy()
        text = doc["modern"].replace("- Delivered 9 projects worth AED 120M on time by tightening",
                                     "- Delivered 9 projects worth AED 120M on time by tightening\n")
        items = [t for t, _ in C.experience_items(C.analyse_cv(fake_doc(text)))]
        self.assertIn("Delivered 9 projects worth AED 120M on time by tightening weekly cost reviews.", items)


if __name__ == "__main__":
    unittest.main()
