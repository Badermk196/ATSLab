"""
Bug reports and the Bug audit page: the team reports a wrong result, the AI explains it, the team decides.

What it is
  An admin can report a bug on any report: a screenshot and one sentence. The screenshot, the sentence and the
  Lab's own result text (the score, the parts and the issue cards) go to the same AI model the Lab uses, which
  answers with a short explanation and a suggested fix. The team then Approve / Reject / Mark as fixed on the
  Bug audit page (Admin only).

Privacy
  The resume itself is NEVER sent: only the screenshot the team chose to upload, the one sentence, and the
  Lab's result text. This is the option the team chose (option A).

The AI never changes the score
  Nothing in this module can change the ATS Lab score, the Job match, a weight, a threshold or a gate. The AI
  only writes text for the team to read. A fix reaches a score only after the team approves it, applies it,
  adds the resume to the golden set as a test and the reference test passes - that checklist is recorded on
  the bug, and this module only reports it.

Screenshots
  A screenshot is kept while a bug is open. After the team sets it Fixed or Rejected it is kept for
  `bug_image_days` days (a setting, 30 by default) and then deleted: only the text stays. This is the only
  image the Lab stores in the database.

Pure functions for everything except `ask_ai` (one network call to the AI), so the tests can check the rules
without a network.
"""

import base64
import json
import os
import re
import time

MODEL = "google/gemini-2.5-flash"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = 90                        # seconds
MAX_IMAGE_MB = 6                    # a bigger screenshot is refused with a plain message
ALLOWED_TYPES = ("image/png", "image/jpeg", "image/jpg", "image/webp")

# --- the states of a bug report ----------------------------------------------------------------------
NEW = "new"                         # reported, nobody has decided yet
APPROVED = "approved"               # the team agrees it is a real bug
FIXED = "fixed"                     # the fix is in the code and the tests pass
REJECTED = "rejected"               # not a bug / not something we change
STATES = (NEW, APPROVED, FIXED, REJECTED)
CLOSED = (FIXED, REJECTED)          # the screenshot is kept `days` after these, then deleted

AREAS = ("scoring", "layout", "text", "ui", "other")

# --- the two kinds of feedback ---------------------------------------------------------------------------
KIND_BUG = "bug"                    # "The Lab got something wrong": a wrong result, works as it always did
KIND_MISSED = "missed"              # "The Lab missed a problem in the resume": a request for a new check
KINDS = (KIND_BUG, KIND_MISSED)
# An approved missed issue never changes a score: it only becomes a request for a new check, built separately.


def kind_of(bug):
    """The kind of a report. Reports saved before there were two kinds are Lab bugs."""
    return KIND_MISSED if (bug or {}).get("kind") == KIND_MISSED else KIND_BUG


def of_kind(bugs, kind):
    """The reports of one kind."""
    return [b for b in bugs or [] if kind_of(b) == kind]

# The steps the team must finish before an approved bug is allowed to affect any score.
FIX_STEPS = (
    ("fix", "The fix is applied to the code"),
    ("golden", "The resume is added to the golden set as a test"),
    ("reference", "The reference test passes with the fix"),
)
# a step name -> the column that records it (the page and this module share this one table)
STEP_COLUMNS = {"fix": "fixed_ok", "golden": "golden_added", "reference": "reference_passed"}


def new_count(bugs):
    """How many bugs nobody has decided yet: the number on the menu."""
    return sum(1 for b in bugs or [] if (b.get("state") or NEW) == NEW)


def find(bugs, state=None, search="", kind=None):
    """The bugs to show: one kind, one state, and/or a word that appears in the description, the resume name or
    the reporter. An empty filter shows everything."""
    out = of_kind(bugs, kind) if kind in KINDS else list(bugs or [])
    if state in STATES:
        out = [b for b in out if (b.get("state") or NEW) == state]
    word = (search or "").strip().lower()
    if word:
        out = [b for b in out
               if word in " ".join(str(b.get(k) or "") for k in
                                   ("description", "cv", "who", "target", "ai_explanation", "ai_fix",
                                    "note")).lower()]
    return out


