"""
2026-10-23: wrapped lines and clean quotes.

The same resume (long degree and job titles, a long company name) is drawn in 2, 3 and 4 columns, with sidebars and
on a landscape page. In a narrow column a degree, a job title or a company wraps onto the next line: the Lab must
join the pieces before any check, so the wrap never causes a false alarm, and every quote on every card must be a
clean line (no letter-spaced words, no text of two columns on one line).

  py -3.12 -m unittest test_wrapped -v
"""

import os

os.environ["ATSLAB_AI_REVIEW"] = "0"
import re
import shutil
import tempfile
import unittest

import ATSLab_v3 as L
import cv_score as C
import dashboard as D
import test_columns as TC

TITLE = "Senior Logistics and Supply Chain Coordinator, GCC Region"
COMPANY = "Gulf Freight Forwarding Services LLC | Dubai, UAE"
DEGREE = "Bachelor of Science in Supply Chain Management and Logistics Engineering"
SCHOOL = "University of Dubai Business School, 2016"
LONG_JOBS = [(TITLE, "Jan 2021 - Present", COMPANY,
              ["Coordinated 40 weekly freight shipments across five GCC markets.",
               "Reduced warehouse costs by 18% through better route planning."]),
             ("Assistant Logistics and Customs Clearance Planner, Middle East", "Mar 2018 - Dec 2020",
              "Desert Cargo and Transport Solutions FZE | Sharjah, UAE",
              ["Built an Excel shipment tracker used daily by 12 planners.",
               "Negotiated carrier rates that saved AED 250,000 in one year."]),
             ("Warehouse Operations and Inventory Clerk, Jebel Ali", "Jun 2016 - Feb 2018",
              "Port Cargo and Handling Services LLC | Dubai, UAE",
              ["Tracked 200 inbound containers a month with the port system."])]


def job_lines(jobs):
    return [x for t, d, co, bs in jobs for x in [f"{t} | {d}", co] + ["- " + b for b in bs]]


WRAPPED = {
    "experience": [("EXPERIENCE", job_lines(LONG_JOBS))],
    "experience_a": [("EXPERIENCE", job_lines(LONG_JOBS[:2]))],
    "experience_b": [("", job_lines(LONG_JOBS[2:]))],
    "education": [("EDUCATION", [DEGREE, SCHOOL])],
}
SPACED = re.compile(r"(?:(?<![A-Za-z])[A-Za-z] ){3,}[A-Za-z](?![A-Za-z])")


def make(path, layout):
    saved = {k: TC.BLOCKS[k] for k in WRAPPED}
    TC.BLOCKS.update(WRAPPED)
    try:
        TC.make_layout_cv(path, layout)
    finally:
        TC.BLOCKS.update(saved)


def quotes_of(r):
    """Every quote of every card: 'What the ATS reads now' / 'In your resume now' and 'After the fix'."""
    out = []
    for c in D.issue_cards(r):
        cap, now, after = D.before_after(c, r)
        out += [(c["name"], q) for q in D.evidence(c, r) + now + [a[0] if isinstance(a, tuple) else a
                                                                  for a in (after or [])]]
    return out


class TestWrappedLines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.r = {}
        for name in TC.LAYOUTS:
            path = os.path.join(cls.tmp, f"lina_{name}.pdf")
            make(path, name)
            with open(path, "rb") as f:
                cls.r[name] = D.run_check(f.read(), f"lina_{name}.pdf", False, "")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_degree_wrapped_in_a_narrow_column_is_one_degree(self):
        for name, r in self.r.items():
            with self.subTest(layout=name):
                self.assertIn(DEGREE, " ".join(r["_vdoc"]["modern"].split()), "the degree line is joined")
                t9 = r["structure_checks"]["T9"]
                self.assertEqual(t9["score"], 1, t9)
                self.assertEqual(t9["entries"], 1)
                self.assertFalse([c for c in D.issue_cards(r) if c["key"] == "education_details"])

    def test_wrapped_job_titles_and_companies_are_whole(self):
        for name, r in self.r.items():
            with self.subTest(layout=name):
                jobs = L.ats_fields(r["_vdoc"], C.analyse_cv(r["_vdoc"]))["jobs"]
                self.assertEqual(len(jobs), 3, [j["title"] for j in jobs])
                self.assertIn(TITLE, [j["title"] for j in jobs])
                self.assertTrue(all(("LLC" in (j["company"] or "")) or ("FZE" in (j["company"] or "")) for j in jobs),
                                [j["company"] for j in jobs])
                t4 = r["structure_checks"]["T4"]
                self.assertEqual(t4["score"], 1, t4["evidence"])
                self.assertFalse([c for c in D.issue_cards(r) if c["key"] == "job_details"])

    def test_no_false_alarm_from_wrapping(self):
        for name, r in self.r.items():
            with self.subTest(layout=name):
                names = [c["name"] for c in D.issue_cards(r)]
                for bad in ("Education details are incomplete", "Some jobs miss a title, company or "
                            "Mon YYYY dates", "Some section names are unusual", "Two job titles written as one"):
                    self.assertNotIn(bad, names)

    def test_every_quote_is_clean(self):
        for name, r in self.r.items():
            with self.subTest(layout=name):
                vtext = " ".join(r["_vdoc"]["modern"].split())
                ats = " ".join(r["_doc"]["modern"].split())
                for card, q in quotes_of(r):
                    self.assertFalse(SPACED.search(q), (card, q))
                    if r["layout"]["columns_found"]:
                        core = re.split(r"\s{2,}\(", q)[0]
                        if len(core.split()) >= 4 and core in ats:
                            self.assertIn(core, vtext, (card, q))       # a line of the ATS text is also a real line


