"""
ATS Checker 4: LeverParser, an open-source resume parser, run locally as a fourth opinion.

What it is
  The PyPI package `leverparser` (https://github.com/wespiper/leverparser), MIT licence, version 0.1.0.
  It reads a resume and returns structured fields: name, email, phone, LinkedIn, GitHub, address, each job
  with its title, company and dates, education and skills. It is a PARSER, not a scorer: it says what it
  could read, which is what an ATS does first. That is why its number is a "parse score", not an ATS score.

Packaging quirk worth knowing
  `pip install leverparser` installs a package whose IMPORT NAME is `pyresume` (`import leverparser` fails).
  This module imports `pyresume` and treats a missing import as "not installed on this server", never as a
  crash, so the Lab works normally without it.

Privacy
  The library runs in this Python process and makes no network call. It reads the text the Lab already
  extracted (pdfplumber), so the same text the Lab scores is the text this checker reads. Nothing is sent
  anywhere.

Failure isolation
  `run()` never raises. No text -> "failed / no_text"; package missing -> "unavailable / not_installed";
  anything unexpected -> "failed" with the exception name. The ATS Lab keeps working in every case.

Never changes the score
  Nothing in this module can change the ATS Lab score or the Job match. It only produces its own number for
  comparison on the Admin page.

Pure functions only (no Streamlit), so the tests can call it without drawing a page.
"""

import re
import time

# --- states (the same words lab_second.py uses) ------------------------------------------------------
DONE = "done"                   # a number to show
FAILED = "failed"               # the parser ran but could not answer
UNAVAILABLE = "unavailable"     # the package is not installed on this machine

# --- what one field looks like ------------------------------------------------------------------------
READ = "read"                   # the parser returned it
MISSED = "missed"               # the resume clearly has it and the parser did not return it
UNCLEAR = "unclear"             # the parser returned something that is not in the resume text

NAME = "LeverParser"
SUB = "Open-source parser"
UNIT = "Parse score"
VERSION = "MIT licence - leverparser 0.1.0 (pyresume)"
VENDOR = "pip install leverparser"

MAX_JOBS = 6                    # jobs listed on the card
MAX_SKILLS = 12                 # skills listed on the card
MIN_TEXT = 40                   # fewer characters than this is not a resume
MAX_FIELD = 70                  # a long field is trimmed: the card must stay readable

# The parse score is NOT an ATS score, so it gets its own words: how much of the resume this parser could
# read. Calling it "Strong" would say something about the resume, which this checker does not measure.
PARSE_SCALE = ((90, "Reads almost everything"), (75, "Reads most fields"), (55, "Reads some fields"),
               (0, "Reads little"))

try:
    import pyresume as _pyresume
except Exception:               # a missing (or broken) package must never stop the Lab
    _pyresume = None

_PARSER = None

# --- what a resume is expected to carry, read from the text itself ------------------------------------
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
LINKEDIN_RE = re.compile(r"linkedin\.com/(in/)?[\w\-%.]+", re.I)
DATE_RANGE_RE = re.compile(r"\b(?:19|20)\d{2}\s*[-–—]\s*(?:(?:19|20)\d{2}|present|current|now|today)\b", re.I)
# "Sep 2013" / "Sept. 2013": a resume that uses month-year dates has job dates even when no two years sit
# side by side ("Sep 2013 - Jun 2016" is written month first).
MONTH_YEAR_RE = re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?:19|20)\d{2}\b",
                           re.I)
EDU_RE = re.compile(r"\b(?:education|university|college|bachelor|master|mba|b\.?sc|m\.?sc|phd|diploma|degree)\b",
                    re.I)
SKILLS_RE = re.compile(r"\bskills?\b", re.I)
PHONE_RE = re.compile(r"\d[\d\s().+-]{6,}\d")


def available():
    """Whether the parser can run here. -> (bool, reason)"""
    if _pyresume is None:
        return False, "not_installed"
    return True, ""


def parser():
    """The parser object, built once (building it again for every check is wasted work)."""
    global _PARSER
    if _PARSER is None:
        _PARSER = _pyresume.ResumeParser()
    return _PARSER


def digits(value):
    """Only the digits of a value, for comparing a phone number with the text."""
    return re.sub(r"\D", "", value or "")


def phone_in(text):
    """Whether the text carries a phone number. A date range ("2022 - 2024") has the same shape as a short
    number, so a run of digits only counts when it has at least nine of them."""
    for match in PHONE_RE.finditer(text or ""):
        if len(digits(match.group())) >= 9:
            return True
    return False


def expected(text):
    """Which fields this resume clearly carries, judged from the text the Lab already read.
    A field that is not expected can never be marked as "missed"."""
    text = text or ""
    low = text.lower()
    dated = bool(DATE_RANGE_RE.search(text)) or len(MONTH_YEAR_RE.findall(text)) >= 2
    return {
        "name": len(text.split()) >= 2,
        "email": bool(EMAIL_RE.search(text)),
        "phone": phone_in(text),
        "linkedin": bool(LINKEDIN_RE.search(text)) or "linkedin" in low,
        "jobs": dated,
        "job_dates": dated,
        "education": bool(EDU_RE.search(text)),
        "skills": bool(SKILLS_RE.search(text)),
    }


def _state(wanted, found, sure=True):
    """One field's state. A field nobody expects is not a miss."""
    if found:
        return READ if sure else UNCLEAR
    return MISSED if wanted else READ


def _text_of(value):
    """A date or a string as a short readable label."""
    if value in (None, ""):
        return ""
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%b %Y")
        except Exception:
            return str(value)
    return str(value).strip()


