"""
Second opinion: two independent ATS checkers shown next to the ATS Lab score on the Admin page.

They exist for comparison only. Nothing in this module can change the ATS Lab score or the Job match:
the Admin page reads the Lab's own numbers and this module only produces a second number to put
beside them. A checker that fails leaves the Lab working normally (the card says so and offers a retry).

Both checkers run on this device. No resume, no text and no screenshot leaves the computer:
  Resume Matcher   reads the job description's own words and measures how many of them the resume
                   carries. It also keeps the words it could not find, so the team can see what a
                   keyword-matching ATS would miss. Compared with the Lab's Job match score.
  ATS Checker 2    reads the extracted text and the page geometry and gives a general ATS score
                   (text layer, contact block, section headings, dates, columns, tables, length).
                   Compared with the Lab's main score.

Pure functions only (no Streamlit), so the cards can be tested without drawing a page. The page calls
`run(checker, res, ...)`, which never raises: a failure comes back as {"state": "failed", ...}.
"""

import re
from collections import Counter

import ATSLab_v3 as L
import cv_score as C

# --- the two checkers -------------------------------------------------------------------------------
# key -> name, sub-line, what it is compared with ("job_match" or "score"), and its short unit
CHECKERS = {
    "matcher": {"name": "Resume Matcher", "sub": "ATS score + keywords", "compares": "job_match",
                "unit": "Keyword match"},
    "checker2": {"name": "ATS Checker 2", "sub": "General score", "compares": "score",
                 "unit": "General score"},
}
ORDER = ("matcher", "checker2")

# --- states the card can be in ----------------------------------------------------------------------
EMPTY = "empty"                 # nothing checked yet: the card shows its button
CHECKING = "checking"           # a check is running
DONE = "done"                   # a number to show
FAILED = "failed"               # the checker could not answer: "Not available right now"
NEEDS_JOB = "needs_job"         # the checker needs a job description and there is none
OFF = "off"                     # switched off in Settings

# --- the score labels (the same six the Lab uses) ---------------------------------------------------
SCALE = ((90, "Excellent"), (80, "Strong"), (70, "Good"), (55, "Needs work"), (40, "At risk"), (0, "Not ready"))
AGREE_POINTS = 10               # "Agrees" when the two numbers are this close or closer
MAX_MISSING_SHOWN = 5           # the Resume Matcher card shows this many missing keywords

# Words that name a section rather than a skill: they say nothing about the fit.
SECTION_WORDS = {"responsibilities", "requirements", "qualifications", "preferred", "required", "duties",
                 "role", "position", "job", "company", "team", "candidate", "applicant", "benefits",
                 "salary", "location", "about", "description", "opportunity", "employer", "include",
                 "including", "etc", "plus", "must", "should", "would", "could", "will", "well",
                 "strong", "good", "great", "excellent", "ability", "able", "work", "working",
                 "years", "year", "month", "months", "day", "days", "time", "full", "part"}
MAX_KEYWORDS = 40


