"""Regression tests for resumes with work history split by non-work sections."""
import unittest

import ATSLab_v3 as lab


def rows(*texts):
    return [{"page": 1, "text": text, "cells": [text]} for text in texts]


class ExperienceParserTests(unittest.TestCase):
    def test_jobs_after_skills_and_certificates_are_kept(self):
        sections = [
            {"title": "Employment", "kind": "experience", "rows": rows(
                "Recruiter - Apr 2026 - Present", "Deliveroo | Dubai"
            )},
            {"title": "Skills", "kind": "skills", "rows": rows(
                "Full-Cycle Recruitment", "Talent Acquisition Specialist . Contract Feb 2023 - Aug 2024",
                "WOOD, Dubai, U.A.E"
            )},
            {"title": "Licenses & Certificates", "kind": "certifications", "rows": rows(
                "LinkedIn: HR Recruiting", "Recruitment Consultant . Full-Time May 2021 - Jan 2023",
                "NES Fircroft, Dubai, U.A.E"
            )},
        ]

        rebuilt = lab.synthesize_experience(sections)
        experience_lines = [
            row["text"]
            for section in rebuilt
            if section["kind"] == "experience"
            for row in section["rows"]
        ]
        jobs = lab.parse_jobs(experience_lines)
        titles = [job["title"] for job in jobs]

        self.assertGreaterEqual(len(jobs), 3)
        self.assertTrue(any("Talent Acquisition Specialist" in title for title in titles))
        self.assertTrue(any("Recruitment Consultant" in title for title in titles))

    def test_dated_workshop_is_not_promoted_to_a_job(self):
        sections = [
            {"title": "Leadership & Volunteering Activities", "kind": "other", "rows": rows(
                "Leadership Workshop . Abu Dhabi 2016 - 2016",
                "Participated in a workshop discussing effective leadership."
            )},
        ]

        rebuilt = lab.synthesize_experience(sections)

        self.assertEqual([section["kind"] for section in rebuilt], ["other"])
        self.assertEqual(rebuilt[0]["rows"][0]["text"], "Leadership Workshop . Abu Dhabi 2016 - 2016")

    def test_overlapping_jobs_are_not_double_counted(self):
        jobs = lab.parse_jobs([
            "Talent Acquisition Specialist . Contract Feb 2023 - Aug 2024",
            "WOOD, Dubai, U.A.E",
            "Recruiter - Apr 2024 - Present",
            "Deliveroo | Dubai",
        ])

        years = lab.experience_years(jobs)

        self.assertGreater(years, 2.5)
        self.assertLess(years, 4.0)


if __name__ == "__main__":
    unittest.main()
