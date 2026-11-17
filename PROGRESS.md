# Progress: v1.4 (2026-10-31), frozen

Run with `py -3.12`. Frozen: v1.0 in `release-v1.0\`, v1.1 in `release-v1.1\`, v1.2 in `release-v1.2\`, v1.3 in
`release-v1.3\`, v1.4 in `release-v1.4\`. Pre-launch re-test (robustness, edge cases, security, load):
`PRELAUNCH_v1.2.md` (v1.4: `security_v1.4.log`, `load_v1.4.log`).

## The X is now the Lab's teaching signal (2026-11-16, no scoring change)

### The score is shown as a whole number (display only, same round)

Bader's rule, from his own example: "79.9 show only 79 - no decimal numbers". The SCORE is printed as a whole
number everywhere (79.9 -> 79, 79.0 -> 79, 100 -> 100); the decimals are dropped, never rounded up. POINTS keep
their decimal (a 3.6-point issue still reads "+3.6 pts"), otherwise a 0.4-point issue would show as "+0" and hide
a real problem. The scorer's own numbers are untouched: the score is still computed and stored exactly as before
(one decimal), so no rule, weight, threshold, penalty, cap or gate changed and every reference score is the same.

| # | Item | Status |
|---|---|---|
| 1 | `dashboard.py`: new `fmt_score(p)` (whole number) next to `fmt(p)` (points, one decimal) | done |
| 2 | Whole number everywhere the score appears: the big circle (`gauge`), "Now / After top fixes", the headline ("can reach about X"), the plain sentence, the client comparison (both sides and the difference), the Admin comparison line, the Admin history table, the log line and the CSV export | done |
| 3 | `lab_ui.py`: the score pill and the score ring (Admin + User page) use a whole number | done |
| 4 | `user_page.py`: "can reach about X" uses the whole number | done |
| 5 | Not changed on purpose: the points of an issue, the part percentages, the meaning match %, the issue count, and the average score of the History cards (a whole number already) | done |

Tests updated to the new rule (display only): `test_dashboard` (the circle and the two "can reach" lines),
`test_jobmode` (the sentence under the score), `test_client_report` (both scores and the difference),
`test_app_pages` (the User page ring), and `test_set_aside` (the score keeps its own decimal inside, the page
prints a whole number; `fmt_score` is now covered).

Results: quick suite 653 tests, 0 failed, 2 errors, 7 skipped (13.9 min; the 2 errors are the Edge-headless PDF
prints, which the test sandbox cannot run). Reference suite 16/16, 0 failed (3.5 min): every reference score is
exactly the same as before, as expected for a display-only change.

Bader's round: the team-only X on an issue card used to set the issue aside silently. It now asks WHY,
records the reason (manual training), changes the score, and shows the log so the team can fix the checks
that cause false alarms. Admin only; no rule, weight, threshold, penalty, cap or gate changed.

| # | Item | Status |
|---|---|---|
| 1 | `dashboard.py`: added the missing `TRAIN_REASONS` and `TRAIN_TEXT` (they were referenced by the set-aside form but never defined, so the first X press raised `NameError`). Five reasons: false alarm, not important for this role, already fixed, the Lab's rule is too strict here, other (with a free note) | done |
| 2 | `dashboard.py`: `render(..., set_aside=False, trainer=None, training=None)` passes both to `set_aside_controls`. A failed save never blocks the X (the trainer call is wrapped, with a clear warning) | done |
| 3 | `admin_page.py`: `training_hooks(who)` returns `(trainer, training)`; `check_view` passes them into `D.render(...)`. The trainer writes a `training` row (admin, check id, cv, job title, score, issue ids, card, reason, note, evidence) and an Activity log line | done |
| 4 | `lab_text.py`: `LOG_KINDS["training"] = ("Teaching", "Set an issue aside")`, `LOG_DETAILS["training"] = "Set aside ({reason})"` | done |
| 5 | The Admin report shows the aggregated log (issue, code, times set aside, why, last time) and a CSV download. The User page and the client report show nothing | done, tested |

Tests: `test_set_aside.py` grew to 20 tests (texts and reasons exist; the log counts and names the reasons;
the CSV keeps the reason; the X asks WHY then saves the reason, a fake trainer records it and the issue leaves
the report; a plain report has no training controls). The older "pressing X changes the report" test now follows
the new two-step flow. All 20 pass. Quick suite (sandbox, offline): 653 tests, 0 failed, 2 errors, 7 skipped
(the 2 errors are Edge-headless PDF printing, which the test sandbox cannot run; unrelated to this change).
Reference suite: 16/16, 0 failed, 0 errors (202 s) - no reference score moved.

## Set an issue aside + clearer cards (2026-11-16, no scoring change)

Bader's round: (1) a team-only X on an issue card that stops it counting and changes the score, small changes
included; (2) clearer "why it hurts" / "how to fix it"; (3) the present-tense card must not read like a bug;
(4) Netlify dropped for now.

| # | Item | Status |
|---|---|---|
| 1 | `cv_score.py`: `score_with` split into `fixed_state` + `parts_score_with` + `score_with`, so a page reads the score AND the parts from ONE computation. `_part_costs` keeps each issue's own part cost (taken before `part_explain` pops `_cost`). The result gains `_parts_with` and `_part_costs`. No rule, weight, threshold, penalty, cap or gate changed | done, tested |
| 2 | `dashboard.py`: `set_aside_key/cards/ids`, `view_with` (a set-aside issue is treated as FIXED, so its points come back through the scorer's own counterfactual and the parts are scaled the same way), `set_aside_controls` (one X per card, one to put it back), `render(..., set_aside=False)` | done, tested |
| 3 | `fmt` no longer rounds a 0.1 away (71.1 shows as 71.1); the big circle uses `fmt` too | done, tested |
| 4 | Clearer text for `skills_unreadable` (what the ATS found, why it matters, a real example) and `tense` (a style point, not a reading problem) | done |
| 5 | `admin_page.py` passes `set_aside=True` — Admin only; the User page and the PDF report are unchanged | done, tested |

New file: `test_set_aside.py` (15 tests). Two older tests updated because the page no longer rounds the score
(`test_dashboard.test_big_circle_...`, `test_pdf.test_one_plain_sentence_...`); the meaning of both is the same.
Quick suite 654 tests, 0 failures, 4 skipped (904 s); reference test 16/16 (231 s).
Summary for Bader: `outputs\Fix_round_2026-11-16.md`.
**Open question:** the present-tense check still costs points (it can be set aside with one press). Removing it
from the score is a scoring change and needs Bader's OK first.

## Second opinion (Admin page only), 2026-11-10 (no scoring change)

| # | Item | Status |
|---|---|---|
| 1 | "Second opinion" section under the big ATS Lab score on the Admin page: two extra ATS checkers, "Resume Matcher" (keyword match, compared with our Job match) and "ATS Checker 2" (general score, compared with our main score) | done, checked in screenshots |
| 2 | Each card is empty until the team presses its button; then it shows its number, the Lab's label (84 = Strong), the difference (Agrees within 10 points / Higher / Lower) with the points, when it was checked, and "Check again" | done, tested |
| 3 | The Resume Matcher card also shows the keyword match and, when it disagrees, the top 5 missing keywords | done, tested |
| 4 | Card states: not checked yet, Checking..., Needs a job description, Not available right now, Switched off in Settings; Settings has one on/off switch per checker | done, tested |
| 5 | The section never changes the score; the user page, the client report and the standalone dashboard draw nothing new (`dashboard.render` draws it only when the Admin page passes the `after_score` hook) | done, tested |
| 6 | An answer is kept per resume AND per job description, so a different file or job never reuses an old answer | done, tested |
| 7 | Both checkers run on this device: no resume leaves the computer | done |

New file: `test_second_opinion.py` (21 tests, ~3 s, no model, no cost). Changed: `lab_second.py`,
`lab_settings.py`, `lab_text.py`, `lab_ui.py`, `dashboard.py`, `admin_page.py`.
Reference suite 16/16 (`ref_10nov.log`); quick suite 613 tests, 0 failures, 4 skipped (`quick_10nov.log`).
Pictures: `outputs\Second_opinion_0_where_it_sits.png` ... `Second_opinion_5_settings_switches.png`;
report: `outputs\ATS_Lab_Second_Opinion_2026-11-10.md`.

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

## Round: Manus Cloud Computer deployment bundle (17 Nov 2026)

Prepared the full deployment so only spinning up the machine and publishing is left. No scoring code changed.

Added deploy/cloud/:
- docker-compose.yml         direct port mode (http://IP:8501), single app container, named volume atslab-data
- docker-compose.https.yml   HTTPS mode: app + Caddy, automatic Let's Encrypt certificate
- Caddyfile                  reverse proxy for the HTTPS mode
- .env.example               the two required settings plus the optional links and limits
- install.sh                 one shot: Docker, UFW ports, .env check, build, start, systemd auto-start
- package.ps1                builds atslab-deploy.tar.gz (code only, no secrets, no data)
- README-CLOUD.md            the runbook, costs and troubleshooting

Verified: both compose files pass "docker compose config"; the HTTPS file correctly refuses an empty DOMAIN;
the tarball is 0.5 MB and contains app.py, run_app.py, Dockerfile, requirements.txt, .dockerignore and the
deploy/cloud files. install.sh could not be linted locally (no bash, Docker daemon not running) and was
reviewed by hand instead.

Not done: no Cloud Computer is attached to this session, so nothing has been deployed yet.

## Cloud Computer deployment kit (17 Nov 2026)
Added deploy/cloud/ so only spinning up the machine and publishing is left:
- docker-compose.yml (direct port 8501) and docker-compose.https.yml (Caddy + sslip.io free HTTPS)
- Caddyfile, .env.example, install.sh (Docker, UFW, build, systemd auto-start), README-CLOUD.md
- package.ps1 builds deploy/cloud/atslab-deploy.tar.gz (0.5 MB, code only: no secrets, no data)
Validated: both compose files pass "docker compose config"; the tarball contains app.py, run_app.py,
Dockerfile, requirements.txt and the whole deploy/cloud kit. No scoring rule was touched.

## 17 Nov 2026 - Cloud Computer deployment bundle (prepared, not yet deployed)

The Lab is a Streamlit/Python app (torch + Chromium), so Manus web publishing cannot host it.
The only "on Manus" path is a Manus Cloud Computer running the Docker image. Everything is prepared
so that only spinning up the machine and running one command remains.

New folder `deploy/cloud/`:
- `docker-compose.yml` - direct port mode, http://IP:8501 (fastest test).
- `docker-compose.https.yml` - app + Caddy, HTTPS with a free `<ip-with-dashes>.sslip.io` name.
- `Caddyfile` - reverse proxy for the HTTPS mode.
- `.env.example` - the settings to fill in (OPENROUTER_API_KEY, ATSLAB_ADMINS, optional DOMAIN).
- `install.sh` - installs Docker, opens UFW ports, checks .env, builds, starts, enables boot start.
- `package.ps1` - builds `atslab-deploy.tar.gz` (code only, no secrets/history/resumes).
- `README-CLOUD.md` - the runbook.

Verified: both compose files pass `docker compose config` (HTTPS mode correctly refuses an empty
DOMAIN); the tarball is 0.5 MB and contains app.py, run_app.py, Dockerfile, requirements.txt,
.dockerignore and the deploy/cloud files. `install.sh` could not be linted locally (no bash, Docker
daemon not running) and was reviewed by hand instead.

No scoring rule, weight or threshold was touched. This round only adds deployment files.

## 17 Nov 2026 - Pushed to GitHub (main)

Git push kept failing with `schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS` and `getaddrinfo() thread failed to start`. Node and Python reached github.com fine, so the fault was git's Windows schannel TLS stack in this session, not the network.

Fix: a small local HTTP-to-HTTPS forward proxy (`.work/scripts/github_proxy.js`, port 8799) that does the TLS leg with Node's OpenSSL, plus the GitHub connector token sent as `Authorization: Basic base64(x-access-token:TOKEN)` with `credential.helper=` disabled. Git then pushes to `http://127.0.0.1:8799/Badermk196/ATSLab.git`.

Result: 4 commits pushed (`57ef99c..533e131`), remote `main` and local `main` identical (`533e131`), working tree clean. Only `.streamlit/secrets.toml.example` is tracked; the real secrets file, `data/` and the deploy tarball stay untracked.

## 17 Nov 2026 - Simpler push method found (no proxy needed)

Git push now works without the local proxy: use `-c http.sslBackend=openssl` and pass the token as an `Authorization: Basic` header, pushing straight to https://github.com/Badermk196/ATSLab.git. The Windows schannel TLS stack is the only broken part; OpenSSL works. Network egress must be allowed for the command. `git ls-remote` still hangs on this machine (getaddrinfo thread), so verify the pushed commit through the GitHub API instead. Result: commit 12a0892 pushed, local main and origin/main identical, working tree clean.