class TestJoinWrapped(unittest.TestCase):
    def rows(self, lines):
        return [{"page": 0, "text": t, "cells": [t], "x0": x0, "x1": x1, "top": top, "bottom": top + 9,
                 "font": (rest[0] if rest else "Regular"), "size": 9.0} for t, x0, x1, top, *rest in lines]

    def doc(self, lines):
        text = "\n".join(t for t, *_ in lines)
        return {"strict": text, "modern": text, "rows": self.rows(lines)}

    def test_open_line_is_joined(self):
        d = C.join_wrapped(self.doc([("Name", 10, 60, 10), ("Bachelor of Science in", 10, 100, 40),
                                     ("Supply Chain", 10, 70, 51), ("Other text here and there", 10, 100, 80)]))
        self.assertEqual([r["text"] for r in d["rows"]], ["Name", "Bachelor of Science in Supply Chain",
                                                          "Other text here and there"])
        self.assertIn("Bachelor of Science in Supply Chain", d["modern"].splitlines())

    def test_a_degree_without_school_and_year_continues_on_the_next_line(self):
        d = C.join_wrapped(self.doc([("Name", 10, 60, 10), ("Bachelor of Science", 10, 70, 40),
                                     ("Supply Chain Management, University of Dubai, 2016", 10, 140, 51)]))
        self.assertEqual(len(d["rows"]), 2)

    def test_separate_items_are_not_joined(self):
        lines = [("Name", 10, 60, 10), ("Senior Manager", 10, 80, 40, "Bold"), ("Acme Trading LLC", 10, 90, 51),
                 ("Dubai, UAE", 10, 70, 62), ("Other line of text", 10, 80, 73)]
        d = self.doc(lines)
        self.assertIs(C.join_wrapped(d), d)                        # a bold title and a plain company: two lines

    def test_a_line_that_cannot_hold_the_next_word_wraps(self):
        lines = [("Name", 10, 60, 10)] + [(f"A long line of text number {k}", 10, 200, 30 + 11 * k) for k in range(5)]
        lines += [("Senior Logistics and Supply Chain", 10, 150, 100), ("Coordinator, GCC Region", 10, 110, 111),
                  ("Next item", 10, 60, 135)]
        d = C.join_wrapped(self.doc(lines))
        self.assertIn("Senior Logistics and Supply Chain Coordinator, GCC Region", [r["text"] for r in d["rows"]])

    def test_bullets_dates_and_headings_are_not_joined(self):
        lines = [("Name", 10, 60, 10), ("EDUCATION", 10, 100, 40), ("Bachelor of Science in", 10, 100, 51),
                 ("Jan 2020 - Present", 10, 90, 62)]
        d = self.doc(lines)
        self.assertEqual([r["text"] for r in C.join_wrapped(d)["rows"]][1:], ["EDUCATION", "Bachelor of Science in",
                                                                               "Jan 2020 - Present"])

    def test_capital_country_after_a_comma_is_not_a_heading(self):
        d = C.join_wrapped(self.doc([("Name", 10, 60, 10), ("Ras Al Khaimah,", 10, 100, 40), ("UAE", 10, 40, 51)]))
        self.assertEqual(d["rows"][1]["text"], "Ras Al Khaimah, UAE")


if __name__ == "__main__":
    unittest.main()
