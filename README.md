---
title: 1000Jobs ATS Lab
emoji: 🧭
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 8501
pinned: false
---

# 1000Jobs ATS Lab

The ATS Lab checks a resume the way an applicant tracking system reads it, then
shows the team what to fix and why. Two pages run in one container:

- `/user` — the public checker (upload a resume, get the score and the issues)
- `/admin` — the team's page (history, needs-review queue, activity log)

## Running it here (Hugging Face Spaces, Docker)

The Space builds the repository `Dockerfile` as-is. Nothing else is needed in the
image: the resume files, the history database and the secrets are deliberately
**not** in the repository and **not** in the image (see `.dockerignore`).

### Settings the Space needs

Add these in **Settings → Variables and secrets** (they are read as environment
variables, so no `secrets.toml` is needed on the server):

| Name | Kind | Value |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | secret | the AI key for the AI review and the job keywords |
| `ATSLAB_ADMINS` | secret | `{"Bader": "long-password", "Sara": "another-long-password"}` |
| `ATSLAB_DATA_DIR` | variable | `/data` |

`ATSLAB_ADMINS` is JSON: one entry per admin, the name is what the History shows
under "Checked by". Keep the passwords long. Nobody can open `/admin` until this
is set.

### Free Space limits to know

- The free CPU tier gives 16 GB RAM and 2 vCPU, which is enough for the meaning
  match model and the PDF rendering.
- The disk is **not** persistent on the free tier: the history database and the
  kept resume files reset when the Space restarts. Add persistent storage in the
  Space settings when the history must survive.
- The Space is **public** by default: the URL is open to anyone and the source is
  visible. Make it private (paid) before real client resumes are processed.

## Local use

    py -3.12 -m pip install -r requirements.txt
    py -3.12 run_app.py --server.port 8501 --server.headless true

Secrets for local use go in `.streamlit/secrets.toml` (copy `.streamlit/secrets.toml.example`).
That file is never committed. See `DEPLOY.md` for the Docker and server notes.
