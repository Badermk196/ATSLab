"""2026-10-23: strong resumes must not be pulled down by false issues. A test set of strong resumes (strongcvs\\) and
of weak ones (weakcvs\\), plus the rules behind it: headline, section names, summary, action verbs, abbreviations,
year-only dates, and the stricter AI reviewer."""
import glob
import os
import re
import unittest

import ATSLab_v3 as L
import cv_review as R
import cv_score as C
import dashboard as D
import test_cv_score as T

HERE = os.path.dirname(os.path.abspath(__file__))
STRONG = sorted(glob.glob(os.path.join(HERE, "strongcvs", "*.pdf")))
WEAK = sorted(glob.glob(os.path.join(HERE, "weakcvs", "*.pdf")))
COMMON = ["KPI", "UX", "UI", "AI", "CEO", "USD", "UAE", "GCC", "ROI", "ROAS", "CRM", "SEO", "B2B", "B2C", "HR", "IT",
          "PR"]


def check_cached_review(path):
    """The dashboard's check with the AI reviewer's SAVED answer (cv_reviews\\): no API call is ever made here."""
    saved = os.environ.get("OPENROUTER_API_KEY")
    real = L.call_ai
    os.environ["OPENROUTER_API_KEY"] = "cache-only"
    L.call_ai = lambda *a, **k: None
    try:
        with open(path, "rb") as f:
            return D.run_check(f.read(), os.path.basename(path), False, "", None, None)
    finally:
        L.call_ai = real
        if saved is None:
            os.environ.pop("OPENROUTER_API_KEY", None)
        else:
            os.environ["OPENROUTER_API_KEY"] = saved


class Results:
    """Every resume of both sets is checked once for the whole file."""
    cache = {}

    @classmethod
    def get(cls, path):
        if path not in cls.cache:
            r = check_cached_review(path)
            cls.cache[path] = (r, D.issue_cards(r))
        return cls.cache[path]


class TestTestSets(unittest.TestCase):
    def test_both_sets_exist(self):
        self.assertGreaterEqual(len(STRONG), 15)
        self.assertGreaterEqual(len(WEAK), 6)
        names = " ".join(os.path.basename(p) for p in STRONG)
        for must in ("Jibran_Konkar_Resume", "Mohamedshokry", "Tareq_MarshMcLennan_latest", "CV4_"):
            self.assertIn(must, names)
        weak = " ".join(os.path.basename(p) for p in WEAK)
        for must in ("Rowan", "Tareq_old_sidebar"):
            self.assertIn(must, weak)


class TestStrongResumes(unittest.TestCase):
    def each(self):
        for p in STRONG:
            r, cards = Results.get(p)
            with self.subTest(cv=os.path.basename(p)):
                yield p, r, cards

    def test_score_75_or_more(self):
        for p, r, cards in self.each():
            self.assertGreaterEqual(r["score"], 75, [c["name"] for c in cards])

    def test_no_headline_card_when_a_headline_exists(self):
        for p, r, cards in self.each():
            if D.headline_text(r):
                self.assertFalse([c["name"] for c in cards if c["name"].startswith("No headline")], r["cv"])

    def test_no_action_verb_card_for_past_tense_verbs(self):
        for p, r, cards in self.each():
            self.assertFalse([c for c in cards if "strong action verb" in c["name"]], r["cv"])
            for c in cards:
                if c["key"] == "weak_openers":
                    for q in c["issues"][0]["evidence"]:
                        self.assertTrue(C.WEAK_OPENERS.match(C.first_word(q)[1]), q)

    def test_no_common_abbreviation_card(self):
        for p, r, cards in self.each():
            flagged = re.findall(r"never written in full: (.+)$", r["content_checks"]["C12"]["detail"])
            words = re.split(r",\s*", flagged[0]) if flagged else []
            self.assertFalse(set(words) & set(COMMON), words)

    def test_at_most_three_ai_findings(self):
        for p, r, cards in self.each():
            ai = [c for c in cards if c.get("ai")]
            self.assertLessEqual(len(ai), R.MAX_FINDINGS, r["cv"])
            if r.get("ai_review"):
                self.assertLessEqual(len(r["ai_review"].get("findings") or ai), R.MAX_FINDINGS)
                for c in ai:
                    self.assertIn(c["severity"], ("Critical", "Major"))

    def test_no_summary_length_card_and_no_old_text(self):
        for p, r, cards in self.each():
            self.assertFalse([c["name"] for c in cards if "40 to 90" in c["name"]], r["cv"])