def state_of(bug):
    state = (bug or {}).get("state") or NEW
    return state if state in STATES else NEW


def allowed_image(mime, size):
    """Whether this file can be stored. -> (bool, why)  `why` is "" when it is fine."""
    if (mime or "").lower() not in ALLOWED_TYPES:
        return False, "type"
    if not size:
        return False, "empty"
    if size > MAX_IMAGE_MB * 1024 * 1024:
        return False, "big"
    return True, ""


def _when(value):
    """A stored time as a datetime, or None."""
    if not value:
        return None
    if hasattr(value, "timetuple"):
        return value
    for shape in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return time.strptime(str(value)[:19], shape)
        except ValueError:
            continue
    return None


def keep_until(bug, days):
    """The day the screenshot may be deleted: the day the bug was closed plus `days`. None while it is open."""
    if state_of(bug) not in CLOSED:
        return None
    closed = _when(bug.get("state_when") or bug.get("created_at"))
    if closed is None:
        return None
    return time.strftime("%Y-%m-%d", time.localtime(time.mktime(closed) + int(days) * 86400))


def image_due(bug, days, now=None):
    """Whether this screenshot should be deleted now: the bug is closed and `days` have passed."""
    if state_of(bug) not in CLOSED:
        return False
    closed = _when(bug.get("state_when") or bug.get("created_at"))
    if closed is None:
        return False
    now = now or time.time()
    return (now - time.mktime(closed)) >= int(days) * 86400


def result_text(res):
    """The Lab's own result as text: what the AI is allowed to read. Never the resume itself."""
    res = res or {}
    parts = res.get("parts") or {}
    lines = [f"ATS Lab score: {res.get('score')} ({res.get('label') or ''})".strip()]
    if parts:
        lines.append("Parts: " + ", ".join(f"{k} {v}" for k, v in parts.items()))
    if res.get("target"):
        lines.append(f"Job: {res['target']}")
    issues = res.get("issues") or []
    for issue in issues[:25]:
        if not isinstance(issue, dict):
            continue
        name = issue.get("name") or issue.get("title") or ""
        why = " ".join(str(issue.get("why") or issue.get("detail") or "").split())[:200]
        lines.append(f"- [{issue.get('severity') or ''}] {name}: {why}".strip())
    if not issues:
        lines.append("No issues were listed.")
    return "\n".join(lines)[:6000]


PROMPT = """You help the 1000Jobs team fix their own resume checker (the "ATS Lab"). An admin reported a problem \
with one report.

What the ATS Lab produced (its own result text):
{result}

What the admin wrote (one sentence):
{description}

Look at the screenshot the admin attached.

Answer with JSON only, in simple English:
{{"explanation": "why this happened, at most 100 words",
  "fix": "exactly what to change (code, text or prompt), at most 100 words",
  "area": "one of: scoring, layout, text, ui, other",
  "score_change_needed": false,
  "lab_was_right": false}}

Rules:
- The Lab must stay strict. Never suggest hiding a real problem or lowering the score to make a report look better.
- If the Lab is right and the report is correct, say so plainly (lab_was_right = true) and suggest only a
  clearer wording.
- score_change_needed is true only when a rule or a weight really is wrong, and then the team must confirm it
  before anything changes.
"""


MISSED_PROMPT = """You help the 1000Jobs team improve their own resume checker (the "ATS Lab"). An admin says the Lab MISSED a problem in a resume: the Lab did not list it, but it should have.

What the ATS Lab produced (its own result text):
{result}

What the admin says the Lab should have caught (one sentence):
{description}

Look at the screenshot the admin attached. The resume file itself is not available to you.

Answer with JSON only, in simple English:
{{"real_problem": true,
  "why": "is it a real problem for a resume or an ATS, and why, at most 60 words",
  "how_common": "how common is this problem in resumes (rare, sometimes, common) and why, at most 40 words",
  "how_to_detect": "how the Lab could detect it from the resume text and layout: what to look for and where, at most 100 words",
  "area": "one of: scoring, layout, text, ui, other"}}

Rules:
- Be honest. If it is not a real problem (or only a style choice), say real_problem = false.
- The new check should first show a card with NO points. Never propose a change to a score, a weight or a gate.
- The Lab must stay strict. Never suggest hiding a real problem.
"""