def _pair(value):
    """A returned title or company, cleaned of the separator the parser sometimes leaves in."""
    text = " ".join(str(value or "").split()).strip(" -–—|,")
    return text[:MAX_FIELD] + "..." if len(text) > MAX_FIELD else text


def job_row(job):
    """One job as the card shows it: title, company and the dates it read."""
    start, end = _text_of(getattr(job, "start_date", None)), _text_of(getattr(job, "end_date", None))
    dates = " - ".join(part for part in (start, end) if part)
    return {"title": _pair(getattr(job, "title", None)), "company": _pair(getattr(job, "company", None)),
            "dates": dates, "location": _pair(getattr(job, "location", None))}


def field_rows(resume, text):
    """Every field the card checks, in order, with what the parser read and its state.
    -> [{"key", "label", "state", "value", "why"}]"""
    contact = getattr(resume, "contact_info", None)
    read = {
        "name": (getattr(contact, "name", None) or "").strip(),
        "email": (getattr(contact, "email", None) or "").strip(),
        "phone": str(getattr(contact, "phone", None) or "").strip(),
        "linkedin": (getattr(contact, "linkedin", None) or "").strip(),
    }
    jobs = list(getattr(resume, "experience", None) or [])
    education = list(getattr(resume, "education", None) or [])
    skills = list(getattr(resume, "skills", None) or [])
    dated = [j for j in jobs if _text_of(getattr(j, "start_date", None)) or _text_of(getattr(j, "end_date", None))]
    want = expected(text)
    text_digits = digits(text)
    # The parser sometimes invents a country code (a UAE number read as "+1 971-..."). A phone that does
    # not appear in the resume's own text is reported as unclear, never as read.
    phone_sure = bool(read["phone"]) and digits(read["phone"])[-6:] in text_digits if read["phone"] else True
    rows = [
        ("name", "Name", read["name"], bool(read["name"]), True, want["name"]),
        ("email", "Email", read["email"], bool(read["email"]), True, want["email"]),
        ("phone", "Phone", read["phone"], bool(read["phone"]), phone_sure, want["phone"]),
        ("linkedin", "LinkedIn", read["linkedin"], bool(read["linkedin"]), True, want["linkedin"]),
        ("jobs", "Jobs", f"{len(jobs)} job(s)", bool(jobs), True, want["jobs"]),
        ("job_dates", "Job dates", f"{len(dated)} with dates", bool(dated), True, want["job_dates"]),
        ("education", "Education", f"{len(education)} entry(ies)", bool(education), True, want["education"]),
        ("skills", "Skills", f"{len(skills)} skill(s)", bool(skills), True, want["skills"]),
    ]
    out = []
    for key, label, value, found, sure, wanted in rows:
        state = _state(wanted, found, sure)
        why = {"read": "read", "missed": "not read, and the resume has it",
               "unclear": "read, but this value is not in the resume text"}[state]
        out.append({"key": key, "label": label, "state": state, "value": value if found else "", "why": why})
    return out


def parse_score(rows):
    """A simple parse score: the share of the fields it read (0-100). A field it read but that is not in the
    resume counts half; a field it missed counts nothing."""
    if not rows:
        return 0
    points = sum(1.0 if r["state"] == READ else 0.5 if r["state"] == UNCLEAR else 0.0 for r in rows)
    return round(100 * points / len(rows))


def parse_label(score):
    """The words beside the parse score (not the Lab's six score labels: see PARSE_SCALE)."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ""
    return next(lbl for low, lbl in PARSE_SCALE if s >= low)


def answer_of(resume, text, seconds=None):
    """The parser's answer -> what the Admin page draws."""
    rows = field_rows(resume, text)
    jobs = [job_row(j) for j in (getattr(resume, "experience", None) or [])]
    education = [{"degree": _pair(getattr(e, "degree", None)),
                  "institution": _pair(getattr(e, "institution", None)),
                  "year": _text_of(getattr(e, "graduation_date", None))}
                 for e in (getattr(resume, "education", None) or [])]
    skills = [_pair(getattr(s, "name", s)) for s in (getattr(resume, "skills", None) or [])]
    years = None
    if hasattr(resume, "get_years_experience"):
        try:
            years = resume.get_years_experience()
        except Exception:
            years = None
    score = parse_score(rows)
    out = {"state": DONE, "score": score, "label": parse_label(score), "source": "lever",
           "fields": rows, "jobs": jobs[:MAX_JOBS], "n_jobs": len(jobs),
           "education": education, "skills": skills[:MAX_SKILLS], "n_skills": len(skills),
           "years": years,
           "missed": [r["label"] for r in rows if r["state"] == MISSED],
           "unclear": [r["label"] for r in rows if r["state"] == UNCLEAR]}
    if seconds is not None:
        out["seconds"] = seconds
    return out


def run(text, job_text=""):
    """Read one resume with LeverParser. Never raises.

    text      the resume text the Lab already extracted (the parser is a text parser: no file is needed)
    job_text  unused: this checker parses a resume and does not compare it with a job description
    -> {"state": "done", "score", "fields", "jobs", "education", "skills", ...}
       {"state": "unavailable" | "failed", "why"}"""
    text = (text or "").strip()
    if len(text) < MIN_TEXT:
        return {"state": FAILED, "why": "no_text"}
    ok, why = available()
    if not ok:
        return {"state": UNAVAILABLE, "why": why}
    started = time.time()
    try:
        resume = parser().parse_text(text)
        return answer_of(resume, text, round(time.time() - started, 1))
    except Exception as e:                       # a checker never breaks the Lab
        return {"state": FAILED, "why": type(e).__name__}
