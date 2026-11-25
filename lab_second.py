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
import lab_third as E
import lab_lever as V

# --- the two checkers -------------------------------------------------------------------------------
# key -> name, sub-line, what it is compared with ("job_match" or "score"), and its short unit
CHECKERS = {
    "matcher": {"name": "Resume Matcher", "sub": "ATS score + keywords", "compares": "job_match",
                "unit": "Keyword match"},
    "checker2": {"name": "ATS Checker 2", "sub": "General score", "compares": "score",
                 "unit": "General score"},
    "engine": {"name": "VeriWorkly", "sub": "Open-source ATS checker", "compares": "score",
               "unit": "Readiness score"},   # with a job description: its Job match, against the Lab's Job match
    "lever": {"name": "LeverParser", "sub": "Open-source parser", "compares": "none",
              "unit": "Parse score"},
}
ORDER = ("matcher", "engine", "checker2", "lever")

# --- states the card can be in ----------------------------------------------------------------------
EMPTY = "empty"                 # nothing checked yet: the card shows its button
CHECKING = "checking"           # a check is running
DONE = "done"                   # a number to show
FAILED = "failed"               # the checker could not answer: "Not available right now"
UNAVAILABLE = "unavailable"     # the checker is not installed on this server
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


def compares_of(checker, answer=None):
    """What this checker's number is compared with: "job_match", "score" or "none". An answer can say it itself
    (VeriWorkly with a job description gives its Job match, so it is compared with the Lab's Job match)."""
    return (answer or {}).get("compares") or CHECKERS[checker]["compares"]


def reference_of(res, checker, answer=None):
    """The Lab number this checker is compared with, from the result."""
    key = compares_of(checker, answer)
    if key == "job_match":
        return round((res.get("parts") or {}).get("job_match") or 0)
    return round(res.get("score") or 0)


def reference_text(res, checker, answer=None):
    """The comparison as shown on the card: 'vs Lab Job match 82' / 'vs Lab score 84'."""
    ref = reference_of(res, checker, answer)
    return (f"vs Lab Job match {ref}" if compares_of(checker, answer) == "job_match"
            else f"vs Lab score {ref}")


def finish(checker, res, answer):
    """A finished answer plus its comparison with the Lab's own number (read only: the score never changes).
    -> the same answer with "reference", "difference", "word" and "agree" added."""
    if answer.get("state") != DONE:
        return answer
    if answer.get("source") in ("role", "skills", "lever"):
        # a general check has no Lab Job match to compare with, and a parse score is not an ATS score:
        # neither is put beside the Lab's number.
        return dict(answer, reference=None, difference="", word="", agree=None)
    ref = reference_of(res, checker, answer)
    d = difference(answer.get("score"), ref)
    return dict(answer, reference=ref, difference=d["text"], word=d["word"], agree=d["agree"])


def top_missing(answer, limit=MAX_MISSING_SHOWN):
    """The job words the Resume Matcher could not find, the first `limit` of them."""
    return list(answer.get("missing") or [])[:limit]


def stems_of(text):
    """Every stem in a text, once: the word set a word-by-word match is checked against."""
    return {L.stem(t) for t in L.tokens(text or "")}


def text_of(res):
    """The resume's own text, read from whichever copy the result carries.

    A saved result does not always keep _doc (the history table stores the score and the report, not the whole
    document), and the old code then fell back to res["cv"], which is the FILE NAME. That is how a checker could
    answer 0 for a resume that scored 46. The file name is never used as text."""
    doc = res.get("_doc") or {}
    if isinstance(doc, dict):
        for key in ("modern", "strict", "text", "clean"):
            part = doc.get(key)
            if isinstance(part, str) and part.strip():
                return part
        rows = doc.get("rows")
        if isinstance(rows, list):
            joined = "\n".join(str((r or {}).get("text") or "") for r in rows if isinstance(r, dict))
            if joined.strip():
                return joined
    for key in ("text", "cv_text", "plain"):
        part = res.get(key)
        if isinstance(part, str) and len(part.strip()) > 40:      # a real text, not a file name
            return part
    return ""


def skills_from_cv(res, limit=25):
    """The skills the resume itself lists: what a general check measures against when there is no job
    description and no known role. Read from the SKILLS section, else from the skills the Lab already found."""
    text = text_of(res)
    found = []
    if text:
        inside = False
        for line in text.splitlines():
            head = " ".join(line.split()).strip().lower()
            if head in ("skills", "core skills", "key skills", "technical skills", "skills & tools",
                        "skills and tools", "expertise", "core competencies", "skills summary"):
                inside = True
                continue
            if inside:
                if head and head.isupper() and len(head) > 3 and "," not in head:
                    break                                  # the next section started
                for part in re.split(r"[,|•·/;]", line):
                    part = " ".join(part.split()).strip(" -–—:")
                    if 2 <= len(part) <= 40:
                        found.append(part)
    if not found:
        for key in ("skills", "hard_skills"):
            value = res.get(key)
            if isinstance(value, (list, tuple)):
                found.extend(str(v) for v in value if str(v).strip())
    seen, out = set(), []
    for item in found:
        low = item.lower()
        if low not in seen:
            seen.add(low)
            out.append(item)
    return out[:limit]


SKILL_HEADS = ("skills", "core skills", "key skills", "skills & tools", "technical skills",
               "core competencies", "expertise", "skills summary")


