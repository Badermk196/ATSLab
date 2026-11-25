# How to run the 1000Jobs ATS Lab (v1.4)

The app has two pages:

| Page | Link | For |
|---|---|---|
| User page | `https://YOUR-ADDRESS/user` (the bare address `/` opens it too) | job seekers: share only this link |
| Admin page | `https://YOUR-ADDRESS/admin` | the 1000Jobs team: name + password |

The Admin page has a menu on the left: **Check a resume**, **History**, **Needs review**, **Settings** and
**Activity log** (on a phone the menu opens with the button at the top left). The version is shown under the menu.

The main file is **`app.py`**. Start it with **`run_app.py`** (it applies a small fix for Streamlit 1.58 before the
server starts, see `streamlit_fix.py`): `python run_app.py` takes the same options as `streamlit run app.py`.
Python **3.12**.

## What the app needs (the secrets)

1. **`OPENROUTER_API_KEY`**: the AI key, used for job keywords and the AI review.
2. **Admin accounts**: one name and password per person. The name is shown in the history as "Checked by".

Write them in a file named `.streamlit/secrets.toml`. Start from `.streamlit/secrets.toml.example`:

```toml
OPENROUTER_API_KEY = "sk-or-v1-..."

[admins]
Bader = "a-long-password"
Sara = "another-long-password"
```

You can also use environment variables instead of the file:
`OPENROUTER_API_KEY=...` and `ATSLAB_ADMINS={"Bader": "...", "Sara": "..."}`.

Never put the real secrets file in a code repository or in a Docker image. `.gitignore` and `.dockerignore` already
leave it out.

## Settings

An admin can change these on the Admin page, under **Settings**. You can also set them as secrets or environment
variables. A value saved on the Settings page wins over a secret or environment variable.

