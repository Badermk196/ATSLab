"""
Tests for ATS Lab v3. All must pass before v3 scores are used.

  python -m unittest test_ATSLab_v3 -v

1. Bug detectors match bug_truth.json (no false alarms, no misses), plus made-up text for B6/B7.
2. Same CV + same job = same score every run.
3. Monotonicity: fixing any bug, check or keyword never lowers the score.
4. The parser fixes: "to" as a date dash, overlapping jobs, word forms on every word.
"""

import glob
import json
import os
import random
import unittest

import ATSLab_v3 as L

HERE = os.path.dirname(os.path.abspath(__file__))
CV_DIR = os.path.join(HERE, "CVS")
JOB_DIR = os.path.join(HERE, "JobDe")
with open(os.path.join(HERE, "bug_truth.json"), encoding="utf-8") as f:
    TRUTH = json.load(f)["cvs"]

_DOCS = {}


def doc(name):
    if name not in _DOCS:
        _DOCS[name] = L.extract_cv(os.path.join(CV_DIR, name + ".pdf"))
    return _DOCS[name]


def scored_names():
    return [n for n in TRUTH if os.path.exists(os.path.join(JOB_DIR, n + ".txt"))]


def fake_doc(text):
    rows = [{"page": 0, "text": l, "cells": [l]} for l in text.splitlines() if l.strip()]
    return {"strict": text, "modern": text, "rows": rows}


def state_for(name):
    job = os.path.join(JOB_DIR, name + ".txt")
    with open(job, encoding="utf-8", errors="ignore") as f:
        job_text = f.read()
    kw = L.load_keywords(job, None)
    return L.build_state(doc(name), job_text, kw)[0]


# ---------------------------------------------------------------------------
class TestBugDetectors(unittest.TestCase):
    def test_registry_matches_bug_table(self):
        self.assertEqual([b["code"] for b in L.BUGS], [f"B{i}" for i in range(1, 14)])
        for b in L.BUGS:
            self.assertIn(b["status"], L.STATUS_RANK)
            self.assertIn(b["severity"], L.SEVERITY_PENALTY)
            self.assertTrue(callable(b["detect"]))

    def test_detectors_against_truth_table(self):
        for name, expected in TRUTH.items():
            if not os.path.exists(os.path.join(CV_DIR, name + ".pdf")):
                continue
            d = doc(name)
            bugs = L.detect_bugs(d, L.analyse(d))
            for code in L.BUG_BY_CODE:
                if code not in expected:          # B13 is batch-only: tested in TestNewBugs
                    continue
                with self.subTest(cv=name, bug=code):
                    self.assertEqual(bugs[code]["found"], expected[code], bugs[code]["detail"])

    def test_tammam_skills_grid_is_not_empty(self):
        d = doc("Tammam_Versuni")
        ana = L.analyse(d)
        items, _ = L.skills_listed(ana)
        self.assertGreaterEqual(items, 8)
        self.assertFalse(L.detect_b2(d, ana)[0])

    def test_one_skill_per_line_is_not_b2(self):
        d = fake_doc("Aisha Noor\nTalent Acquisition Specialist\n"
                     "aisha@mail.com | +971 50 123 4567 | Dubai, UAE\n"
                     "SKILLS\nHeadhunting\nTalent screening\nATS management\n"
                     "Workforce planning\nStakeholder management")
        ana = L.analyse(d)
        items, _ = L.skills_listed(ana)
        self.assertGreaterEqual(items, 5)
        self.assertFalse(L.detect_b2(d, ana)[0])

    def test_category_only_skills_still_is_b2(self):
        d = fake_doc("Aisha Noor\nTalent Acquisition Specialist\n"
                     "aisha@mail.com | +971 50 123 4567 | Dubai, UAE\n"
                     "SKILLS\nTechnical Skills\nSoft Skills")
        ana = L.analyse(d)
        items, _ = L.skills_listed(ana)
        self.assertEqual(items, 0)
        self.assertTrue(L.detect_b2(d, ana)[0])

    def test_spaced_name_only_says_name_only(self):
        """A wide font splits the strict reading only and the readable text is normal ("ALAN ABBAS"), so no card
        (5 Nov 2026). When the letters really are apart the card fires and says "name only"."""
        for name in ("AllanAbbas_Revolut", "MathewOsama_Jobgether", "Tammam_Versuni"):
            d = doc(name)
            found, detail = L.detect_b1(d, L.analyse(d))
            self.assertFalse(found, detail)
        made = fake_doc("S A N A  M A L I K\nSenior Programme Manager\n"
                        "sana@mail.com | +971 50 123 4567 | Dubai, UAE\nSUMMARY\n"
                        "Programme manager with fifteen years of programme delivery across the UAE and KSA.\n"
                        "SKILLS\nProgramme delivery, Stakeholder management, Budgets")
        found, detail = L.detect_b1(made, L.analyse(made))
        self.assertTrue(found)
        self.assertTrue(detail.startswith("name only"), detail)

    def test_text_bugs_on_made_up_text(self):
        clean = "JOHN SMITH\nProduct Manager\njohn@mail.com | +971 50 000 0000\nSUMMARY\nBuilt things."
        cases = {
            "B3": "Prepared with 1000Jobs for John · 1000Jobs",
            "B5": "Led **20%** growth",
            "B6": "Managed <span style='x'>budgets</span>",
            "B7": "Sales Manager | Date Not Specified",
            "B10": "Equally comfortable designing plans",
        }
        d = fake_doc(clean)
        base = L.detect_bugs(d, L.analyse(d))
        for code in cases:
            self.assertFalse(base[code]["found"], f"{code} false alarm on clean text")
        self.assertFalse(base["B4"]["found"])
        for code, line in cases.items():
            with self.subTest(bug=code):
                d = fake_doc(clean + "\n" + line)
                self.assertTrue(L.detect_bugs(d, L.analyse(d))[code]["found"])
        d = fake_doc(clean.replace("john@mail.com | ", ""))
        self.assertTrue(L.detect_bugs(d, L.analyse(d))["B4"]["found"])

    def test_fixed_template_has_no_template_bugs(self):
        """The fixed 1000Jobs template: normal headings, 'Category: a, b' skills, real dates, single column."""
        for heading_case in (str.upper, str.title):
            h = lambda s: heading_case(s)
            text = "\n".join([
                "Jane Doe", "Senior Data Analyst | SQL | Python", "jane@mail.com | +971 50 123 4567 | Dubai, UAE",
                h("Professional Summary"),
                "Data analyst with 6 years of experience turning raw data into decisions for retail and banking teams.",
                h("Professional Experience"),
                "Senior Data Analyst — Acme Retail | Jan 2022 – Present",
                "Built SQL and Python pipelines that cut weekly reporting time by 40%.",
                "Data Analyst — Beta Bank | Mar 2019 – Dec 2021",
                "Created Power BI dashboards used by 12 branch managers.",
                h("Education"),
                "BSc Statistics — University of Sharjah (2018)",
                h("Skills"),
                "Programming: Python, SQL, R",
                "Analytics: Power BI | Tableau | Excel",
                "Methods: Regression, A/B Testing, Forecasting",
            ])
            with self.subTest(headings=heading_case.__name__):
                d = fake_doc(text)
                ana = L.analyse(d)
                bugs = L.detect_bugs(d, ana)
                found = [c for c, b in bugs.items() if b["found"]]
                self.assertEqual(found, [], {c: bugs[c]["detail"] for c in found})
                items, _ = L.skills_listed(ana)
                self.assertGreaterEqual(items, 8)
                c = L.readable_checks(d, ana, bugs, L.ATS_PROFILES["oracle"])
                for name in ("R5", "R6", "R7", "R9", "R11", "R12"):
                    self.assertEqual(c[name]["score"], 1.0, f"{name}: {c[name]['detail']}")

    def test_new_achievements_are_not_repeats(self):
        text = ("JOHN SMITH\nProduct Manager\njohn@mail.com\nPROFESSIONAL EXPERIENCE\n"
                "Manager — Acme | Jan 2020 – Present\nBuilt the billing platform for 2,000 retail clients.\n"
                "SELECT ACHIEVEMENTS\nWon the regional innovation award for warehouse robotics pilot.\n"
                "Published research on supply forecasting with university partners.")
        d = fake_doc(text)
        self.assertFalse(L.detect_b9(d, L.analyse(d))[0])


