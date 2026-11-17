"""
Tests for the CV Score (cv_score.py), measured against the 1000jobs CV standard. No AI calls.

  py -3.12 -m unittest test_cv_score -v
"""

import json
import os
import re
import shutil
import tempfile
import unittest

import ATSLab_v3 as L
import cv_score as C

HERE = os.path.dirname(os.path.abspath(__file__))
ROLE = "Logistics Coordinator"
SKILLS = {"required_skills": ["Inventory Management", "Freight Forwarding", "Customs Clearance", "Warehouse Operations",
                              "SAP", "Shipment Tracking"],
          "preferred_skills": ["Microsoft Excel", "Incoterms", "Route Planning"]}


def fake_doc(text):
    rows = [{"page": 0, "text": l, "cells": [l]} for l in text.splitlines() if l.strip()]
    return {"strict": text, "modern": text, "rows": rows}


def polished_cv(numbers=True, spaced_name=False):
    """A CV that meets every 1000jobs standard. numbers=False: the same bullets without any number."""
    n = (lambda x, plain: x if numbers else plain)
    name = "J A N E D O E" if spaced_name else "Jane Doe"
    bullets = [
        n("Coordinated 40+ weekly freight forwarding shipments across five GCC markets with zero customs penalties.",
          "Coordinated weekly freight forwarding shipments across GCC markets without customs penalties."),
        n("Reduced warehouse operations costs by 18% through better inventory management and route planning.",
          "Reduced warehouse operations costs through better inventory management and route planning."),
        n("Managed customs clearance for 300 import files a year using SAP and Incoterms rules.",
          "Managed customs clearance for import files using SAP and Incoterms rules."),
        n("Built a Microsoft Excel shipment tracking dashboard used daily by 12 planners.",
          "Built a Microsoft Excel shipment tracking dashboard used daily by the planning team."),
        n("Negotiated carrier rates that saved AED 250,000 in the first year.",
          "Negotiated carrier rates that saved money for the logistics department."),
        n("Trained 6 new coordinators on inventory management and customs clearance steps.",
          "Trained new coordinators on inventory management and customs clearance steps."),
    ]
    summary = ("Logistics Coordinator with seven years of experience in freight forwarding, customs clearance and "
               "warehouse operations across the UAE and GCC. Known for accurate shipment tracking, clear vendor "
               "communication and steady improvement of inventory management processes in busy distribution "
               "centres, using SAP, Microsoft Excel and Incoterms every day to keep goods moving on time.")
    return fake_doc(f"""{name}
Logistics Coordinator | Freight Forwarding | Customs Clearance
jane.doe@mail.com | +971 50 123 4567 | Dubai, UAE | linkedin.com/in/janedoe
SUMMARY
{summary}
EXPERIENCE
Logistics Coordinator | Jan 2021 - Present
Gulf Freight LLC | Dubai, UAE
- {bullets[0]}
- {bullets[1]}
- {bullets[2]}
Logistics Assistant | Mar 2018 - Dec 2020
Desert Cargo FZE | Sharjah, UAE
- {bullets[3]}
- {bullets[4]}
- {bullets[5]}
EDUCATION
Bachelor of Science in Supply Chain Management, University of Dubai, 2017
SKILLS
Inventory Management, Freight Forwarding, Customs Clearance, Warehouse Operations, SAP, Shipment Tracking, Microsoft Excel, Incoterms, Route Planning
CERTIFICATIONS
CSCP - Certified Supply Chain Professional, 2022
ADDITIONAL INFORMATION
Visa: UAE residence visa | UAE driving licence | Notice period: 30 days
""")


