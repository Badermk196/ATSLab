"""Three false issues found on a real report (Sana Malik's updated CV, 4 Nov 2026), locked in:

1. a course / program listed under Experience is not a job (no location card, no job checks) and gets one note (T17);
2. "Name has letter spacing" fires only when the readable text really has the letters apart, never for a wide font;
3. bullets of the next part ("Earlier Career") are never counted under the role above it, and an old role is only
   flagged with 4+ real bullets.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ATSLab_v3 as L                                        # noqa: E402
import cv_score as C                                         # noqa: E402
import test_cv_score as T                                    # noqa: E402

SANA = os.path.join(os.path.expanduser("~"), "Downloads", "Sana_Malik_CV_Updated.pdf")


def cv_doc(experience_lines):
    return T.fake_doc("\n".join([
        "Sana Malik",
        "Senior Programme Manager | Digital Transformation",
        "sana.malik@mail.com | +971 50 123 4567 | Dubai, UAE",
        "PROFESSIONAL SUMMARY",
        "Senior programme manager with fifteen years in digital transformation and programme delivery across the "
        "UAE, KSA and Qatar, leading large teams and multi-country rollouts for telecom and retail clients, with a "
        "record of cutting cost and cycle time year after year.",
        "PROFESSIONAL EXPERIENCE",
        *experience_lines,
    ]))


class TestACourseIsNotAJob(unittest.TestCase):
    def test_a_clear_program_is_recognised(self):
        head = ["AI Career Accelerator - Inner Circle | Be10X | Aug 2026 - Present"]
        self.assertTrue(C.is_program_entry(head))

    def test_a_real_job_with_a_role_word_is_never_a_program(self):
        for head in (["Programme Manager | Be10X | Aug 2026 - Present"],
                     ["Training Manager | Coursera | Jan 2020 - Dec 2022"],
                     ["Program Lead - Academy | Deliveroo | 2019 - 2021"]):
            self.assertFalse(C.is_program_entry(head), head)

    def test_an_unclear_entry_is_left_alone(self):
        self.assertFalse(C.is_program_entry(["Inner Circle | Meridian Group | Aug 2026 - Present"]))

    def test_a_learning_provider_alone_is_not_a_course(self):
        self.assertFalse(C.is_program_entry(["AI Career Inner Circle | Be10X | Aug 2026 - Present"]))

    def test_a_job_at_a_learning_provider_is_a_job(self):
        for head in (["Freelance AI Consultant | Coursera | Jan 2025 - Present"],
                     ["Expert Data Scientist | DataCamp | 2024 - Present"],
                     ["Specialist, Machine Learning | Udemy | Mar 2023 - Dec 2024"],
                     ["Contract Engineer | Simplilearn | 2022 - 2023"],
                     ["Part-time Analyst | Great Learning | 2021 - 2022"],
                     ["Pro Bono Advisor | Coursera | 2020"]):
            self.assertFalse(C.is_program_entry(head), head)

    def test_a_title_that_names_a_program_is_a_course(self):
        for head in (["Data Analytics Certificate | Coursera | Jan 2025 - Mar 2025"],
                     ["AI Career Accelerator - Inner Circle | Be10X | Aug 2026 - Present"],
                     ["Cloud DevOps Bootcamp | Udemy | 2024"]):
            self.assertTrue(C.is_program_entry(head), head)

    def test_the_program_is_kept_out_of_the_job_list(self):
        ana = C.analyse_cv(cv_doc([
            "AI Career Accelerator - Inner Circle | Be10X | Aug 2026 - Present",
            "- Completed 120 hours of applied AI coursework and delivered a capstone project.",
            "Senior Programme Manager | Amazon, Dubai, UAE | Jan 2021 - Jul 2026",
            "- Led a $7.5M programme across 14 clients in the UAE, KSA and Qatar.",
            "- Cut delivery cycle time by 30% across three regions.",
            "- Built a delivery dashboard used by 40 people every week.",
        ]))
        titles = [j.get("title") or "" for j in ana["jobs"]]
        self.assertTrue(any("Amazon" in t for t in titles), titles)
        self.assertFalse(any("Accelerator" in t for t in titles), titles)
        self.assertEqual(len(ana["programs"]), 1, ana["programs"])
        self.assertIn("Accelerator", ana["programs"][0].get("title") or "")


class TestNameSpacing(unittest.TestCase):
    def b1(self, strict_first, modern_first):
        doc = {"strict": strict_first + "\nSKILLS\nPython", "modern": modern_first + "\nSKILLS\nPython"}
        return L.detect_b1(doc, None)

    def test_a_normal_name_in_a_wide_font_is_not_flagged(self):
        found, detail = self.b1("S A N A M A L I K", "Sana Malik")     # wide font: only the strict reading splits
        self.assertFalse(found, detail)

    def test_a_name_that_really_reads_as_letters_is_flagged(self):
        found, detail = self.b1("S A N A  M A L I K", "S A N A  M A L I K")
        self.assertTrue(found, detail)
        self.assertIn("name only", detail)

    def test_no_other_persons_name_in_any_card_text(self):
        """No card may show an example name of another person (5 Nov 2026): letter-spaced examples are only allowed
        when they are a section heading word, never a name."""
        import dashboard as D
        import cv_layout as Y
        headings = {w.lower() for w in Y.HEADING_PARTS}
        for key, card in D.ISSUES.items():
            text = " ".join(str(card.get(k, "")) for k in ("name", "why", "fix", "we_fix"))
            for run in re.findall(r"(?:[A-Z] ){3,}[A-Z]", text):
                self.assertIn(run.replace(" ", "").lower(), headings, (key, run))

    def test_overlapping_repeat_checks_are_one_report_card(self):
        import dashboard as D
        quote_a = "$4.9M flagship programme grew one engagement into a three-phase programme for a national oil company"
        quote_b = "The $4.9M flagship programme grew one engagement into a three-phase programme for a national oil company"
        r = {"issues": [
            {"id": "C9", "part": "content", "name": "The same number used more than twice", "points": 3.1,
             "severity": "Minor", "evidence": [quote_a]},
            {"id": "C6", "part": "content", "name": "No repeated text", "points": 1.4,
             "severity": "Minor", "evidence": [quote_b]},
        ]}
        cards = D.issue_cards(r)
        self.assertEqual([c["key"] for c in cards], ["repeated_numbers"])
        self.assertAlmostEqual(cards[0]["points"], 4.5)
        self.assertEqual({i["id"] for i in cards[0]["issues"]}, {"C9", "C6"})


class TestOldRoleBulletCount(unittest.TestCase):
    def test_bullets_of_the_next_part_are_not_counted(self):
        ana = C.analyse_cv(cv_doc([
            "Business Development Manager | Mvergence Media, Lahore, Pakistan | Mar 2010 - May 2011",
            "- Directed a $1M portfolio of mobile content services for all major networks.",
            "- Led two national first-launch campaigns for global brands.",
            "- Cut operational costs by 10% through process re-engineering.",
            "EARLIER CAREER",
            "- Joined as part of the launch team at a telecom operator.",
            "- Spearheaded proactive customer communications using online tools.",
            "- Reduced complaint resolution turnaround from three days to 24 hours.",
            "- Improved quality scores by 25% by coaching new agents.",
            "- Managed vendor relationships for content and billing partners.",
        ]))
        items = C.experience_items_by_job(ana)
        count = len([t for t, b, jk in items if jk == 0 and b])
        self.assertEqual(count, 3, [t for t, b, jk in items if jk == 0])
        self.assertFalse([t for t, b, jk in items if jk == 0 and "launch team" in t])

    def test_an_old_role_needs_four_real_bullets(self):
        self.assertEqual(C.OLD_MAX_BULLETS, 3)


class TestTheRealSanaReport(unittest.TestCase):
    @unittest.skipUnless(os.path.isfile(SANA), "Sana_Malik_CV_Updated.pdf is not in Downloads")
    def test_the_three_cards_are_gone_and_the_note_is_there(self):
        r = C.score_cv(SANA, None, None)
        ids = [i["id"] for i in r["issues"]]
        self.assertNotIn("N1", ids)                       # name spacing: the text reads "SANA MALIK"
        self.assertNotIn("R5", ids)                       # the strict parser's spaced name is not a spaced heading
        self.assertNotIn("B1", ids)
        self.assertNotIn("C13", ids)                      # the old role has three bullets, not nine
        self.assertIn("T17", ids)                         # one note about the course / program
        self.assertTrue(any("Accelerator" in e for e in
                            next(i for i in r["issues"] if i["id"] == "T17")["evidence"]))
        self.assertFalse([i for i in r["issues"] if i["points"] and i["id"] == "T17"])   # a note, no cost


if __name__ == "__main__":
    unittest.main()