def without_skills(text):
    """The resume text with its SKILLS block removed. Used when the skills list itself is what we measure:
    a skill only counts if the experience shows it, not because it is repeated in the list."""
    lines = text.splitlines()
    out, skipping = [], False
    for line in lines:
        stripped = line.strip()
        low = stripped.lower().rstrip(":")
        if low in SKILL_HEADS:
            skipping = True
            continue
        if skipping:
            if stripped and stripped.isupper() and len(stripped) < 40:      # the next section starts
                skipping = False
            else:
                continue
        out.append(line)
    return "\n".join(out)


def found(term, text, stems=None):
    """Word by word: a term counts when every one of its words is in the resume, in any order and not
    necessarily together ("team leadership" is found in "leading cross-functional teams"). A term that sits
    together still counts, as before, so nothing that matched before stops matching."""
    if L.contains(term, text):
        return True
    stems = stems if stems is not None else stems_of(text)
    words = [L.stem(w) for w in L.tokens(term)]
    return bool(words) and all(w in stems for w in words)


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

    Three levels, so the matcher works with and without a job description:
      1. a job description was given        -> the job's own words        ("job")
      2. no job, but the target role is known -> the role's expected skills ("role")
      3. no job and no role                 -> the skills the resume lists ("skills")
    ([], "none", "") only when there is nothing at all to measure against."""
    words = keywords_of(job_text)
    if words:
        return words, "job", ""
    named = (role or res.get("target") or "").strip()
    if named:
        try:
            words = role_words(named)
            if words:
                return words, "role", named
        except (Exception, SystemExit):      # no key, a wrong key or a role list that cannot be read:
            pass                             # fall through to the resume (a card never breaks the page)
    words = skills_from_cv(res)
    if words:
        return words, "skills", ""
    return [], "none", ""


def run_matcher(res, job_text, role=None):
    """The Resume Matcher's answer. -> {"score", "label", "keywords", "matched", "missing", "total",
    "n_matched", "pct", "source", "role"}   "source" says what it read: "job", "role" or "skills"."""
    text = text_of(res)
    if not text.strip():
        return {"error": "no_text", "source": "none", "role": ""}
    words, source, named = matcher_words(res, job_text, role)
    if not words:
        return {"error": "no_job", "source": source, "role": named}
    # when the words come from the resume's own skills list, measure them against the experience only:
    # otherwise a skill would always "match" because it is written in the list we just read.
    body = without_skills(text) if source == "skills" else text
    stems = stems_of(body)
    matched = [w for w in words if found(w, body, stems)]
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
    text = text_of(res)
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
    if not rows:                                  # a saved result has no rows: count the headings in the text
        headings = sum(1 for line in text.splitlines()
                       if line.strip() and line.strip().isupper() and 3 <= len(line.strip()) <= 40)
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
    if not rows:
        bullets = sum(1 for line in text.splitlines() if re.match(r"^\s*[•\-\u2022·▪◦]", line))
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
        except (Exception, SystemExit) as e:    # a checker never breaks the Lab (not even a stopped AI call)
            return {"state": FAILED, "why": type(e).__name__}
        if out.get("error") == "no_text":        # the saved result carries no text: say so, never answer 0
            return {"state": FAILED, "why": "no_text"}
        if out.get("error"):
            return {"state": NEEDS_JOB}
        return {"state": DONE, **out}
    if checker == "checker2":
        try:
            out = run_checker2(res)
        except (Exception, SystemExit) as e:    # a checker never breaks the Lab
            return {"state": FAILED, "why": type(e).__name__}
        return {"state": DONE, **out}
    if checker == "engine":
        try:
            out = E.run(text_of(res), job_text)
        except (Exception, SystemExit) as e:    # a checker never breaks the Lab
            return {"state": FAILED, "why": type(e).__name__}
        out["source"] = "engine"
        if out.get("state") == DONE and (job_text or "").strip() and out.get("job_match") is not None:
            # a job description was given: the number to compare is VeriWorkly's Job match, against the Lab's Job
            # match. Its readiness score stays on the card as a note.
            out["readiness"] = out.get("score")
            out["score"] = out["job_match"]
            out["label"] = label_for(out["score"])
            out["compares"] = "job_match"
        else:                                   # no job description: its readiness score against the Lab's score
            out["compares"] = "score"
        return out
    if checker == "lever":
        try:
            out = V.run(text_of(res))
        except (Exception, SystemExit) as e:    # a checker never breaks the Lab
            return {"state": FAILED, "why": type(e).__name__}
        return out
    return {"state": FAILED, "why": "unknown checker"}


def headline(answers):
    """The line at the top right of the section, from the cards that have a number.
    -> 'All 3 checkers agree with the Lab' | '2 of 3 checkers agree with the Lab' | '' """
    done = [a for a in answers.values() if a and a.get("state") == DONE]
    judged = [a for a in done if a.get("agree") is not None]      # a general check's matcher: nothing to compare
    if not judged:
        return ""
    n = sum(1 for a in judged if a.get("agree"))
    if n == len(judged) and len(judged) >= 2:
        return "Both checkers agree with the Lab" if len(judged) == 2 else f"All {len(judged)} checkers agree with the Lab"
    return f"{n} of {len(judged)} checker{'s' if len(judged) != 1 else ''} agree with the Lab"


def visible_order(lever_on=False, checker2_on=False):
    """The cards to draw: Resume Matcher and VeriWorkly. VeriWorkly is always drawn: when it cannot run here the card
    says why (setting up, Node missing ...), so a problem is seen, not hidden. ATS Checker 2 and LeverParser only when
    their settings are switched on (Settings > Second opinion; both off for now). Their code stays."""
    return tuple(c for c in ORDER if (c != "lever" or lever_on) and (c != "checker2" or checker2_on))