class TestWeakResumes(unittest.TestCase):
    def test_weak_resumes_stay_below_60_with_their_real_issues(self):
        for p in WEAK:
            r, cards = Results.get(p)
            with self.subTest(cv=os.path.basename(p)):
                self.assertLess(r["score"], 60, [c["name"] for c in cards])
                self.assertTrue(cards)

    def test_rowan_and_the_old_sidebar_resume_keep_their_real_issues(self):
        for name in ("Rowan_Elatrache_Original_CV.pdf", "Tareq_old_sidebar_CV.pdf"):
            r, cards = Results.get(os.path.join(HERE, "weakcvs", name))
            keys = {c["key"] for c in cards}
            with self.subTest(cv=name):
                self.assertLess(r["score"], 50)
                self.assertGreaterEqual(len([c for c in cards if c["severity"] in ("Critical", "Major")]), 2, keys)
        r, cards = Results.get(os.path.join(HERE, "weakcvs", "Tareq_old_sidebar_CV.pdf"))
        self.assertIn("Template is hard for ATS to read", [c["name"] for c in cards])


class TestHeadline(T.Base):
    def test_capital_headline_under_the_name_is_the_headline(self):
        for head in ("MEDIA & MARKETING DIRECTOR", "MEDIA & MARKETING DIRECTOR\nBRAND STRATEGY | PERFORMANCE MARKETING"):
            with self.subTest(head=head):
                doc = T.changed("Logistics Coordinator | Freight Forwarding | Customs Clearance", head)
                ana = C.analyse_cv(doc)
                self.assertIn("MEDIA & MARKETING DIRECTOR", [x["text"] for x in ana["header"]])
                self.assertNotIn("MEDIA & MARKETING DIRECTOR", [s["title"] for s in ana["sections"]])
                self.assertEqual(L.ats_fields(doc, ana)["headline"], "MEDIA & MARKETING DIRECTOR")
                self.assertEqual(L.analyse(doc)["header"][1]["text"], "MEDIA & MARKETING DIRECTOR")
                r = self.score(doc)
                self.assertFalse([i for i in r["issues"] if i["id"] in ("R4", "C15")])
                self.assertEqual(r["structure_checks"]["T1"]["score"], 1)

    def test_a_real_heading_under_the_name_is_not_a_headline(self):
        for heading in ("SUMMARY", "PROFESSIONAL SUMMARY", "SKILLS & TOOLS", "CONTACT"):
            self.assertEqual(L.headline_rows(["JANE DOE", heading, "text"]), set(), heading)
        self.assertEqual(L.headline_rows(["JANE DOE", "jane@mail.com | +971 50 123 4567", "MEDIA DIRECTOR"]), set())
        self.assertEqual(L.headline_rows(["JANE DOE", "PROJECT MANAGER"]), {1})

    def test_a_headline_without_a_role_is_not_called_missing(self):
        doc = T.changed("Logistics Coordinator | Freight Forwarding | Customs Clearance",
                        "FREIGHT FORWARDING | CUSTOMS CLEARANCE")
        r = self.score(doc)
        r["_doc"] = doc
        cards = {c["key"]: c for c in D.issue_cards(r)}
        self.assertEqual(cards["headline"]["name"], "Your headline does not name a target role")
        none = T.changed("Logistics Coordinator | Freight Forwarding | Customs Clearance\n", "")
        r = self.score(none)
        r["_doc"] = none
        self.assertTrue({c["key"]: c for c in D.issue_cards(r)}["headline"]["name"].startswith(
            "No headline with a target title"))