def label_for(score):
    """The six labels the Lab uses, from the number alone."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ""
    return next(lbl for low, lbl in SCALE if s >= low)


def difference(score, reference):
    """How a second opinion sits against the Lab's own number.
    -> {"word": "Agrees" | "Higher" | "Lower", "diff": score - reference,
        "text": "Agrees · 1 point lower" | "Higher · 12 points higher" | "Agrees"}
    "Agrees" when the two are within AGREE_POINTS of each other."""
    try:
        s, r = float(score), float(reference)
    except (TypeError, ValueError):
        return {"word": "", "diff": 0.0, "text": "", "agree": False}
    diff = s - r
    n = abs(round(diff))
    pts = "1 point" if n == 1 else f"{n} points"
    side = "higher" if diff > 0 else "lower"
    if abs(diff) <= AGREE_POINTS:
        return {"word": "Agrees", "diff": round(diff, 1), "agree": True,
                "text": "Agrees" if n == 0 else f"Agrees · {pts} {side}"}
    word = "Higher" if diff > 0 else "Lower"
    return {"word": word, "diff": round(diff, 1), "agree": False, "text": f"{word} · {pts} {side}"}


def reference_of(res, checker):
    """The Lab number this checker is compared with, from the result."""
    key = CHECKERS[checker]["compares"]
    if key == "job_match":
        return round((res.get("parts") or {}).get("job_match") or 0)
    return round(res.get("score") or 0)


def reference_text(res, checker):
    """The comparison as shown on the card: 'vs Lab Job match 82' / 'vs Lab score 84'."""
    ref = reference_of(res, checker)
    return (f"vs Lab Job match {ref}" if CHECKERS[checker]["compares"] == "job_match"
            else f"vs Lab score {ref}")


def finish(checker, res, answer):
    """A finished answer plus its comparison with the Lab's own number (read only: the score never changes).
    -> the same answer with "reference", "difference", "word" and "agree" added."""
    if answer.get("state") != DONE:
        return answer
    if answer.get("source") == "role":          # a general check has no Lab Job match to compare with
        return dict(answer, reference=None, difference="", word="", agree=None)
    ref = reference_of(res, checker)
    d = difference(answer.get("score"), ref)
    return dict(answer, reference=ref, difference=d["text"], word=d["word"], agree=d["agree"])


def top_missing(answer, limit=MAX_MISSING_SHOWN):
    """The job words the Resume Matcher could not find, the first `limit` of them."""
    return list(answer.get("missing") or [])[:limit]


# --- Resume Matcher: the job's own words, found in the resume --------------------------------------
def keywords_of(job_text, limit=MAX_KEYWORDS):
    """The job description's real words, most frequent first (one spelling per stem).
    No AI and no network: the same text always gives the same list."""
    keep = []
    for tok in L.tokens(job_text or ""):
        if len(tok) < 3 or tok.isdigit() or tok in L.STOPWORDS or tok in L.FILLER_WORDS \
                or tok in SECTION_WORDS:
            continue
        keep.append(tok)
    counts = Counter(L.stem(t) for t in keep)
    first = {}
    for tok in keep:
        first.setdefault(L.stem(tok), tok)
    ranked = sorted(first.items(), key=lambda kv: (-counts[kv[0]], kv[0]))
    return [first[stem] for stem, _ in ranked[:limit]]


def role_words(role, limit=MAX_KEYWORDS):
    """The skills a role is expected to have: the Lab's own role list (asked once per role, then kept in
    role_skills/). Raises cv_score.ScoreError when the list cannot be read (no key and nothing saved yet)."""
    info = C.role_skills(role)
    words = [w for w in (info.get("required_skills") or []) + (info.get("preferred_skills") or []) if w]
    return words[:limit]


def matcher_words(res, job_text, role=None):
    """What the Resume Matcher measures against. -> (words, source, role)

    With a job description: the job description's own words ("job"). Without one (a general check): the skills
    the resume's own target role is expected to have ("role"). ([], "role", role) when that list cannot be read."""
    words = keywords_of(job_text)
    if words:
        return words, "job", ""
    named = (role or res.get("target") or "").strip()
    if not named:
        return [], "job", ""
    try:
        return role_words(named), "role", named
    except Exception:                       # no key, and nothing saved for this role: the card says so
        return [], "role", named


def run_matcher(res, job_text, role=None):
    """The Resume Matcher's answer. -> {"score", "label", "keywords", "matched", "missing", "total",
    "n_matched", "pct", "source", "role"}   "source" says what it read: "job" or "role"."""
    words, source, named = matcher_words(res, job_text, role)
    if not words:
        return {"error": "no_job", "source": source, "role": named}
    text = ((res.get("_doc") or {}).get("modern") or "") + "\n" + str(res.get("cv") or "")
    matched = [w for w in words if L.contains(w, text)]
    missing = [w for w in words if w not in matched]
    pct = round(100 * len(matched) / len(words))
    return {"score": pct, "label": label_for(pct), "keywords": words, "matched": matched,
            "missing": missing, "total": len(words), "n_matched": len(matched), "pct": pct,
            "source": source, "role": named}


