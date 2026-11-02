# 1000Jobs ATS Lab: scoring rules (version 1.3)

Score version: `2026-10-30.v1.3` (the v1.1 changes are in section 8, v1.2 in section 9, v1.3 in section 10). Frozen copies:
v1.0 in `release-v1.0\`, v1.1 in `release-v1.1\`, v1.2 in `release-v1.2\`, v1.3 in `release-v1.3\`.
The code is in `cv_score.py` (scoring), `cv_layout.py` (reading the page),
`cv_review.py` (AI reviewer) and `ATSLab_v3.py` (keywords and the Job Match). The rules are the same for every resume.

## 1. The score

The score is a **weighted geometric mean** of the parts (0-100): the weakest part pulls the total down.
Every part is floored at 1% so one zero never hides the others.

| Part | No job description | With a job description |
|---|---:|---:|
| Readability | 35% | 26.25% |
| Content | 40% | 30% |
| Structure | 25% | 18.75% |
| Job Match | - | 25% |

Scale: 90-100 Excellent, 80-89 Strong, 70-79 Good, 55-69 Needs work, 40-54 At risk, 0-39 Not ready.
"Excellent" also needs every part at 85 or more and no Critical or Important issue left.

## 2. Issues and their cost

- Severity is fixed per rule, never taken from the points: **Critical**, **Important** (Major in the code), **Minor**.
- A failed standard in Content or Structure costs its part **points on top of its weight**:
  Critical 15, Important 12, **Minor 2**. These extra points are capped at **35** per part.
- Readability: layout and parsing problems cost Critical 15, Important 10, Minor 5 (one shared cap).
- **Minor issues have no cap.** Many small problems add up (decision for 1.0, see section 5).
- A missing required skill from the job is Important; a card with only missing preferred skills is Minor.

## 3. Structure

`T4` *Every job has title, company and Mon YYYY dates* (weight 22%): Important when a job's dates are missing or
year-only.
**A job location is not required.** It has its own note, `T16` *Job locations* (Minor, weight 1%): it can cost
at most 1 point and never the extra 2 points a failed standard costs (`NOTE_ONLY`).
Other checks: standard section names, only degrees under Education, +code phone, LinkedIn, city, email, skills section,
degree/school/year, visa/licence/notice (UAE), one title per job.

## 4. Caps and guardrails on the total

- **"No headline" (Important) takes at most 20 points from the total** (`HEADLINE_CAP = 20`). The Content part still
  pays its full cost.
- No numbers in any bullet: total at most 70.
- A big page overrun: 3 times the page limit or more AND at least 4 pages (e.g. 15 pages for 12 years, 4 pages for
  under 3 years): total at most 75. A 2- or 3-page resume is never capped (section 10).
- Layout limits: a landscape page (Readability max 50, Structure max 55, total max 50); columns or a sidebar
  (Readability 45, Structure 55, total 55); both together: total max 40.
- A page that is an image counts as unreadable for that share of the pages.

## 5. Decision for 1.0: no Minor cap, headline cap 20

During the final fixes two caps were tried as a lesson from resumes that got interviews: Minor issues of a part
cost 10 points at most, and "No headline" costs the total 10 points at most. They were measured against the
calibrated reference ranges (`reference_scores.json`, 17 resumes, and the weak set that must stay under 60):

| Minor cap | Headline cap | Reference resumes out of range | Weak set max (must be under 60) |
|---|---|---|---|
| none | none | 0 of 17 | 52.2 |
| **none** | **20** | **0 of 17** | **52.2** |
| none | 15 | 1 of 17 | 52.2 |
| none | 10 | 3 of 17 | 57.0 |
| 25 | 20 | 1 of 17 | 61.5 (fails) |
| 10 | 10 | 12 of 17 | 72.0 (fails) |

**Why no Minor cap:** a weak original with many small problems (no LinkedIn, no city, phone format, visa line)
lost 20-36 Structure points; with a cap of 10 it lost 10, so weak resumes rose above their ranges
(Shikha's original 52 to 72, Jibran's 70 to 76, Mohamed's 69 to 78). No cap up to 25 keeps the weak set under 60.
**Why headline cap 20:** measured, it changes no reference result (0 of 17 out of range, weak set max 52.2, the same as
no cap), and it still stops one missing headline from sinking a resume that is otherwise strong.
A cap of 10 or 15 moves reference resumes out of range.

The caps are still switches in `cv_score.py`: `MINOR_CAP` (`None` = no cap, or a number of points) and `HEADLINE_CAP`.
Changing them means re-checking the reference ranges first (`py -3.12 run_tests.py --reference`).

## 6. Job Match (only with a job description)

The user types the **Target role (job title)** (required) and pastes the **Job description**. Skills are the searchable
hard skills of the posting (10-25, spelled as in the posting; phrases ending in a quality such as "brand judgement" are
dropped). Weight = type (required 3, preferred 1.5, soft 0.5) x frequency (1 + log2 of the times in the posting).
Credit: exact 1.0, plural/spelling variant 0.8, abbreviation only 0.5, missing 0. Abbreviation issues only count terms
that are in the resume.
Since 1.3: a skill with glued words from a posting pasted without line breaks ("Software DeveloperLocation") is split
and only the real skills inside are kept; a job with fewer than 10 skills counts the missing places as the meaning
match (section 10).

## 7. Honesty and tests

- No content is invented. The AI reviewer can only lower Content (up to 15 points), never add.
- The same resume and job give the same score on every run.
- `py -3.12 run_tests.py --quick` (all tests except the two slow calibration tests), `--reference`, `--full`.

## 8. Changes in 1.1 (2026-10-29)

The same for every resume; no rule names a person, a file or a template. Tests: `test_v11_rules.py` (generated resumes).

1. **Resume length (`C7`, Minor, weight 2%)**: only a resume that is **too short for the experience** is flagged:
   8 or more years of experience in fewer than 350 words, or 10 or more years on one page. A long resume is never
   flagged by this check. The card is "Resume is short for your experience". (The separate page check `D11`, "Too
   many pages for your experience", is unchanged.)
2. **Bullet length (`C3`) is removed**: no card and no points. Its 5% weight is always given in full
   (`RETIRED_WEIGHT`), so its points are simply no longer taken off and every other check keeps its weight.
3. **No employment gap check.** Every AI finding about a gap or a career break is dropped in code
   (`cv_review.is_gap_finding`), and the Lab no longer confirms gap findings or reports gaps. The AI prompt and the
   timeline sent with it are unchanged, so the saved AI reviews stay valid.
4. **The name with a credential or title** ("SANA MALIK, PMP®", "MOHAMED SHOKRY, MBA", "Dr. ...") is found, also when
   letter-spaced: a letter-spaced name is read again from the PDF's own letter positions (`cv_layout.spaced_line_text`).
   The report header and the PDF file name show the name without the title or credential (`ATSLab_v3.bare_name`).
   The name check (`R1`) counts the words of the name without its credentials.
5. **A letter-spaced name only** (no letter-spaced headings, no columns, no landscape page) is the Minor card
   "Name has letter spacing" (`N1`), never "Template is hard for ATS to read". With a real template problem the name is
   listed inside the template card, as before. Same cost as before (Readability, Minor).
6. **Bullets and job headers**: a bullet is never joined with the next line when that line is a job header (a title or
   company with its dates at the end of the line, or dates at the start followed by a separator), even when the job
   list missed that header (`job_header`). Every bullet check (numbers, action verbs / weak openers, repeats, detail
   per role, old roles, tense) reads these same bullets (`experience_items_by_job`).

**Effect on the reference set** (score without the AI reviewer; with the saved AI reviews in brackets):
every resume stays in its range, the strong set stays at 75+ and the weak set under 60.

| Resume | Range | 1.0 | 1.1 | Why |
|---|---|---|---|---|
| Rowan original | 15-30 | 19.2 (18.8) | 20.1 (19.7) | no bullet length, no length card |
| Tareq old sidebar resume | 35-45 | 39.8 (38.8) | 39.2 (38.2) | now "Resume is short for your experience" |
| Shikha original | 45-55 | 52.2 (49.0) | 54.7 (51.8) | no length card (it was "too long"), no bullet length |
| Shikha 1000Jobs (Chanel) | 80-90 | 88.5 (87.6) | 88.5 (88.5) | AI gap finding dropped |
| Shikha 1000Jobs (RAK Bank) | 80-90 | 88.5 (87.6) | 88.5 (88.5) | AI finding built on a gap dropped |
| Shikha 1000Jobs (Sardine) | 80-90 | 89.5 (86.5) | 89.5 (87.5) | AI gap finding dropped |
| Jibran 1000Jobs (NCR Atleos) | 80-90 | 88.8 | 89.0 | no length card |
| Jibran 1000Jobs (Al Futtaim) | 80-90 | 87.6 | 87.8 | no length card |
| Mohamed original | 62-72 | 69.2 | 69.2 | same points; the card is now "Name has letter spacing" |

The scores of the other 8 reference resumes do not change (Rowan's new file loses a 0-point length card).

**Rule removed from the reference set (decision for 1.1):** `reference_scores.json` also said Rowan's new file must have
more Content than Rowan's original. In 1.1 the original's Content rose from 43.6 to 49.0 (it lost a failed bullet-length
check and a "too short/long" length card), and the new file only from 47.7 to 47.9 (with the AI: 46.8 and 43.4). That
rule was set while the two removed checks still counted, so it was **removed**; no special case was added. All total
score ranges stay as they were (Rowan: 20.1 in 15-30, 40 in 40-50).
Strong set lowest: 79.2 to 79.7 (76.0 to 77.3 with the AI). Weak set
highest: 52.2 to 54.7.

**AI findings built on a gap** are removed too, not only findings with "gap" in the title (decision for 1.1). Example:
"Inconsistent experience level in summary", whose reason was "excluding the large gap ...".

## 9. Changes in 1.2 (2026-10-29)

The same for every file; no rule names a person, a file or a template. Tests: `test_v12_rules.py` (generated files).

**Before a score: files that are not scored.** `dashboard.run_check` stops with a clear message, before any AI call:

| File | Message |
|---|---|
| Empty | "This file is empty." |
| Word (`.doc`, `.docx`, also renamed to `.pdf`) | "Please save your resume as a PDF and upload it again." |
| Locked with a password | "This PDF is locked with a password. Save it without a password and upload it again." |
| Damaged | "We could not open '...'. The file may be damaged. Please save it as a PDF again and upload it again." |
| Fewer than 30 words of text (a scan or a picture of a resume) | "No text found in '...'. It may be a scanned image: an ATS cannot read it either." |
| Mostly not English (`cv_score.not_english`) | "We currently check resumes in English. Please upload an English version." |
| No resume signs (`cv_score.resume_signs`) | "This doesn't look like a resume. Please upload your resume as a PDF." |

- *Not English*: under half of the letters are in the Latin alphabet (Arabic, Cyrillic, Chinese ...), or the common
  words of another language (French, Spanish, Portuguese, German, Indonesian, Vietnamese, Turkish, Italian) are 15 or
  more and outnumber the common English words. Under 50 letters is never judged.
- *Resume signs*: an Experience or Education section, a date range, or contact details (an email, a LinkedIn link, an
  international phone number or a labelled one such as "Mobile: 050 ..."). A file with none of them is not a resume.
  Measured: no English resume of the test sets is stopped (about 110 files). In the 200 public resumes, 2 bilingual
  Vietnamese resumes are stopped (Vietnamese headings, contact details removed by the data set, no date ranges).

**MM/YYYY dates** ("08/2022 - 03/2023") are month + year dates and count toward the years of experience (this was
already true for a job the Lab reads; it is now tested). **The page limit's years** (`D11`): the years of the jobs the
Lab reads; when it reads no job with dates (job lines it does not know, e.g. "• DEVELOPER // 01/2013 - 06/2016"),
the years of all date ranges in the resume; with no dates at all there is no page limit. A card never says "about 0
years" (under one year: "less than a year"); the card shows the page check's own sentence.

**Too many pages** (`D11`): 1 page over the limit is Minor; 2 or more pages over (`PAGES_OVER_MAJOR`) is Important,
so such a resume is never "Excellent" (Excellent needs no Critical or Important issue).

**Effect on the reference set** (score without the AI reviewer; with the saved AI reviews in brackets). Every resume
stays in its range, the strong set stays at 75+ and the weak set under 60. 27 of 33 resumes do not change.

| Resume | 1.1 | 1.2 | Why |
|---|---|---|---|
| Jana Sayed (strong set) | 86.2 (84.3) | 84.5 (82.7) | 3 pages for about 2 years: Important |
| Moemen Ahmed (weak set) | 47.0 (44.8) | 45.9 (43.8) | 3 pages for about 3 years: Important |
| Ahmed M. Osman (weak set) | 53.3 (52.5) | 52.1 (51.3) | 3 pages for about 3 years: Important |
| Hanish (weak set) | 47.0 (45.1) | 45.9 (44.1) | 3 pages for less than a year: Important |
| Mohammad Hussain (weak set) | 38.0 (37.5) | 38.8 (38.3) | no page card: the years now come from its dates |
| Rowan new file | 40.0 | 40.0 | 8 pages for about 10 years: Important (0 points: the layout limit already holds the score) |

**Speed (no score change):** a check parses the PDF once (`cv_cache.one_parse`) instead of once per reading (text,
running headers, text version, layout). The same 40 public resumes scored exactly the same, 42% faster; the slowest
public resume (vector drawings) went from 54 s to 15.5 s, with the same score.

## 10. Changes in 1.3 (2026-10-30)

The same for every resume and every job. Tests: `test_v13_rules.py` (11 tests, generated files and made-up postings).

**1. A big page overrun: total at most 75** (`CAP_PAGES`, `PAGES_CAP_TIMES` = 3, `PAGES_CAP_MIN` = 4 in
`cv_score.py`). When a resume has 3 times its page limit or more AND at least 4 pages (the limit: 1 page under 3 years,
2 pages under 10 years, 3 pages from 10 years), the total is at most 75 ("Good" at most). A 2- or 3-page resume is never
capped. The page card (`D11`, Important) then shows what cutting the pages gives back, the cap included; cutting the
pages lifts the cap in every "if fixed" number.

**2. Glued skills** (`ATSLab_v3.clean_keywords`, `glued_parts`). A posting pasted without its line breaks joins words
("Software DeveloperLocation: Pittsburgh, PADuration: 6+ Months", "obtainProject Management"). Such a skill is split at
the join and only the real skills inside are kept: a piece of 2+ words found in the posting, or one word the posting
writes on its own and always with a capital ("Spark" from "ScalaSpark"). The rest is dropped. A join = 3+ letters or
digits, then a capital and 2+ lower-case letters; or 2+ capitals, then a capital and 4+ lower-case letters. Not a join:
"APIs", "KPIs", "RESTful", "OAuth", "McKinsey", "iPhone", and names in `CAMEL_NAMES` ("JavaScript", "PowerShell",
"GitHub", "LinkedIn", "DevOps" ...).

**3. Jobs with fewer than 10 skills** (`ATSLab_v3.few_skills`). The skill checks (F1 hard skills found, M1 keyword
coverage) count the missing places up to 10 as the meaning match (M3): (n x skills + (10 - n) x meaning match) / 10.
With 2 skills and 1 generic hit ("Accounting"), the skills no longer count 50%; with a far meaning match (0.1) they
count 18%. 10 skills or more: no change. Without a meaning match (no embedder): no change. The check weights are
unchanged.

**Effect on the reference set** (scored without a job description: changes 2 and 3 do not apply). Every range passes,
the strong set stays at 75+, the weak set under 60 (`reference_v1.3.log`: 15 tests, 0 failed; `quick_v1.3.log`: 465
tests, 0 failed). No reference resume changes: the only one with 3 times its limit and 4+ pages is Rowan's new file (8
pages, limit 2), which the layout limit already holds at 40. The 15-page pre-launch test resume: 95.4 -> 75.0.

**Effect on the Job Match test** (`JDTEST.md`, 300 public pairs, same saved AI answers): 6 of 50 jobs lose glued skills;
the fit resume beats the no-fit resume for the same job in 72% of the pairs (was 70%; jobs with under 10 skills: 71%,
was 68%); AUC 0.684 (was 0.678).