# ---------------------------------------------------------------------------
class TestParserFixes(unittest.TestCase):
    def test_to_in_prose_is_not_a_date_range(self):
        self.assertEqual(L.find_ranges("revenue grew from 2019 to 2021"), [])
        self.assertEqual(L.find_ranges("moved to 2020 plans"), [])
        self.assertEqual(len(L.find_ranges("Jan 2019 to Mar 2021")), 1)
        self.assertEqual(len(L.find_ranges("2019 to Present")), 1)
        self.assertEqual(len(L.find_ranges("2019 – 2021")), 1)

    def test_overlapping_jobs_are_merged(self):
        jobs = [L.make_job("A", "Jan 2019 – Dec 2021", 0), L.make_job("B", "Jan 2020 – Dec 2022", 1)]
        self.assertAlmostEqual(L.experience_years(jobs), 4.0)
        jobs = [L.make_job("A", "Jan 2015 – Dec 2016", 0), L.make_job("B", "Jan 2019 – Dec 2019", 1)]
        self.assertAlmostEqual(L.experience_years(jobs), 3.0)

    def test_word_forms_on_every_word(self):
        t = L.tokens
        self.assertEqual(L.match_level("manage stakeholder", t("managing stakeholders")), "variant")
        self.assertEqual(L.match_level("optimise campaigns", t("optimized campaign")), "variant")
        self.assertEqual(L.match_level("data modelling", t("data modeling")), "variant")
        self.assertEqual(L.match_level("Google Ads", t("google ads")), "exact")
        self.assertEqual(L.match_level("machine learning", t("built ML models")), "abbr")
        self.assertIsNone(L.match_level("Python", t("java developer")))

    def test_job_dates(self):
        self.assertEqual(L.make_job("X", "Sep 2022 – Present", 0)["problem"], None)
        self.assertEqual(L.make_job("X", "2021 – Present", 0)["problem"], "year only")
        self.assertEqual(L.make_job("X", "2 years", 0)["problem"], "duration instead of dates")
        self.assertEqual(L.make_job("X", "May 2021", 0)["problem"], "start date only")
        self.assertEqual(L.make_job("X", "", 0)["problem"], "no date")

    def test_title_from_first_line(self):
        self.assertEqual(L.title_from_first_line("\n\nSenior Product Manager\nAbout us"), "Senior Product Manager")
        self.assertEqual(L.title_from_first_line("🔍 We’re Hiring: SEO Specialist | SEM Specialist"), "SEO Specialist")
        self.assertIsNone(L.title_from_first_line("About Revolut\nPeople deserve more"))
        self.assertIsNone(L.title_from_first_line("\n\nWho You Are\n"))
        self.assertIsNone(L.title_from_first_line("Do you like working in collaborative teams?"))


# ---------------------------------------------------------------------------
POSTING = """Senior Data Analyst

We are looking for a Senior Data Analyst to join our analytics team in Dubai.
Requirements:
- 5+ years of experience with SQL and Python
- Strong data visualization skills using Power BI or Tableau
- Experience with statistical modelling, A/B testing and forecasting
- Knowledge of data warehousing and ETL pipelines
- Stakeholder management and clear communication
Nice to have: dbt, Snowflake, Looker.
"""


class TestKeywordCleaning(unittest.TestCase):
    def test_stop_lists_remove_generic_items(self):
        raw = {"title": "Senior Data Analyst", "required_skills": [
            "SQL", "Python", "growth", "design", "tools", "English", "internship", "crafting code for browsers",
            "complex technical problems", "creative innovation", "basic statistical modelling skills"]}
        kw = L.clean_keywords(raw, POSTING)
        kept = kw["required_skills"]
        for bad in ("growth", "design", "tools", "English", "internship", "complex technical problems",
                    "creative innovation"):
            self.assertNotIn(bad, kept)
        self.assertIn("statistical modelling", kept)        # qualifier + filler word removed
        reasons = {d["term"]: d["reason"] for d in kw["dropped"]}
        self.assertEqual(reasons["crafting code for browsers"], "too long")
        self.assertEqual(reasons["English"], "language")

    def test_at_least_ten_skills_from_close_matches_and_posting(self):
        raw = {"title": "Senior Data Analyst", "required_skills": ["SQL", "Python", "visualization of data"]}
        kw = L.clean_keywords(raw, POSTING)
        hard = kw["required_skills"] + kw["preferred_skills"]
        self.assertGreaterEqual(len(hard), 10, hard)
        self.assertEqual(kw["skill_sources"]["data visualization"], "close match")   # posting's own words
        self.assertTrue({"requirements / responsibilities", "mined from posting"} & set(kw["skill_sources"].values()))
        self.assertEqual(kw["quality"]["level"], "low")        # mostly mined -> warn

    def test_good_ai_answer_is_quality_ok(self):
        raw = {"title": "Senior Data Analyst", "required_skills": [
            "SQL", "Python", "data visualization", "Power BI", "Tableau", "statistical modelling", "A/B testing",
            "forecasting", "data warehousing", "ETL pipelines"], "preferred_skills": ["dbt", "Snowflake", "Looker"]}
        kw = L.clean_keywords(raw, POSTING)
        self.assertEqual(kw["quality"], {"level": "ok", "reasons": []})
        self.assertEqual(len(kw["required_skills"]) + len(kw["preferred_skills"]), 13)

    def test_title_is_validated_against_the_posting(self):
        posting = "\n\nWho You Are\nYou're an experienced client partner who grows accounts.\nYou'll lead the team."
        title, source, warning = L.choose_title("Account Director", posting)
        self.assertEqual((title, source), ("Client Partner", "posting phrase"))
        self.assertIsNotNone(warning)
        title, source, warning = L.choose_title("Who You Are", posting)
        self.assertEqual(title, "Client Partner")
        title, source, warning = L.choose_title("Audit | IT Audit | Internship | FY27", "Audit | IT Audit | Internship | FY27\nIT Audit work")
        self.assertEqual((title, warning), ("IT Audit", None))


FIELD_MARKETING = """Field Marketing Manager - MENA

Build and execute the demand generation marketing plan for the MENA region, hosting in-person and virtual events
including webinars, and building field marketing campaigns with the Enterprise Sales team.
Support the sales team and business development team with webinars, events, executive round tables,
lunch & learns, trade shows and partner events.
Strong event management skills. B2B marketing experience would be an advantage, as would industry knowledge
of Technology, SaaS or Cyber. We push the boundaries of innovation with creative, social tools.
Working knowledge of Salesforce, Hubspot, and Allocadia. Experience with marketing automation and KPIs.
"""


class TestKeywordRules(unittest.TestCase):
    """At most 20 short (1-3 word) skills, each required or preferred, spelled exactly as in the posting."""

    def assert_rules(self, kw, posting):
        hard = kw["required_skills"] + kw["preferred_skills"]
        self.assertLessEqual(len(hard), L.KEYWORD_MAX)
        for s in hard:
            self.assertLessEqual(len(s.split()), L.MAX_SKILL_WORDS, s)
            self.assertIn(s, posting, f"'{s}' is not spelled exactly as in the posting")
            self.assertIsNone(L.reject_reason(s), s)
        self.assertEqual(len({s.lower() for s in hard}), len(hard), "duplicates")

    def test_field_marketing_example(self):
        raw = {"title": "Field Marketing Manager", "required_skills": [
            "demand generation marketing plan", "field marketing campaigns", "webinars", "event management",
            "sales team", "business development team", "lunch & learns", "trade shows", "executive round tables",
            "B2B marketing", "salesforce", "HubSpot", "Allocadia", "KPI", "marketing automation"],
            "preferred_skills": ["Technology", "SaaS", "Cyber", "social", "creative", "innovation", "tools"]}
        kw = L.clean_keywords(raw, FIELD_MARKETING)
        self.assert_rules(kw, FIELD_MARKETING)
        hard = kw["required_skills"] + kw["preferred_skills"]
        reasons = {d["term"]: d["reason"] for d in kw["dropped"]}
        for bad, why in (("demand generation marketing plan", "too long"), ("sales team", "team, not a skill"),
                         ("business development team", "team, not a skill"), ("lunch & learns", "generic phrase"),
                         ("Technology", "generic word"), ("social", "generic word"), ("creative", "generic word"),
                         ("innovation", "generic word"), ("tools", "generic word")):
            self.assertNotIn(bad, hard)
            self.assertEqual(reasons.get(bad), why, bad)
        for good in ("field marketing campaigns", "webinars", "event management", "trade shows", "B2B marketing",
                     "Salesforce", "Hubspot", "Allocadia", "KPIs", "SaaS", "Cyber"):
            self.assertIn(good, hard)                              # posting spelling: 'Hubspot', 'KPIs'
        self.assertIn("SaaS", kw["preferred_skills"])
        self.assertIn("event management", kw["required_skills"])

    def test_never_more_than_20_required_first(self):
        words = [f"Tool{i}" for i in range(30)]
        posting = "Skills: " + ", ".join(words) + "."
        kw = L.clean_keywords({"required_skills": words[:15], "preferred_skills": words[15:]}, posting)
        self.assertEqual(len(kw["required_skills"]), 15)
        self.assertEqual(kw["preferred_skills"], words[15:20])
        self.assertEqual(sum(d["reason"].startswith("over the") for d in kw["dropped"]), 10)
        self.assert_rules(kw, posting)

    def test_rules_hold_for_every_saved_job(self):
        jobs = glob.glob(os.path.join(HERE, "*", "*_keywords_v3.json"))
        for path in jobs:
            txt = path.replace("_keywords_v3.json", ".txt")
            if not os.path.exists(txt):
                continue
            with open(txt, encoding="utf-8", errors="ignore") as f:
                posting = f.read()
            with self.subTest(job=os.path.basename(txt)):
                self.assert_rules(L.clean_keywords(L.read_raw_keywords(path), posting), posting)