def _json_of(text):
    """The first JSON object in an answer, however the model wrapped it."""
    if not text:
        return None
    cleaned = re.sub(r"```json|```", "", str(text))
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        out = json.loads(cleaned[start:end + 1])
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def _clean(value, limit=600):
    return " ".join(str(value or "").split())[:limit]


def missed_answer(out):
    """The AI's answer about a missed issue as the two texts the page stores: explanation (is it a real problem and
    how common) and fix (how the Lab could detect it)."""
    real = out.get("real_problem")
    real = real if isinstance(real, bool) else str(real).strip().lower() in ("true", "yes")
    why = _clean(out.get("why"), 400)
    common = _clean(out.get("how_common"), 300)
    head = "Real resume problem: yes." if real else "Real resume problem: probably not."
    return {"explanation": " ".join(p for p in (head, why, f"How common: {common}" if common else "") if p),
            "fix": _clean(out.get("how_to_detect"), 700), "real_problem": real}


def ask_ai(image_bytes, mime, description, result, model=MODEL, timeout=TIMEOUT, kind=KIND_BUG):
    """Send the screenshot, the sentence and the Lab's result text to the AI.

    -> {"explanation", "fix", "area", "score_change_needed", "lab_was_right", "model", "seconds"}
       (a missed issue: explanation = is it a real problem and how common, fix = how the Lab could detect it)
       {"error": "no_key" | "no_image" | "http" | "bad_answer" | a network error name, "why": short detail}

    Never raises: a failure is a value the page can show."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return {"error": "no_key", "why": "the AI key is not set on this server"}
    if not image_bytes:
        return {"error": "no_image", "why": "no screenshot was given"}
    prompt = (MISSED_PROMPT if kind == KIND_MISSED else PROMPT).format(result=_clean(result, 6000),
                                                                        description=_clean(description, 400))
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": f"data:{mime or 'image/png'};base64,"
                                  f"{base64.b64encode(image_bytes).decode('ascii')}"}},
        ]}],
    }
    started = time.time()
    try:
        import requests
        answer = requests.post(ENDPOINT, headers={"Authorization": f"Bearer {key}"}, json=payload, timeout=timeout)
    except Exception as exc:                       # a timeout, no line, a DNS hiccup
        return {"error": type(exc).__name__, "why": "the AI could not be reached"}
    if answer.status_code != 200:
        return {"error": "http", "why": f"status {answer.status_code}"}
    try:
        body = answer.json()
    except ValueError:
        return {"error": "bad_answer", "why": "the answer was not JSON"}
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {"error": "bad_answer", "why": "the answer had no text"}
    out = _json_of(content)
    if not out:
        return {"error": "bad_answer", "why": "the answer was not the expected JSON"}
    if kind == KIND_MISSED:
        return dict(missed_answer(out), area=_clean(out.get("area"), 20).lower(), score_change_needed=False,
                    lab_was_right=False, model=model, seconds=round(time.time() - started, 1))
    return {"explanation": _clean(out.get("explanation")), "fix": _clean(out.get("fix")),
            "area": _clean(out.get("area"), 20).lower(), "score_change_needed": bool(out.get("score_change_needed")),
            "lab_was_right": bool(out.get("lab_was_right")), "model": model,
            "seconds": round(time.time() - started, 1)}


def checklist(bug):
    """The steps recorded on the bug before a fix is allowed to affect any score. -> [(label, done)]"""
    bug = bug or {}
    return [(label, bool(bug.get(STEP_COLUMNS.get(step, step)))) for step, label in FIX_STEPS]


def ready_for_score(bug):
    """Whether every step is recorded: only then may a fix change a score."""
    return all(done for _, done in checklist(bug))


def summary(bugs, kind=None):
    """A short line for the page: how many bugs in each state (of one kind when given)."""
    counts = {state: 0 for state in STATES}
    for bug in (of_kind(bugs, kind) if kind in KINDS else bugs) or []:
        counts[state_of(bug)] += 1
    return counts