| Setting | Name as a secret / environment variable | Default |
|---|---|---|
| Days to keep uploaded resume files (the User page's privacy note says the same number) | `ATSLAB_FILE_DAYS` | 30 |
| Free checks per person per day (User page) | `ATSLAB_DAILY_CHECKS` | 3 |
| "Needs review": a score below | `ATSLAB_REVIEW_SCORE` | 55 |
| "Needs review": any Critical issue | `ATSLAB_REVIEW_CRITICAL` | on |
| "Needs review": a missing email or phone | `ATSLAB_REVIEW_CONTACT` | on |
| "Get Premium" button link | `ATSLAB_PREMIUM_URL` | https://1000jobs.club |
| "Book a resume session" button link | `ATSLAB_BOOKING_URL` | https://1000jobs.club |
| "Go to 1000Jobs" link (top of the User page) | `ATSLAB_SITE_URL` | https://1000jobs.club |
| Ask for name and email before the result | `ATSLAB_COLLECT_LEADS` | off |
| Folder for the history database and resume files | `ATSLAB_DATA_DIR` | the `data` folder next to `app.py` |

The history is one file, `atslab.db`, in the data folder. The uploaded resumes are in its `resumes` folder. Resume
files older than the set number of days are deleted automatically. The score and the report stay in the history.
A link must start with `http://` or `https://` (anything else is refused). Changing a "Needs review" rule applies at
once to every check in the history, old ones too.

The same file keeps the **Activity log**: who signed in, checked a resume, marked one reviewed (with the note),
changed a setting (old and new value), deleted a record or exported a CSV, and when. **Delete record** (History)
asks first, then removes the report and the resume file for good; the deletion stays in the log.
**Export CSV** (History and Activity log) exports what the filters show (or the rows ticked in History).

A database made by an older version gets the new columns when the app starts; no row is lost.

## A clean start (empty History, Needs review, Activity log and daily counts)

`reset_data.py` empties the app's data and keeps the structure, the settings and the admin accounts:

```
py -3.12 reset_data.py              show what will go, ask, then clear it
py -3.12 reset_data.py --dry-run    only show it (nothing is deleted)
py -3.12 reset_data.py --yes        clear it without the question
py -3.12 reset_data.py --caches     also empty cv_reviews\ and dashboard_jobs\ (see below)
```

It removes every check (History, with its report), their notes and their "Reviewed by" (Needs review), the
Activity log, the daily check counts, the admin sign-in locks and every kept resume file. It keeps the tables
(the structure), the settings an admin saved (links, days, limits, the "Needs review" rules) and the admin
accounts (they come from the secrets). Nothing is written to the log, so it stays empty.

`cv_reviews\` (the saved AI reviews) and `dashboard_jobs\` (the saved job descriptions) hold text from real
users, so they are kept unless `--caches` is given. With `cv_reviews\` empty, the two slow reference tests
(`test_reference`, `test_strong`) need the AI key again, and with `dashboard_jobs\` empty one dashboard test
checks its resume without a job.

## Limits that protect the server

- **Daily checks:** each person has 3 free checks a day on the User page (the setting above). They are counted on
  the server, by browser (a cookie) and by IP address: when either one has used them up, the next check shows a
  friendly message. A check that ends with a message instead of a score is not counted. The Admin page has no limit.
  Behind a proxy (Nginx, Caddy, a cloud host) the IP address is the **last** address of `X-Forwarded-For`, the one
  your proxy saw, so the proxy must add it (Nginx: `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`).
  People who share one network (an office) share its IP address and so its 3 checks.
- **Queue:** at most 3 checks run at the same time (also from the Admin page). Others wait and see "N people ahead
  of you"; their check starts by itself.
- **Admin sign-in:** after 5 wrong tries for a name or from an IP address, that name or address waits one minute.
  This is counted on the server, so reloading the page does not reset it.
- **Uploads:** at most 10 MB (`.streamlit/config.toml`). A PDF is checked; a Word file gets "Please save your resume
  as a PDF"; a locked, damaged, empty, image-only, non-English or non-resume file gets a clear message, not a score.

---

## Option A: Streamlit Community Cloud

1. Put the code in a **private** GitHub repository.
   `.gitignore` keeps out the secrets, the test resumes, the history and the results. Check before the first push
   that no real resume is in the repository.
2. On https://share.streamlit.io click **Create app**, then:
   - Repository: your repository. Branch: `main`. Main file path: **`app.py`** (here `app.py` applies the
     Streamlit fix itself, on its first page).
   - **Advanced settings**: choose **Python 3.12**, then paste the contents of your `secrets.toml` into the
     **Secrets** box.
3. Click **Deploy**. The first start takes a few minutes, because it installs the packages and the AI model.
   - `requirements.txt` installs the Python packages.
   - `packages.txt` installs Chromium, which makes the PDF reports.
4. Your links are `https://YOUR-APP.streamlit.app/user` and `https://YOUR-APP.streamlit.app/admin`.

**Important:** on Streamlit Cloud the disk is not permanent. After a restart or a redeploy, the history and the kept
resume files are lost. Use Option B when the history must be kept.

To change a secret later: open the app's **Settings → Secrets**, edit, and save. The app restarts by itself.

## Option B: your own server with Docker

1. Copy the code folder to the server. It must include `Dockerfile` and `requirements.txt`.
2. Build the image once, and again after every code change:
   ```
   docker build -t atslab .
   ```
3. Put your secrets file on the server, for example `/srv/atslab/secrets.toml`.
4. Start the app:
   ```
   docker run -d --name atslab --restart unless-stopped -p 8501:8501 \
     -v atslab-data:/data \
     -v /srv/atslab/secrets.toml:/app/.streamlit/secrets.toml:ro \
     atslab
   ```
   - `-v atslab-data:/data` keeps the history and the resume files when the container is replaced.
   - Instead of the secrets file you can pass `-e OPENROUTER_API_KEY=... -e ATSLAB_ADMINS='{"Bader":"..."}'`.
5. Open `http://SERVER:8501/user` and `http://SERVER:8501/admin`.
   For a real address with **https**, put a web server in front (for example Nginx or Caddy) and forward to
   port 8501. It must also forward WebSockets.

Useful commands:
- `docker logs atslab`: see what the app prints.
- `docker restart atslab`: restart it.
- `docker stop atslab && docker rm atslab`: remove it. The history stays in the `atslab-data` volume.
- To update: build again (step 2), remove the old container, then run step 4 again.

## Option C: this Windows computer

- Double-click **1000Jobs ATS Lab** on the desktop. It starts the app and opens the **Admin** page.
  The User page is http://localhost:8501/user. Only this computer can open it (`--server.address 127.0.0.1`).
- **Stop ATS Lab** on the desktop stops it.
- The admin accounts are in `C:\ATSLab\.streamlit\secrets.toml`. The AI key comes from this computer's
  `OPENROUTER_API_KEY` environment variable.
- By hand: `py -3.12 run_app.py --server.address 127.0.0.1`
- The old one-page dashboard still works on its own: `py -3.12 -m streamlit run dashboard.py`

## Look: light and dark mode

The app follows the visitor's system setting (light or dark). The colors are in `.streamlit/config.toml`
(`[theme.light]`, `[theme.dark]`) and `lab_ui.py`; every text of the pages is in `lab_text.py`.

## Check that it works

- Open `/user`, upload a resume, and see the score.
- Open `/admin`, sign in, and click **History**: that check is listed as "User page".

## After changing any code: restart the app

`.streamlit/config.toml` sets `[server] fileWatcherType = "none"` (the watcher was turned off because it scanned every
loaded library on each page run, which made the pages slow and filled the log). The app therefore keeps the code it
loaded when the server started: **an edit to a .py file does not change the running app.**

- Stop the app (**Stop ATS Lab** on the desktop, or Ctrl+C in its terminal) and start it again the same way.
- Then reload the page in the browser.
- A page that behaves like the old version (for example the client comparison report showing the two files the wrong
  way round, or the two upload slots with no separate names) means the app is still running old code: restart it.

## Comparison reports saved before 2026-11-02 (the two files read the wrong way round)

A few client comparison reports saved before the role fix describe the 1000Jobs resume as the user's own resume: the
1000Jobs resume's own issues then appear under **Improved** and **Issues in the original resume**. Those reports were
written by the app while it ran the older code (see the restart note above); the code is fixed, the saved text is not.

```
py -3.12 fix_comparison_reports.py                 look only: which reports are affected (nothing is written)
py -3.12 fix_comparison_reports.py --apply          rebuild them from the files the app kept
py -3.12 fix_comparison_reports.py --apply --also "C:\folder"     also look there for the other file
```

Each rebuilt report is written to the History row again, and the old report is backed up first to
`.work/fixed_reports/backup-<id>.html`. Scores, dates and every other field of the row stay as they are. A report of a
check that was made with a job description is only listed (rebuilding it needs the job text): re-run that check in the
app.

## When the AI service is busy (the red box said "Keyword extraction failed")

OpenRouter sometimes answers `503 UNAVAILABLE` (provider busy) or does not answer at all. That is normal now and then.
Since 4 November 2026 the Lab handles it itself:

- The same model is asked again twice (waiting 2s, then 4s).
- If it still does not answer, the prompt goes to `google/gemini-2.5-flash-lite` instead
  (change it with the environment variable `ATSLAB_AI_FALLBACK_MODEL`).
- Only if both fail, the check stops with one plain sentence:
  *"The AI service is busy right now, so this job could not be read. Nothing was checked - press Run check again in a
  minute."*
- The provider's own answer (status, reason) is printed in the server log, where the team can read it, and is never
  shown in the app. A wrong API key or a model that does not exist is not retried.

So: **a red box about a busy AI means "press Run check again"** - nothing was scored and nothing was lost.

---

## ATS Checker 3 (the open-source checker) and keeping the app awake

### ATS Checker 3: what it is and its licence
`ATS Checker 3` is the third card of the Admin page's **Second opinion** section. It runs
[VeriWorkly ats-engine](https://github.com/VeriWorkly/ats-engine), an open-source resume checker that reads a
resume against a published rubric and prints a readiness score, a job-match score, the failed rules and the
missing keywords.

- **Licence: MIT.** It allows commercial and internal use, modification and redistribution, as long as the
  copyright notice and the licence text travel with the code. They are in `vendor/ats-engine/licence/`
  (`LICENSE` and `NOTICE`). No attribution is required in the user interface.
- **It runs on our own server.** The engine is a local command (`ats-engine check ... --json`). The Lab writes
  the already-extracted resume text to a temporary folder on the server, runs the command, reads the JSON and
  deletes the folder. No resume, text or screenshot leaves the machine. The only network use is the one-time
  `npm install` at build time.
- **It cannot change the ATS Lab score.** The card only reads the Lab's own numbers. If the engine is missing,
  crashes or times out, the card shows "Not installed on this server" or "Not available right now" and the
  Lab report is unchanged.
- **It only runs when the team presses its button.** Nothing runs on page load. It can be switched off in
  **Settings**.

### Switching it on
On this Windows computer the engine is kept in `vendor/ats-engine/` (the folder is ignored by git because it
holds the downloaded package). Install it once:

```
cd C:\ATSLab\vendor\ats-engine
npm install @veriworkly/ats-engine
```

In the Docker image the engine is installed during the build (`npm install -g @veriworkly/ats-engine`), and
Node 22 is copied into the image from the official `node:22-slim` image. Nothing else changes.

**Streamlit Community Cloud (no Node.js there).** The card is now called **VeriWorkly** and it sets itself up:
`requirements.txt` installs Node 24 from pip (`nodejs-wheel-binaries`, it carries `node` and `npm`), and on the first
visit the app runs `npm install` once, in the background, in `vendor/ats-engine` (`package.json` and
`package-lock.json` are in the repo; about 18 MB, about a minute). While it runs the card says "Setting up...";
if it fails the card says why (no Node, the npm install failed ...) and the ATS Lab works normally. The engine's
own PDF and DOCX readers (pdf-parse, pdfjs-dist, mammoth) are not installed: the Lab hands it the text it already
read from the PDF. Switch the card off or on in **Settings**. "ATS Checker 2" was replaced by this card (its code and
its setting stay, off by default).

If the engine is not installed, the third card says "Not installed on this server" and everything else works
normally. To use a different copy, set the environment variable `ATSLAB_ATS_ENGINE` to the full path of the
command.

### Benchmark table
Under the three cards the Admin page shows **Benchmark: the same resume, three checkers**: the ATS Lab score
and each card's number, its label, and how far it sits from the Lab. It is read-only and never changes the
score.

### Keeping the app awake on Streamlit Cloud (short term)
Streamlit Community Cloud puts an app to sleep after about 12 hours without a visitor. The workflow
`.github/workflows/keep-awake.yml` opens the app in a headless browser every 4 hours and clicks
"Yes, get this app back up!" when the sleep page appears (it also runs from the Actions tab with
**Run workflow**). It needs no account and no secret.

- The script is `.github/scripts/keep_awake.py`.
- Change the address with the `ATSLAB_URL` environment variable in the workflow.
- GitHub pauses scheduled workflows in a repository with no activity for 60 days; any push starts them again.
- Scheduled runs can be delayed at busy times (usually a few minutes).

### Moving to Render (long term: never sleeps, keeps the history)
Render runs the Docker image and does not sleep, so the keep-awake workflow is no longer needed. What is needed:

1. A **Web Service** from the GitHub repository, runtime **Docker**, branch `main`, using the existing
   `Dockerfile`. The image already contains Node 22, the open-source checker, Chromium and the meaning-match
   model.
2. A **paid instance with at least 2 GB of memory** (the model and Chromium need it). The free instance is too
   small and also sleeps.
3. The secrets as a **Secret File** named `secrets.toml`, mounted at `/etc/secrets/secrets.toml`.
   `run_app.py` copies it to `.streamlit/secrets.toml` before Streamlit starts. Nothing is printed.
4. A **persistent disk mounted at `/data`** (start with 1 GB) and the environment variable
   `ATSLAB_DATA_DIR=/data`, so the history, the resumes and the settings survive every deploy.
5. Environment variable `PORT=8501` and the health check path `/_stcore/health`.
6. **Auto-deploy** on every push to `main`.

After the first deploy, check `/user` and `/admin`, then make one check and restart the service: the check must
still be in the History. That proves the disk is mounted.