class Base(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()
        os.makedirs(self.cache, exist_ok=True)
        with open(C.role_skills_path(ROLE, self.cache), "w", encoding="utf-8") as f:
            json.dump({"role": ROLE, "prompt_version": C.ROLE_PROMPT_VERSION, "ai_runs": [SKILLS] * 3}, f)

    def tearDown(self):
        shutil.rmtree(self.cache, ignore_errors=True)

    def score(self, doc, role=ROLE):
        return C.score_cv("jane.pdf", None, role, doc=doc, role_cache=self.cache)


class TestGuardrails(Base):
    def test_no_numbers_in_bullets_caps_at_70(self):
        plain = self.score(polished_cv(numbers=False))
        self.assertLessEqual(plain["score"], 70)
        self.assertTrue(plain["gates"])
        self.assertEqual(plain["content_checks"]["C1"]["quant_share"], 0)
        good = self.score(polished_cv(numbers=True))
        self.assertGreater(good["score"], 70)                   # the cap, not the rest, held the plain CV down
        self.assertFalse(good["gates"])

    def test_polished_cv_can_be_excellent_but_not_with_a_critical_issue(self):
        good = self.score(polished_cv())
        self.assertGreaterEqual(min(good["parts"].values()), 70, good["parts"])
        spaced = self.score(polished_cv(spaced_name=True))
        name = [i for i in spaced["issues"] if i["id"] == "N1"]       # one root cause: the letter-spaced name (v1.1)
        self.assertEqual([i["severity"] for i in name], ["Minor"])     # rule 4: only layout problems are Critical
        self.assertFalse(any(i["id"] in ("TPL", "B1", "R1", "R4", "R5") for i in spaced["issues"]))
        self.assertGreater(good["score"], spaced["score"])

    def test_excellent_rule(self):
        parts = {k: 95 for k in C.PART_WEIGHT}
        self.assertEqual(C.label_for(95, parts, []), "Excellent")
        self.assertEqual(C.label_for(95, parts, [{"severity": "Critical"}]), "Strong")
        self.assertEqual(C.label_for(95, parts, [{"severity": "Major"}]), "Strong")
        self.assertEqual(C.label_for(95, parts, [{"severity": "Minor"}]), "Excellent")
        self.assertEqual(C.label_for(95, dict(parts, content=84), []), "Strong")

    def test_weakest_part_limits_the_total(self):
        parts = {"readability": 100, "content": 100, "structure": 20}
        mean = sum(C.PART_WEIGHT[k] * v for k, v in parts.items())
        self.assertLess(C.weighted_geo(parts), mean)
        self.assertAlmostEqual(C.weighted_geo({k: 80 for k in C.PART_WEIGHT}), 80, places=6)
        self.assertAlmostEqual(C.weighted_geo({k: 80 for k in C.PART_WEIGHT_JOB}), 80, places=6)

    def test_part_weights(self):
        self.assertEqual(C.PART_WEIGHT, {"readability": 0.35, "content": 0.40, "structure": 0.25})
        self.assertAlmostEqual(sum(C.PART_WEIGHT_JOB.values()), 1.0)
        self.assertEqual(C.PART_WEIGHT_JOB["job_match"], 0.25)
        for k, w in C.PART_WEIGHT.items():                      # with a job the other 3 keep their proportions
            self.assertAlmostEqual(C.PART_WEIGHT_JOB[k], w * 0.75)

    def test_real_target_role_required(self):
        for bad in ("ab", "12", "a1"):
            with self.assertRaises(C.ScoreError, msg=bad):
                self.score(polished_cv(), role=bad)
        found = C.score_cv("jane.pdf", None, "", doc=polished_cv(), role_cache=self.cache)   # empty: from the CV
        self.assertEqual((found["target"], found["role_source"]), (ROLE, "cv"))
        self.assertEqual(C.check_role(" HR Manager "), "HR Manager")


class TestParts(Base):
    def test_same_score_every_run(self):
        a, b = self.score(polished_cv()), self.score(polished_cv())
        self.assertEqual((a["score"], a["parts"]), (b["score"], b["parts"]))

    def test_issue_points_never_negative_and_sorted(self):
        r = self.score(polished_cv(numbers=False, spaced_name=True))
        pts = [i["points"] for i in r["issues"]]
        self.assertTrue(all(p >= 0 for p in pts))
        self.assertEqual(pts, sorted(pts, reverse=True))
        self.assertTrue(all(i["severity"] in ("Critical", "Major", "Minor") for i in r["issues"]))

    def test_no_role_fit_without_a_job(self):
        r = self.score(polished_cv())
        self.assertEqual(set(r["parts"]), {"readability", "content", "structure"})
        self.assertEqual(r["missing_skills"], [])
        self.assertFalse(any(i["part"] not in ("readability", "content", "structure") for i in r["issues"]))

    def test_soft_role_credit(self):
        stems = [L.stem(t) for t in L.tokens("coordinate 3PL carriers and freight vendors for delivery operations")]
        self.assertEqual(C.soft_role_credit("Freight Forwarding", stems), C.ROLE_PARTIAL_CREDIT)    # 'freight'
        self.assertEqual(C.soft_role_credit("Delivery Operations", stems), C.ROLE_CLOSE_CREDIT)
        self.assertEqual(C.soft_role_credit("Data Entry", [L.stem("data")]), 0.0)   # a generic word is not enough

    def test_structure(self):
        r = self.score(polished_cv())
        self.assertEqual(r["parts"]["structure"], 100)
        doc = fake_doc(polished_cv()["modern"].replace(" | linkedin.com/in/janedoe", ""))
        r2 = self.score(doc)
        # no LinkedIn costs 10 + 2 = 12 points (v1.0 has no cap on Minor issues)
        self.assertAlmostEqual(r2["parts"]["structure"], 100 - 12.0)
        self.assertAlmostEqual(100 * C.STRUCT_WEIGHT["T5"] + C.PART_PENALTY["Minor"], 12.0)


class TestBullets(unittest.TestCase):
    def test_numbers_ignore_dates(self):
        self.assertFalse(C.has_number("Led the regional team from Jan 2020 to Mar 2021 across the GCC."))
        self.assertTrue(C.has_number("Led a team of 5 people."))
        self.assertTrue(C.has_number("Kept a >98% on-time delivery rate."))
        self.assertTrue(C.has_number("Doubled the number of active partners."))

    def test_action_verbs(self):
        for w in ("led", "spearheaded", "coordinate", "optimised", "managing", "reduced"):
            self.assertTrue(C.is_action_verb(w), w)
        for w in ("responsible", "the", "team"):
            self.assertFalse(C.is_action_verb(w), w)

    def test_bullets_from_three_layouts(self):
        counts = {}
        for p in ("CV4/jibran-original-cv.pdf", "CVS/profile-user-2UXAuWAmUaH2A5vU-1790959538885-ynuipc.pdf",
                  "CV4/NedaSefati_Creatio.pdf"):
            st = C.experience_statements(L.analyse(L.extract_cv(os.path.join(HERE, p))))
            counts[p] = st
            self.assertTrue(all(len(s.split()) >= 4 for s in st))
            self.assertFalse(any(re.search(r"\b(Present|Feb 2025)\b", s) and len(s.split()) < 8 for s in st))
        self.assertEqual(len(counts["CV4/jibran-original-cv.pdf"]), 18)          # 18 '•' bullets
        self.assertTrue(counts["CV4/NedaSefati_Creatio.pdf"][2].startswith("Portfolio Delivery Governance:"))


def changed(old, new):
    """The standard CV with one line changed (old must be in it)."""
    text = polished_cv()["modern"]
    assert old in text, old
    return fake_doc(text.replace(old, new))


B0 = "Coordinated 40+ weekly freight forwarding shipments across five GCC markets with zero customs penalties."


class TestStandard(Base):
    """Each 1000jobs standard: met by the standard CV, failed by a CV that breaks only that rule (one card,
    with a quote), and fixing it never lowers the score."""

    def check(self, doc, cid, part="content_checks"):
        r = self.score(doc)
        c = r[part][cid]
        self.assertLess(c["score"], 1, (cid, c))
        card = [i for i in r["issues"] if i["id"] == cid]
        self.assertEqual(len(card), 1, (cid, [i["id"] for i in r["issues"]]))
        self.assertGreater(card[0]["points"], 0)
        self.assertTrue(card[0]["evidence"], cid)
        return r, c, card[0]

    def test_standard_cv_scores_90_plus(self):
        r = self.score(polished_cv())
        self.assertGreaterEqual(r["score"], 90, r["issues"])
        for k in list(C.CONTENT_WEIGHT) + list(C.STRUCT_WEIGHT):
            if k in ("C7",):                                   # length depends on the years (a short test CV)
                continue
            group = "content_checks" if k.startswith("C") else "structure_checks"
            self.assertEqual(r[group][k]["score"], 1, (k, r[group][k]))

    def test_headline_with_target_title(self):
        r, c, card = self.check(changed("Logistics Coordinator | Freight Forwarding | Customs Clearance\n", ""), "C15")
        self.assertEqual(card["severity"], "Major")                  # Important

    def test_only_a_summary_over_150_words_is_flagged(self):
        text = polished_cv()["modern"]
        summ = text.split("SUMMARY\n")[1].split("\nEXPERIENCE")[0]
        short = "Logistics Coordinator with seven years of experience in freight forwarding and customs."
        bullets = "- " + short + "\n- Known for accurate shipment tracking and clear vendor communication in the GCC."
        for body in (short, bullets, summ + " " + summ):             # 14 words, bullets, about 100 words: all fine
            with self.subTest(words=len(body.split())):
                r = self.score(fake_doc(text.replace(summ, body)))
                self.assertEqual(r["content_checks"]["C4"]["score"], 1)
                self.assertFalse([i for i in r["issues"] if i["id"] == "C4"])
        long = (summ + " ") * 3                                       # over 150 words
        r, c, card = self.check(fake_doc(text.replace(summ, long.strip())), "C4")
        self.assertEqual(card["severity"], "Minor")
        self.assertEqual(c["band"], "over 150 words")

    def test_same_number_more_than_twice(self):
        doc = changed("Negotiated carrier rates that saved AED 250,000 in the first year.",
                      "Negotiated carrier rates that saved $25M; the $25M plan was praised, $25M kept and $25M "
                      "reported.")
        r, c, _ = self.check(doc, "C9")
        self.assertIn("$25M (4 times)", c["detail"])
        self.assertEqual(self.score(polished_cv())["content_checks"]["C9"]["score"], 1)   # years are not results

    def test_labels_inside_jobs(self):
        r, c, card = self.check(changed("Gulf Freight LLC | Dubai, UAE\n", "Gulf Freight LLC | Dubai, UAE\n"
                                                                          "Key Accomplishments:\n"), "C10")
        self.assertEqual(card["evidence"], ["Key Accomplishments:"])

    def test_weak_openers(self):
        for opener in ("Responsible for", "Helped", "Assisted", "Participated in", "Worked on"):
            with self.subTest(opener=opener):
                doc = changed(B0, f"{opener} weekly freight forwarding shipments across five GCC markets.")
                self.check(doc, "C11")

    def test_past_tense_verbs_are_never_weak(self):
        for verb in ("Built", "Won", "Used", "Led", "Managed", "Delivered", "Provided", "Handled", "Cut"):
            with self.subTest(verb=verb):
                doc = changed(B0, f"{verb} weekly freight forwarding shipments across five GCC markets.")
                r = self.score(doc)
                self.assertEqual(r["content_checks"]["C11"]["score"], 1)
                self.assertEqual(r["content_checks"]["C2"]["score"], 1)
                self.assertFalse([i for i in r["issues"] if i["id"] in ("C2", "C11")])
        self.assertNotIn("C2", C.CONTENT_WEIGHT)                       # one check (C11) for the weak openers

    def test_repeated_filler_and_buzzwords(self):
        doc = changed("Reduced warehouse operations costs by 18% through better inventory management and route "
                      "planning.", "Reduced warehouse operations costs by approximately 18% through approximately "
                                   "two better inventory plans.")
        r, c, _ = self.check(doc, "C5")
        self.assertIn("approximately", c["detail"])

    def test_abbreviation_written_in_full_once(self):
        one = changed("Built a Microsoft Excel shipment tracking dashboard used daily by 12 planners.",
                      "Built a SLA shipment tracking dashboard used daily by 12 planners.")
        self.assertEqual(self.score(one)["content_checks"]["C12"]["score"], 1)   # one alone is no card (4 Nov 2026)
        two = changed("Built a Microsoft Excel shipment tracking dashboard used daily by 12 planners.",
                      "Built a SLA and MTTR shipment tracking dashboard used daily by 12 planners.")
        r, c, _ = self.check(two, "C12")                                        # two are a pattern worth a card
        self.assertIn("SLA", c["detail"])
        self.assertIn("MTTR", c["detail"])
        full = changed("Built a Microsoft Excel shipment tracking dashboard used daily by 12 planners.",
                       "Built a Service Level Agreement (SLA) dashboard used daily by 12 planners.")
        self.assertEqual(self.score(full)["content_checks"]["C12"]["score"], 1)

    def test_well_known_abbreviations_are_not_flagged(self):
        for abbr in ("KPI", "UX", "UI", "AI", "CEO", "USD", "UAE", "GCC", "ROI", "ROAS", "CRM", "SEO", "B2B", "B2C",
                     "HR", "IT", "PR"):
            with self.subTest(abbr=abbr):
                doc = changed("Built a Microsoft Excel shipment tracking dashboard used daily by 12 planners.",
                              f"Built a {abbr} shipment tracking dashboard used daily by 12 planners.")
                self.assertEqual(self.score(doc)["content_checks"]["C12"]["score"], 1)

    def test_old_roles_kept_short(self):
        # 5 Nov 2026: a role that ended 10+ years ago is flagged only with 4 or more bullets (3 was too strict)
        doc = changed("EDUCATION", "Logistics Clerk | Jan 2010 - Dec 2013\nPort Cargo LLC | Dubai, UAE\n"
                                   "- Tracked 200 inbound containers a month with the port system.\n"
                                   "- Filed 150 customs documents a month without errors.\n"
                                   "- Checked 80 delivery notes a week against purchase orders.\n"
                                   "- Trained two new clerks on the port and customs systems.\nEDUCATION")
        r, c, card = self.check(doc, "C13")
        self.assertIn("Logistics Clerk", card["evidence"][0])
        three = fake_doc(doc["modern"].replace("- Trained two new clerks on the port and customs systems.\n", ""))
        self.assertEqual(self.score(three)["content_checks"]["C13"]["score"], 1)

    def test_past_jobs_in_past_tense(self):
        doc = changed("Negotiated carrier rates that saved AED 250,000 in the first year.",
                      "Negotiate carrier rates that saved AED 250,000 in the first year.")
        r, c, _ = self.check(doc, "C14")
        now = changed(B0, "Coordinate 40+ weekly freight forwarding shipments across five GCC markets.")
        self.assertEqual(self.score(now)["content_checks"]["C14"]["score"], 1)      # current job: present is fine

    def test_non_standard_section_name(self):
        doc = changed("EDUCATION", "WHAT I BRING\nLogistics Clerk | Jan 2016 - Feb 2018\n"
                                   "Port Cargo LLC | Dubai, UAE\n- Tracked 200 inbound containers a month.\nEDUCATION")
        r, c, card = self.check(doc, "T1", "structure_checks")
        self.assertIn("WHAT I BRING", c["detail"])
        for ok in ("Professional Experience", "Work History", "Core Competencies", "Languages",
                   "Additional Information", "Certifications & Licenses", "Professional Summary"):
            self.assertTrue(C.ALLOWED_SECTION_RE.fullmatch(ok), ok)

    def test_common_section_name_variants_are_standard(self):
        for ok in ("Tools & Platforms", "Skills & Tools", "Technical Skills", "Core Competencies",
                   "Languages & Availability", "Early Work Experience", "Technical Skills & Tools", "Key Achievements",
                   "Education & Training", "Areas of Expertise", "Volunteer Experience"):
            with self.subTest(name=ok):
                self.assertTrue(L.is_standard_section(ok))
                doc = changed("EDUCATION", ok.upper() + "\n- Excel, SQL, Tableau, Python, Power BI, Jira, SAP, Oracle\nEDUCATION")
                self.assertEqual(self.score(doc)["structure_checks"]["T1"]["score"], 1, ok)
        for odd in ("What I Bring", "My Journey", "Career Impact at a Glance"):
            with self.subTest(name=odd):
                self.assertFalse(L.is_standard_section(odd))

    def test_only_degrees_under_education(self):
        doc = changed("Bachelor of Science in Supply Chain Management, University of Dubai, 2017",
                      "Bachelor of Science in Supply Chain Management, University of Dubai, 2017\n"
                      "Deloitte Management Consulting Challenge | Deloitte Birmingham | Mar 2016")
        r, c, card = self.check(doc, "T2", "structure_checks")
        self.assertIn("Deloitte", card["evidence"][0])

    def test_phone_format(self):
        for bad in ("(+971) 585-516-848", "0505017855"):
            with self.subTest(phone=bad):
                self.check(changed("+971 50 123 4567", bad), "T3", "structure_checks")
        for ok in ("+971 50 123 4567", "+971-52-888-4433", "+44 7700 900123"):
            self.assertTrue(C.PHONE_OK_RE.fullmatch(ok), ok)

    def test_every_job_has_title_company_location_dates(self):
        # a job location is NOT required (2026-10-28): without it the job still has title, company and dates, and the
        # missing place is a note of its own (T16, at most 1 point)
        r = self.score(changed("Desert Cargo FZE | Sharjah, UAE", "Desert Cargo FZE"))
        self.assertEqual(r["structure_checks"]["T4"]["score"], 1.0)
        self.assertLess(r["structure_checks"]["T16"]["score"], 1.0)
        self.assertIn("location missing", r["structure_checks"]["T16"]["evidence"][0])
        # Since 2026-11-09 this check is right too seldom on the golden set (44%): it no longer changes the score
        # and no longer appears on the user page. The rule still finds the problem (against the date line, not the
        # title line) and the team checks it on the admin page.
        # 2026-11-09: the one job card was split. Year-only dates are now their own check (T4C), and after the truth
        # re-check (4 of 4 confirmed files right) it is scored again. The title-and-company check (T4) passes: this
        # job has both.
        r2 = self.score(changed("Mar 2018 - Dec 2020", "2018 - 2020"))
        self.assertEqual(r2["structure_checks"]["T4"]["score"], 1.0)
        c2 = r2["structure_checks"]["T4C"]
        self.assertLess(c2["score"], 1.0)                       # the year-only date costs points again
        self.assertFalse(c2.get("moved_to_verify"))
        self.assertTrue([i for i in r2["issues"] if i["id"] == "T4C"])
        self.assertEqual(c2["evidence"][0], "2018 - 2020  (year only)")
        for line in ("Infosys, Morgan Stanley Engagement \u2013 Montreal, QC", "Berlitz | Libreville, Gabon",
                     "Markaba \u2013 GCC (Riyadh & Dubai)", "Bohemian General Trading \u2013 UAE Aug 2023 \u2013 Jan 2025"):
            self.assertTrue(C.has_location(line), line)
        self.assertFalse(C.has_location("BabyGrow FZC"))

    def test_contact_email_linkedin_city(self):
        _, _, card = self.check(changed("jane.doe@mail.com | ", ""), "T7", "structure_checks")
        self.assertEqual(card["severity"], "Major")                   # rule 4: a missing email is Important
        self.check(changed(" | linkedin.com/in/janedoe", ""), "T5", "structure_checks")
        # 2026-11-09: after the truth re-check (the city is read from the contact details only) the check is right on
        # all 17 confirmed files, so it is scored again
        r6 = self.score(changed(" | Dubai, UAE | ", " | "))
        t6 = r6["structure_checks"]["T6"]
        self.assertLess(t6["score"], 1.0)
        self.assertNotIn("T6", [v["id"] for v in r6["to_verify"]])
        self.assertFalse(t6.get("moved_to_verify"))

    def test_failed_standards_cost_points(self):
        ok = self.score(polished_cv())
        bad = self.score(changed("Logistics Coordinator | Freight Forwarding | Customs Clearance\n", ""))
        failed = C.standard_failed(bad["content_checks"], bad["structure_checks"])
        self.assertEqual(set(failed) - set(C.standard_failed(ok["content_checks"], ok["structure_checks"])), {"C15"})
        self.assertEqual(failed["C15"], "Major")
        self.assertLess(bad["parts"]["content"], ok["parts"]["content"] - C.PART_PENALTY["Major"])  # in its part
        self.assertLess(bad["score"], ok["score"])

    def test_fixing_any_issue_never_lowers_the_score(self):
        doc = fake_doc(polished_cv()["modern"].replace("+971 50 123 4567", "(+971) 50-123-4567")
                       .replace("Logistics Coordinator | Freight Forwarding | Customs Clearance\n", "")
                       .replace(B0, "Responsible for weekly freight forwarding shipments across five GCC markets."))
        r = self.score(doc)
        self.assertTrue(r["issues"])
        self.assertTrue(all(i["points"] >= 0 for i in r["issues"]))


class TestCalibration(unittest.TestCase):
    """Real CVs scored without a job description against the 1000jobs standard (targets from 2026-10-20)."""
    TARGETS = {"testcvs/MohamedShokry-original.pdf": (65, 75),
               "CV4/jibran-original-cv.pdf": (50, 75),
               "CVS/profile-user-2UXAuWAmUaH2A5vU-1790959538885-ynuipc.pdf": (50, 70),
               "CV4/Tareq Al Masri CV JN26.pdf": (0, 50.6)}

    def test_original_cvs(self):
        for p, (lo, hi) in self.TARGETS.items():
            full = os.path.join(HERE, p)
            if not os.path.exists(full):
                continue
            r = C.score_cv(full, None, None)
            with self.subTest(cv=p):
                self.assertGreaterEqual(r["score"], lo)
                self.assertLessEqual(r["score"], hi)
                self.assertNotEqual(r["label"], "Excellent")

    def test_mohamed_issues_are_found(self):
        full = os.path.join(HERE, "testcvs/MohamedShokry-original.pdf")
        if not os.path.exists(full):
            self.skipTest("Mohamed's original CV is not on this machine")
        r = C.score_cv(full, None, None)
        ids = {i["id"] for i in r["issues"]}
        for cid in ("C15", "C10", "C13", "C5", "T2", "T3"):
            self.assertIn(cid, ids)
        self.assertIn("approximately", r["content_checks"]["C5"]["detail"])
        self.assertEqual(r["structure_checks"]["T1"]["score"], 1)       # 'Early Work Experience' maps to Experience
        self.assertIn("(+971) 585-516-848", r["structure_checks"]["T3"]["detail"])


class TestRules(Base):
    """2026-10-21 fixes: summary ranges, fixed severities, one part per issue, 'if fixed' <= cost, education years,
    the same result with different numbers, merged titles, UAE details."""

    def test_summary_ranges(self):
        for words, flagged in ((10, False), (35, False), (60, False), (120, False), (150, False), (151, True),
                               (200, True)):
            b, score = C.summary_band(words)
            self.assertEqual(score < 1, flagged, words)
            if flagged:
                self.assertEqual(C.rule_severity("C4", {"C4": {"score": score}}), "Minor")

    def test_severity_follows_fixed_rules(self):
        c1 = lambda q, n=20: {"C1": {"quant_share": q, "bullets": n, "score": min(1, q / C.QUANT_TARGET)}}
        for q in (0, 0.1, 0.4):                                     # rule 4: few numbers is Important
            self.assertEqual(C.rule_severity("C1", c1(q)), "Major")
        for iid, sev in (("C9", "Minor"), ("C10", "Minor"), ("C12", "Minor"), ("C15", "Major"), ("C16", "Minor"),
                         ("T4", "Minor"), ("T7", "Major"), ("T10", "Minor"), ("T11", "Minor"), ("D12", "Critical"),
                         ("D4", "Critical"), ("D3", "Critical"), ("D13", "Critical"), ("T15", "Critical"),
                         ("D6", "Minor"), ("B8", "Minor"), ("B1", "Minor"), ("B11", "Major"), ("R6", "Major")):
            self.assertEqual(C.rule_severity(iid, {}, {}), sev, iid)
        self.assertEqual(C.rule_severity("T4", {}, {"T4": {"date_problems": ["year only"]}}), "Major")
        self.assertEqual(C.rule_severity("T3", {}, {"T3": {"detail": "no phone number"}}), "Major")
        self.assertEqual(C.rule_severity("T3", {}, {"T3": {"detail": "0505767221"}}), "Minor")

    def test_fixing_never_adds_more_than_it_costs(self):
        doc = fake_doc(polished_cv()["modern"].replace("+971 50 123 4567", "(+971) 50-123-4567")
                       .replace("Logistics Coordinator | Freight Forwarding | Customs Clearance\n", "")
                       .replace(B0, "Responsible for weekly freight forwarding shipments across five GCC markets."))
        r = self.score(doc)
        for i in r["issues"]:
            self.assertLessEqual(i["points"], i["part_points"] + 1e-9, i)

    def test_education_years(self):
        senior = polished_cv()["modern"].replace("Mar 2018 - Dec 2020", "Mar 2008 - Dec 2020")
        two = "Bachelor of Science in Supply Chain Management, University of Dubai, 2017"
        no_year = two.replace(", 2017", "") + "\nMaster of Business Administration, University of Dubai, 2019"
        r = self.score(fake_doc(senior.replace(two, no_year)))
        t9 = r["structure_checks"]["T9"]
        self.assertTrue(t9["year_hidden"])
        self.assertFalse(t9["every_year"])
        self.assertIn("year hidden", t9["detail"])
        junior = self.score(fake_doc(polished_cv()["modern"].replace(two, no_year)))["structure_checks"]["T9"]
        self.assertLess(junior["score"], 1)                         # under 10 years: the year must be there
        full = self.score(polished_cv())["structure_checks"]["T9"]
        self.assertTrue(full["every_year"])

    def test_same_result_with_different_numbers(self):
        a = "Led the Carnab launch, driving a 10x increase in reservations and projected revenue of $180,000."
        b = "Drove a 10x rise in reservations and over $15,000 in revenue for the Carnab platform."
        r, c, card = TestStandard.check(self, changed(B0, a + "\n- " + b), "C16")
        self.assertEqual(card["severity"], "Minor")                   # rule 4: everything else is Minor
        self.assertTrue(any("$180,000" in e and "$15,000" in e for e in card["evidence"]))   # both quoted
        other = "Introduced cross-sell features, driving 8x first-time user growth and $15,264 in revenue."
        self.assertEqual(C.same_result_conflicts([a, other]), [])        # two different results: not flagged
        self.assertEqual(C.same_result_conflicts([a, a.replace("Led", "Owned")]), [])   # same numbers: fine
        self.assertEqual(self.score(polished_cv())["content_checks"]["C16"]["score"], 1)

    def test_merged_job_titles(self):
        doc = changed("Logistics Assistant | Mar 2018 - Dec 2020", "Senior / Logistics Assistant | Mar 2018 - Dec 2020")
        r, c, card = TestStandard.check(self, doc, "T11", "structure_checks")
        self.assertEqual(card["severity"], "Minor")
        self.assertIn("Senior / Logistics Assistant", card["evidence"][0])
        self.assertNotIn("two titles", " ".join(r["structure_checks"]["T4"]["evidence"]))

    def test_uae_details(self):
        self.assertEqual(self.score(polished_cv())["structure_checks"]["T10"]["score"], 1)
        line = "ADDITIONAL INFORMATION\nVisa: UAE residence visa | UAE driving licence | Notice period: 30 days\n"
        r, c, card = TestStandard.check(self, changed(line, ""), "T10", "structure_checks")
        self.assertEqual(card["severity"], "Minor")
        abroad = polished_cv()["modern"].replace(line, "").replace("+971 50 123 4567", "+44 7700 900123") \
            .replace("Dubai, UAE", "London, UK").replace("UAE", "UK").replace("Dubai", "London")
        self.assertEqual(self.score(fake_doc(abroad))["structure_checks"]["T10"]["score"], 1)   # not a UAE resume


if __name__ == "__main__":
    unittest.main()