GLUED_POSTING = (
    "Acme is an AI platform. We help large companies grow. We're proud to be named a Leader in Gartner and "
    "Forrester reports.Who We're Looking For:The Delivery Lead runs client projects on the Acme platform."
    "Responsibilities: Run webinars, partner events and trade shows.Enforce delivery standards and reporting "
    "frameworks.Requirements:Proven experience in program management and stakeholder management.What to expect "
    "from us:Recognition & Impact: A culture that values your ideas.Benefits & Rewards Package: We provide "
    "competitive compensation and flexible working.")


class TestPostingParts(unittest.TestCase):
    """Skills come only from the role part: never from the company description, values, benefits or perks."""

    def test_company_and_benefit_parts_are_ignored(self):
        role = L.skill_text(GLUED_POSTING)
        for gone in ("Gartner", "Forrester", "Impact", "Rewards Package", "flexible working", "We help"):
            self.assertNotIn(gone, role)
        for kept in ("Delivery Lead", "webinars", "delivery standards", "program management"):
            self.assertIn(kept, role)

    def test_line_headings_and_typed_newlines(self):
        posting = "About the job\\nWe build tools.\\nResponsibilities\\nRun webinars and trade shows.\\nBenefits\\nGym and bonus."
        role = L.skill_text(posting)
        self.assertIn("trade shows", role)
        self.assertNotIn("Gym", role)

    def test_stop_list_for_abstract_benefit_and_award_words(self):
        for term, why in (("Impact", "generic word"), ("Rewards Package", "benefit / perk"),
                          ("Forrester reports", "analyst / award name"), ("Gartner Magic Quadrant", "analyst / award name"),
                          ("health insurance", "benefit / perk"), ("flexible working", "benefit / perk")):
            self.assertEqual(L.reject_reason(term), why, term)
        for ok in ("trade shows", "webinars", "executive round tables", "partner events", "insurance underwriting"):
            self.assertIsNone(L.reject_reason(ok), ok)

    def test_activities_and_channels_are_skills(self):
        raw = {"title": "Delivery Lead", "required_skills": ["program management", "Impact", "Rewards Package",
                                                             "Forrester reports"]}
        kw = L.clean_keywords(raw, GLUED_POSTING)
        hard = kw["required_skills"] + kw["preferred_skills"]
        for s in ("webinars", "partner events", "trade shows", "program management"):
            self.assertIn(s, hard)
        for s in ("Impact", "Rewards Package", "Forrester reports"):
            self.assertNotIn(s, hard)


