# 1000Jobs ATS Lab: release notes

## 2026-10-31: VERSION 1.4, the redesign, frozen

Saved in `release-v1.4\` with `requirements.txt`, the test sets, the test log and `MANIFEST.sha256`, like v1.3.
**No scoring change**: the scoring files are the same as v1.3 (score version `2026-10-30.v1.3`), every reference
score is the same. Everything from v1.2 and v1.3 still works (daily limit, admin lockout, queue, file messages).
The pages follow the design "1000Jobs ATS Lab Redesign" (7 pages); what differs and why: `design_check_v1.4\DESIGN_CHECK.md`.

**Admin page** (`/admin`), with a left sidebar: the views, the red "Needs review" count, the signed-in admin,
"Sign out" and "ATS Lab v1.4".
1. **Check a resume**: the upload area, "Target role (job title)" (required with a job description) and "Job
   description" one under the other, "Compare with a previous resume" with the client comparison checkbox, "The report
   shows" and "Recent checks" on the side. After the check: the full report, as before.
2. **History**: 4 summary cards, label chips, search, filters (with / without job, dates, checked by), a table with
   initials, source, job, colored score and review status. **Export CSV** (what the filters show, or the ticked rows;
   a cell is never run as a formula in a spreadsheet) and **Delete record** (asks first, then removes the report and
   the resume file for good).
3. **Needs review**: one card per resume with the score, the label, the reasons as tags, a notes box, the user's name
   and email when known, and "Mark reviewed" (saves who and when, and the note).
4. **Settings**: days to keep resume files (the user page's privacy note says the same number), the daily check limit,
   the "Needs review" rules (score below N, any Critical issue, missing email or phone: all editable, applied at once
   to every check, old ones too), the three links (only `http(s)://` addresses), the name-and-email switch.
5. **Activity log**: who signed in, checked a resume, marked one reviewed, changed a setting (old → new), deleted a
   record or exported a CSV, and when; search, action chips, dates; Export CSV.

**User page** (`/user`): a landing page ("Free resume check", no account needed, the upload card with an optional
job title and job description, the privacy note) and a result page (score and label, the parts and Job Match with a
job, "can reach about X", the **top 4 issues** with one short "why it matters" line, a locked "+N more issues found"
line, "Why 1000Jobs", "Get Premium" and "Book a resume session"). Never shown: fixes, points, per-ATS details, the AI
review, the full report.

**Look**: one style for every page (`lab_ui.py`), light and dark mode (the system setting), Inter, laptop (1366, 1920)
and phone (390) widths checked in screenshots: nothing cut off or overlapping. Every text is in `lab_text.py`.

**Tests**: `test_v14_ui.py` (30 tests). Quick suite 495 tests, 0 failures. Reference test 15/15. Security in a real
browser 31/31 (new: HTML in a review note is never run). 10 checks at once: 10 scored, 0 errors, 0 health checks
failed; the first 3 ran at once, the others waited in the queue and finished in 38-68 s.

## 2026-10-30: VERSION 1.3 (`2026-10-30.v1.3`), frozen