class TestSummaryCard(unittest.TestCase):
    def test_summary_length_card_is_gone(self):
        text = " ".join(str(v) for k, v in D.ISSUES.items() for v in (v["name"], v["why"], v["fix"]) if k == "summary")
        self.assertEqual(D.ISSUES["summary"]["name"], "Summary is over 150 words")
        self.assertIn("150", text)
        self.assertNotIn("40 to 90", text)
        self.assertEqual(D.ISSUES["summary"]["ids"], ["C4", "R13"])


class TestActionVerbCard(unittest.TestCase):
    def test_one_card_for_weak_openers(self):
        self.assertNotIn("action_verbs", D.ISSUES)
        self.assertEqual(D.ISSUE_OF["C11"], "weak_openers")
        self.assertEqual(D.ISSUE_OF.get("C2"), "weak_openers")
        self.assertEqual(D.ISSUES["weak_openers"]["name"], "Bullets start with weak words")
        for w in ("Responsible for", "Helped", "Assisted", "Participated in"):
            self.assertIn(w, D.ISSUES["weak_openers"]["why"])


class TestYearOnlyDates(T.Base):
    def test_year_only_card_text_and_quotes(self):
        doc = T.changed("Logistics Coordinator | Jan 2021 - Present", "Logistics Coordinator | 2021 - Present")
        r = self.score(doc)
        r["_doc"] = doc
        card = next(c for c in D.issue_cards(r) if c["key"] == "job_details")
        self.assertEqual(card["name"], "Your job dates show years only")
        self.assertEqual(card["fix"], "Your dates show years only (e.g. 2021 - Present). "
                                      "Add the month: Jan 2021 - Present.")
        quotes = D.evidence(card, r)
        self.assertEqual(quotes, ["2021 - Present  (year only)"])           # the date line, not the job title line
        self.assertFalse([q for q in quotes if "Logistics Coordinator" in q])

    def test_a_missing_job_location_is_a_small_note_not_the_general_card(self):
        doc = T.changed("Desert Cargo FZE | Sharjah, UAE", "Desert Cargo FZE")      # (2026-10-28: a location is not required)
        r = self.score(doc)
        r["_doc"] = doc
        cards = D.issue_cards(r)
        self.assertNotIn("job_details", [c["key"] for c in cards])
        card = next(c for c in cards if c["key"] == "job_locations")
        self.assertEqual(card["name"], D.ISSUES["job_locations"]["name"])
        self.assertEqual(card["tag"], "Minor")


if __name__ == "__main__":
    unittest.main()


def bullets_replaced(new, extra=""):
    """The standard CV with its six bullets replaced by `new` (a list, padded with the originals)."""
    lines = T.polished_cv()["modern"].split("\n")
    at = [k for k, l in enumerate(lines) if l.startswith("- ")]
    for k, text in zip(at, new):
        lines[k] = "- " + text
    return T.fake_doc("\n".join(lines) + extra)