class TestStableExtraction(unittest.TestCase):
    """3 AI answers at temperature 0: a skill stays only if 2 of the 3 answers have it."""

    RUNS = [{"title": "Senior Data Analyst", "required_skills": ["SQL", "Python", "Tableau", "Excel"],
             "preferred_skills": ["dbt"], "soft_skills": ["Communication"], "degree_level": "bachelor", "min_years": 5},
            {"title": "Senior Data Analyst", "required_skills": ["SQL", "Python", "ETL pipeline"],
             "preferred_skills": ["dbt", "Looker"], "soft_skills": ["communication", "Teamwork"],
             "degree_level": "bachelor", "min_years": 4},
            {"title": "Data Analyst", "required_skills": ["Python", "SQL", "Tableau", "ETL pipelines"],
             "preferred_skills": [], "soft_skills": [], "degree_level": "master", "min_years": 5}]

    def test_two_of_three_vote(self):
        raw = L.vote_keywords(self.RUNS)
        self.assertEqual(raw["required_skills"], ["SQL", "Python", "Tableau", "ETL pipeline"])  # plural = same skill
        self.assertEqual(raw["preferred_skills"], ["dbt"])
        for once in ("Excel", "Looker", "Teamwork"):                                           # only 1 answer
            self.assertNotIn(once, raw["required_skills"] + raw["preferred_skills"] + raw["soft_skills"])
        self.assertEqual(raw["soft_skills"], ["Communication"])
        self.assertEqual((raw["title"], raw["degree_level"], raw["min_years"]), ("Senior Data Analyst", "bachelor", 5))

    def test_vote_does_not_depend_on_answer_order(self):
        a = L.vote_keywords(self.RUNS)
        b = L.vote_keywords(list(reversed(self.RUNS)))
        for k in ("required_skills", "preferred_skills"):
            self.assertEqual(sorted(L.skill_key(s) for s in a[k]), sorted(L.skill_key(s) for s in b[k]))

    def test_one_valid_answer_is_used_as_is(self):
        raw = L.vote_keywords([self.RUNS[0], None])
        self.assertEqual(raw["required_skills"], ["SQL", "Python", "Tableau", "Excel"])

    def test_retry_only_adds_new_skills(self):
        raw = L.add_retry(L.vote_keywords(self.RUNS), {"required_skills": ["sql", "Looker", "Snowflake"]})
        self.assertEqual(raw["required_skills"], ["SQL", "Python", "Tableau", "ETL pipeline", "Looker", "Snowflake"])

    def test_saved_runs_are_voted_on_load(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "Job_keywords_v3.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"ai_runs": self.RUNS, "ai_retry": {"preferred_skills": ["Snowflake"]}}, f)
            raw = L.read_raw_keywords(path)
        self.assertEqual(raw["preferred_skills"], ["dbt", "Snowflake"])

    def test_under_ten_fills_from_requirements_and_responsibilities_first(self):
        posting = ("Operations Analyst\nAbout us\nWe use Oracle Cloud, Kubernetes and SAP across our offices.\n"
                   "Responsibilities\n- Own inventory forecasting and demand planning\n- Build reports in Power BI\n"
                   "Requirements\n- Experience with SQL, Excel and Tableau\n- Knowledge of supply chain analytics\n"
                   "- Familiar with ERP systems and process mapping\nBenefits\n- Health insurance\n")
        kw = L.clean_keywords({"title": "Operations Analyst", "required_skills": ["SQL"]}, posting)
        hard = kw["required_skills"] + kw["preferred_skills"]
        for s in ("Excel", "Tableau", "inventory forecasting", "demand planning", "supply chain analytics"):
            self.assertIn(s, hard)
        self.assertIn("requirements / responsibilities", kw["skill_sources"].values())
        for company in ("Oracle Cloud", "Kubernetes", "SAP"):                       # company part: never
            self.assertNotIn(company, hard)
        self.assertNotIn("chain analytics", hard)                                  # piece of a longer skill
        for s in hard:
            self.assertLessEqual(len(s.split()), L.MAX_SKILL_WORDS)


class TestNearDuplicates(unittest.TestCase):
    """One skill inside another (also across a slash) -> keep one: the more important (earlier, required first)."""

    POSTING = ("Delivery Lead\nRequirements\n- Program/portfolio management and portfolio management reporting\n"
               "- Salesforce and Salesforce CRM administration\n- Supply chain analytics, SQL Server and SQL\n"
               "- IT audit engagements and auditing standards\n")

    def test_contained_and_slash_skills_are_merged(self):
        raw = {"required_skills": ["portfolio management", "IT audit", "Salesforce CRM", "SQL"],
               "preferred_skills": ["program/portfolio management", "auditing", "Salesforce", "SQL Server",
                                    "supply chain analytics"]}
        kw = L.clean_keywords(raw, self.POSTING)
        self.assertEqual(kw["required_skills"], ["portfolio management", "IT audit", "Salesforce CRM", "SQL"])
        self.assertEqual(kw["preferred_skills"], ["Supply chain analytics"])           # posting's spelling
        reasons = {d["term"]: d["reason"] for d in kw["dropped"]}
        self.assertEqual(reasons["Program/portfolio management"], "near-duplicate of 'portfolio management'")  # slash
        self.assertEqual(reasons["auditing"], "near-duplicate of 'IT audit'")       # generic word never wins
        self.assertEqual(reasons["Salesforce"], "near-duplicate of 'Salesforce CRM'")
        self.assertEqual(reasons["SQL Server"], "near-duplicate of 'SQL'")

    def test_slash_skill_first_keeps_slash_skill(self):
        raw = {"required_skills": ["program/portfolio management", "portfolio management"]}
        kw = L.clean_keywords(raw, self.POSTING)
        hard = kw["required_skills"] + kw["preferred_skills"]
        self.assertEqual(hard[:1], ["Program/portfolio management"])
        self.assertNotIn("portfolio management", hard)

    def test_title_is_never_only_a_job_type(self):
        posting = "Audit | IT Audit | Internship | FY27\nDuring your tenure as an Intern in IT Audit, you will ..."
        self.assertEqual(L.choose_title("Internship | FY27", posting)[0], "IT Audit")
        self.assertEqual(L.choose_title("Internship", posting)[0], "IT Audit")

    def test_no_near_duplicates_in_any_saved_job(self):
        for path in glob.glob(os.path.join(HERE, "*", "*_keywords_v3.json")):
            txt = path.replace("_keywords_v3.json", ".txt")
            if not os.path.exists(txt):
                continue
            with open(txt, encoding="utf-8", errors="ignore") as f:
                kw = L.clean_keywords(L.read_raw_keywords(path), f.read())
            keys = [L.skill_key(s) for s in kw["required_skills"] + kw["preferred_skills"]]
            for a in keys:
                for b in keys:
                    if a != b:
                        self.assertNotIn(f" {a} ", f" {b} ", f"{os.path.basename(txt)}: '{a}' inside '{b}'")


class TestEducationKeywords(unittest.TestCase):
    """Degree subjects are not skills: they go to education_keywords and are used by the education check (M4)."""

    POSTING = ("IT Auditor\nResponsibilities\n- Plan IT audit work and test internal controls\n"
               "- Review client accounting records\nRequirements\n"
               "- Graduate with a BA/BS in Computer Science, Management Information Systems, Accounting "
               "or a related field\n- Knowledge of SQL and risk assessment\n")

    def test_degree_subjects_leave_the_skill_list(self):
        raw = {"required_skills": ["IT audit", "Computer Science", "Management Information Systems", "SQL",
                                   "Accounting", "internal controls", "risk assessment"]}
        kw = L.clean_keywords(raw, self.POSTING)
        hard = kw["required_skills"] + kw["preferred_skills"]
        for subj in ("Computer Science", "Management Information Systems"):
            self.assertNotIn(subj, hard)
            self.assertIn(subj, kw["education_keywords"])
        self.assertIn("Accounting", hard)          # also named outside the degree line ('client accounting')
        self.assertTrue(kw["education_related_ok"])
        reasons = {d["term"]: d["reason"] for d in kw["dropped"]}
        self.assertEqual(reasons["Computer Science"], "degree subject -> education_keywords")

    def test_subjects_read_from_the_degree_sentence(self):
        text = ("Have graduated with a Bachelor's degree in Engineering (all fields), Engineering Technology, "
                "Mathematics, Chemistry, or similar, within the last 36 months.")
        self.assertEqual(L.degree_subjects(text), ["Engineering", "Engineering Technology", "Mathematics", "Chemistry"])

    def test_education_check_uses_subjects(self):
        """Subject part: listed subject 1.0, other subject 0.5 if 'related field' allowed, else 0.
        M4 = average of the parts it has (level, subject)."""
        self.assertEqual(L.RELATED_SUBJECT_CREDIT, 0.5)
        with_level = L.clean_keywords({"required_skills": ["IT audit"], "degree_level": "bachelor"}, self.POSTING)
        no_level = L.clean_keywords({"required_skills": ["IT audit"]}, self.POSTING)
        no_related = L.clean_keywords({"required_skills": ["IT audit"], "degree_level": "bachelor"},
                                      self.POSTING.replace(" or a related field", ""))
        m4 = lambda d, kw: L.matched_static(d, L.analyse(d), "", kw)["M4"]
        cs, bio = fake_doc("Education\nBSc Computer Science, 2020"), fake_doc("Education\nBSc Biology, 2020")
        self.assertEqual(m4(cs, with_level)["score"], 1.0)
        self.assertEqual(m4(bio, with_level)["score"], 0.75)      # level 1.0 + subject 0.5 -> 0.75
        self.assertIn("subject 0.5", m4(bio, with_level)["detail"])
        self.assertEqual(m4(bio, no_level)["score"], 0.5)         # subject part only
        self.assertEqual(m4(bio, no_related)["score"], 0.5)       # level 1.0 + subject 0 -> 0.5

    def test_no_degree_subject_in_any_saved_skill_list(self):
        for path in glob.glob(os.path.join(HERE, "*", "*_keywords_v3.json")):
            txt = path.replace("_keywords_v3.json", ".txt")
            if not os.path.exists(txt):
                continue
            with open(txt, encoding="utf-8", errors="ignore") as f:
                posting = f.read()
            kw = L.clean_keywords(L.read_raw_keywords(path), posting)
            for s in kw["required_skills"] + kw["preferred_skills"]:
                self.assertFalse(L.is_degree_subject(s, posting), f"{os.path.basename(txt)}: {s}")


class TestRoleLists(unittest.TestCase):
    """The under-10 fallback reads lists after any role lead-in line, not only 'Requirements' headings."""

    POSTING = ("Field Technician\n\nJoin our team\n\nAs a Field Technician, you will be responsible for:\n\n"
               "Coordinating crews, including data analysis and cost estimates\n"
               "Providing support for tenders, including invoicing and project scheduling\n\n"
               "Fuel your passion\n\nWe are a global energy company with offices in many places. "
               "We use Kubernetes and Snowflake.\n\n"
               "To be successful in this role you will:\n\n"
               "Have experience with SQL and Power BI, plus quality inspection\n\n"
               "In return we will provide you with:\n\nStock options, gym membership and learning budget planning\n")

    def test_lead_in_lists_are_read_and_offer_lists_are_not(self):
        lines = L.role_list_lines(self.POSTING)
        self.assertEqual(len(lines), 3)
        self.assertFalse(any("Fuel" in l or "Kubernetes" in l or "Stock options" in l for l in lines))

    def test_fallback_adds_only_posting_words_from_role_lists(self):
        kw = L.clean_keywords({"title": "Field Technician", "required_skills": ["data analysis"]}, self.POSTING)
        hard = kw["required_skills"] + kw["preferred_skills"]
        for s in ("cost estimates", "project scheduling", "SQL", "Power BI", "quality inspection"):
            self.assertIn(s, hard)
        for s in ("Kubernetes", "Snowflake", "budget planning"):
            self.assertNotIn(s, hard)
        for s in hard:
            self.assertIn(s, self.POSTING)                   # written exactly as in the posting
            self.assertLessEqual(len(s.split()), L.MAX_SKILL_WORDS)

    def test_chain_tails_and_language_lines_are_not_mined(self):
        text = ("Requirements:\n- Tools, including computer assisted audit techniques\n"
                "- Fluent in English (reading, speaking, and writing)\n")
        mined = L.mine_posting_skills(L.duty_and_requirement_text(text), set(), 20)
        self.assertNotIn("assisted audit", mined)
        self.assertNotIn("writing", mined)

    def test_saved_file_under_ten_gets_its_one_retry(self):
        import tempfile
        posting = self.POSTING * 2
        calls = []
        real = L.call_ai
        L.call_ai = lambda prompt, model: calls.append(prompt) or {"required_skills": ["quality inspection"]}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                job = os.path.join(tmp, "X_Job.txt")
                with open(job, "w", encoding="utf-8") as f:
                    f.write(posting)
                with open(L.keywords_path(job), "w", encoding="utf-8") as f:
                    json.dump({"ai_runs": [{"required_skills": ["data analysis"]}] * 3, "ai_retry": None}, f)
                L.load_keywords(job, "fake-model")
                L.load_keywords(job, "fake-model")                # second load: retry already saved, no call
                with open(L.keywords_path(job), encoding="utf-8") as f:
                    saved = json.load(f)
        finally:
            L.call_ai = real
        self.assertEqual(len(calls), 1)
        self.assertIn(L.RETRY_NOTE.strip()[:40], calls[0])
        self.assertEqual(saved["ai_retry"], {"required_skills": ["quality inspection"]})
        self.assertEqual(len(saved["ai_runs"]), 3)


class TestMeaningMatch(unittest.TestCase):
    """M3 = local embedding model (all-MiniLM-L6-v2, pinned), calibrated on our own CVs and jobs."""

    def test_scale_anchors_and_limits(self):
        self.assertEqual(L.meaning_scale(L.M3_RAW_GOOD), 0.8)    # typical good match -> 80
        self.assertEqual(L.meaning_scale(L.M3_RAW_POOR), 0.2)    # typical poor match -> 20
        self.assertEqual(L.meaning_scale(0.0), 0.0)
        self.assertEqual(L.meaning_scale(1.0), 1.0)
        raws = [i / 100 for i in range(101)]
        scaled = [L.meaning_scale(r) for r in raws]
        self.assertEqual(scaled, sorted(scaled))                 # more similar never scores lower

    def test_same_result_every_run(self):
        cv = doc("NedaSefati_Creatio")["modern"]
        with open(os.path.join(JOB_DIR, "NedaSefati_Creatio.txt"), encoding="utf-8") as f:
            job = f.read()
        first = L.meaning_match_raw(cv, job)
        L._EMBED_CACHE.clear()
        self.assertEqual(L.meaning_match_raw(cv, job), first)
        self.assertTrue(L.EMBED_REVISION)                        # pinned model version

    def test_weight_unchanged(self):
        d = doc("NedaSefati_Creatio")
        with open(os.path.join(JOB_DIR, "NedaSefati_Creatio.txt"), encoding="utf-8") as f:
            job = f.read()
        c = L.matched_static(d, L.analyse(d), job, L.load_keywords(os.path.join(JOB_DIR, "NedaSefati_Creatio.txt"), None))
        self.assertEqual(c["M3"]["weight"], 0.25)
        self.assertIn("embeddings", c["M3"]["name"])

    def test_own_job_beats_unrelated_jobs(self):
        """Calibration still holds on the 10 base CVs: own job ~70+, other people's jobs low."""
        names = scored_names()
        jobs = {}
        for n in names:
            with open(os.path.join(JOB_DIR, n + ".txt"), encoding="utf-8", errors="ignore") as f:
                jobs[n] = f.read()
        good, poor = [], []
        for n in names:
            cv = doc(n)["modern"]
            for j, text in jobs.items():
                (good if j == n else poor).append(L.meaning_match(cv, text))
        good.sort(); poor.sort()
        self.assertGreaterEqual(good[len(good) // 2], 0.70, good)
        self.assertLessEqual(poor[len(poor) // 2], 0.30)
        self.assertLess(sum(p >= 0.70 for p in poor) / len(poor), 0.10)

    def test_no_job_text_means_no_m3(self):
        self.assertIsNone(L.meaning_match("Some CV text with many words here.", ""))
        self.assertEqual(L.meaning_match_raw("", "Responsibilities: build data pipelines in Python."), 0.0)


class TestRoleTextFilter(unittest.TestCase):
    """M3 and keywords read only the role text: no perks, hiring process, legal, scam or company lines."""

    POSTING = ("Who are we? Acme is the leading cloud-first enterprise data company. We believe in open data.\n"
               "Responsibilities\n- You will manage employee benefits, pension and health insurance programmes.\n"
               "- Experience marketing wellness products is a strong advantage.\n- Build data pipelines in Python.\n"
               "Employees At Acme Enjoy These Perks A weekly lunch stipend of $75.\n"
               "Full health and dental benefits.\n100% Parental Leave top-up for 6 months.\n"
               "Job scams are on the rise.\nReport it now.\nWe won't ask for payment during the hiring process.\n"
               "By submitting this application, I confirm that all the information is true.\n"
               "We are an equal opportunity employer. Emails come from an @acme.com address.\n")

    def test_non_role_sentences_are_dropped(self):
        role = L.skill_text(self.POSTING)
        for gone in ("Who are we", "leading cloud-first", "We believe", "lunch stipend", "dental", "Parental Leave",
                     "Job scams", "Report it now", "hiring process", "I confirm", "equal opportunity", "@acme.com"):
            self.assertNotIn(gone, role)
        for kept in ("You will manage employee benefits, pension", "wellness products", "data pipelines in Python"):
            self.assertIn(kept, role)          # role sentences stay even when they mention benefits / wellness

    def test_real_postings_have_no_perks_or_boilerplate_in_m3_text(self):
        for name, gone in (("rashaadnmohammed_Cohere", ("stipend", "dental", "Parental Leave", "recruitment process",
                                                         "Who are we", "headquartered")),
                           ("AllanAbbas_Revolut", ("scam", "submitting this application", "Privacy Notice",
                                                   "diverse backgrounds", "@revolut.com"))):
            with open(os.path.join(JOB_DIR, name + ".txt"), encoding="utf-8", errors="ignore") as f:
                pieces = " ".join(L.meaning_chunks(L.skill_text(f.read())))
            for g in gone:
                self.assertNotIn(g.lower(), pieces.lower(), f"{name}: {g}")


class TestHeadlineScores(unittest.TestCase):
    """Readability + Job Match + Total in the report, results.json and results.csv; the total is unchanged."""

    def test_headline_values(self):
        name = "NedaSefati_Creatio"
        res = L.score_cv(os.path.join(CV_DIR, name + ".pdf"), os.path.join(JOB_DIR, name + ".txt"), None, doc=doc(name))
        h = res["headline"]
        self.assertEqual(h["total"], res["overall"])                        # total = the same overall as before
        self.assertEqual(h["readability"], res["readable_overall"])
        for p, a in res["ats"].items():
            f, m = a["findable"] / 100, a["matched"] / 100
            expect = (max(0.01, f) ** 0.3 * max(0.01, m) ** 0.4) ** (1 / 0.7) * 100
            self.assertAlmostEqual(a["job_match"], expect, delta=0.15, msg=p)
            self.assertTrue(min(f, m) * 100 - 0.1 <= a["job_match"] <= max(f, m) * 100 + 0.1)   # between F and M
        self.assertAlmostEqual(h["job_match"], sum(a["job_match"] for a in res["ats"].values()) / 3, delta=0.1)

    def test_no_job_has_readability_only(self):
        name = "NedaSefati_Creatio"
        res = L.score_cv(os.path.join(CV_DIR, name + ".pdf"), None, None, doc=doc(name))
        self.assertIsNone(res["headline"]["job_match"])
        self.assertIsNone(res["headline"]["total"])
        self.assertIsNotNone(res["headline"]["readability"])

    def test_csv_and_json_have_the_headline(self):
        import csv as _csv
        import tempfile
        name = "NedaSefati_Creatio"
        res = L.score_cv(os.path.join(CV_DIR, name + ".pdf"), os.path.join(JOB_DIR, name + ".txt"), None, doc=doc(name))
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "r.json")
            L.write_outputs([res], out)
            with open(out, encoding="utf-8") as f:
                data = json.load(f)
            with open(os.path.join(tmp, "r.csv"), encoding="utf-8") as f:
                row = next(_csv.DictReader(f))
        self.assertEqual(data["results"][0]["headline"], res["headline"])
        self.assertEqual(data["summary"]["average_job_match"], res["headline"]["job_match"])
        self.assertEqual(float(row["readability"]), res["headline"]["readability"])
        self.assertEqual(float(row["job_match"]), res["headline"]["job_match"])
        self.assertEqual(float(row["overall"]), res["overall"])


class TestFalseAlarms(unittest.TestCase):
    """Step 3: punctuation, MM/YYYY dates, 'Additional Information', no graduation year for 10+ years."""

    def test_punctuation_is_normalized(self):
        same = [("Talent & Culture", "Product Manager - Talent and Culture"),
                ("Talent and Culture", "Talent & Culture"),
                ("Product Manager - Digital Projects", "Product Manager – Digital Projects"),
                ("Product Manager — Digital Projects", "Product Manager - Digital Projects"),
                ("full-stack", "fullstack developer"), ("fullstack", "full stack developer"),
                ("e-commerce", "ecommerce"), ("R&D", "R and D")]
        for term, text in same:
            self.assertEqual(L.match_level(term, L.tokens(text)), "exact", (term, text))
        for term, text in (("Java", "JavaScript"), ("data", "database"), ("Product Manager", "Project Manager")):
            self.assertIsNone(L.match_level(term, L.tokens(text)), (term, text))

    def test_title_check_ignores_punctuation(self):
        d = fake_doc("Jane Doe\nProduct Manager – Talent and Culture\njane@x.com +971 50 123 4567\n")
        ana = L.analyse(d)
        f3 = L.findable_static(d, ana, {"title": "Product Manager - Talent & Culture"}, None, L.ATS_PROFILES["oracle"])
        self.assertEqual(f3["F3"]["score"], 1.0)
        f4 = L.findable_static(d, ana, {"title": ""}, {"titles": ["Product Manager - Talent & Culture"]},
                               L.ATS_PROFILES["oracle"])
        self.assertEqual(f4["F4"]["score"], 1.0)

    def test_mm_yyyy_dates_are_valid(self):
        r = L.find_ranges("03/2021 - 06/2023")
        self.assertTrue(r and r[0]["month_format"])
        self.assertTrue(L.find_ranges("11/2019 – Present")[0]["month_format"])
        self.assertIsNone(L.make_job("Analyst", "03/2021 - 06/2023", 0)["problem"])
        self.assertEqual(L.make_job("Analyst", "2021 - 2023", 0)["problem"], "year only")   # year-only still flagged

    def cv(self, years):
        start = L.TODAY.year - years
        return fake_doc("Jane Doe\nOperations Manager\njane@x.com +971 50 123 4567\nEXPERIENCE\n"
                        f"Operations Manager | Acme | Jan {start} - Present\n- Ran operations.\n"
                        "EDUCATION\nBachelor of Science in Engineering, Cairo University\n"
                        "ADDITIONAL INFORMATION\nDriving licence\n")

    def test_no_graduation_year_needed_after_10_years(self):
        for years, expect in ((12, 1.0), (3, 0.5)):
            d = self.cv(years)
            ana = L.analyse(d)
            r8 = L.readable_checks(d, ana, L.detect_bugs(d, ana), L.ATS_PROFILES["oracle"])["R8"]
            self.assertEqual(r8["score"], expect, (years, r8["detail"]))

    def test_additional_information_is_standard(self):
        self.assertTrue(L.is_heading("Additional Information"))
        d = self.cv(5)
        ana = L.analyse(d)
        r11 = L.readable_checks(d, ana, L.detect_bugs(d, ana), L.ATS_PROFILES["workday"])["R11"]
        self.assertEqual(r11["score"], 1.0, r11["detail"])


class TestNewBugs(unittest.TestCase):
    """Step 4: B12 backticks, B10 phrase list, B13 text shared between different users' CVs."""

    LEAK = "Senior business operations leader with 12 years of experience across GCC markets and teams."

    def test_b12_backticks(self):
        d = fake_doc("Jane Doe\nUsed `Python` and `SQL` daily.")
        self.assertTrue(L.detect_b12(d, L.analyse(d))[0])
        self.assertIn("B12", L.BROKEN_TEXT_BUGS)
        d = fake_doc("Jane Doe\nUsed Python and SQL daily.")
        self.assertFalse(L.detect_b12(d, L.analyse(d))[0])

    def test_b10_has_running_the_room(self):
        d = fake_doc("Jane Doe\nComfortable running the room with executives.")
        found, detail = L.detect_b10(d, L.analyse(d))
        self.assertTrue(found)
        self.assertIn("running the room", detail)

    def test_b13_shared_between_users_only(self):
        docs = {"a/Jane_X.pdf": fake_doc(f"Jane Doe\nSUMMARY\n{self.LEAK}\nI led five teams."),
                "a/Omar_Y.pdf": fake_doc(f"Omar Ali\nSUMMARY\nProfile: {self.LEAK} Strong in finance."),
                "a/Jane_Z.pdf": fake_doc(f"Jane Doe\nSUMMARY\n{self.LEAK}\nOther text."),     # same user
                "a/Lina_W.pdf": fake_doc("Lina Saad\nSUMMARY\nSenior business operations leader in retail.")}
        users = L.mark_shared_text(docs)
        self.assertEqual(users["a/Jane_X.pdf"], users["a/Jane_Z.pdf"])
        found = {p: L.detect_b13(d, L.analyse(d)) for p, d in docs.items()}
        self.assertTrue(found["a/Jane_X.pdf"][0])
        self.assertIn("Omar_Y.pdf", found["a/Jane_X.pdf"][1])
        self.assertNotIn("Jane_Z.pdf", found["a/Jane_X.pdf"][1])       # the same user's other CV is not a leak
        self.assertTrue(found["a/Omar_Y.pdf"][0])                     # copied phrase inside a longer sentence
        self.assertFalse(found["a/Lina_W.pdf"][0])                    # short overlap (< 10 words) is fine

    def test_b13_needs_a_batch(self):
        d = fake_doc("Jane Doe\n" + self.LEAK)
        found, detail = L.detect_b13(d, L.analyse(d))
        self.assertFalse(found)
        self.assertIn("not checked", detail)

    def test_b13_on_real_rounds(self):
        import glob as _g
        docs = {p: L.extract_cv(p) for p in sorted(_g.glob(os.path.join(HERE, "CV4", "*.pdf")))}
        L.mark_shared_text(docs)
        hit = sorted(os.path.basename(p) for p, d in docs.items() if L.detect_b13(d, L.analyse(d))[0])
        self.assertEqual(hit, ["AllanAbbas_Revolut.pdf", "Tammam_Versuni.pdf"])

    def test_b13_penalty_and_monotonic(self):
        self.assertEqual(L.bug_penalty("B13"), 8)
        self.assertEqual(L.bug_penalty("B12"), 3)
        st = state_for("NedaSefati_Creatio")
        st["bugs"] = st["bugs"] + ["B13"]
        self.assertGreaterEqual(L.overall_of(L.fix_bug(st, "B13")), L.overall_of(st))


class TestSmellChecks(unittest.TestCase):
    """Step 5: possible new bugs are listed for a human, never scored."""

    BASE = ("Jane Doe\nOperations Manager\njane@x.com +971 50 123 4567\nSUMMARY\nRan operations for 8 years.\n"
            "EXPERIENCE\n")

    def kinds(self, text, strict=None):
        d = fake_doc(text)
        if strict is not None:
            d["strict"] = strict
        return [x["kind"] + ": " + x["detail"] for x in L.smell_checks(d, L.analyse(d))]

    def test_symbols_and_code(self):
        found = " ".join(self.kinds(self.BASE + "Built <div class='x'> pages, **bold**, `code`, {name}, #TODO.\n"))
        for label in ("code", "'**'", "backtick", "'{' or '}'", "'#'"):
            self.assertIn(label, found)
        clean = self.kinds(self.BASE + "Kept a >98% on-time rate with C# and F#, ranked #1 of 20.\n")
        self.assertFalse([x for x in clean if x.startswith("symbols")], clean)

    def test_placeholders(self):
        for ph in ("[Company Name]", "[ ]", "? - 2020", "N/A", "TBD", "Location not specified"):
            self.assertTrue(any(x.startswith("placeholder") for x in self.kinds(self.BASE + f"Acme {ph}\n")), ph)

    def test_empty_section_and_strict_difference(self):
        self.assertTrue(any(x.startswith("empty section") for x in self.kinds(self.BASE + "EDUCATION\nSKILLS\nSQL, Python\n")))
        text = self.BASE + "Managed suppliers and logistics across three countries for many years.\n"
        self.assertFalse(any(x.startswith("strict") for x in self.kinds(text, strict=text)))
        broken = text.replace("suppliers and logistics across three", "suppliersandlogisticsacrossthree")
        self.assertTrue(any(x.startswith("strict") for x in self.kinds(text, strict=broken)))

    def test_odd_dates(self):
        y = L.TODAY.year
        cv = (self.BASE + f"Manager | Acme | Mar {y + 2} - Present\nLead | Beta | Jun 2020 - Jan 2019\n"
              f"Analyst | Gamma | Jan 2015 - Dec 2018\nClerk | Delta | Jan 2016 - Jun 2017\n")
        found = " ".join(self.kinds(cv))
        for what in ("future", "ends before it starts", "overlapping", "not in date order"):
            self.assertIn(what, found)

    def test_smells_never_change_the_score(self):
        name = "NedaSefati_Creatio"
        job = os.path.join(JOB_DIR, name + ".txt")
        a = L.score_cv(os.path.join(CV_DIR, name + ".pdf"), job, None, doc=doc(name))
        real = L.smell_checks
        L.smell_checks = lambda d, ana: [{"kind": "odd dates", "detail": "x"}] * 5
        try:
            b = L.score_cv(os.path.join(CV_DIR, name + ".pdf"), job, None, doc=doc(name))
        finally:
            L.smell_checks = real
        self.assertEqual(a["overall"], b["overall"])
        self.assertEqual(len(b["possible_new_bugs"]), 5)


class TestWhatChanged(unittest.TestCase):
    def snap(self, text):
        d = fake_doc(text)
        ana = L.analyse(d)
        return {"user": "jane", "fields": L.ats_fields(d, ana),
                "lines": [L._norm_line(x) for x in text.splitlines() if len(x.split()) >= 3]}

    def test_fields_sections_jobs_and_text(self):
        a = self.snap("Jane Doe\nOperations Manager\n+971 50 123 4567\nSUMMARY\nRan operations for many years.\n"
                      "EXPERIENCE\nOperations Manager | Acme | Jan 2019 - Present\nCAREER IMPACT\n$4m 67% 34%\n")
        b = self.snap("Jane Doe\nOperations Manager\njane@x.com | +971 50 123 4567\nSUMMARY\nRan operations for many "
                      "years.\nEXPERIENCE\nOperations Manager | Acme | Feb 2019 - Present\nSKILLS\nSQL, Excel, Python\n")
        c = L.compare_cvs(a, b)
        self.assertIn({"field": "email", "change": "appeared", "before": None, "after": "jane@x.com"}, c["fields"])
        self.assertEqual(c["sections"]["appeared"], ["SKILLS"])
        self.assertEqual(c["sections"]["disappeared"], ["CAREER IMPACT"])
        self.assertEqual(c["jobs"]["dates_changed"], ["Operations Manager: Jan 2019 - Present -> Feb 2019 - Present"])
        self.assertEqual(c["skills"], [0, 3])
        self.assertIn("$4m 67% 34%", c["text"]["disappeared"])

    def test_real_folders_pair_by_name(self):
        pairs = L.compare_folders(os.path.join(HERE, "CV2"), os.path.join(HERE, "CV4"))
        both = [x for x in pairs if x["changes"] is not None]
        self.assertEqual(len(both), 10)
        self.assertIn("jibran-original-cv.pdf", [x["cv_b"] for x in pairs if x["cv_a"] is None])


class TestWhatTheATSSees(unittest.TestCase):
    """Step 6: fields an ATS fills in, with cut-off / merged titles flagged."""

    CV = ("Jane Doe\nOperations Manager | Supply Chain | Logistics &\n"
          "jane@x.com | +971 50 123 4567 | Dubai, UAE | linkedin.com/in/janedoe\n"
          "EXPERIENCE\nSupply Chain Executive | Feb 2025 - Present\nBabyGrow FZC\nRan daily supplier coordination.\n"
          "Alshaya Group - UAE Sep 2021 - Jun 2023\nAssistant Merchandiser\nManaged stock allocation.\n"
          "PRODUCT MANAGER - 3 Years | Jan 2018 - Aug 2021\nAcme LLC, Dubai\nLed the roadmap.\n"
          "EDUCATION\nBachelor of Commerce | 2015\nUniversity of Wollongong in Dubai\n"
          "SKILLS\nLogistics, Excel, SAP, Inventory Control\n")

    def test_fields(self):
        d = fake_doc(self.CV)
        f = L.ats_fields(d, L.analyse(d))
        self.assertEqual((f["name"], f["email"], f["phone"]), ("Jane Doe", "jane@x.com", "+971 50 123 4567"))
        self.assertEqual((f["location"], f["linkedin"]), ("Dubai, UAE", "linkedin.com/in/janedoe"))
        got = [(j["title"], j["company"], j["dates"]) for j in f["jobs"]]
        self.assertEqual(got[0], ("Supply Chain Executive", "BabyGrow FZC", "Feb 2025 - Present"))     # 1000Jobs layout
        self.assertEqual(got[1][:2], ("Assistant Merchandiser", "Alshaya Group"))   # company line first, place removed
        self.assertEqual(f["education"], ["Bachelor of Commerce | 2015", "University of Wollongong in Dubai"])
        self.assertEqual(f["skills"], ["Logistics", "Excel", "SAP", "Inventory Control"])

    def test_cut_off_and_merged_titles_are_flagged(self):
        d = fake_doc(self.CV)
        f = L.ats_fields(d, L.analyse(d))
        self.assertIn("cut off", f["headline_problem"])
        self.assertIn("merged", f["jobs"][2]["title_problem"])                      # '- 3 Years' in the title
        self.assertIsNone(f["jobs"][0]["title_problem"])
        self.assertIn("cut off", L.title_problem("Head of Sales and"))
        self.assertIn("merged", L.title_problem("Sales Manager Led a team of 12 people across five GCC markets daily"))
        self.assertIsNone(L.title_problem("Marketing Lead | Strategy | Growth | Brand | Media | Digital | Retail | "
                                          "Consumer | Analytics", max_words=None))   # long headline is fine
        smells = L.smell_checks(d, L.analyse(d))
        self.assertTrue(any(x["kind"] == "cut-off or merged title" for x in smells))

    def test_places(self):
        for p in ("Dubai, UAE", "United Arab Emirates", "Sharjah, United Arab Emirates", "Assiut, Egypt"):
            self.assertTrue(L.is_place(p), p)
        for p in ("Global FMCG Media Strategy", "Marketing Lead, Middle East", "jane@x.com", "Acme LLC"):
            self.assertFalse(L.is_place(p), p)

    def test_glyph_codes_are_a_smell(self):
        d = fake_doc("Jane Doe\nEXPERIENCE\nMedia Director | Mar 2020 - Present\n(cid:11)Universa lMedia\n")
        self.assertTrue(any("cid" in x["detail"] for x in L.smell_checks(d, L.analyse(d))))

    def test_results_have_the_view(self):
        name = "NedaSefati_Creatio"
        res = L.score_cv(os.path.join(CV_DIR, name + ".pdf"), None, None, doc=doc(name))
        v = res["ats_view"]
        self.assertEqual(v["text_strict"], doc(name)["strict"])
        for k in ("name", "email", "phone", "location", "linkedin", "headline", "jobs", "education", "skills"):
            self.assertIn(k, v["fields"])
        self.assertTrue(v["fields"]["jobs"] and all({"title", "company", "dates"} <= set(j) for j in v["fields"]["jobs"]))


class TestCVEvaluationMode(unittest.TestCase):
    """Step 7: no job description, a target role -> readability, bugs, plain feedback that reveals nothing inside."""

    LEAK_RE = __import__("re").compile(
        r"\b[RFMB]\d{1,2}\b|weight|penalt|formula|points|keyword|\^|0\.\d|mon yyyy|mm/yyyy|\d+\s*-\s*\d+ words|"
        r"\b(add|remove|rename|replace|change|write|use|move|delete)\b|template|1000jobs", __import__("re").I)

    def test_feedback_shape_and_score(self):
        name = "NedaSefati_Creatio"
        res = L.score_cv(os.path.join(CV_DIR, name + ".pdf"), None, None, doc=doc(name), role="Delivery Lead")
        fb = res["feedback"]
        self.assertEqual(fb["score"], round(res["headline"]["readability"]))
        self.assertEqual(fb["label"], L.label_for(res["headline"]["readability"]))
        self.assertLessEqual(len(fb["problems"]), 3)
        self.assertIn("target role", res["mode"])
        self.assertTrue(res["bugs"])                           # the bug list is still there

    def test_role_missing_is_the_first_problem(self):
        name = "NedaSefati_Creatio"
        fb = L.score_cv(os.path.join(CV_DIR, name + ".pdf"), None, None, doc=doc(name), role="Data Scientist")["feedback"]
        self.assertEqual(fb["problems"][0], "Your CV does not clearly present you as a Data Scientist.")
        d = fake_doc("Jane Doe\nLogistics Coordinators | Supply Chain\njane@x.com\nSUMMARY\nLogistics coordinator.\n")
        self.assertTrue(L.role_presented(d, L.analyse(d), "Logistics Coordinator"))     # variant counts

    def test_feedback_reveals_no_formula_keywords_or_fixes(self):
        import re as _re
        for name in TRUTH:
            if not os.path.exists(os.path.join(CV_DIR, name + ".pdf")):
                continue
            fb = L.score_cv(os.path.join(CV_DIR, name + ".pdf"), None, None, doc=doc(name), role="Product Manager")["feedback"]
            text = " ".join([fb["summary"]] + fb["problems"])
            with self.subTest(cv=name):
                self.assertIsNone(self.LEAK_RE.search(text), text)
                self.assertFalse(_re.search(r"\d", text), text)            # the only number shown is the score

    def test_job_mode_has_no_feedback(self):
        name = "NedaSefati_Creatio"
        res = L.score_cv(os.path.join(CV_DIR, name + ".pdf"), os.path.join(JOB_DIR, name + ".txt"), None,
                         doc=doc(name), role="Delivery Lead")
        self.assertNotIn("feedback", res)                     # with a job description, the full report is used
        self.assertEqual(res["mode"], "full")


class TestRounds(unittest.TestCase):
    """Step 8: results_v3_round1/2/3 = CVS / CV2 / CV4 scored by this v3 with JobDe and its _keywords_v3.json."""

    def test_round_files_match_a_fresh_score(self):
        for i, folder in ((1, "CVS"), (2, "CV2"), (3, "CV4")):
            path = os.path.join(HERE, f"results_v3_round{i}.json")
            if not os.path.exists(path):
                self.skipTest(f"{path} not made yet")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            saved = {r["cv"]: r for r in data["results"]}
            pdfs = sorted(os.path.basename(p) for p in glob.glob(os.path.join(HERE, folder, "*.pdf")))
            self.assertTrue(set(saved) <= set(pdfs), folder)      # every scored CV is still there (new ones may be added)
            name = "NedaSefati_Creatio"
            docs = {p: L.extract_cv(p) for p in sorted(glob.glob(os.path.join(HERE, folder, "*.pdf")))}
            L.mark_shared_text(docs)                  # B13 is checked across the batch, like the round run
            cv = os.path.join(HERE, folder, name + ".pdf")
            res = L.score_cv(cv, os.path.join(JOB_DIR, name + ".txt"), None, doc=docs[cv])
            with self.subTest(round=i):
                self.assertEqual(res["overall"], saved[name + ".pdf"]["overall"])
                self.assertEqual(res["headline"], saved[name + ".pdf"]["headline"])


class TestNotAJob(unittest.TestCase):
    """A .txt that is a web page or not a job description is skipped (no AI call) and the reason is given."""

    def test_web_page_short_text_and_non_job_are_skipped(self):
        page = "<!DOCTYPE html>\n<html><head><title>Workspace</title></head><body><div>Hi</div></body></html>"
        self.assertIn("web page", L.not_a_job_reason(page))
        self.assertIn("web page", L.not_a_job_reason("Notes\n" + "<div class='x'>cell</div>\n" * 40))
        self.assertIn("too short", L.not_a_job_reason("Senior Data Analyst. Apply now."))
        recipe = "Mix the flour with sugar and eggs, then bake for twenty minutes at a medium heat. " * 10
        self.assertIn("no job-description words", L.not_a_job_reason(recipe))
        self.assertIsNone(L.not_a_job_reason(POSTING * 3))

    def test_every_real_job_passes(self):
        for txt in glob.glob(os.path.join(HERE, "*", "*.txt")):
            if os.path.basename(txt).lower().startswith("!doctype"):
                continue
            folder = os.path.basename(os.path.dirname(txt))
            if folder.startswith("release-") or folder == "pretest_public":    # a frozen copy, a downloaded test set
                continue
            with open(txt, encoding="utf-8", errors="ignore") as f:
                self.assertIsNone(L.not_a_job_reason(f.read()), txt)

    def test_load_and_score_skip_with_reason(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            job = os.path.join(tmp, "Someone_Page.txt")
            with open(job, "w", encoding="utf-8") as f:
                f.write("<!DOCTYPE html>\n<html><body><div>TalentLens</div></body></html>")
            with self.assertRaises(L.NotAJob) as e:
                L.load_keywords(job, "any-model")             # stops before any AI call
            self.assertIn("web page", str(e.exception))
            self.assertEqual(os.listdir(tmp), ["Someone_Page.txt"])   # no keyword file written
            name = next(iter(TRUTH))
            res = L.score_cv(os.path.join(CV_DIR, name + ".pdf"), job, None, doc=doc(name))
            self.assertIn("web page", res["job_skipped"])
            self.assertEqual(res["mode"], "readable only (no job description)")


# ---------------------------------------------------------------------------
class TestProtectedFiles(unittest.TestCase):
    """The v2 Lab and the original _keywords.json files must never be changed, filtered or read by v3."""

    @staticmethod
    def sha(path):
        import hashlib
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def test_v2_lab_and_old_keyword_files_unchanged(self):
        with open(os.path.join(HERE, "protected_files.json"), encoding="utf-8") as f:
            protected = json.load(f)["files"]
        self.assertIn("ATSLab_v2_frozen.py", protected)
        for rel, digest in protected.items():
            with self.subTest(file=rel):
                self.assertEqual(self.sha(os.path.join(HERE, rel)), digest, f"{rel} was changed")
        self.assertEqual(self.sha(os.path.join(HERE, "ATSLab_v2_frozen.py")), self.sha(os.path.join(HERE, "ATSLab.py")))

    def test_v3_keyword_path_is_never_the_old_file(self):
        for job in glob.glob(os.path.join(HERE, "*", "*.txt")):
            self.assertTrue(L.keywords_path(job).endswith("_keywords_v3.json"))

    def test_v3_never_falls_back_to_old_keyword_file(self):
        import shutil
        import tempfile
        src = os.path.join(JOB_DIR, "NedaSefati_Creatio")
        with tempfile.TemporaryDirectory() as tmp:
            job = os.path.join(tmp, "Neda.txt")
            old = os.path.join(tmp, "Neda_keywords.json")
            shutil.copy(src + ".txt", job)
            shutil.copy(src + "_keywords.json", old)
            before = self.sha(old)
            with self.assertRaises(SystemExit):        # no _keywords_v3.json and no model -> stop, never read v2
                L.load_keywords(job, None)
            self.assertEqual(self.sha(old), before)
            self.assertEqual(sorted(os.listdir(tmp)), ["Neda.txt", "Neda_keywords.json"])

    def test_loading_every_job_leaves_old_files_alone(self):
        olds = {p: self.sha(p) for p in glob.glob(os.path.join(HERE, "*", "*_keywords.json"))}
        for path in glob.glob(os.path.join(HERE, "*", "*_keywords_v3.json")):
            txt = path.replace("_keywords_v3.json", ".txt")
            if os.path.exists(txt):
                L.load_keywords(txt, None)
        for p, digest in olds.items():
            self.assertEqual(self.sha(p), digest, p)


# ---------------------------------------------------------------------------
class TestReadableOnly(unittest.TestCase):
    def test_cv_without_job_gets_readable_and_bugs(self):
        name = "profile-user-2UXAuWAmUaH2A5vU-1790959538885-ynuipc"
        res = L.score_cv(os.path.join(CV_DIR, name + ".pdf"), None, doc=doc(name))
        self.assertEqual(res["mode"], "readable only (no job description)")
        self.assertIsNone(res["overall"])
        self.assertEqual(len(res["bugs"]), len(L.BUGS))
        for p in L.ATS_PROFILES:
            self.assertIsNotNone(res["ats"][p]["readable"])
            self.assertIsNone(res["ats"][p]["findable"])
            self.assertIsNone(res["ats"][p]["matched"])
            self.assertFalse(any(n.startswith(("F", "M")) for n in res["ats"][p]["checks"]))
        self.assertFalse(res["ready_for_any_ats"])


# ---------------------------------------------------------------------------
class TestScoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.states = {n: state_for(n) for n in scored_names()}

    def test_same_score_every_run(self):
        for name in scored_names()[:4]:
            job = os.path.join(JOB_DIR, name + ".txt")
            cv = os.path.join(CV_DIR, name + ".pdf")
            a = L.score_cv(cv, job)
            b = L.score_cv(cv, job)
            self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True), name)

    def assertNotLower(self, before, after, what):
        for p in L.ATS_PROFILES:
            self.assertGreaterEqual(L.evaluate(after, p)["total"] + 1e-9, L.evaluate(before, p)["total"], f"{what} ({p})")

    def test_fixing_any_bug_never_lowers_the_score(self):
        for name, s in self.states.items():
            for code in L.BUG_BY_CODE:
                with self.subTest(cv=name, bug=code):
                    self.assertNotLower(s, L.fix_bug(s, code), f"{name} fix {code}")

    def test_fixing_any_check_or_keyword_never_lowers_the_score(self):
        for name, s in self.states.items():
            for c in s["checks"]["oracle"]:
                self.assertNotLower(s, L.fix_check(s, c), f"{name} fix {c}")
            for r in s["kw"]:
                self.assertNotLower(s, L.fix_keyword(s, r["term"]), f"{name} add '{r['term']}'")

    def test_random_chains_of_fixes_never_lower_the_score(self):
        rnd = random.Random(7)
        for name, s in self.states.items():
            fixes = ([("bug", c) for c in L.BUG_BY_CODE] + [("check", c) for c in s["checks"]["oracle"]]
                     + [("kw", r["term"]) for r in s["kw"]])
            for _ in range(5):
                cur = s
                for kind, x in rnd.sample(fixes, min(12, len(fixes))):
                    nxt = {"bug": L.fix_bug, "check": L.fix_check, "kw": L.fix_keyword}[kind](cur, x)
                    self.assertNotLower(cur, nxt, f"{name} chain {kind} {x}")
                    cur = nxt

    def test_no_double_counting(self):
        for b in L.BUGS:
            if b["owns"]:
                self.assertEqual(L.bug_penalty(b["code"]), 0, b["code"])
            else:
                self.assertEqual(L.bug_penalty(b["code"]), L.SEVERITY_PENALTY[b["severity"]], b["code"])
        self.assertEqual({b["code"] for b in L.BUGS if not b["owns"]}, {"B3", "B5", "B6", "B7", "B8", "B9", "B10", "B12", "B13"})

    def test_penalty_cap_and_gates(self):
        s = next(iter(self.states.values()))
        allbugs = dict(s, bugs=list(L.BUG_BY_CODE))
        self.assertLessEqual(L.evaluate(allbugs, "oracle")["penalty"], L.PENALTY_CAP)
        self.assertEqual(L.evaluate(dict(s, honest=False), "oracle")["total"], 0.0)
        nocontact = dict(s, contact={"email": False, "phone": False})
        self.assertLessEqual(L.evaluate(nocontact, "oracle")["total"], L.CAP_NO_CONTACT)
        nokw = dict(s, kw=[dict(r, hits=[]) for r in s["kw"]])
        self.assertLessEqual(L.evaluate(nokw, "oracle")["total"], L.CAP_LOW_REQUIRED)

    def test_perfect_cv_gets_the_badge(self):
        s = next(iter(self.states.values()))
        for code in L.BUG_BY_CODE:
            s = L.fix_bug(s, code)
        for c in s["checks"]["oracle"]:
            s = L.fix_check(s, c)
        for r in s["kw"]:
            s = L.fix_keyword(s, r["term"])
        s = dict(s, honest=True, contact={"email": True, "phone": True})
        self.assertAlmostEqual(L.evaluate(s, "oracle")["total"], 100.0)
        ok, why = L.badge(s)
        self.assertTrue(ok, why)

    def test_score_scale(self):
        self.assertEqual(L.label_for(95), "Excellent")
        self.assertEqual(L.label_for(80), "Strong")
        self.assertEqual(L.label_for(79.9), "Good")
        self.assertEqual(L.label_for(55), "Needs work")
        self.assertEqual(L.label_for(40), "At risk")
        self.assertEqual(L.label_for(39.9), "Not ready")


if __name__ == "__main__":
    unittest.main()
