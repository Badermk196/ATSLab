"""
ATS Checker 3: the open-source VeriWorkly ats-engine, run locally as a third opinion.

What it is
  https://github.com/VeriWorkly/ats-engine - an MIT-licensed resume checker that reads a resume the way
  an applicant tracking system does and scores it with a published rubric. It prints a readiness score
  (0-100), a job match score when a job description is given, every failed check with its fix, and the
  keywords the posting asks for that the resume never mentions.

Licence
  MIT. It allows commercial and internal use, modification and redistribution, as long as the copyright
  notice and the licence text are kept. NOTICE and LICENSE are copied into vendor/ats-engine/ so the
  notice travels with the code. No attribution is required in the app's user interface.

Privacy
  The engine runs as a local command on this machine. It makes no network call and keeps no state: the
  resume text is written to a temporary folder on this device, read by the command, and the folder is
  deleted. Nothing is sent to VeriWorkly or to any other server. The only network use is the one-time
  `npm install` that puts the command on the machine (see DEPLOY.md).

How it is called
  The Lab already extracts the resume text (pdfplumber), so this module hands the engine plain text
  (.txt) instead of the PDF. That avoids the optional PDF readers and keeps the same text the Lab scores.

Failure isolation
  `run()` never raises. If the command is not installed, Node is missing, the command times out or it
  prints something unexpected, the answer is a state the Admin page can draw ("not installed" or
  "not available right now") and the ATS Lab keeps working normally.

Pure functions only (no Streamlit), so the tests can call it without drawing a page.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import lab_node

# --- states -----------------------------------------------------------------------------------------
DONE = "done"                   # a number to show
FAILED = "failed"               # the command ran but could not answer
UNAVAILABLE = "unavailable"     # the command is not installed on this machine (or Node is missing)

# --- how the command is found -----------------------------------------------------------------------
# 1. ATSLAB_ATS_ENGINE  full path to the command (or a command with arguments), set in the environment
# 2. "ats-engine"       installed globally with: npm install -g @veriworkly/ats-engine
# 3. "npx"              the package is fetched on first use (needs network and a slow first run)
ENV_COMMAND = "ATSLAB_ATS_ENGINE"
NPM_PACKAGE = "@veriworkly/ats-engine"
TIMEOUT = 120                   # seconds; the engine reads a text resume in a few seconds
MAX_FAILED = 6                  # failed checks shown on the card, the costliest first
MAX_MISSING = 8                 # missing keywords shown on the card
HERE = os.path.dirname(os.path.abspath(__file__))
# The copy kept beside the app (vendor/ats-engine), installed once with:
#   npm install --prefix vendor/ats-engine @veriworkly/ats-engine
VENDOR = os.path.join(HERE, "vendor", "ats-engine", "node_modules", ".bin")

NAME = "VeriWorkly"
SUB = "Open-source checker"
UNIT = "Readiness score"
VERSION = "MIT licence"


def _split(command):
    """A command string -> the list subprocess needs. Quoted paths stay whole."""
    return [part.strip('"') for part in re.findall(r'"[^"]+"|\S+', command or "")]


def _windows():
    return os.name == "nt"


def command():
    """How to start the engine on this machine. -> list of arguments, or None when it is not installed.

    A command is only returned when it really exists: a missing command must read as "not installed",
    never as a crash."""
    configured = os.environ.get(ENV_COMMAND, "").strip()
    if configured:
        parts = _split(configured)
        if parts and (shutil.which(parts[0]) or os.path.isfile(parts[0])):
            return parts
    ours = lab_node.engine_command()                                   # node (the wheel's, or the PATH's) + the engine
    if ours:                                                           # installed once in vendor/ats-engine
        return ours
    names = (("ats-engine.cmd", "ats-engine.exe", "ats-engine") if _windows()
             else ("ats-engine",))
    for name in names:                                                  # the copy beside the app first
        path = os.path.join(VENDOR, name)
        if os.path.isfile(path):
            return [path]
    for name in names:
        path = shutil.which(name)
        if path:
            return [path]
    npx = shutil.which("npx")
    if npx:
        return [npx, "--yes", NPM_PACKAGE]
    return None


def available():
    """Whether the engine can run here. -> (bool, reason)
    reason: "installing" (the one-time npm install is running), "node_missing", "node_too_old", "npm_missing",
    "npm_install_failed", "npm_install_timeout" or "not_installed"."""
    lab_node.ensure()                                   # sets the engine up once, in the background (never in a test)
    if lab_node.engine_command() is not None:           # node + the engine in vendor/ats-engine
        return True, ""
    state = lab_node.status()
    if state["state"] == "installing":
        return False, "installing"
    if state["state"] == "failed":
        return False, state["why"] or "not_installed"
    if not shutil.which("node") and not os.environ.get(ENV_COMMAND):
        return False, "node_missing"
    if command() is None:
        return False, "not_installed"
    return True, ""


def _run(args, cwd):
    """Run the command and return its standard output. Raises on a timeout or a start failure."""
    kwargs = {"cwd": cwd, "capture_output": True, "timeout": TIMEOUT, "text": True,
              "encoding": "utf-8", "errors": "replace"}
    if _windows():
        # never open a console window on the server; the engine needs no shell
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(args, env=lab_node.env(), **kwargs)
    return proc.stdout or "", proc.stderr or "", proc.returncode


def _json_of(stdout):
    """The report the engine printed as JSON. The CLI may print a banner before it, so the first
    object that parses is taken."""
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None


def _num(value):
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def _failed(report):
    """The failed checks, the costliest first. -> [{"name", "why", "fix", "severity"}]"""
    rows = report.get("failedChecks") or report.get("failed_checks") or []
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        out.append({"name": str(row.get("id") or row.get("rule") or row.get("category") or "Check"),
                    "why": str(row.get("evidence") or "")[:240],
                    "fix": str(row.get("fix") or "")[:240],
                    "severity": str(row.get("severity") or ""),
                    "impact": _num(row.get("scoreImpact")) or 0})
    out.sort(key=lambda r: -r["impact"])
    return out[:MAX_FAILED]


def _missing(report):
    """The posting's words the resume never mentions, hard skills first."""
    words = report.get("missingKeywords") or report.get("missing_keywords") or []
    if not words:
        groups = report.get("missingKeywordGroups") or {}
        words = list(groups.get("hard") or []) + list(groups.get("soft") or [])
    return [str(w) for w in words][:MAX_MISSING]