class TestOpenPoints(T.Base):
    """2026-10-23 (2): a date under a degree, a headline of areas, font-code bullets, the same result repeated."""

    def test_date_line_under_a_degree_is_part_of_the_degree(self):
        old = "Bachelor of Science in Supply Chain Management, University of Dubai, 2017"
        for lines in ("Bachelor of Science in Supply Chain Management, University of Dubai\n(2013–2017)",
                      "Bachelor of Science in Supply Chain Management, University of Dubai\n2017",
                      "Bachelor of Science in Supply Chain Management, University of Dubai\nGraduated 2017",
                      "Bachelor of Science in Supply Chain Management, University of Dubai\nSep 2013 - Jun 2017"):
            with self.subTest(lines=lines):
                r = self.score(T.changed(old, lines))
                self.assertEqual(r["structure_checks"]["T2"]["score"], 1, r["structure_checks"]["T2"])
        flagged = T.changed(old, old + "\nDeloitte Management Consulting Challenge | Deloitte | Mar 2016")
        self.assertLess(self.score(flagged)["structure_checks"]["T2"]["score"], 1)    # a real non-degree item stays

    def test_headline_of_areas_counts_as_no_headline(self):
        # 2026-10-26 (rule 4, reference set): a headline that names no job title is "no headline": Important
        r = self.score(T.changed("Logistics Coordinator | Freight Forwarding | Customs Clearance",
                                 "SUPPLY CHAIN & LOGISTICS | INVENTORY & VENDOR OPERATIONS"))
        card = next(i for i in r["issues"] if i["id"] == "C15")
        self.assertEqual(card["severity"], "Major")
        self.assertEqual(r["content_checks"]["C15"]["score"], 0)
        none = self.score(T.changed("Logistics Coordinator | Freight Forwarding | Customs Clearance\n", ""))
        big = next(i for i in none["issues"] if i["id"] == "C15")
        self.assertEqual(big["severity"], "Major")                                  # no headline: still Important
        self.assertGreater(big["points"], 6)

    def test_font_code_bullets_are_bullets(self):
        text = T.polished_cv()["modern"]
        coded = T.fake_doc(text.replace("\n- ", "\n(cid:127) "))
        plain = self.score(T.fake_doc(text))
        r = self.score(coded)
        self.assertEqual(r["content_checks"]["C1"]["bullets"], plain["content_checks"]["C1"]["bullets"])
        self.assertEqual(r["content_checks"]["C1"]["detail"], plain["content_checks"]["C1"]["detail"])
        t14 = next(i for i in r["issues"] if i["id"] == "T14")
        self.assertEqual(t14["severity"], "Minor")
        self.assertIn("(cid:127)", t14["evidence"][0])
        self.assertEqual(D.ISSUES["icon_bullets"]["name"], "Some bullet symbols may not display in every ATS")
        self.assertEqual(D.ISSUE_OF["T14"], "icon_bullets")
        self.assertFalse([i for i in plain["issues"] if i["id"] == "T14"])

    def groups(self, new, extra=""):
        return C.repeated_results(C.analyse_cv(bullets_replaced(new, extra)))

    RESULT = "Grew freight revenue by {n} through new carrier contracts across the region."

    def test_same_result_four_times_is_flagged_three_is_not(self):
        three = [self.RESULT.format(n="$25M")] * 3 + ["Tracked inbound containers with the port system daily."] * 3
        self.assertEqual(self.groups(three), [])
        four = [self.RESULT.format(n="$25M")] * 4 + ["Tracked inbound containers with the port system daily."] * 2
        g = self.groups(four)
        self.assertEqual([(x["number"], x["count"]) for x in g], [("$25M", 4)])
        r = self.score(bullets_replaced(four))
        self.assertIn("$25M (4 times)", r["content_checks"]["C9"]["detail"])
        self.assertEqual([i["severity"] for i in r["issues"] if i["id"] == "C9"], ["Minor"])

    def test_three_times_when_one_is_in_a_highlight_section(self):
        three = [self.RESULT.format(n="$25M")] * 2 + ["Tracked inbound containers with the port system daily."] * 4
        self.assertEqual(self.groups(three), [])
        extra = "\nCAREER IMPACT AT A GLANCE\n- $25M freight revenue growth through new carrier contracts"
        g = self.groups(three, extra)
        self.assertEqual([(x["number"], x["count"]) for x in g], [("$25M", 3)])
        extra = "\nSELECT ACHIEVEMENTS\n- $25M freight revenue growth through new carrier contracts"
        self.assertEqual(len(self.groups(three, extra)), 1)

    def test_years_dates_phones_and_small_numbers_are_ignored(self):
        for n in ("5", "7 clients", "2024", "+971 50 123 4567", "Mar 2021", "9"):
            with self.subTest(n=n):
                lines = [f"Grew freight revenue by {n} through new carrier contracts across the region."] * 6
                self.assertEqual(self.groups(lines), [], n)

    def test_same_number_with_different_words_is_not_the_same_result(self):
        lines = ["Grew freight revenue by 40% through new carrier contracts across the region.",
                 "Cut customs clearance errors by 40% after retraining the documentation team.",
                 "Improved warehouse picking accuracy by 40% with barcode scanners installed.",
                 "Raised customer satisfaction scores by 40% using weekly feedback calls.",
                 "Tracked inbound containers with the port system daily.",
                 "Trained new coordinators on inventory management steps."]
        self.assertEqual(self.groups(lines), [])