Saved in `release-v1.3\` with `requirements.txt`, the test sets, the test log and `MANIFEST.sha256`, like v1.2.
Details: `SCORING_RULES.md`, section 10. The Job Match test on public data: `JDTEST.md`.

1. **A big page overrun**: 3 times the page limit or more AND at least 4 pages -> the total is at most 75. A 2- or
   3-page resume is never capped. Cutting the pages lifts the cap.
2. **Glued skills**: a skill made of words glued together by a posting pasted without line breaks ("Software
   DeveloperLocation", "PADuration") is split; only the real skills inside are kept.
3. **Jobs with fewer than 10 skills**: the missing places count as the meaning match, so one generic skill cannot
   count for too much. Check weights unchanged.

**Effect**: no reference resume changes (all 17 ranges, strong set 75+, weak set under 60); the 15-page test resume
95.4 -> 75.0. Job Match test (300 public pairs): fit beats no fit for the same job in 72% of pairs (was 70%).

**Tests**: `test_v13_rules.py` (11 tests). Quick suite 465 tests, 0 failures (752 s). Reference test 15/15 (143 s).

## 2026-10-29: VERSION 1.2 (`2026-10-29.v1.2`), pre-launch fixes, frozen

Saved in `release-v1.2\` with `requirements.txt`, the test sets, the test log and `MANIFEST.sha256`, like v1.1.
Details and the effect on each reference resume: `SCORING_RULES.md`, section 9. Server limits: `DEPLOY.md`.

**Before going live**
1. **Daily check limit** on the User page: 3 checks per person per day (setting `daily_checks`), counted on the server
   by browser (a cookie) and by IP address. The 4th check shows "You've used today's 3 free checks. Please come back
   tomorrow." A check that ends with a message, not a score, is not counted. The Admin page has no limit.
2. **Admin sign-in**: 5 wrong tries for a name or from an IP address = 1 minute wait, counted on the server (a page
   reload no longer resets it).
3. **No file watcher** (`.streamlit/config.toml`): pages open faster and the log stays clean.
4. **Queue**: at most 3 checks run at the same time (Admin checks too); the others see "N people ahead of you" and
   start by themselves. The User page says "This usually takes 20 to 60 seconds".
5. `.dockerignore` and `.gitignore` leave out `release-*/`, `pretest_public/`, `calib_*/`, `nextsteps-resumes/`,
   `data/` (and every other folder with resumes).
6. **Local start** listens on this computer only (`--server.address 127.0.0.1`); Docker keeps all addresses.
7. **Clear messages**: locked PDF, Word file (now accepted by the upload box, then explained), damaged file (no
   technical words), empty file.
8. **Not a resume** (no Experience / Education section, no date range, no contact details): not scored.
9. **Not English**: not scored.

**Scoring**
10. MM/YYYY dates are month + year dates (already true, now tested). The page limit's years come from the dates in
    the resume when no job can be read; never "about 0 years".
11. **Too many pages**: 1 page over = Minor; 2 or more = Important, so never "Excellent".

**Smaller**
12. `/favicon.png` gave a server error: Streamlit 1.58 does not match Starlette 1.8. Fixed in `streamlit_fix.py`; the
    app now starts with `run_app.py` (the desktop shortcut and Docker use it).
13. The 54-second resume: the PDF (full of vector drawings) was parsed 4 times per check. Now once
    (`cv_cache.one_parse`): 15.5 s, same score. Every check is faster (the 200 public resumes: 19 min -> 6 min).

**Tests**: `test_v12_rules.py` (24 tests, generated files). Quick suite 454 tests, 0 failures (415 s). Reference test
15/15 (142 s): all 17 ranges, strong set 75+, weak set under 60. Pre-launch re-test: see `PRELAUNCH_v1.2.md`.

## 2026-10-29: VERSION 1.1 (`2026-10-29.v1.1`), frozen

The code, `requirements.txt`, the docs, the test sets and the test log are saved in `release-v1.1\` (with
`MANIFEST.sha256`), the same way as v1.0. v1.1 = the Admin and User pages + the six scoring changes below.
Not in the copy: `.streamlit\secrets.toml` (admin passwords and the AI key) and `data\` (the check history).

**Decisions for 1.1:**
- The reference rule "Rowan's new file has more Content than Rowan's original" is **removed** from
  `reference_scores.json`. It was set while the bullet-length and the old length checks still counted. All total
  score ranges are kept. No special case was added.
- The gap filter stays as it is: an AI finding whose reason depends on a gap is removed too (not only a finding with
  "gap" in its title).

Result: reference test 15 tests, all pass (316 s): all 17 resumes in their ranges, strong set 75+, weak set under 60.
Quick suite 430 tests, 0 failures (554 s). Log: `release-v1.1\TEST_RESULT_v1.1.log`.

## 2026-10-29: v1.1 scoring changes (`2026-10-29.v1.1`)

Six rule changes for every resume (details and the effect on each reference resume: `SCORING_RULES.md`, section 8).

1. **Resume length**: only "too short for the experience" is flagged (8+ years in under 350 words, or 10+ years on one
   page), Minor. A long resume is never flagged by this check. New card name: "Resume is short for your experience".
2. **"Some bullets are too long or too short" is removed** (no card, no points; its weight is given in full).
3. **No employment gap check**: AI gap findings are dropped in code; the Lab no longer confirms or reports gaps.
4. **Names with a credential or title** ("NAME, PMP®", "NAME, MBA", "Dr. ...") are found, also when letter-spaced;
   the report header and the PDF file name show the name without the credential.
5. **A letter-spaced name only** is the Minor card "Name has letter spacing", not "Template is hard for ATS to read".
6. **Bullets never swallow a job header** ("Title | Company, City, Mon YYYY - Mon YYYY"), also a long one the job list
   missed; every bullet check reads the fixed bullets.

Quick suite: 430 tests, all pass. Reference test: all 17 resumes in their ranges, strong set 75+, weak set under 60.
The reference rule "Rowan's new file has more Content than Rowan's original" failed (original 49.0, new 47.9; with the
AI 46.8 and 43.4) and was then removed (see the 1.1 section above and `SCORING_RULES.md`, section 8).
New tests: `test_v11_rules.py`.
Older tests that pinned the old rules were updated (`test_cv_score`, `test_dashboard`, `test_regression`,
`test_jobmode`, `test_final`, `test_report`, `test_strong`).

## 2026-10-29: v1.1, Admin page and User page (scoring unchanged: `2026-10-28.v1.0`)

- **One app, two links** (`app.py`): `/user` (also the bare address) for job seekers, `/admin` for the team.
  Start: `py -3.12 -m streamlit run app.py`, or the "1000Jobs ATS Lab" desktop shortcut (opens `/admin`).
- **Admin page**: sign in with name + password (several accounts, from secrets or `ATSLAB_ADMINS`). Views:
  - *Check a resume*: the whole dashboard.
  - *History*: every check by an admin or a user; open any past report, its PDF and the resume file.
  - *Needs review*: score under 55, a Critical issue, no email or no phone; "Mark reviewed".
  - *Settings*.
- **User page**: shows the score, the label, the parts, "can reach about X" and the top issues (about half of the
  points, at most 5) with one "why" line each. Also a locked "+N more issues found", "Why 1000Jobs", "Get Premium" and
  "Book a resume session". It never shows fixes, points per issue, ATS details, keywords, the AI review or the full
  report. There is an optional name-and-email step (off by default) and a privacy note.
- **History**: SQLite file in the data folder (`ATSLAB_DATA_DIR`). Resume files are deleted after `file_days` days
  (30 by default, a setting); the score and the report stay.
- **Deployment**: `Dockerfile`, `.dockerignore`, `packages.txt` (Streamlit Cloud), `.streamlit/secrets.toml.example`,
  `.gitignore`, and `DEPLOY.md` in simple English. `requirements.txt` now carries the PyTorch CPU index itself.

## 2026-10-28: VERSION 1.0 (`2026-10-28.v1.0`), frozen

The code, `requirements.txt`, the docs and the test sets are saved in `release-v1.0\` (with `MANIFEST.sha256`).
Scoring rules: `SCORING_RULES.md`.

**Decision on the two caps from the final fixes** (see the table in `SCORING_RULES.md`, section 5):
- **No Minor cap** (`MINOR_CAP = None`). A cap of 10 pushed 12 of 17 reference resumes out of their ranges and the weak set
  up to 72 (it must stay under 60). No Minor cap up to 25 keeps the weak set under 60.
- **"No headline" takes at most 20 points from the total** (`HEADLINE_CAP = 20`), not 10. A cap of 20 changes no reference result;
  10 or 15 moves reference resumes out of range.
- **The job-location change stays**: a job location is not required (title, company and Mon YYYY dates are); a missing one is a
  Minor note worth at most 1 point (`T16`).

Result: the whole suite passes, 433 tests, 0 failures (882 s), including the reference test (all 17 resumes inside their
ranges, weak set under 60) and the strong test.

## 2026-10-28: final fixes before 1.0 (`2026-10-28.v1-final-1`)

1. **From the resumes that got interviews.**
   - A **job location** is not required. *Title, company and Mon YYYY dates* still are (check `T4`). A missing job
     location is its own Minor note (`T16`, "Some jobs show no location") worth at most 1 point of Structure.
   - Two caps were built and measured here: Minor issues of a part cost 10 points at most (`MINOR_CAP`), and "No headline"
     takes at most 10 points from the total (`HEADLINE_CAP`). They conflicted with the reference ranges, so **1.0 ships with
     no Minor cap and a headline cap of 20** (see the 1.0 section above). Both are still switches in `cv_score.py`.
2. **Shifted page boxes** (error "Bounding box ... is not fully within parent page bounding box"): every crop is clamped to the
   page's own box; a page that still cannot be read skips only its layout checks, with a note.
3. **Speed.** `cv_cache.py` keeps each file's text and layout by its fingerprint (SHA-256 of the bytes), so the same resume is read
   once per run, whatever its name. The meaning-match model is loaded once per run, also after the Lab modules are reloaded.
   `py -3.12 run_tests.py --quick` runs every test except the two slow calibration tests; `--reference` and `--full` also exist.
4. **Job description layout.** In "With job description" mode: *Target role (job title)* (required), then *Job description*, one
   under the other, full width.

## 2026-10-28: "With job description" mode (`2026-10-28.jobmode-1`)

All seven changes apply to every resume checked with a job description. Without a job description nothing changes.

1. **Job title field.** A required "Job title" box sits next to the job description. It is used for "The job title is
   not near the top" and for the headline check, and is shown in the report header (*Job title*). The title is never
   guessed from the posting again. Without a title the dashboard says so instead of checking.
2. **Severity.** Missing *required* skills are **Important** (they were Minor). A card that lists only missing
   *preferred* skills stays Minor. The card quotes the two apart: *Required, not found in the resume* and *Preferred,
   not found*.
3. **Skills kept from the posting.** Only what a recruiter types into a search box. A phrase that ends in a quality or a
   judgement ("brand judgement", "creative evaluation") and a bare "messaging" are dropped. The AI prompt says so too.
4. **"Abbreviations written only one way"** only counts terms that are in the resume. A skill that is missing from the
   resume appears only in the missing-skills card.
5. **One job title card.** "The job title is not near the top" and the AI finding about the job title not matching
   the target role are one card (the AI finding is listed under *Also covers*).
6. **AI gap findings follow the Lab's own timeline.** Before, any gap in the timeline let *every* AI gap finding
   through, even one about a period that a degree covers (an MA from Sep 2021 to Feb 2023). Now a gap finding is kept
   only when the period it names overlaps a gap the Lab found, and only then is it "confirmed by the Lab".
7. **The sentence under the score** in the report: *"... the score shows how easily an ATS can read this resume, how well
   it meets the 1000Jobs standard, and how well it matches this job."*

## 2026-10-26: scoring rebuilt around six principles (`2026-10-26.principles-13`)

Until now the Lab grew one fix at a time, often after one resume. This release puts the scoring rules in one place
(`cv_score.py`, section **THE SCORING RULES**) and locks them with a reference set of real resumes
(`reference_scores.json`, checked by `test_reference.py`). No rule names a person, a file or a template.

### The principles

1. **Score the file as it is uploaded.** An ATS reads the whole file, so every page counts. The special case that
   scored only the "text version" of a file is gone. The note *"This file has a designed version and a text version.
   For online applications, upload only the text version."* stays, but it no longer changes the score.
2. **Three parts, each with one meaning.**
   - **Readability:** can an ATS read it (layout, columns, images, fonts, reading order).
   - **Content:** how strong the information is (headline, numbers, results, verbs, clarity). Good, detailed content
     is rewarded even on a bad template. A new check, *Enough detail about your roles*, expects about 3 bullets for
     each role of the last 10 years.
   - **Structure:** is it built like a standard resume. This now includes the page format: a landscape page, columns
     or a sidebar are also a Structure problem (*The page is not a standard resume page*).
3. **Layout limits.** These are hard caps, the same for everyone:

   | Layout | Readability | Structure | Total |
   |---|---|---|---|
   | Any landscape page | 50 at most | 55 at most | 50 at most |
   | Two or more columns, or a sidebar, on any page | 45 at most | 55 at most | 55 at most |
   | Landscape **and** columns / sidebar | 45 at most | 55 at most | **40 at most** |

   A page that is an image (or mostly one) is an unreadable page: Readability counts only the readable pages. Strong
   content moves a resume up inside these limits, never past them.
4. **Fixed severity, the same for every resume.**
   - **Critical:** the layout problems above (landscape, columns, sidebar, image pages, the page format).
   - **Important:** no headline (a headline that names no job title counts as no headline), few numbers, missing or
     year-only job dates, missing email or phone.
   - **Minor:** everything else. Letter-spaced headings alone are Minor too.
   - AI findings are Important at most, and there are 3 at most.
   - What a problem costs follows its severity. In Readability: Critical 15, Important 10, Minor 5 points. In Content
     and Structure, a failed standard costs Critical 15, Important 12, Minor 2 points (at most 35 per part).
5. **"Can reach about X" is capped at 95.** When the layout must be rebuilt, the sentence reads *"... can reach about
   X after moving to a single-column, portrait resume and fixing N more issues."*
6. **Quotes are clean, readable lines.** The name alone is never quoted. When something is missing, the card says
   *"Not found in your resume"*.

### Explainable scores

The points in each part's **Why this score** add up to what the part lost. Each cost is tied to an issue; a layout
limit is counted in the cost of the layout card (*Template is hard for ATS to read* in Readability, *The page is not a
standard resume page* in Structure).

### Reference set

`reference_scores.json` lists 17 real resumes with their expected ranges, plus two sets: every resume in `strongcvs`
must score 75 or more, every resume in `weakcvs` 60 or less. Scores are measured without the AI reviewer, so the test
gives the same numbers every run. If a score leaves its range, fix the general rule, never one file.

### Changed on purpose

- A headline that names areas but no job title ("SUPPLY CHAIN & LOGISTICS | INVENTORY & VENDOR OPERATIONS") is now
  Important again, as "no headline". This reverses the Minor rule of 2026-10-23; it is the one general rule that puts
  Jibran's freelancer resume in its range (75-82) without moving any other reference resume out of its range.
- Column detection: a column of bullet symbols, or a few line ends past a wide gap, is not a column.
- A resume whose jobs sit under company names (no "Experience" heading, or a second block of jobs) has all of them
  read as Experience.