def answer_of(report):
    """The engine's JSON report -> the answer the Admin page draws."""
    score = _num(report.get("readinessScore") or report.get("readiness_score"))
    if score is None:
        return {"state": FAILED, "why": "no_score"}
    job = _num(report.get("jobMatchScore") or report.get("job_match_score"))
    cats = report.get("categories") or {}
    weakest = []
    if isinstance(cats, dict):
        for name, row in cats.items():
            if isinstance(row, dict):
                value = _num(row.get("score"))
                if value is not None:
                    weakest.append((value, str(name)))
    weakest.sort()
    return {"state": DONE, "score": max(0, min(100, score)), "job_match": job,
            "checks": _failed(report), "missing": _missing(report),
            "n_checks": _num(report.get("checksPassed")), "n_total": _num(report.get("checksTotal")),
            "weakest": [name for _, name in weakest[:3]],
            "words": _num(report.get("wordCount"))}


def run(text, job_text=""):
    """Check one resume with the open-source engine. Never raises.

    text      the resume text the Lab already extracted
    job_text  the job description, or "" (then the engine gives a readiness score only)
    -> {"state": "done", "score", "job_match", "checks", "missing", ...}
       {"state": "unavailable" | "failed", "why"}"""
    text = (text or "").strip()
    if len(text) < 40:
        return {"state": FAILED, "why": "no_text"}
    ok, why = available()
    if not ok:
        return {"state": UNAVAILABLE, "why": why}
    args = command()
    folder = None
    try:
        folder = tempfile.mkdtemp(prefix="atslab_engine_")
        resume = os.path.join(folder, "resume.txt")
        with open(resume, "w", encoding="utf-8") as fh:
            fh.write(text)
        call = list(args) + ["check", resume, "--json"]
        job_text = (job_text or "").strip()
        if job_text:
            job = os.path.join(folder, "job.txt")
            with open(job, "w", encoding="utf-8") as fh:
                fh.write(job_text)
            call += ["--job", job]
        stdout, stderr, code = _run(call, folder)
        report = _json_of(stdout)
        if report is None:
            return {"state": FAILED, "why": "no_report", "exit": code,
                    "detail": (stderr or stdout or "")[:200]}
        answer = answer_of(report)
        answer["exit"] = code
        return answer
    except subprocess.TimeoutExpired:
        return {"state": FAILED, "why": "timeout"}
    except FileNotFoundError:
        return {"state": UNAVAILABLE, "why": "not_installed"}
    except Exception as e:                       # a checker never breaks the Lab
        return {"state": FAILED, "why": type(e).__name__}
    finally:
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