class TestFontCodeBeforeCompanyLine(T.Base):
    def test_marker_before_a_company_line_is_not_a_bullet(self):
        text = T.polished_cv()["modern"].replace("Gulf Freight LLC | Dubai, UAE", "(cid:11)Gulf Freight LLC — Dubai, UAE")
        doc, notes = C.normalize_doc(T.fake_doc(text))
        self.assertIn("Gulf Freight LLC — Dubai, UAE", doc["modern"])
        self.assertNotIn("• Gulf Freight", doc["modern"])
        self.assertNotIn("(cid:", doc["modern"])
        self.assertEqual(len(notes["icon_bullets"]), 1)                 # still noted: the symbol may not display


# ---------------------------------------------------------------------------
# 2026-10-23: clean quotes and education, on every resume of both sets
# ---------------------------------------------------------------------------
SPACED_WORDS = re.compile(r"(?:(?:^|(?<=[^A-Za-z]))[A-Za-z] ){3,}[A-Za-z](?![A-Za-z])")
DEGREE_LINE = re.compile(r"\b(?:bachelor|master|mba|ph\.?d|doctorate|diploma|b\.\s?[a-z]{1,4}\b|m\.\s?[a-z]{1,4}\b|"
                         r"b\.?\s?sc|m\.?\s?sc)", re.I)
SCHOOL_HINT = re.compile(r"universit|college|institute|school|academy|polytechni|facult|école|ecole|"
                         r"(?:[—–|,(]\s*)[A-Z]{3,8}\b", re.I)
YEAR = re.compile(r"\b(?:19|20)\d\d\b")


def all_quotes(r):
    out = []
    for c in D.issue_cards(r):
        cap, now, after = D.before_after(c, r)
        out += [(c["name"], q) for q in D.evidence(c, r) + now + [a[0] if isinstance(a, tuple) else a
                                                                  for a in (after or [])]]
    return out


def flat(text):
    return " ".join(re.sub(r"[\W_]+", " ", text).lower().split())


def each_resume(case, paths):
    for p in paths:
        r, cards = Results.get(p)
        with case.subTest(cv=os.path.basename(p)):
            yield p, r, cards


class TestQuotesAreClean(unittest.TestCase):
    PATHS = STRONG + WEAK

    def test_no_letter_spaced_words_in_any_quote(self):
        for p, r, cards in each_resume(self, self.PATHS):
            for card, q in all_quotes(r):
                self.assertFalse(SPACED_WORDS.search(q), (card, q))

    def test_no_text_of_two_columns_on_one_line(self):
        """In a resume with columns every quoted line is a line of the column-by-column text (an ATS reads a line of
        two columns joined; a card never quotes that)."""
        for p, r, cards in each_resume(self, self.PATHS):
            if not (r.get("layout") or {}).get("columns_found"):
                continue
            seen, ats = flat(r["_vdoc"]["modern"] + " " + r["_vdoc"]["strict"]), flat(r["_doc"]["modern"] + " " +
                                                                                      r["_doc"]["strict"])
            for card, q in all_quotes(r):
                for seg in [q.replace("…", ""), re.split(r"\s{2,}\(", q)[0].replace("…", "")] + \
                        re.findall(r"\"([^\"]{8,})\"", q):
                    seg = flat(seg)
                    if len(seg.split()) >= 4 and seg in ats:
                        self.assertIn(seg, seen, (card, q))

    def test_quotes_are_short_readable_lines(self):
        for p, r, cards in each_resume(self, self.PATHS):
            for card, q in all_quotes(r):
                self.assertLessEqual(len(q), D.QUOTE_MAX + 40, (card, q[:80]))


