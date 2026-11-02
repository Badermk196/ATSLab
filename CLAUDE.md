# 1000Jobs ATS Lab - Project Brief

## Goal
Make 1000Jobs-generated CVs score higher in ATS systems, WITHOUT inventing content.
The ATS Lab is our own scorer: it reads a CV PDF like an ATS, compares it with the job
description, gives a score, and lists exactly what is wrong.

Target ATS systems (UAE focus): Greenhouse, Workday, Oracle.
Workday and Oracle are the strictest: a CV that passes them is "ready for any ATS".

## Folder structure (C:\ATSLab)
- `ATSLab.py`            current Lab (v2). Do NOT change it.
- `ATSLab_v2_frozen.py`  frozen copy used for before/after comparison. Never edit.
- `CVS\`                 CV PDFs (Name_Company.pdf)
- `JobDe\`               job descriptions (Name_Company.txt) + saved keywords (Name_Company_keywords.json)
- `results_before.csv / .json`  baseline scores BEFORE the developers fix the bugs. Never overwrite.

Rules:
- Keep the same job .txt and _keywords.json files for before/after tests.
- Before and after must be measured with the SAME Lab version.
- Python on Windows: install packages with `python -m pip install ...`
- OpenRouter key is read from env var `OPENROUTER_API_KEY`; model used: `google/gemini-2.5-flash`.
- Never print or save the API key.

## How v2 works (current)
1. Extracts PDF text twice with pdfplumber: strict (x_tolerance=1, like Workday/Oracle) and modern (x_tolerance=3, like Greenhouse).
2. AI extracts job keywords once and saves them: title, hard_skills, soft_skills, degree_level, min_years.
3. Checks:
   - Readable: R1 name, R2 email, R3 phone with +code, R4 headline, R5 readable headings (no letter spacing),
     R6 job date ranges, R7 "Mon YYYY - Mon YYYY", R8 degree + year, R9 skills section has real skills,
     R10 no broken text, R11 standard section names (Workday/Oracle only)
   - Findable: F1 hard skills found, F2 abbreviations in both forms, F3 exact job title near top, F4 past titles unchanged
   - Matched: M1 hard skills weighted by job frequency, M2 soft skills, M3 TF-IDF meaning match, M4 degree level, M5 years
4. Score = 30% Readable + 30% Findable + 40% Matched, computed for Greenhouse / Workday / Oracle, overall = average.
5. Honesty Gate: if a profile is given and the CV contains job skills not in the profile, score = 0.

## Baseline results (10 CVs, v2)
- Average overall 49.4 (Greenhouse 52.1, Workday 48.2, Oracle 47.7).
- Correlation with Jobscan (9 CVs): overall 0.17, F1 hard skills +0.42, Findable +0.38, Matched +0.04, M3 +0.01, Readable -0.30.
- Known Lab problems: AI picked wrong job titles ("Who You Are" for eliasgk, a category line for MohamedIrfan);
  hard-skill scores much lower than Jobscan (too many/too specific keywords, Oracle exact-only);
  M3 scale too harsh; Tammam's 4-column skills grid wrongly flagged as empty skills.

## Bug list (found in 21 CVs) - use these codes everywhere
| Code | Bug | Count | Status | Severity |
|---|---|---|---|---|
| B1 | Spaced-out headings ("E D U C A T I O N") | 21/21 | Now | Critical |
| B2 | Skills section unreadable (category names only, or grid) | 18/21 | Now | Critical |
| B3 | "Prepared with 1000Jobs" watermark inside the text | 18/21 | Now | Major |
| B4 | Email missing | 9/21 | Now | Critical |
| B5 | Markdown ** marks printed | 4/21 | Now | Minor |
| B6 | HTML <span> code printed | 2/21 | Now | Major |
| B7 | Placeholder text ("Date Not Specified") | 1/21 | Now | Major |
| B8 | "Career Impact at a Glance" boxes (non-standard, side by side) | 21/21 | Later | Major |
| B9 | "Select Achievements" repeats the experience | 21/21 | On hold | Minor |
| B10 | Template phrases ("equally comfortable", "senior business operations leader") | 10/21 | On hold | Minor |
| B11 | Job dates missing, year-only, or durations ("2 years") | 9/21 | On hold | Major |

## TASK: build Lab v3 (new file ATSLab_v3.py, keep v2 untouched)

### 1. Bug registry
Define every bug once (code, name, status, severity, detection function). Each bug = its own report line:
`[FAIL] B2 Skills section unreadable (Now)`. Adding a new bug = adding one registry entry.

### 2. Scoring math
- Every check returns a partial score 0-1 (not only pass/fail). Examples:
  dates = jobs with Mon YYYY / total jobs; headings = readable / total; skills = min(1, skills_listed / 8);
  summary = 1 if 40-90 words, decreasing for longer.
- Keyword weight = type x frequency. Type: required 3, preferred 1.5, soft 0.5. Frequency = 1 + log2(times in job).
- Partial credit: exact 1.0; variant (plural/spelling) 0.8 (0.5 in Oracle mode); abbreviation-only when job uses full form 0.5; missing 0.
- Location multiplier: found in Skills section or experience of last 5 years x1.0; only summary/old jobs x0.8.
- Coverage = sum(weight x credit) / sum(weight).
- Base = R^0.3 x F^0.3 x M^0.4 (weighted geometric mean: the weakest part limits the total). Use 0-1 inputs, floor each at 0.01.
- Penalties by bug severity: Critical -15, Major -8, Minor -3, total penalty capped at -40.
- Gates: Honesty fail -> 0; no email AND no phone -> cap 40; under 30% of required skills -> cap 50.
- Computed per ATS (Greenhouse, Workday, Oracle); overall = average.

### 3. Score scale
90-100 Excellent, 80-89 Strong, 70-79 Good, 55-69 Needs work, 40-54 At risk, 0-39 Not ready.

"Ready for any ATS" badge only if, in the strictest mode (Oracle/Workday):
Readable >= 85, Findable >= 70, Matched >= 65, Total >= 80, AND all must-haves pass:
email + phone, skills section with real skills, readable standard headings, single column,
Mon YYYY dates, no broken text, exact job title in headline/summary, >= 70% required skills, Honesty Gate passed.

### 4. Explanations (for the dashboard later)
- "Why" panel: points pulling the score down / up. Compute each item's points by re-scoring with that issue fixed (counterfactual).
- ATS-ready checklist with per-ATS ticks (Greenhouse / Workday / Oracle).
- Fix plan sorted by points gained, each tagged "template fix" (developers) or "content" (prompt/ML).
- Batch summary: each bug's count across CVs and its average points gain.
- Save all of this in results.json so a dashboard can read it.

### 5. Keyword extraction fixes
- Job title: use the FIRST LINE of the job .txt if it looks like a title; else AI.
- Prompt: 10-25 concrete, searchable hard skills spelled exactly as in the posting; no sentences or generic phrases.
- Treat plurals and UK/US spelling as variants (credit rule above).

### 6. Tests (must pass before using v3)
- Monotonicity: fixing any bug must never lower the score.
- Same CV + same job = same score every run.
- Each bug detector checked against the bug table above (no false alarms, no misses), e.g. Tammam's grid is not "empty".

### Later (not now)
- Dashboard (Streamlit): overview, bug tracker, CV detail with "what the ATS sees" text, upload & score. No Lab-vs-Jobscan compare page.
- Calibrate weights with more data (Jobscan, SkillSyncer, interview results).
- ML optimization of the 1000Jobs generator only after bugs are fixed and the score is trusted.

## Style
The user prefers simple English, step-by-step instructions, one step at a time.
