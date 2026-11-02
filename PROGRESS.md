# Progress: v1.4 (2026-10-31), frozen

Run with `py -3.12`. Frozen: v1.0 in `release-v1.0\`, v1.1 in `release-v1.1\`, v1.2 in `release-v1.2\`, v1.3 in
`release-v1.3\`, v1.4 in `release-v1.4\`. Pre-launch re-test (robustness, edge cases, security, load):
`PRELAUNCH_v1.2.md` (v1.4: `security_v1.4.log`, `load_v1.4.log`).

## Part 5: v1.4, the redesign (no scoring change: score version still `2026-10-30.v1.3`)

| # | Page / item | Status |
|---|---|---|
| 1 | Admin: left sidebar (views, "Needs review" count, admin, sign out, "ATS Lab v1.4") | done, tested |
| 2 | Check a resume: upload, target role + job description, compare (client comparison), "The report shows", "Recent checks" | done, tested |
| 3 | History: 4 cards, label chips, search, filters (job, dates, checked by), table, Export CSV, Delete record (asks first) | done, tested |
| 4 | Needs review: cards, reasons as tags, notes, name and email, "Mark reviewed" (who and when) | done, tested |
| 5 | Settings: file days (privacy note follows), daily limit, review rules (editable), links, name-and-email switch | done, tested |
| 6 | Activity log: checks, reviews, settings (old -> new), deletions, exports, sign-ins; filters; Export CSV | done, tested |
| 7 | User landing page and result page (top 4 issues, locked line, "Why 1000Jobs", the two buttons) | done, tested |
| 8 | One style (lab_ui.py), light and dark mode, all texts in lab_text.py, laptop and phone widths | done, checked in screenshots |

New files: `lab_text.py` (every text), `lab_ui.py` (the look), `test_v14_ui.py` (30 tests), `design_check_v1.4\`
(52 screenshots + `DESIGN_CHECK.md`: what matches the PDF and the differences). Changed: `admin_page.py`,
`user_page.py`, `lab_pages.py`, `lab_settings.py`, `lab_store.py` (notes, review facts, delete, activity log; an older
database gets the new columns), `app.py`, `.streamlit/config.toml` (light and dark theme). The scoring files are
byte-for-byte the same as v1.3.

Tests (2026-10-31): quick suite 495 tests, 0 failures (`quick_v1.4.log`); reference test 15/15 (`reference_v1.4.log`);
security in a real browser 31/31 (`security_v1.4.log`); 10 checks at once: 10 scored, 0 errors, 0 health checks failed
(`load_v1.4.log`). Old tests updated to the new pages: `test_app_pages` (views, top 4 issues, privacy note with days,
review facts), `test_dashboard` (the theme color is the redesign's indigo).

## Part 4: v1.3 (score version `2026-10-30.v1.3`)

| # | Change (for every resume / job) | Status |
|---|---|---|
| 1 | Page cap: 3 times the page limit or more AND 4+ pages -> total at most 75; 2-3 pages never capped | done, tested |
| 2 | Glued skills from a pasted posting split; only real skills inside kept | done, tested |
| 3 | Jobs with under 10 skills: missing places count as the meaning match (weights unchanged) | done, tested |
| - | Job Match test on public labelled data (`JDTEST.md`; data `jdtest_public\`, scripts `jdtest_tools\`) | done |

Tests: `test_v13_rules.py` (11 tests). Reference test 15/15 (`reference_v1.3.log`); quick suite 465 tests, 0 failures
(`quick_v1.3.log`). No reference resume changes; the 15-page test resume 95.4 -> 75.0. Job Match test: fit beats no
fit for the same job 72% (was 70%). Details: `SCORING_RULES.md`, section 10. **Frozen as v1.3 in `release-v1.3\`.**

## Part 3: v1.2, pre-launch fixes (score version `2026-10-29.v1.2`)

| # | Change (for every file) | Where | Status |
|---|---|---|---|
| 1 | Daily limit: 3 checks per person per day (setting `daily_checks`), by browser cookie and by IP, on the server; a message gives the check back | `lab_store`, `lab_pages`, `user_page`, `lab_settings` | done, tested |
| 2 | Admin wrong tries counted on the server, per name and per IP (5, then 1 minute) | `lab_store`, `admin_page` | done, tested |
| 3 | No file watcher (`fileWatcherType = "none"`) | `.streamlit/config.toml` | done, tested |
| 4 | Queue: at most 3 checks at once (Admin page too), "N people ahead of you", "20 to 60 seconds" | `lab_pages`, `user_page`, `dashboard` | done, tested |
| 5 | `release-*/`, `pretest_public/`, `calib_*/`, `nextsteps-resumes/`, `data/` in `.dockerignore` and `.gitignore` | | done, tested |
| 6 | Local start on 127.0.0.1 (Docker keeps 0.0.0.0) | `Start ATS Lab.bat` | done, tested |
| 7 | Messages: locked, Word, damaged (no technical words), empty | `dashboard.run_check` | done, tested |
| 8 | Not a resume: no section, no date range, no contact details | `cv_score.resume_signs` | done, tested |
| 9 | Not English | `cv_score.not_english` | done, tested |
| 10 | MM/YYYY dates; the page limit's years from the dates when no job is read; never "about 0 years" | `cv_score`, `dashboard` | done, tested |
| 11 | Too many pages: 1 over = Minor, 2+ over = Important (never Excellent) | `cv_score.rule_severity` | done, tested |
| 12 | `/favicon.png` error (Streamlit 1.58 + Starlette 1.8): fix in `streamlit_fix.py`, started by `run_app.py` | | done, tested |
| 13 | Slow resume (54 s): the PDF was parsed 4 times; now once per check (`cv_cache.one_parse`): 15.5 s | | done, tested |

Tests: `test_v12_rules.py` (24 tests, generated files). Reference test 15/15 (`reference_v1.2.log`); quick suite 454
tests, 0 failures (`quick_v1.2.log`). Old tests updated: `test_app_pages` (server-side lockout), `test_reference`
(page severity), `test_dashboard` (Word message), `test_ATSLab_v3` (skips the downloaded test set).

## Part 2: scoring changes (score version `2026-10-29.v1.1`)

| # | Change (for every resume) | Status |
|---|---|---|
| 1 | Resume length: only "too short for the experience" (8+ years under 350 words, or 10+ years on 1 page), Minor | done, tested |
| 2 | "Some bullets are too long or too short" removed (no card, no points) | done, tested |
| 3 | Employment gap check removed (AI gap findings dropped in code, no Lab gap confirmation) | done, tested |
| 4 | Name found with a credential or title ("NAME, PMP®", "Dr. ..."), also letter-spaced; shown without it | done, tested |
| 5 | Letter-spaced name only = Minor "Name has letter spacing", never the template card | done, tested |
| 6 | A bullet is never joined with a job header; all bullet checks read the fixed bullets | done, tested |

Changed: `cv_score.py`, `cv_review.py`, `cv_layout.py` (`spaced_line_text`), `ATSLab_v3.py` (`bare_name`, the name
check `R1`), `dashboard.py`. New tests: `test_v11_rules.py` (18 tests, generated resumes). Old tests that pinned the
old rules were updated. Effect on each reference resume: `SCORING_RULES.md`, section 8.

Decision: the reference rule "Rowan's new file has more Content than his original" (49.0 vs 47.9) was removed; all
total score ranges kept. The gap filter stays (findings whose reason depends on a gap are removed too).

Tests (2026-10-29): reference test 15 tests, all pass (`reference_v1.1.log`); quick suite 430 tests, 0 failures
(`quick_v1.1.log`). **Frozen as v1.1 in `release-v1.1\`.**

## Part 1: Admin page and User page (no scoring change)

| # | Item | Status |
|---|---|---|
| 1 | One app (`app.py`), two links: `/user` (also `/`) and `/admin`; no menu between them | done |
| 1 | Admin sign in: several accounts (name + password) from secrets or `ATSLAB_ADMINS`; nothing in the code; 5 wrong tries = 1 minute wait | done |
| 1 | OpenRouter key from secrets or the environment; data folder `ATSLAB_DATA_DIR` (no folder of this computer in the code) | done |
| 2 | Admin "Check a resume" = the full dashboard (job / no job, previous resume, client comparison, Download PDF) | done |
| 2 | History table (date, candidate, admin or "user", job, job title, score, label); click a row to open the report, its PDF and the resume file | done |
| 2 | "Needs review": score under 55, a Critical issue, no email, no phone; "Mark reviewed" saves who and when | done |
| 2 | SQLite history (`data\atslab.db`); resume files deleted after `file_days` (30, a setting); score and report stay | done |
| 3 | User page: score, label, parts, "can reach about X", top issues (about half the points, at most 5) with one "why" line, "+N more issues found" (locked) | done |
| 3 | Hidden on the User page: how to fix, what the ATS reads, points per issue, AI review, per-ATS details, keywords, full report | done, tested |
| 3 | "Why 1000Jobs", "Get Premium" and "Book a resume session" (links are settings), name-and-email step (off by default), privacy note | done |
| 3 | Every User page check is in the Admin history as "user" | done, tested |
| 4 | Same look as the dashboard; the User page checked at phone width (390 px) in a real browser | done |
| 5 | `requirements.txt`, `Dockerfile`, `.dockerignore`, `packages.txt`, `.streamlit/secrets.toml.example`, `.gitignore`, `DEPLOY.md` | done |
| 5 | "Start ATS Lab" shortcut runs `app.py` and opens `/admin`; "Stop ATS Lab" stops it | done |

New files: `app.py`, `admin_page.py`, `user_page.py`, `lab_pages.py`, `lab_settings.py`, `lab_store.py`, `test_app_pages.py`.
Changed: `dashboard.py` (a hook to save each check, a bar under the top bar, server-friendly messages, `--no-sandbox` for
Chromium on Linux only); `test_ATSLab_v3.py` (skips the frozen `release-*` folder, whose `requirements.txt` is not a job).

## Tests (2026-10-29)

- `test_app_pages.py`: 31 tests (links, sign in right and wrong, accounts, settings, the AI key from the secrets, history,
  needs review, mark reviewed, the 30-day clean-up, User page shows and hides, lead step). All pass.
- Quick suite: 415 tests, 1 failure: `test_every_real_job_passes` read `release-v1.0\requirements.txt` as a job. Fixed in the test;
  `test_ATSLab_v3` then ran again: 95 tests, all pass.
- Reference test: 15 tests, all pass (299 s). Scores did not change.
- In a real browser (Edge, headless): resume uploaded on `/user` at phone width, result shown; signed in on `/admin`; History,
  opening a past report, Needs review and Settings all work.