# --- ATS Checker 2: a general ATS score, read independently ----------------------------------------
def _checks(res):
    """The signals ATS Checker 2 reads, each with its weight and its plain reason.
    -> [(name, passed, weight, why)]"""
    doc = res.get("_doc") or {}
    text = doc.get("modern") or ""
    low = text.lower()
    layout = res.get("layout") or {}
    pages = layout.get("pages") or 1
    words = len(text.split())
    rows = doc.get("rows") or []
    findings = {f.get("id"): f for f in (layout.get("findings") or []) if isinstance(f, dict)}
    out = []

    def add(name, passed, weight, why):
        out.append((name, bool(passed), weight, why))

    add("Text layer", words >= 60, 14,
        "the page carries selectable text" if words >= 60 else "little or no selectable text")
    add("Contact block", bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)), 12,
        "an email address is in the text" if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
        else "no email address in the text")
    headings = sum(1 for r in rows if L.is_heading(r.get("text") or ""))
    add("Section headings", headings >= 3, 12, f"{headings} section heading(s)")
    dates = len(re.findall(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}\b", low))
    add("Dates as Mon YYYY", dates >= 2, 12, f"{dates} date(s) written as Mon YYYY")
    columns = bool(layout.get("columns_found")) or (layout.get("n_columns") or 1) > 1
    add("One column", not columns, 12, "a sidebar or two columns" if columns else "one column")
    add("Portrait page", not layout.get("landscape"), 8, "a landscape page" if layout.get("landscape")
        else "a portrait page")
    add("No printed code", not re.search(r"<[a-z][^>]{0,80}>", low), 8,
        "HTML or code printed as text" if re.search(r"<[a-z][^>]{0,80}>", low) else "no printed code")
    tables = "D5" in findings or "D6" in findings
    add("No tables", not tables, 8, "text inside a table" if tables else "no tables")
    add("Length", 250 <= words <= 1200, 8, f"{words} words")
    bullets = sum(1 for r in rows if re.match(r"^\s*[•\-\u2022·▪◦]", r.get("text") or ""))
    add("Bullets", bullets >= 6, 6, f"{bullets} bullet(s)")
    return out


def run_checker2(res):
    """ATS Checker 2's answer. -> {"score", "label", "checks": [{"name", "passed", "weight", "why"}],
    "failed": [names]}"""
    checks = _checks(res)
    total = sum(w for _, _, w, _ in checks)
    lost = sum(w for _, ok, w, _ in checks if not ok)
    score = max(0, round(100 * (total - lost) / total)) if total else 0
    return {"score": score, "label": label_for(score),
            "checks": [{"name": n, "passed": ok, "weight": w, "why": why} for n, ok, w, why in checks],
            "failed": [n for n, ok, _, _ in checks if not ok]}


# --- one entry point for the page ------------------------------------------------------------------
def run(checker, res, job_text="", settings=None):
    """Run one checker and never raise. -> {"state", "score", "label", "detail", "checked_at", ...}
    settings: {"matcher": bool, "checker2": bool} from the Admin page's saved settings."""
    settings = settings or {}
    if settings.get(checker) is False:
        return {"state": OFF}
    if checker == "matcher":
        try:
            out = run_matcher(res, job_text, res.get("target"))
        except Exception as e:                  # a checker never breaks the Lab
            return {"state": FAILED, "why": type(e).__name__}
        if out.get("error"):
            return {"state": NEEDS_JOB}
        return {"state": DONE, **out}
    if checker == "checker2":
        try:
            out = run_checker2(res)
        except Exception as e:
            return {"state": FAILED, "why": type(e).__name__}
        return {"state": DONE, **out}
    return {"state": FAILED, "why": "unknown checker"}


def headline(answers):
    """The line at the top right of the section, from the cards that have a number.
    -> 'Both checkers agree with the Lab' | '1 of 2 checkers agree with the Lab' | '' """
    done = [a for a in answers.values() if a and a.get("state") == DONE]
    judged = [a for a in done if a.get("agree") is not None]      # a general check's matcher: nothing to compare
    if not judged:
        return ""
    n = sum(1 for a in judged if a.get("agree"))
    if n == len(judged) == 2:
        return "Both checkers agree with the Lab"
    return f"{n} of {len(judged)} checker{'s' if len(judged) != 1 else ''} agree with the Lab"