def education_complete(r):
    """True when the resume has degrees and each has a degree name, a school and a year (checked on its own, from
    the column-by-column text: the line, the next three lines and the line above)."""
    ana = C.analyse_cv(r["_vdoc"])
    rows = [x["text"] for x in L.section_rows(ana, "education")]
    degrees = [k for k, t in enumerate(rows) if DEGREE_LINE.search(t) and not re.match(r"^\s*[•*-]", t)
               and not re.match(r"^[\w ]{2,25}:", t.strip())]
    if not degrees:
        return False
    for n, k in enumerate(degrees):
        end = degrees[n + 1] if n + 1 < len(degrees) else len(rows)
        text = " ".join(rows[max(0, k - 1): min(end, k + 4)])
        if not (SCHOOL_HINT.search(text) and YEAR.search(text)):
            return False
    return True


class TestEducationCard(unittest.TestCase):
    def test_no_incomplete_education_card_when_every_degree_has_name_school_and_year(self):
        checked = 0
        for p, r, cards in each_resume(self, STRONG + WEAK):
            if education_complete(r):
                checked += 1
                self.assertFalse([c["name"] for c in cards if c["key"] == "education_details"], r["cv"])
                self.assertEqual(r["structure_checks"]["T9"]["every_year"], True, r["cv"])
        self.assertGreaterEqual(checked, 10)                       # the check really ran on many resumes


class TestEducationEntries(unittest.TestCase):
    def test_school_and_year_on_the_lines_after_the_degree(self):
        e = C.education_entries(["Bachelor of Arts, Environmental Design | Sep 2013 – Jun 2016",
                                 "Université du Québec à Montréal (UQAM) — Montreal, QC"])
        self.assertEqual([(x["school"], x["year"]) for x in e], [(True, True)])

    def test_school_as_an_acronym_and_degree_with_short_name(self):
        for line in ("MBA, Finance — JDBIMS, Mumbai | 2002 – 2004",
                     "B.E., Electronics & Telecommunications — Pune University, India (2010)",
                     "B.S. in Marketing & Management (LAU, 2009)"):
            e = C.education_entries([line])
            self.assertEqual([(x["school"], x["year"]) for x in e], [(True, True)], line)

    def test_school_above_the_degree_and_year_below(self):
        e = C.education_entries(["University of the Arts London", "MA Graphic Branding & Identity", "2023"])
        self.assertEqual([(x["school"], x["year"]) for x in e], [(True, True)])

    def test_two_degrees_each_need_their_own_year(self):
        e = C.education_entries(["Bachelor of Science, University of Dubai, 2017",
                                 "Master of Business Administration, University of Dubai"])
        self.assertEqual([x["year"] for x in e], [True, False])

    def test_date_line_with_a_grade_belongs_to_the_degree(self):
        self.assertTrue(C.is_date_line("2022–2026 | CGPA: 3.41"))
        self.assertTrue(C.is_date_line("Graduated 2016, GPA 3.8/4.0"))
        self.assertFalse(C.is_date_line("Deloitte Management Consulting Challenge | 2022"))


class TestEducationFlag(T.Base):
    def test_a_degree_with_no_year_is_still_flagged(self):
        old = "Bachelor of Science in Supply Chain Management, University of Dubai, 2017"
        r = self.score(T.changed(old, old.replace(", 2017", "")))
        self.assertEqual(r["structure_checks"]["T9"]["every_year"], False)
        self.assertLess(r["structure_checks"]["T9"]["score"], 1)
