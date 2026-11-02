"""
1000Jobs ATS LAB v3  -  UAE ATS profiles: Greenhouse, Workday, Oracle
=====================================================================

Scores CVs (PDF) against their job descriptions, lists every known bug (B1-B11),
and explains what would raise the score.

  READABLE  - can the ATS parser read it?
  FINDABLE  - would a recruiter's keyword search find it?
  MATCHED   - how well does it fit the job?

  Base    = R^0.3 x F^0.3 x M^0.4      (weakest part limits the total)
  Penalty = fixed points for bugs that have no check of their own (cap 40)
  Gates   = honesty fail -> 0, no email AND no phone -> max 40, <30% required skills -> max 50
  Overall = average of Greenhouse, Workday, Oracle

USAGE (PowerShell, inside C:\\ATSLab)
-------------------------------------
  py -3.12 -m pip install pdfplumber requests sentence-transformers
  python ATSLab_v3.py --cvdir CVS --jobdir JobDe --model google/gemini-2.5-flash
  python ATSLab_v3.py --cv CVS\\Name.pdf --job JobDe\\Name.txt --model google/gemini-2.5-flash
  python -m unittest test_ATSLab_v3 -v

Job keywords are saved as JobDe\\Name_keywords_v3.json (the v2 _keywords.json files are not touched).
Outputs: a report per CV on screen, results_v3.json (everything, for the dashboard) and results_v3.csv.
"""

import argparse
import bisect
import copy
import csv
import glob
import json
import math
import os
import re
import sys
from datetime import date

import pdfplumber

import cv_cache

LAB_VERSION = "v3"
TODAY = date.today()

ATS_PROFILES = {
    "greenhouse": {"strict_parser": False, "variant_credit": 0.8, "standard_headings": False, "date_weight": 1.0},
    "workday":    {"strict_parser": True,  "variant_credit": 0.8, "standard_headings": True,  "date_weight": 2.0},
    "oracle":     {"strict_parser": True,  "variant_credit": 0.5, "standard_headings": True,  "date_weight": 1.5},
}
STRICT_ATS = ("workday", "oracle")

PART_EXP = {"R": 0.3, "F": 0.3, "M": 0.4}
PART_FLOOR = 0.01
TYPE_WEIGHT = {"required": 3.0, "preferred": 1.5, "soft": 0.5}
ABBR_CREDIT = 0.5
OLD_LOCATION = 0.8          # keyword only in summary / old jobs / other sections
RECENT_YEARS = 5
SENIOR_YEARS = 10          # 10+ years of experience: no graduation year needed (R8)
SEVERITY_PENALTY = {"Critical": 15, "Major": 8, "Minor": 3}
PENALTY_CAP = 40
CAP_NO_CONTACT = 40
CAP_LOW_REQUIRED = 50
LOW_REQUIRED = 0.30
SCALE = [(90, "Excellent"), (80, "Strong"), (70, "Good"), (55, "Needs work"), (40, "At risk"), (0, "Not ready")]
BADGE = {"readable": 85, "findable": 70, "matched": 65, "total": 80, "required": 0.70}
STATUS_RANK = {"Now": 0, "Later": 1, "On hold": 2}

STANDARD_HEADING_WORDS = [
    "summary", "profile", "objective", "experience", "employment", "work history", "education",
    "skills", "certification", "certificate", "license", "language", "project", "award",
    "achievement", "publication", "volunteer", "interest", "reference", "training", "competenc",
    "course", "contact", "honor", "activities", "conference", "additional information",
]
SECTION_KINDS = [  # first match wins
    ("glance", r"at a glance|career impact|key metrics|highlights"),
    ("achievements", r"achievement|accomplishment"),
    ("skills", r"skill|technolog|tools"),
    ("competencies", r"competenc|expertise|strengths"),
    ("experience", r"experience|employment|work history|career history"),
    ("education", r"education|academic|qualification"),
    ("certifications", r"certif|licen|course|training"),
    ("projects", r"project"),
    ("summary", r"summary|profile|objective|about"),
    ("languages", r"language"),
]
CORE_SECTIONS = {"summary": ("summary",), "experience": ("experience",),
                 "education": ("education",), "skills": ("skills", "competencies")}

ABBREVIATIONS = {
    "llm": "large language model", "llms": "large language models",
    "nlp": "natural language processing", "ml": "machine learning",
    "ai": "artificial intelligence", "seo": "search engine optimization",
    "crm": "customer relationship management", "kpi": "key performance indicator",
    "kpis": "key performance indicators", "etl": "extract transform load",
    "ui": "user interface", "ux": "user experience", "qa": "quality assurance",
    "hr": "human resources", "pmo": "project management office", "cv": "computer vision",
    "api": "application programming interface", "sem": "search engine marketing",
    "ppc": "pay per click", "gtm": "go to market", "b2b": "business to business",
    "saas": "software as a service", "erp": "enterprise resource planning",
}

DEGREE_RANK = {"none": 0, "diploma": 1, "bachelor": 2, "master": 3, "phd": 4}
DEGREE_PATTERNS = [
    ("phd", r"\b(ph\.?d|doctorate)\b"),
    ("master", r"\b(master'?s?|m\.?sc|mba|m\.?eng|m\.?a\.)\b"),
    ("bachelor", r"\b(bachelor'?s?|b\.?sc|b\.?tech|b\.?eng|b\.?a\.|bba|b\.?com)\b"),
    ("diploma", r"\b(diploma)\b"),
]

# Dates. "to" only counts as a dash between two real dates, and at least one side
# must carry a month or Present (so prose like "from 2019 to 2021" is not a job range).
MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
YEAR = r"(?:19|20)\d{2}"
POINT = rf"(?:{MONTH}\s*{YEAR}|\d{{1,2}}/{YEAR}|{YEAR})"
END_WORD = r"(?:present|current|now|today)"
RANGE_RE = re.compile(rf"(?P<a>{POINT})(?P<sep>\s*[-\u2013\u2014]+\s*|\s+to\s+)(?P<b>{POINT}|{END_WORD})\b", re.I)
POINT_RE = re.compile(rf"\b{POINT}\b", re.I)
DURATION_RE = re.compile(r"\b(\d+)\s*(years?|yrs?|months?|mos?)\b", re.I)
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

WATERMARK_RE = re.compile(r"prepared with 1000jobs", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"(\+?\d[\d\s\-()]{7,}\d)")
SPACED_RE = re.compile(r"(?:\b[A-Za-z]\s){4,}[A-Za-z]")
CELL_GAP = 20      # points between words that mean "new column"
TEMPLATE_PHRASES = ["equally comfortable", "senior business operations leader", "running the room"]
SHARED_MIN_WORDS = 10     # B13: this many words in a row also found in another user's CV = leaked text
PLACEHOLDER_RE = re.compile(r"\b(not specified|date not specified|tbd|lorem ipsum)\b", re.I)
HTML_RE = re.compile(r"<\s*/?\s*(span|div|br|p|b|i|strong)\b[^>]*>", re.I)


# ---------------------------------------------------------------------------
# PDF -> text + rows (rows keep column cells, found from gaps between words)
# ---------------------------------------------------------------------------
def page_rows(page, pno):
    words = sorted(page.extract_words(x_tolerance=3), key=lambda w: (round(w["top"]), w["x0"]))
    by_y = sorted((((c["top"] + c["bottom"]) / 2, c) for c in page.chars), key=lambda t: t[0])
    mids = [m for m, _ in by_y]
    groups = []
    for w in words:
        if groups and abs(w["top"] - groups[-1][0]["top"]) <= 3:
            groups[-1].append(w)
        else:
            groups.append([w])
    rows = []
    for g in groups:
        g.sort(key=lambda w: w["x0"])
        cells, cur = [], [g[0]]
        for prev, w in zip(g, g[1:]):
            if w["x0"] - prev["x1"] > CELL_GAP:
                cells.append(cur)
                cur = [w]
            else:
                cur.append(w)
        cells.append(cur)
        texts = [" ".join(w["text"] for w in c) for c in cells]
        # where the line sits on the page and its font (used to join a line that wraps onto the next one)
        x0, x1 = min(w["x0"] for w in g), max(w["x1"] for w in g)
        top, bottom = min(w["top"] for w in g), max(w["bottom"] for w in g)
        lo, hi = bisect.bisect_left(mids, top - 1), bisect.bisect_right(mids, bottom + 1)
        used = {}
        for _, ch in by_y[lo:hi]:
            if x0 - 1 <= (ch["x0"] + ch["x1"]) / 2 <= x1 + 1:
                key = (ch.get("fontname"), round(ch.get("size", 0), 1))
                used[key] = used.get(key, 0) + 1
        font, size = max(used, key=used.get) if used else (None, None)
        rows.append({"page": pno, "text": " ".join(texts), "cells": texts, "x0": x0, "x1": x1, "top": top,
                     "bottom": bottom, "font": font, "size": size})
    return rows


def extract_cv(pdf_path, pages=None):
    """The CV text and rows. pages: only these page numbers (0-based), e.g. the text version of a two-version file.
    Kept by the file's fingerprint (cv_cache): the same file is read once."""
    return cv_cache.cached("text", pdf_path, (None if pages is None else tuple(sorted(pages)),),
                           lambda: _extract_cv(pdf_path, pages))


def _extract_cv(pdf_path, pages=None):
    strict, modern, rows = [], [], []
    with cv_cache.open_pdf(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages):
            if pages is not None and pno not in pages:
                continue
            strict.append(page.extract_text(x_tolerance=1) or "")   # like Workday / Oracle parsers
            modern.append(page.extract_text(x_tolerance=3) or "")   # like Greenhouse
            rows += page_rows(page, pno)
    return {"strict": "\n".join(strict), "modern": "\n".join(modern), "rows": rows}


def lines_of(text):
    return [l.strip() for l in text.splitlines() if l.strip()]


def spaced_lines(text):
    return [l for l in lines_of(text) if len(l) <= 70 and SPACED_RE.search(l)]


# Normal-case headings a fixed template may use ("Professional Experience", "Skills"). Whole line must match.
HEADING_VOCAB = re.compile(
    r"(professional |executive |career |personal )?(summary|profile|objective)"
    r"|(professional |work |relevant )?experience|(employment|work|career) history"
    r"|education( (&|and) training)?|(technical |key |core )?skills( (&|and) (tools|expertise))?"
    r"|core competencies|certifications?( (&|and) licenses)?|licenses|languages|projects"
    r"|(key |select |selected )?achievements|awards|publications|volunteering|interests|references|training|courses"
    r"|additional information",
    re.I)


def is_heading(line):
    line = line.strip()
    if HEADING_VOCAB.fullmatch(line.rstrip(":")):
        return True
    parts = [p for p in re.split(r"\s*\|\s*", line) if p.strip()]
    if len(parts) >= 2 and all(len(p.split()) >= 2 for p in parts):
        return False                                      # 'AREA ONE | AREA TWO' under the name: a headline
    return (len(line) <= 70 and len(line.split()) <= 9 and line.isupper()
            and re.search(r"[A-Z]{2}", line.replace(" ", "")) is not None and not re.search(r"[@\d]", line))


def section_kind(title):
    low = title.lower()
    return next((k for k, pat in SECTION_KINDS if re.search(pat, low)), "other")


# The headline: the 1-2 lines right under the name, before the contact line ('MEDIA & MARKETING DIRECTOR'), even in
# capitals. They are never a section name.
CONTACT_LINE_RE = re.compile(r"@|linkedin|https?:|www\.|\+\s?\d|\d[\d\s().-]{6,}\d", re.I)
HEADLINE_MAX_LINES = 2


def headline_rows(texts):
    """Indexes (1..2) of the rows that are the headline: between the name (row 0) and the contact line / first real
    heading. A short heading like 'SKILLS & TOOLS' or 'CONTACT' is not one; a line with a job title always is."""
    out = set()
    for i in range(1, min(len(texts), HEADLINE_MAX_LINES + 1)):
        t = texts[i].strip()
        if not t or CONTACT_LINE_RE.search(t) or len(t.split()) > 20:
            break
        title = bool(TITLE_WORDS.search(t))
        low = t.lower().rstrip(":")
        if HEADING_VOCAB.fullmatch(low) or (not title and (section_kind(t) != "other" or len(t.split()) < 2 or
                                                           any(w in low for w in STANDARD_HEADING_WORDS))):
            break
        out.add(i)
    return out


# Section names an ATS can map to a section: every part ('Tools & Platforms' = 'Tools' and 'Platforms') is a known
# noun, with optional modifiers ('Technical Skills', 'Core Competencies', 'Languages & Availability').
_NOUNS = (r"summary|profile|objective|statement|about(?: me)?|experience|employment|history|positions held|education|"
          r"qualifications?|academic background|training|courses?|skills?|competenc(?:y|ies)|expertise|strengths|"
          r"proficienc(?:y|ies)|tools?|platforms?|technologies|technology|software|systems|certifications?|certificates?|"
          r"licen[cs]es?|accreditations?|languages?|availability|additional information|additional details|"
          r"personal details|personal information|contact(?: details| information)?|interests|hobbies|references|"
          r"referees|projects?|publications?|awards?|honou?rs|achievements|accomplishments|volunteering|volunteer work|"
          r"activities|memberships|affiliations|conferences|visa status|notice period|nationality|other|"
          r"professional development|links|portfolio")
_MODS = (r"professional|executive|career|personal|work|working|relevant|related|key|core|technical|soft|hard|it|"
         r"computer|digital|selected|select|notable|additional|other|academic|industry|previous|recent|main|"
         r"areas of|language|volunteer|volunteering|international|freelance|leadership|teaching|research|military|"
         r"consulting|early|earlier|prior|further|more|professional and")
_PART_RE = re.compile(rf"(?:(?:{_MODS})\s+){{0,3}}(?:{_NOUNS})(?:\s+(?:{_NOUNS}))?", re.I)


def is_standard_section(title):
    """True when an ATS can map this section name ('Tools & Platforms', 'Technical Skills', 'Core Competencies',
    'Languages & Availability'). Only names an ATS cannot map ('What I Bring', 'My Journey') are False."""
    t = re.sub(r"\s+", " ", title.strip(" :")).lower()
    if not t:
        return False
    parts = [p.strip() for p in re.split(r"\s*(?:&|\band\b|/|,|\+|\|)\s*", t) if p.strip()]
    return bool(parts) and all(_PART_RE.fullmatch(p) for p in parts)


# ---------------------------------------------------------------------------
# Dates and jobs
# ---------------------------------------------------------------------------
def _month_index(point, is_end):
    p = point.lower()
    y = int(re.search(YEAR, p).group(0))
    m = re.match(r"(\d{1,2})/", p)
    if m:
        return y * 12 + int(m.group(1)) - 1
    mon = re.match(MONTH, p)
    if mon:
        return y * 12 + MONTHS.index(p[:3])
    return y * 12 + (11 if is_end else 0)


def find_ranges(text):
    out = []
    for m in RANGE_RE.finditer(text):
        a, b, sep = m.group("a"), m.group("b"), m.group("sep")
        # a month is given as a name ('Mar 2021') or a number ('03/2021'): both are full dates
        has_month = lambda s: re.match(rf"{MONTH}|\d{{1,2}}/{YEAR}", s.strip(), re.I) is not None
        is_end = re.fullmatch(END_WORD, b.strip(), re.I) is not None
        if sep.strip().lower() == "to" and not (has_month(a) or has_month(b) or is_end):
            continue
        start = _month_index(a, False)
        end = TODAY.year * 12 + TODAY.month - 1 if is_end else _month_index(b, True)
        out.append({"text": m.group(0), "start": start, "end": end,
                    "month_format": has_month(a) and (has_month(b) or is_end)})
    return out


def _strip_dates(text):
    t = RANGE_RE.sub(" ", text)
    t = POINT_RE.sub(" ", t)
    t = DURATION_RE.sub(" ", t)
    return re.sub(r"[\s|&,;()\-\u2013\u2014]+", "", t)


def date_only(text):
    """True if the text is nothing but dates / durations (plus separators)."""
    has = RANGE_RE.search(text) or POINT_RE.search(text) or DURATION_RE.search(text)
    return bool(has) and _strip_dates(text) == ""


def tail_date(line):
    parts = re.split(r"\s[|\u2014]\s", line)
    if len(parts) >= 2 and date_only(parts[-1]):
        return parts[-1]
    # "Company, City Apr 2024 to Feb 2026": a range at the very end of a short, non-sentence line
    last = list(RANGE_RE.finditer(line))
    if (last and line[last[-1].end():].strip(" )") == "" and last[-1].start() > 0 and ":" not in line
            and len(line.split()) <= 14 and not line.lstrip().startswith(("\u2022", "-", "*"))):
        return line[last[-1].start():]
    return None


def make_job(title, dtext, line_no):
    ranges = find_ranges(dtext)
    rest = RANGE_RE.sub(" ", dtext)
    singles = [p.group(0) for p in POINT_RE.finditer(rest)]
    durations = [(int(n), u.lower()) for n, u in DURATION_RE.findall(rest)]
    intervals = [(r["start"], r["end"]) for r in ranges]
    for s in singles:
        start = _month_index(s, False)
        intervals.append((start, start + 2))
    if not dtext:
        problem = "no date"
    elif durations and not ranges:
        problem = "duration instead of dates"
    elif not ranges:
        problem = "start date only"
    elif not all(r["month_format"] for r in ranges):
        problem = "year only"
    else:
        problem = None
    end_year = max((e // 12 for _, e in intervals), default=None)
    return {"title": title.strip(), "dates": dtext.strip(), "line": line_no, "has_range": bool(ranges),
            "month_format": problem is None, "problem": problem, "intervals": intervals,
            "duration_months": sum(n * 12 if u.startswith("y") else n for n, u in durations),
            "end_year": end_year}


def parse_jobs(lines):
    jobs = []
    for i, l in enumerate(lines):
        if date_only(l):
            jobs.append(make_job(lines[i - 1] if i else "", l, max(0, i - 1)))
            continue
        parts = re.split(r"\s[|\u2014]\s", l)
        mid = next((k for k in range(1, len(parts) - 1) if date_only(parts[k])), None)
        if mid is not None and not l.lstrip().startswith(("\u2022", "-", "*")):
            prev = lines[i - 1].strip() if i else ""
            above = (prev and len(prev.split()) <= 8 and not prev.endswith((".", ",", ";")) and not find_ranges(prev)
                     and not re.match(r"^[\u2022\-*\u25aa\u25cf\u00b7]", prev) and "|" not in prev)
            company = " | ".join(parts[:mid])
            if above:                                     # the title is the short line above the company line
                jobs.append(make_job(prev + " | " + company, parts[mid], i - 1))
            else:
                jobs.append(make_job(company, parts[mid], i))
            continue
        tail = tail_date(l)
        if tail:
            jobs.append(make_job(l[: len(l) - len(tail)].rstrip(" |\u2014"), tail, i))
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        prev = lines[i - 1] if i else ""
        if (len(l.split()) <= 12 and re.search(r"\s[|\u2014]\s", l) and ":" not in l
                and not l.endswith((".", ",")) and (not prev or prev.endswith(".")) and not date_only(nxt)):
            jobs.append(make_job(l, "", i))
    return jobs


def experience_years(jobs):
    iv = sorted(iv for j in jobs for iv in j["intervals"])
    merged = []
    for s, e in iv:  # merge overlapping jobs so parallel roles are not counted twice
        if merged and s <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    months = sum(e - s + 1 for s, e in merged) + sum(j["duration_months"] for j in jobs)
    return months / 12


# ---------------------------------------------------------------------------
# CV structure: header zone, sections, jobs, keyword location chunks
# ---------------------------------------------------------------------------
# A resume with no 'Experience' heading (the jobs sit under company names: 'BLR WORLD (Dubai)' / 'Designer
# January 2025 - Present'): its jobs are still its experience. The rows from the first job on, up to a section that is
# not experience (achievements, languages, skills, ...), become one Experience section.
NOT_EXPERIENCE_RE = re.compile(r"achievement|accomplishment|language|certif|licen|volunteer|professional development|"
                               r"training|courses|awards|publications|references|interests|skills|competenc|summary|"
                               r"profile|objective|education|additional information", re.I)
EXPERIENCE_NOT_FROM = ("education", "summary", "languages", "certifications", "skills", "competencies", "achievements")


def _job_row(text):
    t = text.strip()
    # a job line starts with a word (a title or a company), never with a number ('6 UAE roles Feb 2025 - Present')
    return bool(find_ranges(t)) and t[:1].isalpha() and len(t.split()) <= 16


def synthesize_experience(sections):
    """-> sections where the jobs found under other headings (company names, a highlights box) are Experience too.
    Each run of such sections, from the first job line up to a section that is not experience (achievements,
    languages, skills, ...), becomes an Experience section. Resumes without such jobs keep the very same list."""
    out, si, changed = [], 0, False
    while si < len(sections):
        sec = sections[si]
        ri = next((k for k, r in enumerate(sec["rows"]) if _job_row(r["text"])), None)             if sec["kind"] not in EXPERIENCE_NOT_FROM + ("experience", "projects") else None
        if ri is None:
            out.append(sec)
            si += 1
            continue
        changed = True
        start, title_first = ri, False
        prev = sec["rows"][ri - 1]["text"].strip() if ri else None
        if ri and prev and len(prev.split()) <= 10 and not find_ranges(prev) and not re.match(r"^[•\-*]", prev):
            start = ri - 1                               # the company line above the job line
        elif not ri:
            title_first = True                           # the section's own title is the company line
        rows = ([{"page": sec["rows"][0]["page"] if sec["rows"] else 0, "text": sec["title"], "cells": [sec["title"]]}]
                if title_first else []) + sec["rows"][start:]
        if not (title_first or start == 0):
            out.append(dict(sec, rows=sec["rows"][:start]))
        sj = si + 1
        while sj < len(sections):
            t = sections[sj]
            if t["kind"] in EXPERIENCE_NOT_FROM + ("experience", "projects") or NOT_EXPERIENCE_RE.search(t["title"]):
                break
            rows += [{"page": t["rows"][0]["page"] if t["rows"] else 0, "text": t["title"], "cells": [t["title"]]}]                 + t["rows"]
            sj += 1
        merged = ([sec["title"]] if title_first else []) + [sections[k]["title"] for k in range(si + 1, sj)]
        out.append({"title": "EXPERIENCE", "kind": "experience", "rows": rows, "merged_titles": merged})
        si = sj
    return out if changed else sections


def analyse(doc):
    rows = [r for r in doc["rows"] if not WATERMARK_RE.search(r["text"])]
    header, sections = [], []
    headline = headline_rows([r["text"] for r in rows])
    for i, r in enumerate(rows):
        t = r["text"].strip()
        if i > 0 and i not in headline and is_heading(t):
            sections.append({"title": t, "kind": section_kind(t), "rows": []})
        elif sections:
            sections[-1]["rows"].append(r)
        else:
            header.append(r)
    sections = synthesize_experience(sections)
    exp_lines = [r["text"].strip() for s in sections if s["kind"] == "experience" for r in s["rows"]]
    jobs = parse_jobs(exp_lines)

    recent_from = TODAY.year - RECENT_YEARS
    chunks = [(" ".join(r["text"] for r in header), OLD_LOCATION)]
    for s in sections:
        texts = [r["text"] for r in s["rows"]]
        if s["kind"] in ("skills", "competencies"):
            chunks.append((" ".join(texts), 1.0))
        elif s["kind"] == "experience":
            starts = [j["line"] for j in jobs] + [len(texts)]
            chunks.append((" ".join(texts[: starts[0]]), OLD_LOCATION))
            for j, nxt in zip(jobs, starts[1:]):
                recent = j["end_year"] is not None and j["end_year"] >= recent_from
                chunks.append((" ".join(texts[j["line"]: nxt]), 1.0 if recent else OLD_LOCATION))
        else:
            chunks.append((" ".join(texts), OLD_LOCATION))
    return {"header": header, "sections": sections, "jobs": jobs,
            "chunks": [(tokens(t), m) for t, m in chunks if t.strip()]}


def section_rows(ana, *kinds):
    return [r for s in ana["sections"] if s["kind"] in kinds for r in s["rows"]]


# ---------------------------------------------------------------------------
# Keyword matching: exact / variant (plural, word form, UK-US spelling) / abbreviation
# ---------------------------------------------------------------------------
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.]*[a-z0-9+#]|[a-z0-9]")


DASHES_RE = re.compile(r"[‐‑‒–—―−﹘﹣－]")


def norm_punct(text):
    """Same text for an ATS: every dash is '-', curly quotes are straight, '&' is 'and'."""
    text = DASHES_RE.sub("-", text).replace("’", "'").replace("‘", "'")
    return re.sub(r"\s*&\s*", " and ", text)


def tokens(text):
    return TOKEN_RE.findall(DASHES_RE.sub("-", text).lower())


def stem(tok):
    t = tok.lower()
    t = re.sub(r"ll(ing|ed|er)$", r"l\1", t)                  # modelling -> modeling
    t = re.sub(r"is(ation|ations|e|es|ed|ing)$", r"iz\1", t)   # optimise -> optimize
    t = re.sub(r"ys(e|es|ed|ing)$", r"yz\1", t)                # analyse -> analyze
    if len(t) > 5:
        t = re.sub(r"our(s)?$", r"or\1", t)                    # behaviour -> behavior
        t = re.sub(r"tre(s)?$", r"ter\1", t)                   # centre -> center
    t = re.sub(r"ogue(s)?$", r"og\1", t)                       # catalogue -> catalog
    for suf, rep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if t.endswith(suf) and len(t) - len(suf) >= 3:
            if suf == "s" and t.endswith(("ss", "is", "us")):
                continue
            t = t[: len(t) - len(suf)] + rep
            break
    return t.rstrip("e") if len(t) > 4 else t


def _find_seq(seq, toks):
    n = len(seq)
    return n > 0 and any(toks[i:i + n] == seq for i in range(len(toks) - n + 1))


def _count_seq(seq, toks):
    n = len(seq)
    return sum(toks[i:i + n] == seq for i in range(len(toks) - n + 1)) if n else 0


_NO_AND = {}


def _no_and(toks):
    """The tokens without 'and' (a '&' is never a token, so '&' and 'and' compare equal). Cached per list."""
    hit = _NO_AND.get(id(toks))
    if hit is None or hit[0] is not toks:
        if len(_NO_AND) > 5000:
            _NO_AND.clear()
        hit = _NO_AND[id(toks)] = (toks, [x for x in toks if x != "and"])
    return hit[1]


def _joined_match(compact, toks):
    """'fullstack' found as 'full stack' / 'full-stack' (or the other way round): 1-3 words written together."""
    if len(compact) < 5:
        return False
    first = compact[0]
    for i, tok in enumerate(toks):
        if tok[0] != first:
            continue
        joined = ""
        for k in range(i, min(i + 3, len(toks))):
            joined += toks[k]
            if joined == compact:
                return True
            if not compact.startswith(joined):
                break
    return False


def other_form(term):
    key = " ".join(tokens(term))
    if key in ABBREVIATIONS:
        return ABBREVIATIONS[key]
    return next((a for a, f in ABBREVIATIONS.items() if f == key), None)


def match_level(term, toks, stems=None):
    """'exact', 'variant', 'abbr' or None. Variants are checked on EVERY word, not only the last."""
    t = tokens(term)
    if not t:
        return None
    if _find_seq(t, toks):
        return "exact"
    # punctuation only: '&' = 'and' ('Talent & Culture' / 'Talent and Culture'), and a hyphen, a space or
    # nothing between word parts is the same word ('full-stack' / 'full stack' / 'fullstack')
    if _find_seq(_no_and(t), _no_and(toks)) or _joined_match("".join(t), toks):
        return "exact"
    stems = stems if stems is not None else [stem(x) for x in toks]
    if _find_seq([stem(x) for x in t], stems):
        return "variant"
    other = other_form(term)
    if other:
        o = [stem(x) for x in tokens(other)]
        if _find_seq(o, stems):
            return "abbr"
    return None


def contains(term, text):
    toks = tokens(text)
    return match_level(term, toks) in ("exact", "variant")


def level_credit(level, prof):
    return {"exact": 1.0, "variant": prof["variant_credit"], "abbr": ABBR_CREDIT}.get(level, 0.0)


def keyword_records(kw, ana, job_text):
    job_stems = [stem(x) for x in tokens(job_text)]
    chunks = [(toks, [stem(x) for x in toks], mult) for toks, mult in ana["chunks"]]
    recs = []
    for typ, key in (("required", "required_skills"), ("preferred", "preferred_skills"), ("soft", "soft_skills")):
        for term in kw.get(key, []):
            times = max(1, _count_seq([stem(x) for x in tokens(term)], job_stems))
            hits = sorted({(lvl, m) for toks, stems, m in chunks
                           for lvl in [match_level(term, toks, stems)] if lvl})
            recs.append({"term": term, "type": typ, "times_in_job": times,
                         "weight": round(TYPE_WEIGHT[typ] * (1 + math.log2(times)), 3), "hits": hits})
    return recs


def best_credit(rec, prof, with_location=True):
    best = 0.0
    for lvl, mult in rec["hits"]:
        best = max(best, level_credit(lvl, prof) * (mult if with_location else 1.0))
    return best


def best_level(rec):
    order = {"exact": 3, "variant": 2, "abbr": 1}
    return max((lvl for lvl, _ in rec["hits"]), key=lambda l: order[l], default=None)


# ---------------------------------------------------------------------------
# BUG REGISTRY  -  add a new bug = add one entry here
#   owns:  checks this bug already lowers (no fixed penalty, to avoid double counting)
#   fix:   "template fix" (developers) or "content" (prompt / ML)
# ---------------------------------------------------------------------------
def detect_b1(doc, ana):
    sp = spaced_lines(doc["strict"])
    if not sp:
        return False, "no letter-spaced lines"
    first = lines_of(doc["strict"])[0]
    if sp == [first]:
        return True, f"name only: '{first[:40]}'"
    return True, f"{len(sp)} letter-spaced line(s), e.g. '{(sp[1] if sp[0] == first and len(sp) > 1 else sp[0])[:40]}'"


SKILL_SEP = r"[,;|\u2022\u00b7]"   # "Category: Python, SQL" / "Python | SQL" / "\u2022 Python \u2022 SQL"


def skill_items(rows):
    """The skills an ATS can read from skills-section rows: 'a, b, c' lists, grid cells, 'Category: a'."""
    items = []
    for r in rows:
        sep_cells = [c for c in r["cells"] if re.search(SKILL_SEP, c)]
        if sep_cells:
            for c in sep_cells:
                c = c.split(":", 1)[-1]
                items += [x.strip() for x in re.split(SKILL_SEP, c) if x.strip()]
        elif len(r["cells"]) >= 2:
            items += [c.strip() for c in r["cells"]]          # grid: one skill per column
        elif ":" in r["text"] and r["text"].split(":", 1)[1].strip():
            items.append(r["text"].split(":", 1)[1].strip())
    return items


def count_skill_items(rows):
    return len(skill_items(rows))


def skills_listed(ana):
    secs = [s for s in ana["sections"] if s["kind"] == "skills"]
    return sum(count_skill_items(s["rows"]) for s in secs), secs


def detect_b2(doc, ana):
    n, secs = skills_listed(ana)
    if not secs:
        return True, "no Skills section"
    if n < 4:
        return True, f"'{secs[0]['title']}' shows category names only ({n} real skills)"
    return False, f"{n} skills listed"


def detect_b3(doc, ana):
    n = len(WATERMARK_RE.findall(doc["modern"]))
    return n > 0, f"{n} watermark line(s) in the text" if n else "none"


def detect_b4(doc, ana):
    m = EMAIL_RE.search(doc["modern"])
    return (not m), (m.group(0) if m else "no email address found")


def detect_b5(doc, ana):
    n = doc["modern"].count("**")
    return n > 0, f"{n} '**' marks" if n else "none"


def detect_b6(doc, ana):
    tags = HTML_RE.findall(doc["modern"])
    return bool(tags), f"{len(tags)} HTML tag(s)" if tags else "none"


def detect_b7(doc, ana):
    ph = sorted({m.group(0) for m in PLACEHOLDER_RE.finditer(doc["modern"])})
    return bool(ph), ", ".join(ph) if ph else "none"


def detect_b8(doc, ana):
    glance = [s["title"] for s in ana["sections"] if s["kind"] == "glance"]
    multi = [r["text"] for s in ana["sections"] if s["kind"] not in ("skills", "competencies")
             for r in s["rows"] if len(r["cells"]) >= 2 and not any(date_only(c) for c in r["cells"])]
    if glance:
        return True, f"'{glance[0]}' boxes side by side ({len(multi)} multi-column rows)"
    if len(multi) >= 2:
        return True, f"{len(multi)} multi-column rows outside Skills"
    return False, "single column"


STOPWORDS = set("a an the and or of to in for with by on at from as into across through using via while within over "
                "under its their our your his her this that these those be is are was were been being has have had it "
                "which who including".split())
REPEAT_SHARE = 0.6   # an achievement line "repeats" if 60% of its meaning words sit in 3 nearby lines elsewhere


def content_words(text):
    t = RANGE_RE.sub(" ", text)
    return {stem(x) for x in tokens(t) if x not in STOPWORDS and len(x) > 2 and not re.fullmatch(YEAR, x)}


def detect_b9(doc, ana):
    ach = [content_words(r["text"]) for r in section_rows(ana, "achievements")]
    ach = [c for c in ach if len(c) >= 3]
    if len(ach) < 2:
        return False, "no Select Achievements list"
    other = [r["text"] for r in ana["header"]] + [r["text"] for s in ana["sections"] if s["kind"] != "achievements"
                                                  for r in s["rows"]]
    windows = [content_words(" ".join(other[i:i + 3])) for i in range(len(other))]
    rep = sum(max((len(c & w) / len(c) for w in windows), default=0) >= REPEAT_SHARE for c in ach)
    return rep / len(ach) >= 0.5, f"{rep} of {len(ach)} achievement lines repeat the rest of the CV"


def detect_b10(doc, ana):
    low = doc["modern"].lower()
    hits = [p for p in TEMPLATE_PHRASES if p in low]
    return bool(hits), ", ".join(f"'{h}'" for h in hits) if hits else "none"


def detect_b12(doc, ana):
    n = doc["modern"].count("`")
    return bool(n), f"{n} backtick mark(s) printed" if n else "none"


def detect_b13(doc, ana):
    shared = doc.get("shared_text")
    if shared is None:
        return False, "not checked (needs a batch with CVs of 2+ users)"
    if not shared:
        return False, "no text shared with another user's CV"
    eg = "; ".join(f"'{t[:60]}...' also in {', '.join(o[:2])}" for t, o in shared[:2])
    return True, f"{len(shared)} passage(s) also in other users' CVs: {eg}"


def detect_b11(doc, ana):
    jobs = ana["jobs"]
    if not jobs:
        return True, "no jobs with dates found"
    bad = [j for j in jobs if j["problem"]]
    if not bad:
        return False, f"all {len(jobs)} jobs dated with month + year"
    eg = "; ".join(f"'{j['title'][:30]}' {j['problem']}" for j in bad[:3])
    return True, f"{len(bad)} of {len(jobs)} jobs: {eg}"


BUGS = [
    {"code": "B1", "name": "Spaced-out headings", "status": "Now", "severity": "Critical",
     "owns": ["R5"], "fix": "template fix", "detect": detect_b1},
    {"code": "B2", "name": "Skills section unreadable", "status": "Now", "severity": "Critical",
     "owns": ["R9"], "fix": "template fix", "detect": detect_b2},
    {"code": "B3", "name": "Watermark inside the text", "status": "Now", "severity": "Major",
     "owns": [], "fix": "template fix", "detect": detect_b3},
    {"code": "B4", "name": "Email missing", "status": "Now", "severity": "Critical",
     "owns": ["R2"], "fix": "template fix", "detect": detect_b4},
    {"code": "B5", "name": "Markdown ** marks printed", "status": "Now", "severity": "Minor",
     "owns": [], "fix": "template fix", "detect": detect_b5},
    {"code": "B6", "name": "HTML code printed", "status": "Now", "severity": "Major",
     "owns": [], "fix": "template fix", "detect": detect_b6},
    {"code": "B7", "name": "Placeholder text", "status": "Now", "severity": "Major",
     "owns": [], "fix": "content", "detect": detect_b7},
    {"code": "B8", "name": "Career Impact boxes side by side", "status": "Later", "severity": "Major",
     "owns": [], "fix": "template fix", "detect": detect_b8},
    {"code": "B9", "name": "Select Achievements repeats experience", "status": "On hold", "severity": "Minor",
     "owns": [], "fix": "template fix", "detect": detect_b9},
    {"code": "B10", "name": "Template phrases", "status": "On hold", "severity": "Minor",
     "owns": [], "fix": "content", "detect": detect_b10},
    {"code": "B11", "name": "Job dates missing, year-only or durations", "status": "On hold", "severity": "Major",
     "owns": ["R6", "R7"], "fix": "content", "detect": detect_b11},
    {"code": "B12", "name": "Backtick ` marks printed", "status": "Now", "severity": "Minor",
     "owns": [], "fix": "template fix", "detect": detect_b12},
    {"code": "B13", "name": "Text shared with another user's CV", "status": "Now", "severity": "Major",
     "owns": [], "fix": "content", "detect": detect_b13},
]
BUG_BY_CODE = {b["code"]: b for b in BUGS}
BROKEN_TEXT_BUGS = ("B3", "B5", "B6", "B7", "B12")


def bug_penalty(code):
    b = BUG_BY_CODE[code]
    return 0 if b["owns"] else SEVERITY_PENALTY[b["severity"]]


def detect_bugs(doc, ana):
    out = {}
    for b in BUGS:
        found, detail = b["detect"](doc, ana)
        out[b["code"]] = {"found": bool(found), "detail": detail}
    return out


# ---------------------------------------------------------------------------
# Checks (each returns a score 0-1)
# ---------------------------------------------------------------------------
CHECK_TAG = {"R1": "template fix", "R2": "template fix", "R3": "template fix", "R4": "template fix",
             "R5": "template fix", "R6": "content", "R7": "content", "R8": "content", "R9": "template fix",
             "R11": "template fix", "R12": "template fix", "R13": "content", "F1": "content", "F2": "content",
             "F3": "content", "F4": "content", "M1": "content", "M3": "content", "M4": "content", "M5": "content"}


def chk(name, part, score, detail, weight=1.0):
    return {"name": name, "part": part, "score": None if score is None else max(0.0, min(1.0, float(score))),
            "detail": detail, "weight": weight}


NAME_MARKS_RE = re.compile(r"[®™©]")                     # 'PMP®', 'CSM™'
# credentials and degrees written after a name ('SANA MALIK, PMP®', 'Jane Doe, MSc, PMP')
CREDENTIAL_RE = re.compile(r"(?i)^(?:mba|m\.?b\.?a\.?|msc|m\.?sc\.?|bsc|b\.?sc\.?|phd|ph\.?d\.?|dba|cpa|cfa|cma|pmp|"
                           r"capm|acca|fcca|cima|cipd|cia|cisa|cism|cissp|frm|ma|ba|ms|bs|beng|meng|ceng|eng\.?|pe|"
                           r"md|mph|llb|llm|sphr|phr|shrm-[cs]cp|itil|prince2|csm|psm|pmi-acp)$")
CREDENTIAL_END_RE = re.compile(r"(?i)^(?:mba|msc|bsc|phd|dba|cpa|cfa|cma|pmp|acca|cima|cipd|cissp)$")   # no comma
NAME_FRONT_RE = re.compile(r"(?i)^(?:dr\.?|mr\.?|mrs\.?|ms\.?|miss|prof\.?|sir|eng\.?)$")


def bare_name(text):
    """The name without titles and credentials: 'SANA MALIK, PMP®' -> 'SANA MALIK', 'Dr. Jane Doe, PhD' ->
    'Jane Doe', 'Ali Hassan MBA' -> 'Ali Hassan'."""
    parts = [p.strip() for p in NAME_MARKS_RE.sub("", text or "").split(",")]
    while len(parts) > 1 and all(CREDENTIAL_RE.match(w) for w in parts[-1].split()):
        parts.pop()                                          # ', MBA' / ', MSc, PMP' / a trailing comma
    words = " ".join(parts).split()
    while len(words) > 1 and CREDENTIAL_END_RE.match(words[-1]):
        words.pop()
    while len(words) > 1 and NAME_FRONT_RE.match(words[0]):
        words.pop(0)
    return " ".join(words).strip(" ,")


def readable_checks(doc, ana, bugs, prof):
    c = {}
    head = [r["text"].strip() for r in ana["header"]]
    name = head[0] if head else ""
    bare = bare_name(name)                                   # a credential or title after the name is fine
    c["R1"] = chk("Name", "R", 2 <= len(bare.split()) <= 6 and not re.search(r"[@\d]", bare),
                  name or "no text extracted")
    email = EMAIL_RE.search(doc["modern"])
    c["R2"] = chk("Email", "R", bool(email), email.group(0) if email else "no email found")
    phone = PHONE_RE.search(doc["modern"])
    ph = phone.group(1).strip() if phone else ""
    c["R3"] = chk("Phone with +country code", "R", 1.0 if ph.startswith("+") else 0.5 if ph else 0.0,
                  ph or "no phone found")
    headline = next((l for l in head[1:4] if not re.search(r"@|\+?\d{6,}", l) and 2 <= len(l.split()) <= 20), None)
    c["R4"] = chk("Headline", "R", bool(headline), headline or "no headline under the name")

    total = 1 + len(ana["sections"])
    spaced = len(spaced_lines(doc["strict"] if prof["strict_parser"] else doc["modern"]))
    spaced = min(spaced, total)
    note = " (name only)" if bugs["B1"]["detail"].startswith("name only") and spaced else ""
    c["R5"] = chk("Section headings readable", "R", (total - spaced) / total,
                  f"{total - spaced} of {total} headings readable{note}")

    jobs = ana["jobs"]
    n = len(jobs)
    c["R6"] = chk("Jobs have date ranges", "R", sum(j["has_range"] for j in jobs) / n if n else 0,
                  f"{sum(j['has_range'] for j in jobs)} of {n} jobs", prof["date_weight"])
    c["R7"] = chk("Job dates with month + year (Mon YYYY or MM/YYYY)", "R", sum(j["month_format"] for j in jobs) / n if n else 0,
                  f"{sum(j['month_format'] for j in jobs)} of {n} jobs", prof["date_weight"])

    low = doc["modern"].lower()
    degree = next((lvl for lvl, pat in DEGREE_PATTERNS if re.search(pat, low)), None)
    edu = " ".join(r["text"] for r in section_rows(ana, "education"))
    year = re.search(YEAR, edu)
    senior = experience_years(ana["jobs"]) >= SENIOR_YEARS      # 10+ years: a graduation year is not expected
    c["R8"] = chk("Education (degree + year)", "R", 0.5 * bool(degree) + 0.5 * bool(year or senior),
                  f"degree: {degree or 'not found'}, year: "
                  + ("yes" if year else f"not needed ({SENIOR_YEARS}+ years of experience)" if senior else "no"))

    items, _ = skills_listed(ana)
    c["R9"] = chk("Skills section has real skills", "R", min(1.0, items / 8), f"{items} skills listed (8 = full marks)")

    if prof["standard_headings"]:
        heads = [s["title"] for s in ana["sections"] if s["kind"] != "glance"]   # glance boxes are B8
        odd = [h for h in heads if not is_standard_section(h)
               and not any(w in h.lower() for w in STANDARD_HEADING_WORDS)]
        c["R11"] = chk("Only standard section names", "R", (len(heads) - len(odd)) / len(heads) if heads else 0,
                       "non-standard: " + "; ".join(odd[:4]) if odd else "all section names standard")

    kinds = {s["kind"] for s in ana["sections"]}
    found = [k for k, ks in CORE_SECTIONS.items() if kinds & set(ks)]
    c["R12"] = chk("Core sections present", "R", len(found) / 4,
                   "missing: " + ", ".join(k for k in CORE_SECTIONS if k not in found) if len(found) < 4
                   else "Summary, Experience, Education, Skills")

    words = len(" ".join(r["text"] for r in section_rows(ana, "summary")).split())
    if words == 0:
        s = 0.0
    elif words < 40:
        s = words / 40
    elif words <= 90:
        s = 1.0
    else:
        s = 1 - (words - 90) / 180
    c["R13"] = chk("Summary length (40-90 words)", "R", s, f"{words} words")
    return c


def findable_static(doc, ana, kw, profile, prof):
    c = {}
    toks = tokens(doc["modern"])
    stems = [stem(x) for x in toks]
    hard = kw.get("required_skills", []) + kw.get("preferred_skills", [])
    found = lambda t: match_level(t, toks, stems) in ("exact", "variant")
    # only a term the resume really uses (in either form) can be "written only one way"; a skill that is missing
    # from the resume belongs to the missing-skills card alone
    pairs = [s for s in hard if other_form(s) and (found(s) or found(other_form(s)))]
    both = sum(found(s) and found(other_form(s)) for s in pairs)
    c["F2"] = chk("Abbreviations in both forms", "F", both / len(pairs) if pairs else None,
                  f"{both}/{len(pairs)} written both ways" if pairs else
                  "no abbreviation term of this job is in the resume", 0.15)

    title = (kw.get("title") or "").strip()
    top_rows = ana["header"] + section_rows(ana, "summary")
    top = tokens(" ".join(r["text"] for r in top_rows))
    lvl = match_level(title, top) if title else None
    c["F3"] = chk("Exact job title in headline/summary", "F",
                  (level_credit(lvl, prof) if lvl in ("exact", "variant") else 0.0) if title else None,
                  f"'{title}' {lvl or 'NOT found'}" if title else "no job title extracted", 0.25)

    titles = (profile or {}).get("titles", [])
    if titles:
        low = re.sub(r"\s+", " ", norm_punct(doc["modern"]).lower())       # dashes, '&' and spaces normalized
        changed = [t for t in titles if not re.search(
            rf"{re.escape(re.sub(r'\s+', ' ', norm_punct(t).lower()))}(?!\s*[\u2014|\-/]\s*\w{{4,}})", low)]
        c["F4"] = chk("Past titles unchanged", "F", (len(titles) - len(changed)) / len(titles),
                      "changed/missing: " + (", ".join(changed) or "none"), 0.10)
    else:
        c["F4"] = chk("Past titles unchanged", "F", None, "skipped (no profile titles)", 0.10)
    return c


# M3 meaning match: a free local embedding model (no API, same result every run).
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"   # pinned: a model update can never change scores
EMBED_CHUNK_WORDS = 60
# Calibration (2026-10-15, 28 CVs x 16 jobs: CVS, CV4, shikhatest, tariqtest, competitorcvs; re-done after
# perks / hiring / legal / company sentences were removed from the role text).
# raw = how well the CV covers the job's role text (see meaning_match_raw).
#   CV vs its own job (good match):    median 0.509  ->  80 points
#   CV vs other people's jobs (poor):  median 0.372  ->  20 points
# straight line between the two, cut to 0-100.
M3_RAW_POOR, M3_SCORE_POOR = 0.372, 0.20
M3_RAW_GOOD, M3_SCORE_GOOD = 0.509, 0.80
RELATED_SUBJECT_CREDIT = 0.5   # M4 subject part when no listed subject but "or a related field" is allowed
_EMBEDDER = cv_cache.shared("embedder", list)             # the model is loaded ONCE per run, also after a reload
_EMBED_CACHE = cv_cache.shared("embed_cache", dict)
EMBED_OFF = os.environ.get("ATSLAB_EMBED", "1") == "0"     # switch the model off by hand (ATSLAB_EMBED=0)
LAB_DIR = os.path.dirname(os.path.abspath(__file__))
EMBED_PROBE_FILE = os.path.join(LAB_DIR, "embed_probe.json")
_EMBED_OK = cv_cache.shared("embed_ok", list)
EMBED_NOTE = ("The meaning-match model could not run on this computer, so 'Meaning match' was skipped; "
              "every other check ran.")


def _probe_key():
    """The model works or not for one Python + package versions + CPU: the probe result is saved per key."""
    import importlib.metadata as md
    import platform
    vers = []
    for n in ("torch", "sentence-transformers", "transformers", "numpy", "tokenizers", "safetensors"):
        try:
            vers.append(f"{n}={md.version(n)}")
        except Exception:
            vers.append(f"{n}=none")
    return "|".join([sys.version.split()[0], platform.processor(), *vers])


def embedder_ok():
    """Can the model load and run here? Tried ONCE in a separate process: a library built for CPU instructions this
    computer lacks (e.g. AVX-512) crashes that process, never this one. The answer is saved in embed_probe.json."""
    if EMBED_OFF:
        return False
    if _EMBED_OK:
        return _EMBED_OK[0]
    key = _probe_key()
    try:
        with open(EMBED_PROBE_FILE, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    if key not in saved:
        import subprocess
        code = ("import os; os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false');"
                "import ATSLab_v3 as L; m = L._load_embedder(); print(m.encode(['probe text here']).shape)")
        try:
            p = subprocess.run([sys.executable, "-c", code], cwd=LAB_DIR, capture_output=True, text=True,
                               timeout=600)
            ok = p.returncode == 0
            why = "" if ok else (p.stderr.strip().splitlines() or [f"exit code {p.returncode}"])[-1][:300]
        except (OSError, subprocess.SubprocessError) as e:
            ok, why = False, f"{type(e).__name__}: {e}"[:300]
        saved[key] = {"ok": ok, "why": why, "checked": TODAY.isoformat()}
        try:
            with open(EMBED_PROBE_FILE, "w", encoding="utf-8") as f:
                json.dump(saved, f, indent=1)
        except OSError:
            pass
    _EMBED_OK.append(bool(saved[key]["ok"]))
    return _EMBED_OK[0]


def _load_embedder():
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    from sentence_transformers import SentenceTransformer
    try:          # the pinned model from the local cache (no internet needed after the first run)
        return SentenceTransformer(EMBED_MODEL, revision=EMBED_REVISION, device="cpu", local_files_only=True)
    except OSError:
        return SentenceTransformer(EMBED_MODEL, revision=EMBED_REVISION, device="cpu")   # first run: download once


def _embedder():
    if not _EMBEDDER:
        if not embedder_ok():
            raise ImportError("the meaning-match model cannot run on this computer")
        _EMBEDDER.append(_load_embedder())
    return _EMBEDDER[0]


def meaning_chunks(text, max_words=EMBED_CHUNK_WORDS):
    """Sentences / lines (3+ words) grouped into pieces of at most ~60 words (the model reads short texts best)."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?;])\s+|\n", text) if len(p.split()) >= 3]
    out, cur = [], []
    for p in parts:
        if cur and len(" ".join(cur + [p]).split()) > max_words:
            out.append(" ".join(cur))
            cur = []
        cur.append(p)
    if cur:
        out.append(" ".join(cur))
    return out


def _embed(text):
    if text not in _EMBED_CACHE:
        _EMBED_CACHE[text] = _embedder().encode(meaning_chunks(text), normalize_embeddings=True,
                                                show_progress_bar=False, batch_size=32)
    return _EMBED_CACHE[text]


def meaning_match_raw(cv_text, job_text):
    """Coverage: for each piece of the job's role text, the closest piece of the CV (cosine); the average.
    Uses only the role part of the posting (no company description or benefits). None if it cannot run."""
    role = skill_text(job_text) or job_text
    if not meaning_chunks(role):
        return None
    if not meaning_chunks(cv_text):
        return 0.0
    try:
        sims = _embed(role) @ _embed(cv_text).T
    except (ImportError, OSError, RuntimeError):         # the model cannot run here: the check goes on without it
        return None
    return round(float(sims.max(axis=1).mean()), 4)     # rounded: same number every run


def meaning_scale(raw):
    """Calibrated 0-1 score from the raw coverage (see M3_RAW_* above)."""
    slope = (M3_SCORE_GOOD - M3_SCORE_POOR) / (M3_RAW_GOOD - M3_RAW_POOR)
    return round(max(0.0, min(1.0, M3_SCORE_POOR + (raw - M3_RAW_POOR) * slope)), 4)


def meaning_match(cv_text, job_text):
    if not job_text.strip():
        return None
    raw = meaning_match_raw(cv_text, job_text)
    return None if raw is None else meaning_scale(raw)


def matched_static(doc, ana, job_text, kw):
    c = {}
    raw = meaning_match_raw(doc["modern"], job_text) if job_text.strip() else None
    m3 = None if raw is None else meaning_scale(raw)
    c["M3"] = chk("Meaning match (embeddings)", "M", m3,
                  f"CV covers the job's role text: similarity {raw:.3f} (own-job median {M3_RAW_GOOD}, "
                  f"unrelated-job median {M3_RAW_POOR})" if raw is not None
                  else ("skipped: " + EMBED_NOTE if job_text.strip() and not embedder_ok()
                        else "needs job text + sentence-transformers"), 0.25)
    low = doc["modern"].lower()
    need = str(kw.get("degree_level") or "none").lower()
    have = next((lvl for lvl, pat in DEGREE_PATTERNS if re.search(pat, low)), "none")
    parts, details = [], []
    if need in DEGREE_RANK and need != "none":
        parts.append(float(DEGREE_RANK.get(have, 0) >= DEGREE_RANK[need]))
        details.append(f"level {parts[-1]:g}: job needs {need}, CV shows {have}")
    subjects = kw.get("education_keywords") or []
    if subjects:   # the posting lists alternatives ('Computer Science, Engineering or a related field'): one is enough
        found = [s for s in subjects if contains(s, doc["modern"])]
        related = kw.get("education_related_ok", False)
        subject = 1.0 if found else RELATED_SUBJECT_CREDIT if related else 0.0
        parts.append(subject)
        details.append(f"subject {subject:g}: " + (found[0] if found else f"none of {', '.join(subjects[:4])}"
                       + (" (related field allowed)" if related else "")))
    # M4 = average of its parts: level met (1) + related-field subject (0.5) -> 0.75; subject part alone -> 0.5
    c["M4"] = chk("Education (level + subject)", "M", sum(parts) / len(parts) if parts else None,
                  "; ".join(details) or "job sets no degree level or subject", 0.075)
    try:
        need_y = float(kw.get("min_years") or 0)
    except (TypeError, ValueError):
        need_y = 0
    if need_y:
        have_y = experience_years(ana["jobs"])
        c["M5"] = chk("Experience level", "M", have_y / need_y,
                      f"job needs {need_y:g}+ years, CV shows ~{have_y:.1f} (overlaps merged)", 0.075)
    else:
        c["M5"] = chk("Experience level", "M", None, "job sets no minimum years", 0.075)
    return c


def few_skills(score, n, m3):
    """A job with fewer than KEYWORD_MIN hard skills: the missing places up to KEYWORD_MIN count as the meaning
    match, so one generic skill ('Accounting' of 2) cannot count for too much. -> (score, note)."""
    if m3 is None or not 0 < n < KEYWORD_MIN:
        return score, ""
    return (n * score + (KEYWORD_MIN - n) * m3) / KEYWORD_MIN, \
        f" (only {n} job skills: {KEYWORD_MIN - n} of {KEYWORD_MIN} count as the meaning match)"


def keyword_checks(recs, prof, m3=None):
    """F1 and M1. m3: the meaning match (0-1), used when the job has fewer than KEYWORD_MIN hard skills."""
    hard = [r for r in recs if r["type"] in ("required", "preferred")]
    c = {}
    if hard:
        tw = sum(TYPE_WEIGHT[r["type"]] for r in hard)
        f1, note = few_skills(sum(TYPE_WEIGHT[r["type"]] * best_credit(r, prof, False) for r in hard) / tw,
                              len(hard), m3)
        missing = [r["term"] for r in hard if not r["hits"]]
        c["F1"] = chk("Hard skills found", "F", f1,
                      f"{len(hard) - len(missing)}/{len(hard)} found; missing: {', '.join(missing) or 'none'}" + note,
                      0.50)
    else:
        c["F1"] = chk("Hard skills found", "F", None, "no hard skills extracted", 0.50)
    if recs:
        m1, note = few_skills(sum(r["weight"] * best_credit(r, prof) for r in recs) / sum(r["weight"] for r in recs),
                              len(hard), m3)
        c["M1"] = chk("Keyword coverage (type x frequency x credit x location)", "M", m1,
                      f"{sum(1 for r in recs if r['hits'])}/{len(recs)} keywords present" + note, 0.60)
    else:
        c["M1"] = chk("Keyword coverage (type x frequency x credit x location)", "M", None, "no keywords", 0.60)
    return c


def required_coverage(recs, prof):
    req = [r for r in recs if r["type"] == "required"]
    return sum(best_credit(r, prof, False) for r in req) / len(req) if req else None


# ---------------------------------------------------------------------------
# Honesty gate
# ---------------------------------------------------------------------------
def honesty_gate(cv_text, kw, profile):
    if not profile or not profile.get("text"):
        return None, "skipped (no profile text given)"
    hard = kw.get("required_skills", []) + kw.get("preferred_skills", [])
    invented = [s for s in hard if contains(s, cv_text) and not contains(s, profile["text"])]
    return (not invented), ("invented: " + ", ".join(invented)) if invented else "all job skills in the CV exist in the profile"


# ---------------------------------------------------------------------------
# Scoring math (pure function of the state, so counterfactuals are exact)
# ---------------------------------------------------------------------------
def label_for(score):
    return next(lbl for low, lbl in SCALE if score >= low)


def evaluate(state, pname):
    prof = ATS_PROFILES[pname]
    checks = dict(state["checks"][pname])
    if not state.get("readable_only"):
        checks.update(keyword_checks(state["kw"], prof, (checks.get("M3") or {}).get("score")))
    for name, val in state.get("overrides", {}).items():
        if name in checks and checks[name]["score"] is not None:
            checks[name] = dict(checks[name], score=val)
    if state.get("readable_only"):   # no job description: the "total" is the Readable score only
        usable = [(c["score"], c["weight"]) for c in checks.values() if c["part"] == "R" and c["score"] is not None]
        r = sum(s * w for s, w in usable) / sum(w for _, w in usable) if usable else 0.0
        return {"total": r * 100, "base": r * 100, "penalty": 0, "parts": {"R": r, "F": None, "M": None},
                "gates": [], "required_coverage": None, "checks": checks}
    parts = {}
    for p in "RFM":
        usable = [(c["score"], c["weight"]) for c in checks.values() if c["part"] == p and c["score"] is not None]
        parts[p] = sum(s * w for s, w in usable) / sum(w for _, w in usable) if usable else 0.0
    base = 100.0
    for p in "RFM":
        base *= max(PART_FLOOR, parts[p]) ** PART_EXP[p]
    penalty = min(PENALTY_CAP, sum(bug_penalty(code) for code in state["bugs"]))
    total = max(0.0, base - penalty)
    gates = []
    req = required_coverage(state["kw"], prof)
    if state["honest"] is False:
        total = 0.0
        gates.append("Honesty Gate failed -> 0")
    if not state["contact"]["email"] and not state["contact"]["phone"]:
        total = min(total, CAP_NO_CONTACT)
        gates.append(f"no email and no phone -> max {CAP_NO_CONTACT}")
    if req is not None and req < LOW_REQUIRED:
        total = min(total, CAP_LOW_REQUIRED)
        gates.append(f"under {LOW_REQUIRED:.0%} of required skills -> max {CAP_LOW_REQUIRED}")
    return {"total": total, "base": base, "penalty": penalty, "parts": parts, "gates": gates,
            "required_coverage": req, "checks": checks}


def job_match_of(parts):
    """Job Match headline (0-1): Findable and Matched combined like the total does (F^0.3 x M^0.4, rescaled)."""
    if parts.get("F") is None or parts.get("M") is None:
        return None
    w = PART_EXP["F"] + PART_EXP["M"]
    return (max(PART_FLOOR, parts["F"]) ** PART_EXP["F"] * max(PART_FLOOR, parts["M"]) ** PART_EXP["M"]) ** (1 / w)


def overall_of(state):
    return sum(evaluate(state, p)["total"] for p in ATS_PROFILES) / len(ATS_PROFILES)


# Counterfactual fixes (used by the Why panel, the fix plan and the monotonicity test)
def fix_bug(state, code):
    s = copy.deepcopy(state)
    s["bugs"] = [c for c in s["bugs"] if c != code]
    for name in BUG_BY_CODE[code]["owns"]:
        s.setdefault("overrides", {})[name] = 1.0
    if code == "B4":
        s["contact"]["email"] = True
    return s


def fix_check(state, name, value=1.0):
    s = copy.deepcopy(state)
    s.setdefault("overrides", {})[name] = value
    return s


def fix_keyword(state, term, present=True):
    s = copy.deepcopy(state)
    for r in s["kw"]:
        if r["term"] == term:
            r["hits"] = [("exact", 1.0)] if present else []
    return s


# ---------------------------------------------------------------------------
# Must-haves, badge, explanations
# ---------------------------------------------------------------------------
def must_haves(state, ev):
    c = ev["checks"]
    sc = lambda n: (c[n]["score"] if n in c else None)
    bugs = set(state["bugs"])
    req = ev["required_coverage"]
    no_job = state.get("readable_only")
    return {
        "Email and phone": state["contact"]["email"] and state["contact"]["phone"],
        "Skills section with real skills": "B2" not in bugs,
        "Readable standard headings": sc("R5") == 1 and sc("R12") == 1 and sc("R11") in (None, 1),
        "Single column layout": "B8" not in bugs,
        "Job dates as Mon YYYY": sc("R7") == 1,
        "No broken text": not (bugs & set(BROKEN_TEXT_BUGS)),
        "Exact job title in headline/summary": None if no_job else sc("F3") == 1,
        f"At least {BADGE['required']:.0%} of required skills": None if no_job else (req is not None and req >= BADGE["required"]),
        "Honesty Gate passed": None if no_job else state["honest"] is True,
    }


def badge(state):
    if state.get("readable_only"):
        return False, ["no job description: Findable and Matched not scored"]
    reasons = []
    for p in STRICT_ATS:
        ev = evaluate(state, p)
        for key, part in (("readable", "R"), ("findable", "F"), ("matched", "M")):
            if ev["parts"][part] * 100 < BADGE[key]:
                reasons.append(f"{p}: {key.capitalize()} {ev['parts'][part] * 100:.0f} < {BADGE[key]}")
        if ev["total"] < BADGE["total"]:
            reasons.append(f"{p}: Total {ev['total']:.0f} < {BADGE['total']}")
        reasons += [f"{p}: {name}" for name, ok in must_haves(state, ev).items() if not ok]
    return not reasons, reasons


def explain(state):
    base = overall_of(state)
    owned = {n for code in state["bugs"] for n in BUG_BY_CODE[code]["owns"]}
    down, up = [], []
    for code in state["bugs"]:
        b = BUG_BY_CODE[code]
        down.append({"kind": "bug", "id": code, "item": f"{code} {b['name']}", "tag": b["fix"],
                     "status": b["status"], "points": overall_of(fix_bug(state, code)) - base})
    static = state["checks"]["oracle"].keys() | state["checks"]["greenhouse"].keys()
    for name in sorted(static):
        scores = [state["checks"][p][name]["score"] for p in ATS_PROFILES if name in state["checks"][p]]
        if name in owned or all(s is None for s in scores):
            continue
        cname = next(state["checks"][p][name]["name"] for p in ATS_PROFILES if name in state["checks"][p])
        if any(s is not None and s < 1 for s in scores):
            down.append({"kind": "check", "id": name, "item": f"{name} {cname}", "tag": CHECK_TAG.get(name, "content"),
                         "status": "Now", "points": overall_of(fix_check(state, name)) - base})
        if any(s for s in scores):
            up.append({"kind": "check", "id": name, "item": f"{name} {cname}",
                       "points": base - overall_of(fix_check(state, name, 0.0))})
    for r in state["kw"]:
        if r["type"] == "soft":
            continue
        if not r["hits"] or best_level(r) != "exact" or any(m < 1 for _, m in r["hits"]):
            gain = overall_of(fix_keyword(state, r["term"])) - base
            if gain > 0.01:
                down.append({"kind": "keyword", "id": r["term"], "tag": "content", "status": "Now",
                             "item": f"{r['type'].capitalize()} skill '{r['term']}' "
                                     f"({'missing' if not r['hits'] else best_level(r) + ' / weak location'})",
                             "points": gain, "note": "only if the candidate really has this skill"})
        if r["hits"]:
            up.append({"kind": "keyword", "id": r["term"], "item": f"{r['type'].capitalize()} skill '{r['term']}'",
                       "points": base - overall_of(fix_keyword(state, r["term"], False))})
    for lst in (down, up):
        for x in lst:
            x["points"] = round(x["points"], 1)
    # without a job, bugs that have no Readable check still belong in the plan (their points are not measurable)
    keep = lambda x: x["points"] > 0 or (state.get("readable_only") and x["kind"] == "bug")
    down = [x for x in down if keep(x)]
    up = [x for x in up if x["points"] > 0]
    down.sort(key=lambda x: -x["points"])
    up.sort(key=lambda x: -x["points"])
    plan = sorted(down, key=lambda x: (STATUS_RANK.get(x["status"], 0), -x["points"]))
    return {"why_down": down, "why_up": up[:10], "fix_plan": plan}


# ---------------------------------------------------------------------------
# Keywords (title rule + AI extraction, saved for reuse)
# ---------------------------------------------------------------------------
TITLE_WORDS = re.compile(
    r"\b(manager|engineer|specialist|lead|director|analyst|developer|executive|coordinator|consultant|officer|"
    r"partner|designer|head|intern|associate|planner|scientist|architect|administrator|representative|supervisor|"
    r"strategist|buyer|accountant|technician|advisor|programmer|marketer|owner|president|chief|vp|trainee|"
    r"entrepreneur|fellow|auditor)s?\b", re.I)
NOT_TITLE = re.compile(
    r"^(about|who|what|why|how|we|we're|we\u2019re|our|join|company|location|do you|are you|this|the role|role|"
    r"job description|overview|summary|responsibilities|requirements|position)\b", re.I)
KEYWORD_MIN = 10          # always try to end with at least 10 real skills
KEYWORD_MAX = 20          # never more than 20 (required first, then preferred)
MAX_SKILL_WORDS = 3       # a searchable skill is 1-3 words
LOOSE_SHARE_LOW = 0.4     # more than 40% close/mined skills -> "keyword quality: low"
# Glued words: a posting pasted without its line breaks joins words ("Software DeveloperLocation: Pittsburgh,
# PADuration: 6+ Months", "obtainProject Management"). A join = 3+ letters or digits, then a capital and 2+ lower-case
# letters ('DeveloperLocation'); or 2+ capitals, then a capital and 4+ lower-case letters ('AWXTower', 'PADuration';
# not 'APIs', 'RESTful'). Real names written this way are not joins (CAMEL_NAMES, lower case).
GLUE_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z][a-z])|(?<=[A-Z])(?=[A-Z][a-z])")
CAMEL_NAMES = set(
    "javascript typescript coffeescript actionscript powershell powerpoint powerapps github gitlab devops devsecops "
    "mlops finops dataops gitops aiops sharepoint quickbooks wordpress woocommerce hubspot netsuite successfactors "
    "servicenow peoplesoft solidworks tensorflow cloudformation cloudwatch cloudfront cloudtrail bigquery openshift "
    "openstack openai linkedin youtube tiktok whatsapp numpy scipy xgboost onedrive onenote microstrategy qlikview "
    "qliksense appdynamics newrelic sonarqube loadrunner testrail browserstack saucelabs filemaker sketchup sagemaker "
    "codepipeline codebuild codecommit elasticache eventbridge freshdesk zendesk mailchimp surveymonkey websphere "
    "weblogic clickup docusign paypal adwords adsense doubleclick godaddy solarwinds fortigate checkpoint proofpoint "
    "crowdstrike sentinelone logrhythm sailpoint cyberark onetrust blackline floqast quicksight hiveql teamcity "
    "youtrack smartsheet airtable salesloft outreachio zoominfo seamless gong dynamodb postgresql pagerduty "
    "fintech edtech proptech insurtech regtech healthtech medtech martech adtech ecommerce shotgrid openid".split())


def glued_parts(word):
    """'DeveloperLocation' -> ['Developer', 'Location']; 'PADuration' -> ['PA', 'Duration'];
    'JavaScriptNode' -> ['JavaScript', 'Node']; 'JavaScript', 'McKinsey', 'OAuth' -> one part (not glued)."""
    pieces, start = [], 0
    for m in GLUE_RE.finditer(word):
        left = word[start:m.start()]
        lower = len(re.match(r"[A-Z]([a-z]*)", word[m.start():]).group(1))     # lower-case letters after the capital
        if (left[-1:].isupper() and len(re.search(r"[A-Z]*$", left).group(0)) >= 2 and lower >= 4) or \
                (not left[-1:].isupper() and len(re.search(r"[A-Za-z0-9]*$", left).group(0)) >= 3 and lower >= 2):
            pieces.append(left)
            start = m.start()
    pieces.append(word[start:])
    merged = []
    for p in pieces:                      # put real names back together ('Java' + 'Script' -> 'JavaScript')
        if merged and any(n.startswith((merged[-1] + p).lower()) for n in CAMEL_NAMES):
            merged[-1] += p
        else:
            merged.append(p)
    return merged


def unglue(text):
    """The text with glued words split by a space ('DeveloperLocation' -> 'Developer Location')."""
    return re.sub(r"[A-Za-z0-9]+", lambda m: " ".join(glued_parts(m.group(0))), text)


def glued_skill_pieces(skill):
    """-> the skill split at its glued words, or None when no word is glued.
    'Software DeveloperLocation' -> ['Software Developer', 'Location']; 'obtainProject Management' ->
    ['obtain', 'Project Management']."""
    out, cur, split = [], [], False
    for w in skill.split():
        parts = glued_parts(w)
        split |= len(parts) > 1
        for k, p in enumerate(parts):
            if k:
                out.append(" ".join(cur))
                cur = []
            cur.append(p)
    out.append(" ".join(cur))
    return [p for p in out if p] if split else None
# Stop lists for automatic keyword cleaning.
#   KW_STOP: a ONE-word skill in this list is too generic to search for ("design", "tools").
#   VAGUE:   a multi-word skill made ONLY of these words is dropped ("creative innovation", "attention to detail").
VAGUE = {"social", "digital", "creative", "innovation", "growth", "revenue", "margins", "performance", "execution",
         "ideation", "results", "goals", "ideas", "opportunities", "environment", "mindset", "conduct", "ethical",
         "professional", "attention", "detail", "deadlines", "problem", "problems", "solving", "complex", "records",
         "tasks", "work", "quality", "thinking", "strategic", "lunch", "learns", "learn", "breakfast", "coffee",
         "socials", "perks", "benefits", "tools", "technology", "personal", "continuous", "lifelong", "self"}
VAGUE_NOUNS = {"problems", "issues", "things", "matters"}
# a phrase ending in one of these names a group of people, not a skill ("sales team", "business development team")
# a phrase ending in one of these names a quality or a judgement, not a searchable skill ("brand judgement",
# "creative evaluation"); a bare "messaging" is the same
ABSTRACT_TAILS = {"judgement", "judgment", "evaluation", "evaluations", "messaging", "acumen", "mindset"}
NOT_SKILL_TAILS = {"team", "teams", "department", "departments", "colleagues", "members", "stakeholders", "partners",
                   "company", "organisation", "organization"}
KW_STOP = {
    "social", "digital", "creative", "innovation", "revenue", "growth", "margins", "scopes", "contracts",
    "performance", "strategy", "maintenance", "design", "development", "launch", "execution", "ideation", "hiring",
    "analytical", "documenting", "reporting", "coordination", "scheduling", "follow-up", "follow", "up", "storage",
    "filters", "media", "systems", "system", "controls", "confidentiality", "records", "methodology", "tools", "tool",
    "code", "data", "process", "processes", "procedures", "operations", "project", "projects", "team", "teams",
    "client", "clients", "customer", "customers", "business", "product", "products", "service", "services",
    "solutions", "platform", "platforms", "quality", "results", "work", "tasks", "management", "support",
    "communication", "problem", "problems", "solving", "complex", "technical", "detail", "attention", "deadlines",
    "mindset", "conduct", "ethical", "professional", "environment", "opportunities", "1:1s", "goals", "ideas",
    "technology", "technologies", "lunch", "learns", "events", "event", "travel", "region",
    # abstract words from company values / culture text
    "impact", "value", "values", "excellence", "success", "passion", "culture", "mission", "vision", "purpose",
    "integrity", "diversity", "inclusion", "wellbeing", "well-being", "recognition", "rewards", "ambition", "care",
    "trust", "transparency", "curiosity", "empathy", "resilience",
}
# benefits / perks and analyst / award names are never skills ("Rewards Package", "Forrester reports")
BENEFIT_RE = re.compile(
    r"\b(rewards?|benefits?|perks?|(rewards?|benefits?|compensation|relocation) package|compensation|salary|"
    r"bonus(es)?|pension|allowances?|(annual|parental|paid|sick|maternity|paternity) leave|holidays?|wellbeing|"
    r"well-being|wellness|gym|(stock|share) options|flexible (working|work|hours)|remote working|career paths?|"
    r"career (development|growth|progression)|"
    r"(health|medical|life) insurance|learning budget|social events?|team events?|offsites?|happy hours?)\b", re.I)
AWARD_RE = re.compile(r"\b(gartner|forrester|idc|g2|capterra|magic quadrant|great place to work|best places? to work|"
                      r"best workplaces?|awards?|ranked|rankings?|recogni[sz]ed)\b", re.I)
# named activities and channels ARE skills ("trade shows", "webinars", "executive round tables", "partner events")
ACTIVITY_STEMS = {"event", "show", "webinar", "conferenc", "campaign", "workshop", "roadshow", "exhibition", "summit",
                  "meetup", "hackathon", "podcast", "newsletter", "roundtabl", "tradeshow", "expo"}
PLACES = {"uae", "gcc", "dubai", "ksa", "mena", "middle", "east", "africa", "abu", "dhabi", "sharjah", "emea",
          "global", "international", "local", "regional", "riyadh", "saudi", "qatar", "doha"}
FILLER_WORDS = {"experience", "skills", "skill", "knowledge", "ability", "abilities", "proficiency", "expertise",
                "concepts", "background", "exposure", "understanding", "capabilities", "capability", "familiarity",
                "activities", "tasks", "industry"}
QUALIFIERS = {"basic", "strong", "excellent", "good", "proven", "solid", "advanced", "deep", "hands-on", "working",
              "sound", "great", "demonstrated", "relevant", "proficient", "previous", "prior"}
DUTY_VERBS = {"build", "building", "create", "creating", "craft", "crafting", "design", "designing", "implement",
              "implementing", "maintain", "maintaining", "scale", "scaling", "identify", "identifying", "deploy",
              "deploying", "review", "reviewing", "document", "test", "testing", "evaluate", "evaluating",
              "support", "supporting", "ensure", "ensuring", "drive", "driving", "deliver", "delivering", "help",
              "helping", "own", "owning", "contribute", "contributing", "prepare", "preparing", "receive", "receiving",
              "liaise", "liaison", "handle", "handling", "spotting", "grow", "growing", "prioritize", "meet",
              "develop", "lead", "leading", "work", "working", "set", "setting", "run", "running", "host",
              "hosting", "organise", "organize", "organising", "organizing", "attend", "attending", "execute",
              "executing"}
JOB_TYPE_RE = re.compile(r"\b(internship|summer position|school job|university project|full[- ]time|part[- ]time|"
                         r"job experience|work experience)\b", re.I)
LANGUAGE_RE = re.compile(r"\b(english|arabic|french|german|hindi|urdu|spanish|bilingual|fluent|spoken)\b", re.I)


def title_from_first_line(job_text):
    first = next((l.strip() for l in job_text.splitlines() if l.strip()), "")
    cand = re.sub(r"^[^\w]+", "", first).strip()
    hiring = re.search(r"hiring\s*[:\-\u2013\u2014]\s*(.+)$", cand, re.I)
    if hiring:
        cand = re.split(r"\s[|/]\s", hiring.group(1))[0].strip()
    elif NOT_TITLE.match(cand):
        return None
    if not cand or len(cand.split()) > 8 or cand.endswith((".", "?", "!", ":")) or not TITLE_WORDS.search(cand):
        return None
    return cand


KEYWORD_PROMPT = """You are extracting ATS keywords from a job description.
Return ONLY a JSON object, no other text:
{"title": "", "required_skills": [], "preferred_skills": [], "soft_skills": [], "degree_level": "none", "min_years": 0}

Rules:
- title: the exact job title as written in the posting (e.g. "Senior Product Manager").
  NEVER a section heading ("Who You Are", "About the role", "Requirements"), a company name or a job category.
- required_skills + preferred_skills together: aim for 15-20 (NEVER more than 20) short, searchable hard skills:
  tools, software, programming languages, technical methods, certifications, domain knowledge
  (e.g. "Python", "Financial modelling", "Salesforce", "Go-to-market strategy", "IT audit", "Google Ads").
  Test for each one: would a recruiter type it into an ATS search box? If not, leave it out.
  Each is a 1-3 word noun phrase, spelled EXACTLY as in the posting (copy the posting's words, same spelling).
  NO sentences, long phrases or duty descriptions ("demand generation marketing plan", "lunch & learns",
  "liaison with customers", "crafting code for browsers"), NO teams ("sales team"), NO job titles,
  NO generic words ("social", "creative", "innovation", "tools", "growth", "revenue", "design", "launch",
  "execution", "technology"), NO languages ("English"), NO job types ("internship").
  NO qualities, judgements or soft abilities ("brand judgement", "creative evaluation", "messaging",
  "attention to detail", "strategic thinking"): those are not searched for. Keep only what a recruiter types into
  a search box: a skill, a tool or a method (e.g. "Brand Marketing", "Content Marketing", "CRM",
  "Project Management", "Google Analytics").
  Cover BOTH the duties and the requirements: include every named tool, platform, channel, method or
  format a recruiter could search for. Named activities and channels ARE skills
  (e.g. "trade shows", "webinars", "executive round tables", "partner events").
  IGNORE the company description, company values, awards and analyst reports ("Gartner", "Forrester"),
  and the benefits / perks part ("Rewards Package", "flexible working"). NO abstract words ("Impact").
  Put the most important skills first.
- required_skills: skills the posting requires or that the core duties need.
- preferred_skills: skills marked as preferred, a plus, bonus or nice to have.
- soft_skills: up to 8 personal qualities as single words or short phrases (e.g. "Communication").
- degree_level: one of none, diploma, bachelor, master, phd (minimum required).
- min_years: minimum years of experience required as a number, 0 if not stated.

JOB DESCRIPTION:
"""


RETRY_NOTE = """
IMPORTANT: a first answer gave too few hard skills. Read the duties, requirements and qualifications again
and return at least 15 hard skills, still following every rule above.
"""
AI_RUNS = 3               # the AI reads each job 3 times (temperature 0) ...
AI_MIN_VOTES = 2          # ... and a skill is kept only if it is in at least 2 of the answers


def call_ai(prompt, model):
    """One AI answer as a dict, or None when the answer is not valid JSON."""
    import requests
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("ERROR: OPENROUTER_API_KEY is not set. Run:  $env:OPENROUTER_API_KEY=\"your-key\"")
    r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": model, "temperature": 0,
                            "messages": [{"role": "user", "content": prompt}]},
                      timeout=180)
    if r.status_code != 200:
        sys.exit(f"ERROR from OpenRouter ({r.status_code}): {r.text[:300]}")
    text = re.sub(r"```json|```", "", r.json()["choices"][0]["message"]["content"])
    try:
        out = json.loads(text[text.find("{"): text.rfind("}") + 1])
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def extract_keywords_ai(job_text, model, runs=AI_RUNS):
    """The AI's raw answers: `runs` separate calls. A bad answer is asked again once."""
    answers = []
    for _ in range(runs):
        a = call_ai(KEYWORD_PROMPT + job_text, model) or call_ai(KEYWORD_PROMPT + job_text, model)
        if a:
            answers.append(a)
    if not answers:
        sys.exit("ERROR: the AI gave no valid keyword answer.")
    return answers


def skill_key(s):
    return " ".join(stem(t) for t in tokens(tidy_skill(s)))


def vote_keywords(answers):
    """Merge several AI answers into one: keep a skill only if it is in at least AI_MIN_VOTES answers.

    Same skill = same words after plurals / UK-US spelling ('KPIs' = 'KPI'). A skill goes to the list
    (required / preferred) where most answers put it; order = most votes, then average position."""
    answers = [a for a in answers if isinstance(a, dict)]
    need = min(AI_MIN_VOTES, len(answers))
    out = {}
    for field, lists in (("hard", ("required_skills", "preferred_skills")), ("soft", ("soft_skills",))):
        votes = {}                                   # key -> {"runs", "spelling", "pos", "lists"}
        for run, a in enumerate(answers):
            pos = 0
            for lst in lists:
                for s in a.get(lst) or []:
                    k = skill_key(s)
                    if not k:
                        continue
                    v = votes.setdefault(k, {"runs": set(), "spelling": tidy_skill(s), "pos": [], "lists": []})
                    if run not in v["runs"]:
                        v["runs"].add(run)
                        v["pos"].append(pos)
                        v["lists"].append(lst)
                    pos += 1
        kept = sorted((k for k in votes if len(votes[k]["runs"]) >= need),
                      key=lambda k: (-len(votes[k]["runs"]), sum(votes[k]["pos"]) / len(votes[k]["pos"])))
        for lst in lists:
            out[lst] = []
        for k in kept:
            ls = votes[k]["lists"]
            home = max(lists, key=lambda l: (ls.count(l), l == lists[0]))   # tie -> required
            out[home].append(votes[k]["spelling"])
    titles = [str(a.get("title") or "").strip() for a in answers]
    titles = [t for t in titles if t]
    out["title"] = max(titles, key=lambda t: (titles.count(t), -titles.index(t))) if titles else ""
    degrees = [str(a.get("degree_level") or "none").lower() for a in answers] or ["none"]
    out["degree_level"] = max(degrees, key=lambda d: (degrees.count(d), -degrees.index(d)))
    years = []
    for a in answers:
        try:
            years.append(float(a.get("min_years") or 0))
        except (TypeError, ValueError):
            years.append(0.0)
    years.sort()
    out["min_years"] = years[len(years) // 2] if years else 0
    return out


def add_retry(raw, retry):
    """The retry answer only adds skills that are not there yet (it never removes or reorders)."""
    if not isinstance(retry, dict):
        return raw
    raw = copy.deepcopy(raw)
    have = {skill_key(s) for lst in ("required_skills", "preferred_skills") for s in raw.get(lst) or []}
    for lst in ("required_skills", "preferred_skills"):
        for s in retry.get(lst) or []:
            k = skill_key(s)
            if k and k not in have:
                have.add(k)
                raw.setdefault(lst, []).append(tidy_skill(s))
    return raw


def content_tokens(text):
    return [t for t in tokens(text) if t not in STOPWORDS]


def tidy_skill(s):
    """'basic IT audit concepts' -> 'IT audit'; 'account management experience' -> 'account management'."""
    words = str(s).strip().strip(" .,;:").split()
    while words and words[0].lower() in QUALIFIERS:
        words.pop(0)
    while len(words) > 1 and words[-1].lower().strip(".,") in FILLER_WORDS:
        words.pop()
    return " ".join(words).strip(" .,;:")


def reject_reason(s):
    ct = content_tokens(s)
    toks = tokens(s)
    if not ct:
        return "empty"
    if len(s.split()) > MAX_SKILL_WORDS:
        return "too long"
    if toks[0] in DUTY_VERBS:
        return "duty phrase"
    if toks[-1] in NOT_SKILL_TAILS:
        return "team, not a skill"
    if toks[-1] in ABSTRACT_TAILS:
        return "a quality, not a searchable skill"
    if TITLE_WORDS.fullmatch(toks[-1]):
        return "job title, not a skill"
    if BENEFIT_RE.search(s):
        return "benefit / perk"
    if AWARD_RE.search(s):
        return "analyst / award name"
    if JOB_TYPE_RE.search(s):
        return "job type"
    if LANGUAGE_RE.search(s):
        return "language"
    if len(ct) == 1 and (ct[0] in KW_STOP or ct[0] in PLACES or ct[0] in FILLER_WORDS):
        return "generic word"
    if len(ct) > 1 and all(t in VAGUE or t in PLACES or t in FILLER_WORDS for t in ct):
        return "generic phrase"
    if any(t in VAGUE_NOUNS for t in ct):
        return "vague phrase"
    return None


SPAN_RE = re.compile(TOKEN_RE.pattern, re.I)


def posting_spelling(term, job_text):
    """-> (the posting's own words for this skill, 'exact' | 'variant' | 'close') or (None, None).

    exact:   same words ('Hubspot');  variant: plural / word form / UK-US spelling ('KPIs' for 'KPI');
    close:   all meaning words inside a span of at most 3 words ('visualization of data' -> 'data visualization').
    The returned text is copied from the posting, so every saved skill is spelled exactly as in the job."""
    spans = [(m.group(0).lower(), m.start(), m.end()) for m in SPAN_RE.finditer(job_text)]
    toks = [t for t, _, _ in spans]
    stems = [stem(t) for t in toks]
    text = lambda i, j: job_text[spans[i][1]:spans[j][2]]
    t = tokens(term)
    n = len(t)
    if not n:
        return None, None
    st = [stem(x) for x in t]
    tries = [("exact", t, toks), ("variant", st, stems)]
    if re.fullmatch(r"[A-Z]{2,6}", term.strip()):          # acronym plural: 'KPI' -> 'KPIs'
        tries.append(("variant", [t[0] + "s"], toks))
    for level, seq, hay in tries:
        hits = [text(i, i + n - 1) for i in range(len(hay) - n + 1) if hay[i:i + n] == seq]
        if hits:   # prefer the posting's occurrence with the same capitals ('Cyber', not 'cyber')
            return next((h for h in hits if h == term.strip()), hits[0]), level
    want = {stem(x) for x in content_tokens(term)}
    if want:
        for size in range(len(want), MAX_SKILL_WORDS + 1):
            for i in range(len(stems) - size + 1):
                win = stems[i:i + size]
                if want <= set(win) and win[0] in want and win[-1] in want:
                    return text(i, i + size - 1), "close"
    return None, None


COMMON_WORDS = STOPWORDS | set(
    "you your you'll you’ll we we're we’re our us i me my they them their he she will would can could may might must "
    "should shall do does did done not no yes all any some more most other such only same so than too very just also "
    "well like join apply role job jobs company team teams people candidate candidates position opportunity "
    "opportunities day days year years month months time new great good best strong ideal key ability able "
    "about what who why how when where if then there here etc including include includes within across based "
    "every each one two three first make help get take work working looking look want need needs".split())
SKILL_HEADS = {stem(w) for w in (
    "analysis analytics management engineering planning development design testing modelling modeling reporting "
    "programming marketing strategy research accounting auditing audit operations optimization automation integration "
    "security architecture compliance budgeting forecasting negotiation documentation maintenance installation "
    "troubleshooting sales procurement logistics administration governance estimation estimating modeling "
    "learning science intelligence writing copywriting editing recruitment sourcing scheduling inspection").split()}
NOT_SKILL_ACRONYMS = {"GPA", "CV", "FAQ", "EEO", "EOE", "USA", "UK", "US", "CEO", "CFO", "CTO", "COO", "MBA", "BSC",
                      "BA", "BS", "PHD", "LLC", "LTD", "FZE", "FZCO", "FZC", "AM", "PM", "OK", "ID"}
TOOL_RE = re.compile(r"(?<![\w-])([A-Z][a-z]*[A-Z][\w+#./-]*|[A-Z]{2,}[\w+#/-]*)(?![\w-])")


SKILL_CONTEXT_RE = re.compile(r"\b(knowledge|experience|proficien\w*|familiar\w*|using|use of|tools?|software|"
                              r"platforms?|skills?|stack|technolog\w*|nice to have|preferred|plus|bonus|"
                              r"requirements?|qualifications?|certifi\w*)\b", re.I)
LIST_LEAD_RE = re.compile(r"^.*?\b(?:experience (?:with|in|of)|knowledge of|proficiency (?:in|with)|"
                          r"skills? (?:in|with)|familiarity with|using|including|such as|like|plus|as well as|"
                          r"along with)\s+", re.I)


def _tool_like(word, sentence_start):
    w = word.strip(".")
    if w.upper() in NOT_SKILL_ACRONYMS or w.lower() in PLACES:
        return False
    return bool(TOOL_RE.fullmatch(w)) or (not sentence_start and w[:1].isupper() and w.lower() not in COMMON_WORDS)


def mine_posting_skills(job_text, known, need):
    """Last resort when the AI gave too few skills. In this order:
    1. items of lists in the posting ("SQL, Python and Tableau") that look like a tool or end in a skill noun
    2. 2-word phrases ending in a skill noun ("statistical modelling")
    3. acronyms seen at least twice ("ERP")"""
    found = {}   # phrase -> (tier, -count, first position)

    def add(phrase, tier, pos):
        phrase = phrase.strip(" .-")
        k = " ".join(stem(t) for t in tokens(phrase))
        if not k or k in known or reject_reason(phrase) or TITLE_WORDS.search(phrase):
            return
        t, c, p = found.get(phrase, (tier, 0, pos))
        found[phrase] = (min(t, tier), c - 1, min(p, pos))

    proper = {w.lower() for w in re.findall(r"\b[A-Z][a-z]+\b", job_text)} - \
             {w.lower() for w in re.findall(r"\b[a-z]+\b", job_text)}   # always capitalised: names, not skills
    pos = 0
    acronyms = {}
    for line in job_text.splitlines():
        body = line.strip().lstrip("-*•· ").strip()
        if (body and not body.isupper() and not re.search(r"\b(degree|bachelor|master|diploma|gpa)\b", body, re.I)
                and not LANGUAGE_RE.search(body)):                 # 'Fluent in English (reading, writing)'
            parts = re.split(r"([,;:()]|\s(?:and|or|&)\s)", body)   # text, separator, text, ...
            for k in range(0, len(parts), 2):
                raw_seg = parts[k].strip()
                cut = LIST_LEAD_RE.sub("", raw_seg)
                seg = tidy_skill(cut)
                words = seg.split()
                if (not 1 <= len(words) <= MAX_SKILL_WORDS or re.search(r"\d|[?!]|\.\s|\.[A-Z]", seg)
                        or any(t in COMMON_WORDS for t in tokens(seg) if len(t) > 1)):   # 'A/B' is not 'a'
                    continue
                # a capital only hints "tool name" mid-sentence: after "using ...", or after "," / "and" / "or"
                prev = parts[k - 1].strip() if k else ""
                start = cut == raw_seg and prev in ("", ":", ";", "(", ")")
                flags = [_tool_like(w, start and j == 0) for j, w in enumerate(words)]
                # capitals mean "tool" only on a line about skills ('knowledge of Salesforce'), not 'like Citi'
                tool = any(flags) and (len(words) <= 2 or all(flags)) and SKILL_CONTEXT_RE.search(body) is not None
                # always-capitalised names: a company ("Baker Hughes"), unless one word inside a list ("or Tableau")
                name = all(w.lower() in proper for w in words) and (len(words) > 1 or start)
                if (tool or stem(tokens(seg)[-1]) in SKILL_HEADS) and not name:
                    add(seg, 1, pos)
            for piece in re.split(r"[,;:()?!]|\.\s", body):      # 2-word phrases never cross punctuation
                toks = tokens(piece)
                for i, (a, b) in enumerate(zip(toks, toks[1:])):
                    prev = toks[i - 1] if i else ""
                    if prev and prev not in COMMON_WORDS | DUTY_VERBS | QUALIFIERS:
                        continue        # tail of a longer chain: 'computer assisted audit' is not 'assisted audit'
                    if (len(a) > 1 and a not in COMMON_WORDS and b not in COMMON_WORDS and not a.isdigit()
                            and not (a in proper and b in proper) and stem(b) in SKILL_HEADS
                            and a not in KW_STOP | VAGUE | PLACES and b not in VAGUE | PLACES | FILLER_WORDS):
                        add(f"{a} {b}", 2, len(job_text) + pos)
            for m in TOOL_RE.finditer(line):
                w = re.split(r"\.(?=[A-Z])", m.group(1))[0].strip("./-")   # "DNA.We" -> "DNA"
                if w.isupper() and 2 <= len(w) <= 6 and w not in NOT_SKILL_ACRONYMS and w.lower() not in PLACES:
                    acronyms[w] = acronyms.get(w, 0) + 1
        pos += len(line) + 1
    for w, c in acronyms.items():
        if c >= 2:
            add(w, 3, 2 * len(job_text))
    ranked = sorted(found, key=lambda p: found[p])
    out, seen = [], set()
    for p in ranked:
        k = " ".join(stem(t) for t in tokens(p))
        inside = any(f" {k} " in f" {x} " for x in seen | set(known))   # 'chain analytics' in 'supply chain analytics'
        if not inside:
            seen.add(k)
            out.append(p)
        if len(out) >= need:
            break
    return out


TITLE_LEAD_STOP = {"experienced", "new", "great", "brilliant", "strong", "talented", "seasoned", "ideal", "future",
                   "develop", "lead", "mentor", "join", "become", "hire", "hiring", "will", "can", "must"}


def find_title_in_posting(job_text):
    """Most frequent 2-4 word phrase in the posting that ends in a role word ('client partner')."""
    pat = re.compile(r"(?<![\w'’])((?:[A-Za-z][\w&+-]*\s+){1,3}" + TITLE_WORDS.pattern + ")", re.I)
    counts, first = {}, {}
    for line_no, line in enumerate(job_text.splitlines()):
        for m in pat.finditer(line):
            words = m.group(1).split()
            while words and (words[0].lower() in COMMON_WORDS or words[0].lower() in TITLE_LEAD_STOP):
                words.pop(0)
            if not 2 <= len(words) <= 4 or any(w.lower() in COMMON_WORDS for w in words):
                continue
            key = " ".join(words).lower()
            counts[key] = counts.get(key, 0) + 1
            first.setdefault(key, (line_no, m.start()))
    if not counts:
        return None
    best = sorted(counts, key=lambda k: (-counts[k], first[k]))[0]
    return " ".join(w if w.isupper() else w.capitalize() for w in best.split())


def choose_title(ai_title, job_text):
    """-> (title, source, warning or None). The title must be in the posting, never a heading like 'Who You Are'."""
    first = title_from_first_line(job_text)
    if first:
        return first, "first line", None
    t = str(ai_title or "").strip()
    if t and (" | " in t or JOB_TYPE_RE.fullmatch(t)):   # 'Internship | FY27' -> the posting's whole header line
        line = next((l.strip() for l in job_text.splitlines()
                     if " | " in l and t in l and len(l.strip()) > len(t)), None)
        t = line or t
    segs = [s.strip() for s in re.split(r"\s\|\s", t) if s.strip()]
    if len(segs) > 1:  # "Audit | IT Audit | Internship | FY27" -> the most title-like part
        plain = [s for s in segs if not re.search(r"\bfy\d+|\binternship\b|\d{4}", s, re.I)] or segs
        t = next((s for s in segs if TITLE_WORDS.search(s)), None) or max(plain, key=len)
    # drop location parts: "Field Marketing Manager - MENA - Dubai, UAE" -> "Field Marketing Manager"
    parts = [p.strip() for p in re.split(r"\s[-–—|]\s|,", t) if p.strip()]
    where = lambda p: all(x in PLACES or x in ("remote", "hybrid", "onsite") for x in tokens(p))
    if len(parts) > 1 and not where(parts[0]) and all(where(p) for p in parts[1:]):
        t = parts[0]
    if t and not NOT_TITLE.match(t) and not JOB_TYPE_RE.fullmatch(t) and contains(t, job_text):
        return t, "ai (found in posting)", None
    found = find_title_in_posting(job_text)
    if found:
        return found, "posting phrase", f"AI title '{t}' is not in the posting; used '{found}' from the posting"
    return t, "ai (not verified)", f"job title '{t}' was not found in the posting"


# Posting parts: skills only come from the role part, never from the company description, values or benefits.
ROLE_HEADS = (r"who we(?:'|’)?re looking for|who you are|about the (?:role|job|position|opportunity)|"
              r"role overview|the role|your role|what you(?:'|’)?ll do|what you will do|key responsibilities|"
              r"responsibilities|duties|(?:preferred|desired|minimum) qualifications|qualifications|requirements|"
              r"skills (?:&|and) experience|nice to have|what you(?:'|’)?ll bring|what you bring|"
              r"job description|role")
DROP_HEADS = (r"about us|about the company|about (?-i:[A-Z])[\w&.’'-]*|who we are|our (?:story|values|culture|mission)|"
              r"life at [\w .]+|why (?:join|work)[\w .'’]*|benefits(?: (?:&|and) rewards(?: package)?)?|"
              r"perks(?: (?:&|and) benefits)?|what we offer|what to expect from us|compensation(?: (?:&|and) benefits)?|"
              r"rewards|equal (?:employment )?opportunit\w*|our commitment[\w ]*|"
              r"[^\n.:]{0,40}\b(?:perks|benefits)\b[^\n.:]{0,40}(?=:)")
POSTING_HEAD_RE = re.compile(rf"(?:^|(?<=[.!?\n]))[ \t]*(?:(?P<keep>{ROLE_HEADS})|(?P<drop>{DROP_HEADS}))"
                             rf"[ \t]*(?::|(?=[ \t]*(?:\n|$)))", re.I | re.M)
# a company / benefits part ends where the role text starts again (Deloitte: "During your tenure ... you will")
ROLE_START_RE = re.compile(r"\b(you will|you’ll|you'll|you have|you bring|your (?:main )?responsibilit\w*|"
                           r"responsibilities|requirements|qualifications|during your|in this role|knowledge of|"
                           r"experience (?:in|with)|ability to)\b", re.I)
WE_RE = re.compile(r"\b(we|we're|we’re|we've|we’ve|our|us)\b", re.I)
WE_START_RE = re.compile(r"^\W*(we|we're|we’re|we've|we’ve|our|at [A-Z]\w+,)\b", re.I)
YOU_RE = re.compile(r"\b(you|your|you'll|you’ll|you're|you’re|looking for|seeking|hiring|this role|"
                    r"the role|this position|candidates?)\b", re.I)   # sentence is about the role, not the company
NOT_ROLE_RE = re.compile(
    # perks and benefits
    r"\b(perks?|stipend|dental|parental leave|maternity|paternity|pension|401k|rrsp|paid time off|pto|"
    r"health (?:insurance|benefits|cover)|medical (?:insurance|cover)|life insurance|annual leave|gym|"
    r"wellness (?:programs?|programmes?|allowance|benefits?|days?|credit)|fitness/wellness|"
    r"competitive (?:salary|pay|package|compensation)|stock options|equity package|"
    # hiring process, legal, privacy, scams, diversity
    r"(?:recruitment|application|hiring|interview) process|submitting this application|privacy notice|"
    r"personal data|job scams?|scam|third-party (?:services|recruiters|agencies)|official [\w ]{0,20}channels|"
    r"emails you receive|false or incorrect|wilfully|willfully|i confirm|i accept|i agree|i have disclosed|"
    r"equal (?:employment )?opportunit\w*|diverse (?:backgrounds|talent)|inclusive workplace|diversity|"
    r"reasonable accommodations?|we encourage applications|will be in touch|next stage|when applying|"
    r"background checks?|right to work|"
    # company description
    r"who are we|we believe|our mission|headquartered|offices in|founded in|"
    r"(?:is|are) (?:the|a|an) (?:[\w&]+[- ]){0,6}(?:company|companies|firm|organi[sz]ation|employer|"
    r"bank|startup|group|team of))\b|@[\w-]+\.(?:com|ae|org|net|io)\b", re.I)
# a sentence that clearly describes the job is never dropped as perks / company text
ROLE_DUTY_RE = re.compile(r"\b(you will|you’ll|you'll|you have|you bring|you should|responsible for|"
                          r"experience (?:in|with)|knowledge of|ability to|in this role)\b", re.I)


def skill_text(job_text):
    """The role part of the posting only: drops the company description, values, benefits and perks.

    - text under a company / benefits heading ('About us', 'Benefits', 'What to expect from us') is dropped
    - text before the first role heading ('Who we're looking for', 'Responsibilities') is dropped when it
      talks about the company ('we', 'our')
    - in the role part, a sentence about the company ('we ... our ...', no 'you', no skill words) is dropped
    Works on headings stuck to sentences too ('...United Arab Emirates.Responsibilities: ...')."""
    text = job_text.replace("\\n", "\n")          # some postings hold a typed "\n" instead of a line break
    heads = list(POSTING_HEAD_RE.finditer(text))
    blocks = []                                     # (kind, text)
    lead = text[: heads[0].start()] if heads else text
    if not heads or not (any(h.group("keep") for h in heads) and WE_RE.search(lead)):
        blocks.append(("keep", lead))
    for h, nxt in zip(heads, heads[1:] + [None]):
        body = text[h.end(): nxt.start() if nxt else len(text)]
        if h.group("keep"):
            blocks.append(("keep", body))
            continue
        lines = body.split("\n")
        start = next((i for i, l in enumerate(lines) if i > 0 and ROLE_START_RE.search(l)), None)
        if start is not None:                 # the role text starts again inside this part: keep from there
            blocks.append(("keep", "\n".join(lines[start:])))

    def company_talk(sent):
        we = len(WE_RE.findall(sent))
        if ((we >= 2 or (we and WE_START_RE.search(sent))) and not YOU_RE.search(sent)
                and not SKILL_CONTEXT_RE.search(sent)):
            return True
        # perks, hiring process, legal / privacy / scam notices, diversity statements, company description:
        # dropped anywhere in the posting, unless the sentence clearly describes the role ('you will manage benefits')
        return bool(NOT_ROLE_RE.search(sent)) and not ROLE_DUTY_RE.search(sent)

    sents = [s.strip() for _, body in blocks
             for s in re.split(r"(?<=[.!?])\s+|(?<=[a-z][.!?])(?=[A-Z])|\n", body) if s.strip()]
    drop = [company_talk(s) for s in sents]
    for i, s in enumerate(sents):            # a short line between two dropped ones belongs to them ('Report it.')
        if 0 < i < len(sents) - 1 and drop[i - 1] and drop[i + 1] and len(s.split()) < 6:
            drop[i] = True
    return "\n".join(s for s, d in zip(sents, drop) if not d)


DUTY_REQ_HEAD_RE = re.compile(r"responsibilit|duties|what you(?:'|’)?ll do|what you will do|requirement|"
                              r"qualification|skills (?:&|and) experience|what you(?:'|’)?ll bring|what you bring|"
                              r"who you are|who we(?:'|’)?re looking for|nice to have", re.I)


# a line that opens a list about the role: "you will be responsible for:", "To be successful in this role you will:"
ROLE_LEAD_RE = re.compile(r"\b(you will|you['’]ll|you are|you have|you bring|you need|you should|responsib\w*|"
                          r"successful|requirements?|qualifications?|duties|in this role|ideal candidate|"
                          r"looking for|must have|should have|key skills|skills|experience)\b", re.I)
OFFER_LEAD_RE = re.compile(r"\b(we (?:will |can )?(?:provide|offer|give)|offer you|benefits?|perks?|in return|"
                           r"what we offer|rewards?)\b", re.I)
BULLET_RE = re.compile(r"^\s*([-*•·▪●◦–]|\d+[.)])\s*")


def role_list_lines(text):
    """Lines of each list that follows a role lead-in line ending in ':'. A list ends at the next line ending
    in ':' or at a short heading-like line after a blank line ('Fuel your passion')."""
    out, inside, gap = [], False, False
    for line in text.split("\n"):
        body = line.strip()
        if not body:
            gap = True
            continue
        bullet = bool(BULLET_RE.match(body))
        if body.endswith(":") and not bullet:
            inside, gap = bool(ROLE_LEAD_RE.search(body)) and not OFFER_LEAD_RE.search(body), False
            continue
        if inside and gap and not bullet and len(body.split()) <= 6 and not body.endswith((".", ",", ";")):
            inside = False                                  # a heading after a blank line ends the list
        if inside and OFFER_LEAD_RE.search(body):
            inside = False                                  # 'we will provide you with ...' is the company's part
        if inside:
            out.append(BULLET_RE.sub("", body))
        gap = False
    return out


def duty_and_requirement_text(job_text):
    """Role list text: under requirements / responsibilities / qualifications headings, and the lists after any
    role lead-in line ('you will be responsible for:'). '' if the posting has neither."""
    text = job_text.replace("\\n", "\n")
    heads = list(POSTING_HEAD_RE.finditer(text))
    parts = []
    for h, nxt in zip(heads, heads[1:] + [None]):
        if h.group("keep") and DUTY_REQ_HEAD_RE.search(h.group("keep")):
            body = text[h.end(): nxt.start() if nxt else len(text)]
            parts.extend(s.strip() for s in re.split(r"(?<=[a-z][.!?])(?=[A-Z])|\n", body) if s.strip())
    for line in role_list_lines(text):
        if line not in parts:
            parts.append(line)
    return "\n".join(parts)


def activity_skills(text):
    """Named activities and channels in list form ('webinars, events, executive round tables, trade shows')."""
    out = []
    for line in text.splitlines():
        for seg in re.split(r"[,;:()]|\s(?:and|or|&)\s", line):
            words = tidy_skill(LIST_LEAD_RE.sub("", seg.strip())).split()
            while words and words[0].lower() in DUTY_VERBS:      # "Run webinars" -> "webinars"
                words.pop(0)
            seg = " ".join(words)
            toks = tokens(seg)
            if not toks or len(seg.split()) > MAX_SKILL_WORDS or any(t in COMMON_WORDS for t in toks if len(t) > 1):
                continue
            if stem(toks[-1]) in ACTIVITY_STEMS or (toks[-1].startswith("table") and toks[-2:-1] == ["round"]):
                out.append(seg)
    return out


DEGREE_WORD_RE = re.compile(r"\b(degrees?|bachelor['’]?s?|master['’]?s?|diploma|ph\.?d|doctorate|b\.?sc|m\.?sc|mba|"
                            r"ba/bs|b\.?a\.?|b\.?s\.?|graduated? with|major(?:ed|ing)? in|field of study)\b", re.I)
SUBJECT_STOP = {"related", "similar", "equivalent", "relevant", "field", "fields", "preferably", "discipline",
                "area", "areas", "top", "tier", "university", "quantitative"}


def degree_sentences(job_text):
    parts = re.split(r"(?<=[.!?;])\s+|\n", job_text.replace("\\n", "\n"))
    return [p.strip() for p in parts if DEGREE_WORD_RE.search(p)]


def is_degree_subject(skill, job_text):
    """True when the posting names this skill ONLY in degree sentences ('BA/BS in Computer Science, ...')."""
    sents = [p.strip() for p in re.split(r"(?<=[.!?;])\s+|\n", job_text.replace("\\n", "\n")) if p.strip()]
    hits = [s for s in sents if contains(skill, s)]
    return bool(hits) and all(DEGREE_WORD_RE.search(s) for s in hits)


def degree_subjects(job_text):
    """Subjects listed after a degree word: 'Bachelor's degree in Engineering (all fields), Mathematics, or similar'
    -> ['Engineering', 'Mathematics']. Spelled exactly as in the posting."""
    out = []
    for sent in degree_sentences(job_text):
        m = re.search(DEGREE_WORD_RE.pattern + r"[^.;]*?\b(?:in|of)\s+(.+)", sent, re.I)
        if not m:
            continue
        rest = re.sub(r"\([^)]*\)", "", m.group(m.lastindex))
        for item in re.split(r"[,;/]|\s(?:or|and|&)\s", rest):
            words = item.strip(" .:-").split()
            toks = tokens(item)
            if (not 1 <= len(words) <= 4 or re.search(r"\d", item)
                    or any(t in COMMON_WORDS or t in SUBJECT_STOP for t in toks)):
                continue
            s = " ".join(words)
            if skill_key(s) not in {skill_key(x) for x in out}:
                out.append(s)
    return out


def clean_keywords(raw, job_text):
    """Turn the AI's raw answer into clean keywords. Runs on every load, so it works the same for any job.

    0. use only the role part of the posting (no company description, values, benefits or perks)
    1. tidy + stop lists (generic words, long phrases, duty phrases, teams, benefits, awards, languages, job types)
    2. copy each skill's spelling from the posting (exact, or plural / UK-US variant)
    3. add named activities and channels listed in the posting ("trade shows", "webinars")
       (every step: near-duplicates are merged, the more important skill stays; degree subjects such as
       'Computer Science' go to education_keywords, not skills; a skill with glued words from a posting pasted
       without line breaks ('Software DeveloperLocation') is split and only the real skills inside are kept -
       see place())
    4. if fewer than 10: close matches (all words within 3 words of each other in the posting), then
       short tool names / skill phrases from the requirements and responsibilities sections, then from
       the rest of the role text
    5. at most 20 skills (1-3 words each), required first; education_keywords = degree subjects
    6. quality warning when the result is still weak
    """
    full_text = job_text
    job_text = skill_text(full_text) or full_text
    seen, dropped, sources = set(), [], {}
    out = {"required_skills": [], "preferred_skills": [], "soft_skills": []}
    education = []
    key_of = lambda s: " ".join(stem(t) for t in tokens(s))
    inside = lambda a, b: f" {a} " in f" {b} "
    close = []
    unglued = unglue(job_text)
    # words the posting writes on their own (not inside a glued word): with a capital / in lower case
    alone = r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])"
    own_caps = set(re.findall(alone % r"[A-Z][A-Za-z0-9+#]*", job_text))
    own = set(re.findall(alone % r"[a-z][a-z0-9+#]*", job_text))

    def place(s, lst, source):
        """Add a hard skill unless it is a near-duplicate of one already kept. Near-duplicate = one skill inside
        the other, also across a slash ('portfolio management' / 'program/portfolio management'). The skill kept
        first stays: skills arrive most important first (required, in AI order), so 'IT audit' is never lost to
        a later generic 'auditing'."""
        k = key_of(s)
        if k in seen:
            return False
        pieces = glued_skill_pieces(s)
        if pieces:                              # glued words from a pasted posting: keep only real skills inside
            dropped.append({"term": s, "reason": "glued words: split"})
            for p in pieces:
                p = tidy_skill(p)
                spelled, level = posting_spelling(p, unglued) if p and not reject_reason(p) else (None, None)
                # one word alone: only a name the posting also writes on its own, always with a capital ('Spark';
                # not 'Duration', only glued; not 'Components', also written 'components')
                if spelled and level in ("exact", "variant") and not reject_reason(spelled) and \
                        not glued_skill_pieces(spelled) and (len(tokens(spelled)) > 1 or
                                                             (spelled in own_caps and spelled.lower() not in own)):
                    place(spelled, lst, source + " (split)")
            return False
        if is_degree_subject(s, full_text):     # named only in 'Bachelor's degree in ...' -> education, not a skill
            if k not in {key_of(e) for e in education}:
                education.append(s)
                dropped.append({"term": s, "reason": "degree subject -> education_keywords"})
            return False
        twin = next((x for l in ("required_skills", "preferred_skills") for x in out[l]
                     if inside(key_of(x), k) or inside(k, key_of(x))), None)
        if twin:
            dropped.append({"term": s, "reason": f"near-duplicate of '{twin}'"})
            return False
        out[lst].append(s)
        seen.add(k)
        sources[s] = source
        return True
    for key in ("required_skills", "preferred_skills", "soft_skills"):
        for s in raw.get(key, []) or []:
            s = tidy_skill(s)
            if not s or key_of(s) in seen:
                continue
            if key == "soft_skills":
                if len(out[key]) < 8:
                    seen.add(key_of(s))
                    out[key].append(s)
                continue
            why = reject_reason(s)
            spelled, level = (None, None) if why else posting_spelling(s, job_text)
            if spelled and not why:
                why = reject_reason(spelled)
            if why:
                dropped.append({"term": s, "reason": why})
            elif level in ("exact", "variant"):
                place(spelled, key, "posting")
            elif level == "close":
                close.append((key, s, spelled))
            elif posting_spelling(s, full_text)[0]:
                dropped.append({"term": s, "reason": "only in company / benefits part"})
            else:
                dropped.append({"term": s, "reason": "not in posting"})

    hard = lambda: len(out["required_skills"]) + len(out["preferred_skills"])
    for a in activity_skills(job_text):
        s, _ = posting_spelling(a, job_text)
        if s and not reject_reason(s):
            place(s, "preferred_skills", "activity in posting")
    for key, s, spelled in close:
        if hard() >= KEYWORD_MIN:
            dropped.append({"term": s, "reason": "close match not needed"})
        else:
            place(spelled, key, "close match")
    # still under 10: short skills from the requirements / responsibilities sections first, then the whole role text
    for text, label in ((duty_and_requirement_text(full_text), "requirements / responsibilities"),
                        (job_text, "mined from posting")):
        if hard() >= KEYWORD_MIN or not text:
            continue
        for s in mine_posting_skills(text, seen, 2 * (KEYWORD_MIN - hard())):   # extra: some may be duplicates
            if hard() >= KEYWORD_MIN:
                break
            spelled, level = posting_spelling(s, job_text)
            if spelled and level in ("exact", "variant") and not reject_reason(spelled):   # posting's own words only
                place(spelled, "preferred_skills", label)
    while hard() > KEYWORD_MAX:   # keep the first 20: all required (in AI order) before preferred
        lst = out["preferred_skills"] if out["preferred_skills"] else out["required_skills"]
        s = lst.pop()
        sources.pop(s, None)
        dropped.append({"term": s, "reason": f"over the {KEYWORD_MAX}-skill limit"})

    title, title_source, title_warning = choose_title(raw.get("title"), full_text)
    n = hard()
    loose = sum(1 for v in sources.values() if v not in ("posting", "activity in posting"))
    reasons = []
    if n < KEYWORD_MIN:
        reasons.append(f"only {n} skills (want {KEYWORD_MIN})")
    if n and loose / n > LOOSE_SHARE_LOW:
        reasons.append(f"{loose} of {n} skills are close matches or mined from the posting")
    if title_warning:
        reasons.append(title_warning)
    try:
        min_years = float(raw.get("min_years") or 0)
    except (TypeError, ValueError):
        min_years = 0
    for subj in degree_subjects(full_text):
        if key_of(subj) not in {key_of(e) for e in education}:
            education.append(subj)
    related_ok = any(re.search(r"\b(related|similar|equivalent|relevant)\b", d, re.I) for d in degree_sentences(full_text))
    return {"title": title, "title_source": title_source, **out, "skill_sources": sources,
            "education_keywords": education[:KEYWORD_MAX], "education_related_ok": related_ok,
            "degree_level": str(raw.get("degree_level") or "none").lower(), "min_years": min_years,
            "dropped": dropped, "quality": {"level": "low" if reasons else "ok", "reasons": reasons}}


JOB_WORDS_RE = re.compile(r"\b(responsibilit\w*|requirements?|qualifications?|experience|skills?|you will|you['’]ll|"
                          r"role|position|candidates?|degree|duties|apply|hiring|job)\b", re.I)
HTML_TAG_RE = re.compile(r"<\s*/?\s*[a-z][\w-]*(?:\s[^<>]*)?>", re.I)
MIN_JOB_WORDS = 80          # a real job description is longer than this


class NotAJob(ValueError):
    """The .txt file is a web page or not a job description: no keywords, no AI call."""


def not_a_job_reason(text):
    """-> why this text is not a job description, or None when it looks like one."""
    words = re.findall(r"[A-Za-z]{2,}", text)
    tags = len(HTML_TAG_RE.findall(text))
    if re.match(r"\s*(<!doctype\s+html|<html\b)", text, re.I) or (tags >= 10 and tags * 10 > len(words)):
        return f"web page (HTML code, {tags} tags), not a job description"
    if len(words) < MIN_JOB_WORDS:
        return f"too short for a job description ({len(words)} words, want {MIN_JOB_WORDS}+)"
    found = {m.lower().replace("’", "'") for m in JOB_WORDS_RE.findall(text)}
    if len(found) < 3:
        return "no job-description words (responsibilities, requirements, experience, role, ...)"
    return None


def keywords_path(job_path):
    return os.path.splitext(job_path)[0] + "_keywords_v3.json"


def read_raw_keywords(path):
    """The saved file holds the AI's raw answers. New files: 3 answers (voted here, so the rule lives in code)
    + an optional retry answer. Older files: one answer ('ai_raw') or cleaned lists, read back as raw."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("ai_runs"):
        return add_retry(vote_keywords(data["ai_runs"]), data.get("ai_retry"))
    if "ai_raw" in data:
        return data["ai_raw"]
    legacy = [d["term"] if isinstance(d, dict) else d for d in data.get("dropped", [])]
    return {"title": data.get("title", ""), "required_skills": data.get("required_skills", []) + legacy,
            "preferred_skills": data.get("preferred_skills", []), "soft_skills": data.get("soft_skills", []),
            "degree_level": data.get("degree_level", "none"), "min_years": data.get("min_years", 0)}


def load_keywords(job_path, model):
    """v3 reads and writes ONLY Name_keywords_v3.json. The v2 Name_keywords.json files are never opened."""
    with open(job_path, encoding="utf-8", errors="ignore") as f:
        job_text = f.read()
    why = not_a_job_reason(job_text)
    if why:
        raise NotAJob(f"{os.path.basename(job_path)} skipped: {why}")
    path = keywords_path(job_path)
    too_few = lambda r: (lambda kw: len(kw["required_skills"]) + len(kw["preferred_skills"]) < KEYWORD_MIN)(
        clean_keywords(r, job_text))
    if os.path.exists(path):
        raw = read_raw_keywords(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # saved before a rule change and now under 10: run the one retry it never had (the 3 answers stay)
        if model and data.get("ai_runs") and data.get("ai_retry") is None and too_few(raw):
            data["ai_retry"] = call_ai(KEYWORD_PROMPT + RETRY_NOTE + "\n" + job_text, model)
            raw = add_retry(raw, data["ai_retry"])
            data["ai_raw"] = raw
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"   (retry added to {path})")
    elif not model:
        sys.exit(f"ERROR: {path} not found. Add --model to extract keywords with AI.")
    else:
        runs = extract_keywords_ai(job_text, model)
        raw = vote_keywords(runs)
        retry = None
        if too_few(raw):                       # too few: ask the AI once more
            retry = call_ai(KEYWORD_PROMPT + RETRY_NOTE + "\n" + job_text, model)
            raw = add_retry(raw, retry)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"model": model, "created": TODAY.isoformat(), "temperature": 0,
                       "method": f"{len(runs)} AI answers, a skill is kept if it is in at least "
                                 f"{min(AI_MIN_VOTES, len(runs))}; retry once if under {KEYWORD_MIN} skills",
                       "ai_raw": raw, "ai_runs": runs, "ai_retry": retry}, f, indent=2, ensure_ascii=False)
        print(f"   (keywords saved to {path})")
    return clean_keywords(raw, job_text)


# ---------------------------------------------------------------------------
# Score one CV  (job_path=None -> Readable score + bug list only)
# ---------------------------------------------------------------------------
def build_state(doc, job_text, kw, profile=None):
    ana = analyse(doc)
    bugs = detect_bugs(doc, ana)
    readable_only = kw is None
    honest, h_detail = (None, "skipped (no job description)") if readable_only else honesty_gate(doc["modern"], kw, profile)
    checks = {}
    for pname, prof in ATS_PROFILES.items():
        c = readable_checks(doc, ana, bugs, prof)
        if not readable_only:
            c.update(findable_static(doc, ana, kw, profile, prof))
            c.update(matched_static(doc, ana, job_text, kw))
        checks[pname] = c
    state = {"checks": checks, "kw": [] if readable_only else keyword_records(kw, ana, job_text),
             "bugs": [code for code, b in bugs.items() if b["found"]],
             "contact": {"email": bool(EMAIL_RE.search(doc["modern"])), "phone": bool(PHONE_RE.search(doc["modern"]))},
             "honest": honest, "readable_only": readable_only}
    return state, bugs, ana, h_detail


def r1(v, scale=1):
    return None if v is None else round(v * scale, 1)


# ---------------------------------------------------------------------------
# What the ATS sees: the fields a parser fills in
# ---------------------------------------------------------------------------
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w\-%]+/?", re.I)
CITY_COUNTRY_RE = re.compile(r"^[A-Z][A-Za-z.'\- ]{1,30},\s*[A-Z][A-Za-z.'\- ]{1,30}$")
TITLE_SPLIT_RE = re.compile(r"\s[|\u2014\u2013]\s|\s-\s|\s+at\s+|\s*@\s+")
COUNTRIES = ("united arab emirates", "uae", "saudi arabia", "ksa", "qatar", "kuwait", "bahrain", "oman", "egypt",
             "jordan", "lebanon", "iraq", "syria", "morocco", "tunisia", "algeria", "turkey", "iran", "pakistan",
             "india", "sri lanka", "bangladesh", "nepal", "philippines", "indonesia", "malaysia", "singapore",
             "china", "hong kong", "japan", "south korea", "australia", "new zealand", "united kingdom", "uk",
             "england", "ireland", "france", "germany", "netherlands", "spain", "italy", "portugal", "switzerland",
             "sweden", "poland", "united states", "usa", "us", "canada", "mexico", "brazil", "south africa",
             "nigeria", "kenya", "remote")
COUNTRY_END_RE = re.compile(r"(?:^|[\s,])(?:" + "|".join(re.escape(c) for c in COUNTRIES) + r")\.?$", re.I)
CUT_END_WORDS = {"and", "of", "for", "the", "to", "in", "with", "&", "a", "an", "or", "at", "-", "/", ","}


def contact_segments(ana):
    """Header text cut into pieces at | . bullets and column gaps ('Dubai, UAE | +971 ... | jane@x.com')."""
    segs = []
    for r in ana["header"]:
        for c in r["cells"]:
            segs += [x.strip(" |\u2022\u00b7\u25aa\u25cf,;") for x in re.split(r"\s[|\u2022\u00b7\u25aa\u25cf]\s|\s{2,}", c)
                     if x.strip(" |\u2022\u00b7\u25aa\u25cf,;")]
    return segs


def is_place(seg):
    """'Dubai, UAE' / 'United Arab Emirates' / 'Freelance - Remote, Egypt' end: a place, not a role or a slogan."""
    seg = seg.strip(" ,|")
    if not seg or re.search(r"[@\d]|https?:|www\.|linkedin", seg, re.I) or TITLE_WORDS.search(seg):
        return False
    return bool(len(seg.split()) <= 6 and (COUNTRY_END_RE.search(seg) or CITY_COUNTRY_RE.match(seg)))


def find_location(ana):
    return next((seg for seg in contact_segments(ana)[1:] if is_place(seg)), None)


def title_problem(title, max_words=12):
    """Why a job title looks cut off or merged with other text (None if it looks fine).
    max_words=None for a headline ('Title | skill | skill' is long on purpose): only cut-off is checked."""
    t = title.strip()
    words = t.split()
    if not words:
        return "empty"
    if words[-1].lower().strip(".") in CUT_END_WORDS or t.endswith(("-", "/", ",", "&", "(")):
        return f"cut off (ends with '{words[-1]}')"
    if t[0].islower():
        return "cut off (starts in lower case)"
    if max_words is None:
        return None
    if len(words) > max_words:
        return f"merged with other text ({len(words)} words)"
    if POINT_RE.search(t) or EMAIL_RE.search(t) or DURATION_RE.search(t):
        return "merged with a date, duration or email"
    if len(re.findall(r"[.!?]\s+[A-Z]", t)):
        return "merged with a sentence"
    return None


def split_title(line):
    """'Operations Manager | Acme LLC' -> ('Operations Manager', 'Acme LLC')."""
    parts = [x.strip() for x in TITLE_SPLIT_RE.split(line, maxsplit=1) if x.strip()]
    return (parts[0], parts[1]) if len(parts) == 2 else (line.strip(), None)


def drop_place(text):
    """'CRITEO - Dubai, UAE' -> 'CRITEO'; 'Babygrow FZC - Sharjah, UAE' -> 'Babygrow FZC'."""
    parts = [x.strip() for x in re.split(r"\s[\u2013\u2014|-]\s|\s\u2022\s", text) if x.strip()]
    while len(parts) > 1 and is_place(parts[-1]):
        parts.pop()
    if len(parts) == 1 and "," in parts[0]:
        head, tail = parts[0].rsplit(",", 1)
        if is_place(tail) and not is_place(head):
            return head.strip()
    return " - ".join(parts)


def company_above(job, lines):
    """The company on the short line ABOVE the job line ('BLR WORLD (Dubai, U.A.E)' / 'Designer January 2025 -
    Present'), or None."""
    prev = lines[job["line"] - 1].strip() if 0 < job["line"] <= len(lines) else ""
    if prev and len(prev.split()) <= 10 and not prev.endswith((".", ",")) and not find_ranges(prev)             and not date_only(prev) and not re.match(r"^[•\-*▪●·]", prev):
        return drop_place(prev) or None
    return None


def job_title_company(job, lines):
    """Title and company of a job. The job line has the title (or company) and dates; the short line under it,
    if any, has the other one. The line with a role word ('Manager', 'Coordinator') is the title."""
    first = job["title"].strip()
    nxt = lines[job["line"] + 1].strip() if job["line"] + 1 < len(lines) else ""
    second = None
    if (nxt and len(nxt.split()) <= 9 and not nxt.endswith(".") and not re.match(r"^[\u2022\-*\u25aa\u25cf\u00b7]", nxt)
            and not find_ranges(nxt) and not date_only(nxt)):
        second = nxt
    head = re.split(r"\s\|\s", first)[0].strip()       # 'Title | specialism | dates' -> 'Title'
    if second is None:
        title, company = split_title(first)
        company = drop_place(company) if company else None
        return title, (company or company_above(job, lines))
    head_place, second_place = drop_place(head) != head, drop_place(second) != second
    if ((TITLE_WORDS.search(second) and not TITLE_WORDS.search(head))
            or (head_place and not second_place)):        # the line with a place is the company line
        return second, drop_place(head)                   # 'Babygrow FZC - Sharjah, UAE' / 'Logistics Coordinator'
    return head, drop_place(second)


def ats_fields(doc, ana):
    """The fields an ATS parser fills in from this CV (what the recruiter's screen shows)."""
    head = [r["text"].strip() for r in ana["header"]]
    email = EMAIL_RE.search(doc["modern"])
    phone = PHONE_RE.search(doc["modern"])
    linkedin = LINKEDIN_RE.search(doc["modern"])
    headline = next((l for l in head[1:4] if not re.search(r"@|\+?\d{6,}", l) and 2 <= len(l.split()) <= 20), None)
    jobs = []
    exp_lines = [r["text"].strip() for sec in ana["sections"] if sec["kind"] == "experience" for r in sec["rows"]]
    for j in ana["jobs"]:
        title, company = job_title_company(j, exp_lines)
        jobs.append({"title": title, "company": company, "dates": j["dates"] or None,
                     "date_problem": j["problem"], "title_problem": title_problem(title)})
    edu_rows = [r["text"].strip() for r in section_rows(ana, "education")]
    education = [l for l in edu_rows if any(re.search(pat, l.lower()) for _, pat in DEGREE_PATTERNS)
                 or re.search(r"\b(university|college|institute|school|academy)\b", l, re.I)]
    skills = []
    for sec in ana["sections"]:
        if sec["kind"] in ("skills", "competencies"):
            skills += skill_items(sec["rows"])
    return {"name": head[0] if head else None, "email": email.group(0) if email else None,
            "phone": phone.group(1).strip() if phone else None, "location": find_location(ana),
            "linkedin": linkedin.group(0) if linkedin else None, "headline": headline,
            "headline_problem": title_problem(headline, max_words=None) if headline else None,
            "sections": [s["title"] for s in ana["sections"]], "jobs": jobs, "education": education[:6],
            "skills": skills}


# ---------------------------------------------------------------------------
# Smell checks: "possible new bug" (shown, never scored)
# ---------------------------------------------------------------------------
SMELL_SYMBOLS = [("'<' or '>' code", re.compile(r"</?[A-Za-z!]|[A-Za-z\"'/]>|&lt;|&gt;")), ("'**'", re.compile(r"\*\*")),
                 ("backtick", re.compile(r"`")), ("'{' or '}'", re.compile(r"[{}]")),
                 ("PDF glyph code (cid:N)", re.compile(r"\(cid:\d+\)")),
                 ("'#'", re.compile(r"(?<![A-Za-z])#(?![\d\s]?\d)|(?<=\s)#(?=[A-Za-z])"))]
PLACEHOLDER_SMELL_RE = re.compile(r"\[\s*\]|\[[A-Z][A-Za-z ]{2,30}\]|\?|\bN/A\b|\bTBD\b|\bTBC\b|\bnot specified\b|"
                                  r"\bXX+\b|\blorem ipsum\b|\byour (?:name|company|email)\b", re.I)
STRICT_DIFF_LOW = 0.90      # strict vs modern text: under 90% the same words -> the strict parsers see other text


def _context(text, m, width=25):
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    return re.sub(r"\s+", " ", text[a:b]).strip()


def text_similarity(a, b):
    """Share of words the strict and modern text have in common (1 = same words)."""
    import difflib
    wa, wb = re.findall(r"\S+", a.lower()), re.findall(r"\S+", b.lower())
    if not wa and not wb:
        return 1.0
    return difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio()


def smell_checks(doc, ana):
    """Possible new bugs: odd symbols or code, placeholders, empty sections, strict/modern text differences,
    odd dates. Listed for a human to look at; they never change the score."""
    text = doc["modern"]
    out = []
    for label, pat in SMELL_SYMBOLS:
        hits = list(pat.finditer(text))
        if hits:
            out.append({"kind": "symbols or code", "detail": f"{len(hits)} x {label}, e.g. '{_context(text, hits[0])}'"})
    hits = list(PLACEHOLDER_SMELL_RE.finditer(text))
    if hits:
        eg = "; ".join(f"'{_context(text, m, 15)}'" for m in hits[:2])
        out.append({"kind": "placeholder", "detail": f"{len(hits)} x placeholder-like text, e.g. {eg}"})
    empty = [sec["title"] for sec in ana["sections"] if len(" ".join(r["text"] for r in sec["rows"]).split()) < 2]
    if empty:
        out.append({"kind": "empty section", "detail": "no content under: " + ", ".join(empty[:4])})
    sim = text_similarity(doc["strict"], doc["modern"])
    if sim < STRICT_DIFF_LOW:
        only = sorted(set(re.findall(r"\S+", doc["strict"].lower())) - set(re.findall(r"\S+", text.lower())),
                      key=len, reverse=True)
        out.append({"kind": "strict vs modern text", "detail": f"only {sim:.0%} the same words; strict-only "
                    f"words e.g. {', '.join(only[:3])}"})
    now = TODAY.year * 12 + TODAY.month - 1
    dated = [j for j in ana["jobs"] for _ in [0] if j["intervals"]]
    for j in dated:
        rng = find_ranges(j["dates"])
        for r in rng:
            if r["end"] < r["start"]:
                out.append({"kind": "odd dates", "detail": f"'{j['title'][:40]}': ends before it starts ({r['text']})"})
            if r["start"] > now or (r["end"] > now and not re.search(END_WORD, r["text"], re.I)):
                out.append({"kind": "odd dates", "detail": f"'{j['title'][:40]}': date in the future ({r['text']})"})
    overlaps = []
    monthly = [j for j in dated if j["month_format"]]    # year-only dates are B11 and too rough for overlaps
    for i, a in enumerate(monthly):            # each job's own periods ('2016 - 2017 & 2023 - 2024' = two)
        for b in monthly[i + 1:]:
            if any(min(e1, e2) - max(s1, s2) >= 2 for s1, e1 in a["intervals"] for s2, e2 in b["intervals"]):
                overlaps.append(f"'{a['title'][:30]}' & '{b['title'][:30]}'")   # 2+ months at the same time
    if overlaps:
        out.append({"kind": "odd dates", "detail": f"{len(overlaps)} overlapping job(s): " + "; ".join(overlaps[:3])})
    f = ats_fields(doc, ana)
    bad = [f"'{j['title'][:40]}' {j['title_problem']}" for j in f["jobs"] if j["title_problem"]]
    if f["headline_problem"]:
        bad.insert(0, f"headline '{f['headline'][-40:]}' {f['headline_problem']}")
    if bad:
        out.append({"kind": "cut-off or merged title", "detail": "; ".join(bad[:3])
                    + (f" (+{len(bad) - 3} more)" if len(bad) > 3 else "")})
    starts = [min(s for s, _ in j["intervals"]) for j in dated]
    if len(starts) >= 2 and starts != sorted(starts, reverse=True) and starts != sorted(starts):
        out.append({"kind": "odd dates", "detail": "jobs are not in date order (newest first)"})
    return out


# ---------------------------------------------------------------------------
# What changed: two folders of CVs for the same users
# ---------------------------------------------------------------------------
def _norm_line(l):
    return re.sub(r"\s+", " ", norm_punct(l)).strip().lower()


def cv_snapshot(path):
    doc = extract_cv(path)
    ana = analyse(doc)
    return {"user": cv_user(doc, path), "fields": ats_fields(doc, ana),
            "lines": [l for l in (_norm_line(x) for x in doc["modern"].splitlines()) if len(l.split()) >= 3]}


def compare_cvs(a, b):
    """What appeared, disappeared or changed between two versions of one user's CV (a = before, b = after)."""
    fa, fb = a["fields"], b["fields"]
    ch = {"fields": [], "sections": {}, "jobs": {}, "text": {}}
    for k in ("name", "email", "phone", "location", "linkedin", "headline"):
        if fa[k] != fb[k]:
            what = "appeared" if not fa[k] else "disappeared" if not fb[k] else "changed"
            ch["fields"].append({"field": k, "change": what, "before": fa[k], "after": fb[k]})
    sa, sb = [_norm_line(x) for x in fa["sections"]], [_norm_line(x) for x in fb["sections"]]
    ch["sections"] = {"appeared": [x for x in fb["sections"] if _norm_line(x) not in sa],
                      "disappeared": [x for x in fa["sections"] if _norm_line(x) not in sb]}
    ta = [_norm_line(j["title"]) for j in fa["jobs"]]
    tb = [_norm_line(j["title"]) for j in fb["jobs"]]
    da = {_norm_line(j["title"]): j["dates"] for j in fa["jobs"]}
    ch["jobs"] = {"count": [len(ta), len(tb)],
                  "appeared": [j["title"] for j in fb["jobs"] if _norm_line(j["title"]) not in ta],
                  "disappeared": [j["title"] for j in fa["jobs"] if _norm_line(j["title"]) not in tb],
                  "dates_changed": [f"{j['title']}: {da[_norm_line(j['title'])]} -> {j['dates']}" for j in fb["jobs"]
                                    if _norm_line(j["title"]) in da and da[_norm_line(j["title"])] != j["dates"]]}
    ch["skills"] = [len(fa["skills"]), len(fb["skills"])]
    ch["education"] = {"appeared": [x for x in fb["education"] if x not in fa["education"]],
                       "disappeared": [x for x in fa["education"] if x not in fb["education"]]}
    la, lb = set(a["lines"]), set(b["lines"])
    ch["text"] = {"lines_before": len(la), "lines_after": len(lb),
                  "appeared": sorted(lb - la, key=lambda x: b["lines"].index(x)),
                  "disappeared": sorted(la - lb, key=lambda x: a["lines"].index(x))}
    return ch


def compare_folders(dir_a, dir_b):
    """Pairs CVs by file name, else by user (name at the top). -> list of {cv_a, cv_b, user, changes}."""
    snaps_a = {p: cv_snapshot(p) for p in sorted(glob.glob(os.path.join(dir_a, "*.pdf")))}
    snaps_b = {p: cv_snapshot(p) for p in sorted(glob.glob(os.path.join(dir_b, "*.pdf")))}
    by_name = {os.path.basename(p): p for p in snaps_b}
    by_user = {}
    for p, sn in snaps_b.items():
        by_user.setdefault(sn["user"], p)
    out, used = [], set()
    for pa, sa in snaps_a.items():
        pb = by_name.get(os.path.basename(pa)) or by_user.get(sa["user"])
        if not pb or pb in used:
            out.append({"cv_a": os.path.basename(pa), "cv_b": None, "user": sa["user"], "changes": None})
            continue
        used.add(pb)
        out.append({"cv_a": os.path.basename(pa), "cv_b": os.path.basename(pb), "user": sa["user"],
                    "changes": compare_cvs(sa, snaps_b[pb])})
    for pb in snaps_b:
        if pb not in used:
            out.append({"cv_a": None, "cv_b": os.path.basename(pb), "user": snaps_b[pb]["user"], "changes": None})
    return out


def print_compare(dir_a, dir_b, pairs):
    print(f"\n WHAT CHANGED: {dir_a} -> {dir_b}")
    for x in pairs:
        print("=" * 78)
        if x["changes"] is None:
            print(f" {x['cv_a'] or x['cv_b']}: only in {dir_a if x['cv_a'] else dir_b}")
            continue
        c = x["changes"]
        print(f" {x['cv_a']}" + (f"  ->  {x['cv_b']}" if x["cv_b"] != x["cv_a"] else ""))
        for f in c["fields"]:
            print(f"   field {f['field']} {f['change']}: {f['before']!r} -> {f['after']!r}")
        for k in ("appeared", "disappeared"):
            if c["sections"][k]:
                print(f"   sections {k}: {', '.join(c['sections'][k])}")
        j = c["jobs"]
        if j["count"][0] != j["count"][1]:
            print(f"   jobs found: {j['count'][0]} -> {j['count'][1]}")
        for k in ("appeared", "disappeared"):
            if j[k]:
                print(f"   job titles {k}: {'; '.join(j[k][:4])}")
        for d in j["dates_changed"][:4]:
            print(f"   dates changed: {d}")
        if c["skills"][0] != c["skills"][1]:
            print(f"   skills listed: {c['skills'][0]} -> {c['skills'][1]}")
        for k in ("appeared", "disappeared"):
            if c["education"][k]:
                print(f"   education {k}: {'; '.join(c['education'][k][:3])}")
        t = c["text"]
        print(f"   text lines: {len(t['appeared'])} new, {len(t['disappeared'])} gone"
              f" (of {t['lines_before']} -> {t['lines_after']})")
        for l in t["appeared"][:3]:
            print(f"      + {l[:100]}")
        for l in t["disappeared"][:3]:
            print(f"      - {l[:100]}")


def cv_user(doc, path):
    """Who the CV belongs to: the name line at the top, else the file name before '_' ('Shikha_Chanel.pdf')."""
    name = next((r["text"].strip() for r in analyse(doc)["header"][:1]), "")
    key = re.sub(r"[^a-z]", "", name.lower())
    if 4 <= len(key) <= 40 and len(name.split()) <= 6:
        return key
    return re.sub(r"[^a-z]", "", os.path.basename(path).split("_")[0].lower())


def cv_words(text):
    return re.findall(r"[a-z0-9]+", norm_punct(text).lower())


def mark_shared_text(docs):
    """B13 for a batch: {path: doc}. A run of SHARED_MIN_WORDS+ words in a row that is also in another user's CV
    is leaked text (it catches a copied phrase inside an otherwise personal sentence). Each doc gets
    'shared_text' = [(passage, [other users' files])], overlapping runs joined into one passage."""
    n = SHARED_MIN_WORDS
    users = {p: cv_user(d, p) for p, d in docs.items()}
    words = {p: cv_words(d["modern"]) for p, d in docs.items()}
    where = {}
    for p, w in words.items():
        for i in range(len(w) - n + 1):
            where.setdefault(tuple(w[i:i + n]), set()).add(p)
    for p, w in words.items():
        spans = []                                   # [start, end, other files]
        for i in range(len(w) - n + 1):
            others = {q for q in where[tuple(w[i:i + n])] if users[q] != users[p]}
            if not others:
                continue
            if spans and i <= spans[-1][1]:
                spans[-1][1] = i + n
                spans[-1][2] |= others
            else:
                spans.append([i, i + n, set(others)])
        docs[p]["shared_text"] = [(" ".join(w[a:b]), sorted(os.path.basename(q) for q in o)) for a, b, o in spans]
    return users


# ---------------------------------------------------------------------------
# CV evaluation mode (no job description, a target role): plain-language feedback for the CV owner.
# It names the problem area only: never the formula, keyword lists or the exact fix.
# ---------------------------------------------------------------------------
FEEDBACK_TEXT = {
    "B1": "Some section headings may not be read correctly by applicant tracking systems.",
    "B2": "Your skills may not be recognised as a list of skills.",
    "B3": "Extra text in the document may be read as part of your CV.",
    "B4": "Your contact details look incomplete.",
    "B5": "Some formatting marks show up as plain text.",
    "B6": "Some formatting marks show up as plain text.",
    "B7": "Some information in your CV looks unfinished.",
    "B8": "Part of the layout may be read in the wrong order.",
    "B9": "Some of your content seems to be repeated.",
    "B10": "Some wording sounds generic rather than personal.",
    "B11": "Some job dates may be hard for these systems to read.",
    "B12": "Some formatting marks show up as plain text.",
    "B13": "Some wording is not unique to you.",
    "R1": "Your name may not be picked up clearly.",
    "R2": "Your contact details look incomplete.",
    "R3": "Your contact details look incomplete.",
    "R4": "The top of your CV does not clearly say who you are professionally.",
    "R5": "Some section headings may not be read correctly by applicant tracking systems.",
    "R6": "Some job dates may be hard for these systems to read.",
    "R7": "Some job dates may be hard for these systems to read.",
    "R8": "Your education details may be incomplete.",
    "R9": "Your skills may not be recognised as a list of skills.",
    "R11": "Some section names are unusual for applicant tracking systems.",
    "R12": "One or more of the main CV sections seems to be missing.",
    "R13": "Your summary may be too short or too long.",
}
FEEDBACK_SUMMARY = {
    "Excellent": "Applicant tracking systems should read your CV very well.",
    "Strong": "Applicant tracking systems should read your CV well, with a few small problems.",
    "Good": "Applicant tracking systems can read most of your CV, but some problems may cost you.",
    "Needs work": "Applicant tracking systems may miss important parts of your CV.",
    "At risk": "Applicant tracking systems are likely to misread important parts of your CV.",
    "Not ready": "Applicant tracking systems will have serious trouble reading your CV.",
}
SEVERITY_RANK = {"Critical": 0, "Major": 1, "Minor": 2}


def role_presented(doc, ana, role):
    """Is the target role stated near the top (headline / summary)? Exact or a word-form variant."""
    top = tokens(" ".join(r["text"] for r in ana["header"] + section_rows(ana, "summary")))
    return match_level(role, top) in ("exact", "variant")


def cv_feedback(res, role, role_ok):
    """Score, label and the top 3 problems in plain words (one line each, no duplicates)."""
    score = res["headline"]["readability"]
    label = label_for(score)
    found = {b["code"]: b for b in res["bugs"] if b["found"]}
    ranked = []
    for x in res["fix_plan"]:                    # check / bug fixes that would raise the score, biggest first
        if x["id"] in FEEDBACK_TEXT and (x["kind"] == "check" and x["points"] > 0 or x["id"] in found):
            sev = SEVERITY_RANK[BUG_BY_CODE[x["id"]]["severity"]] if x["kind"] == "bug" else 1
            ranked.append((-x["points"], sev, FEEDBACK_TEXT[x["id"]]))
    for code, b in found.items():                # bugs with no points in this mode: by severity
        if code in FEEDBACK_TEXT:
            ranked.append((0, SEVERITY_RANK[b["severity"]], FEEDBACK_TEXT[code]))
    problems = [] if role_ok else [f"Your CV does not clearly present you as a {role}."]
    for _, _, text in sorted(ranked, key=lambda r: (r[0], r[1])):
        if text not in problems:
            problems.append(text)
    return {"role": role, "score": round(score), "label": label, "summary": FEEDBACK_SUMMARY[label],
            "problems": problems[:3]}


def print_feedback(fb):
    print("-" * 78 + f"\n FEEDBACK FOR THE CV OWNER  (target role: {fb['role']})")
    print(f"   ATS readability: {fb['score']}/100 - {fb['label']}")
    print(f"   {fb['summary']}")
    if fb["problems"]:
        print("   Main problems:")
        for i, t in enumerate(fb["problems"], 1):
            print(f"     {i}. {t}")
    else:
        print("   No major problems found.")


def score_cv(cv_path, job_path=None, model=None, profile_path=None, doc=None, role=None, job_title=None):
    """role: target role for CV evaluation mode (no job description) -> adds 'feedback' for the CV owner.
    job_title: the title the user typed for this job; it replaces the title found in the posting (never guessed)."""
    doc = doc or extract_cv(cv_path)
    kw, job_text, job_skipped = None, "", None
    if job_path:
        with open(job_path, encoding="utf-8", errors="ignore") as f:
            job_text = f.read()
        try:
            kw = load_keywords(job_path, model)
            if (job_title or "").strip():
                kw = dict(kw, title=job_title.strip(), title_source="user",
                          quality=dict(kw["quality"], reasons=[r for r in kw["quality"]["reasons"]
                                                               if "title" not in r.lower()]))
                kw["quality"]["level"] = "low" if kw["quality"]["reasons"] else "ok"
        except NotAJob as e:          # web page / not a job: score Readable + bugs only, and say why
            job_skipped, job_text = str(e), ""
            print(f"   {e} -> Readable score and bugs only")
    profile = None
    if profile_path and os.path.exists(profile_path):
        with open(profile_path, encoding="utf-8") as f:
            profile = json.load(f)
    state, bugs, ana, h_detail = build_state(doc, job_text, kw, profile)
    no_job = state["readable_only"]

    per_ats = {}
    for pname in ATS_PROFILES:
        ev = evaluate(state, pname)
        per_ats[pname] = {
            "total": None if no_job else round(ev["total"], 1), "label": None if no_job else label_for(ev["total"]),
            "base": None if no_job else round(ev["base"], 1), "penalty": None if no_job else ev["penalty"],
            "gates": ev["gates"], "readable": r1(ev["parts"]["R"], 100), "findable": r1(ev["parts"]["F"], 100),
            "matched": r1(ev["parts"]["M"], 100), "job_match": r1(job_match_of(ev["parts"]), 100),
            "required_coverage": r1(ev["required_coverage"], 100),
            "checks": {n: {"name": c["name"], "part": c["part"], "score": r1(c["score"], 100),
                           "detail": c["detail"], "weight": c["weight"]} for n, c in sorted(ev["checks"].items())},
            "must_haves": must_haves(state, ev),
        }
    overall = None if no_job else round(sum(a["total"] for a in per_ats.values()) / len(per_ats), 1)
    ready, ready_reasons = badge(state)
    names = list(per_ats["oracle"]["must_haves"])
    checklist = [{"item": n, **{p: per_ats[p]["must_haves"][n] for p in ATS_PROFILES}} for n in names]
    bug_list = [{"code": b["code"], "name": b["name"], "status": b["status"], "severity": b["severity"],
                 "found": bugs[b["code"]]["found"], "detail": bugs[b["code"]]["detail"],
                 "penalty": bug_penalty(b["code"]) if bugs[b["code"]]["found"] else 0,
                 "owns_checks": b["owns"], "fix": b["fix"]} for b in BUGS]
    keywords = [{"term": r["term"], "type": r["type"], "weight": r["weight"], "times_in_job": r["times_in_job"],
                 "source": (kw or {}).get("skill_sources", {}).get(r["term"], "ai"), "match": best_level(r) or "missing",
                 "credit": {p: round(best_credit(r, ATS_PROFILES[p]), 2) for p in ATS_PROFILES}} for r in state["kw"]]
    res = {"cv": os.path.basename(cv_path),
            "mode": "readable only (no job description)" if no_job else "full", "job_skipped": job_skipped,
            "job_title": (kw or {}).get("title"), "title_source": (kw or {}).get("title_source"),
            "keyword_quality": (kw or {}).get("quality"), "keywords_dropped": (kw or {}).get("dropped", []),
            "education_keywords": (kw or {}).get("education_keywords", []),
            "overall": overall, "label": None if no_job else label_for(overall),
            "readable_overall": round(sum(a["readable"] for a in per_ats.values()) / len(per_ats), 1),
            "headline": {"readability": round(sum(a["readable"] for a in per_ats.values()) / len(per_ats), 1),
                         "job_match": None if no_job else
                         round(sum(a["job_match"] for a in per_ats.values()) / len(per_ats), 1),
                         "total": overall},
            "ready_for_any_ats": ready, "ready_blockers": ready_reasons,
            "honesty": {None: "not checked", True: "pass", False: "FAIL"}[state["honest"]], "honesty_detail": h_detail,
            "experience_years": round(experience_years(ana["jobs"]), 1),
            "jobs": [{k: j[k] for k in ("title", "dates", "problem")} for j in ana["jobs"]],
            "possible_new_bugs": smell_checks(doc, ana),
            "ats_view": {"fields": ats_fields(doc, ana), "text_strict": doc["strict"], "text_modern": doc["modern"]},
            "ats": per_ats, "bugs": bug_list, "checklist": checklist, "keywords": keywords, **explain(state)}
    if role and no_job:
        res["mode"] = f"CV evaluation (target role: {role})"
        res["feedback"] = cv_feedback(res, role, role_presented(doc, ana, role))
    return res


# ---------------------------------------------------------------------------
# Detector accuracy against a hand-made truth file (no tuning)
# ---------------------------------------------------------------------------
def check_truth(truth_path, cvdir):
    with open(truth_path, encoding="utf-8") as f:
        truth = json.load(f)["cvs"]
    stats = {code: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for code in BUG_BY_CODE}
    misses, checked = [], 0
    for name, expected in truth.items():
        pdf = os.path.join(cvdir, name + ".pdf")
        if not os.path.exists(pdf):
            print(f" SKIPPED {name}: no {pdf}")
            continue
        d = extract_cv(pdf)
        bugs = detect_bugs(d, analyse(d))
        checked += 1
        for code in BUG_BY_CODE:
            want = expected.get(code)
            if want is None:      # not labelled
                continue
            got = bugs[code]["found"]
            stats[code][("tp" if want else "fp") if got else ("fn" if want else "tn")] += 1
            if got != bool(want):
                misses.append((name, code, "false alarm" if got else "missed", bugs[code]["detail"]))
    print(f"\n Detector accuracy on {checked} CVs ({truth_path})")
    print(f"   {'bug':<4} {'TP':>3} {'FP':>3} {'FN':>3} {'TN':>3}  accuracy  precision  recall")
    tot_ok = tot = 0
    for code, s in stats.items():
        n = sum(s.values())
        if not n:
            continue
        ok = s["tp"] + s["tn"]
        tot_ok, tot = tot_ok + ok, tot + n
        prec = f"{s['tp'] / (s['tp'] + s['fp']):.0%}" if s["tp"] + s["fp"] else "  -"
        rec = f"{s['tp'] / (s['tp'] + s['fn']):.0%}" if s["tp"] + s["fn"] else "  -"
        print(f"   {code:<4} {s['tp']:>3} {s['fp']:>3} {s['fn']:>3} {s['tn']:>3}  {ok / n:>7.0%}  {prec:>9}  {rec:>6}")
    if tot:
        print(f"   ALL  {tot_ok}/{tot} correct = {tot_ok / tot:.1%}")
    for name, code, kind, detail in misses:
        print(f"   - {name}: {code} {kind} ({detail})")
    return stats, misses


def truth_template(cvdir, out_path):
    """Blank label file for new CVs: fill each bug with true/false by reading the CV, BEFORE running --truth."""
    cvs = {os.path.splitext(os.path.basename(p))[0]: {**{c: None for c in BUG_BY_CODE}, "notes": ""}
           for p in sorted(glob.glob(os.path.join(cvdir, "*.pdf")))}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"_about": "fill true/false per bug by reading each CV", "cvs": cvs}, f, indent=2)
    print(f"Wrote {out_path} with {len(cvs)} CVs")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def fmt(v):
    return " -- " if v is None else f"{v:4.0f}"


def print_ats_view(res, full_text=False):
    """What the ATS sees: the fields a parser fills in (and, with --view, the plain extracted text)."""
    f = res["ats_view"]["fields"]
    print("-" * 78 + "\n WHAT THE ATS SEES")
    show = lambda v: v if v else "-- not found --"
    print(f"   Name: {show(f['name'])}   Email: {show(f['email'])}   Phone: {show(f['phone'])}")
    print(f"   Location: {show(f['location'])}   LinkedIn: {show(f['linkedin'])}")
    print(f"   Headline: {show(f['headline'])}" + (f"   <-- {f['headline_problem']}" if f["headline_problem"] else ""))
    print(f"   Jobs ({len(f['jobs'])}):")
    for j in f["jobs"]:
        flag = "   <-- " + "; ".join(x for x in (j["title_problem"], j["date_problem"]) if x) \
            if j["title_problem"] or j["date_problem"] else ""
        print(f"     - {j['title']}  |  {show(j['company'])}  |  {show(j['dates'])}{flag}")
    print(f"   Education: {'; '.join(f['education']) if f['education'] else '-- not found --'}")
    print(f"   Skills ({len(f['skills'])}): {', '.join(f['skills'][:12])}" + (" ..." if len(f["skills"]) > 12 else ""))
    if full_text:
        print("-" * 78 + "\n PLAIN TEXT (strict parser, like Workday / Oracle)\n" + "-" * 78)
        print(res["ats_view"]["text_strict"])


def print_report(res, full_text=False):
    if "feedback" in res:                      # CV evaluation mode: readability, bugs, feedback only
        print("\n" + "=" * 78 + f"\n {res['cv']}   ->   {res['mode']}\n" + "=" * 78)
        print(f" READABILITY {res['headline']['readability']}  ({label_for(res['headline']['readability'])})")
        print("-" * 78 + "\n BUGS")
        for b in res["bugs"]:
            print(f" [{'FAIL' if b['found'] else ' ok '}] {b['code']} {b['name']} ({b['status']})")
        if full_text:
            print_ats_view(res, full_text)
        print_feedback(res["feedback"])
        return
    a = res["ats"]
    no_job = res["mode"] != "full"
    print("\n" + "=" * 78)
    if no_job:
        print(f" {res['cv']}   ->   NO JOB DESCRIPTION (Readable + bugs only)")
    else:
        print(f" {res['cv']}   ->   {res['job_title']}  (title: {res['title_source']})")
    print("=" * 78)
    h = res["headline"]
    print(f" READABILITY {h['readability']}  |  JOB MATCH {'n/a' if h['job_match'] is None else h['job_match']}"
          f"  |  TOTAL {'n/a' if h['total'] is None else str(h['total']) + ' (' + res['label'] + ')'}")
    if no_job:
        print(f" READABLE {res['readable_overall']}  |  Greenhouse {a['greenhouse']['readable']}  |  "
              f"Workday {a['workday']['readable']}  |  Oracle {a['oracle']['readable']}")
    else:
        print(f" OVERALL {res['overall']} ({res['label']})  |  Greenhouse {a['greenhouse']['total']}  |  "
              f"Workday {a['workday']['total']}  |  Oracle {a['oracle']['total']}   (Honesty: {res['honesty']})")
        q = res["keyword_quality"]
        if q and q["level"] == "low":
            print(" WARNING keyword quality: low  -  " + "; ".join(q["reasons"]))
        o = a["oracle"]
        print(f" Oracle: Readable {o['readable']}  Findable {o['findable']}  Matched {o['matched']}  "
              f"base {o['base']} - penalty {o['penalty']}" + (f"  gates: {'; '.join(o['gates'])}" if o["gates"] else ""))
    print(f" Ready for any ATS: {'YES' if res['ready_for_any_ats'] else 'NO'}"
          + ("" if res["ready_for_any_ats"] else f"  ({len(res['ready_blockers'])} blockers)"))
    print("-" * 78 + "\n BUGS")
    for b in res["bugs"]:
        pen = f"  -{b['penalty']}" if b["penalty"] and not no_job else ""
        print(f" [{'FAIL' if b['found'] else ' ok '}] {b['code']} {b['name']} ({b['status']}){pen}\n          {b['detail']}")
    print_ats_view(res, full_text)
    if res["possible_new_bugs"]:
        print("-" * 78 + "\n POSSIBLE NEW BUGS (not scored - for a human to check)")
        for x in res["possible_new_bugs"]:
            print(f" [ ?? ] {x['kind']}: {x['detail']}")
    print("-" * 78 + "\n CHECKS (strictest view: Oracle; score 0-100)")
    for n, c in a["oracle"]["checks"].items():
        print(f" [{fmt(c['score'])}] {n} {c['name']}\n          {c['detail']}")
    unit = "Readable" if no_job else "overall"
    print("-" * 78 + f"\n FIX PLAN (top 6, points = {unit} gain)")
    for x in res["fix_plan"][:6]:
        pts = "n/a" if no_job and x["points"] == 0 else f"+{x['points']}"
        print(f"   {pts:<6} {x['item']}  [{x['tag']}, {x['status']}]")


def batch_summary(results):
    full = [r for r in results if r["mode"] == "full"]
    n = len(full)
    summary = {"cvs": len(results), "scored_with_job": n, "readable_only": len(results) - n,
               "average_overall": round(sum(r["overall"] for r in full) / n, 1) if n else None,
               "average_per_ats": {p: round(sum(r["ats"][p]["total"] for r in full) / n, 1) if n else None
                                   for p in ATS_PROFILES},
               "average_readable_all": round(sum(r["readable_overall"] for r in results) / len(results), 1),
               "average_readability": round(sum(r["headline"]["readability"] for r in results) / len(results), 1),
               "average_job_match": round(sum(r["headline"]["job_match"] for r in full) / n, 1) if n else None,
               "ready_for_any_ats": sum(r["ready_for_any_ats"] for r in results),
               "keyword_quality_low": [r["cv"] for r in full if (r["keyword_quality"] or {}).get("level") == "low"],
               "labels": {lbl: sum(r["label"] == lbl for r in full) for _, lbl in SCALE},
               "possible_new_bugs": {k: sum(any(x["kind"] == k for x in r["possible_new_bugs"]) for r in results)
                                     for k in sorted({x["kind"] for r in results for x in r["possible_new_bugs"]})},
               "bugs": {}}
    for b in BUGS:  # count over all CVs; average gain over CVs scored with a job (overall points)
        gains = [x["points"] for r in full for x in r["why_down"] if x["kind"] == "bug" and x["id"] == b["code"]]
        count = sum(any(bb["code"] == b["code"] and bb["found"] for bb in r["bugs"]) for r in results)
        summary["bugs"][b["code"]] = {"name": b["name"], "status": b["status"], "severity": b["severity"],
                                      "count": count,
                                      "average_points_gain": round(sum(gains) / len(gains), 1) if gains else 0.0}
    return summary


def print_summary(summary, results):
    print("\n" + "#" * 78)
    print(f" SUMMARY: {summary['scored_with_job']} CVs scored with a job"
          + (f", {summary['readable_only']} readable-only" if summary["readable_only"] else ""))
    if summary["scored_with_job"]:
        print(f" Average READABILITY {summary['average_readability']}   JOB MATCH {summary['average_job_match']}"
              f"   TOTAL {summary['average_overall']}")
        print(f" Average OVERALL {summary['average_overall']}   |   "
              + "   ".join(f"{p.capitalize()} {v}" for p, v in summary["average_per_ats"].items()))
    print(f" Ready for any ATS: {summary['ready_for_any_ats']}/{summary['cvs']}")
    if summary["keyword_quality_low"]:
        print(f" Keyword quality low: {', '.join(summary['keyword_quality_low'])}")
    print("#" * 78)
    for r in sorted([r for r in results if r["mode"] == "full"], key=lambda x: x["overall"]):
        a = r["ats"]
        print(f"   {r['overall']:5}  {r['label']:<10}  Read {r['headline']['readability']:5}  "
              f"Match {r['headline']['job_match']:5}  GH {a['greenhouse']['total']:5}  WD {a['workday']['total']:5}  "
              f"OR {a['oracle']['total']:5}   {r['cv']}")
    for r in results:
        if r["mode"] != "full":
            print(f"   Readable {r['readable_overall']:5} (no job)   {r['cv']}")
    if summary["possible_new_bugs"]:
        print("\n Possible new bugs (not scored), CVs with each: "
              + ", ".join(f"{k} {v}" for k, v in summary["possible_new_bugs"].items()))
    print(f"\n Bugs across all {summary['cvs']} CVs (count, average overall points gained by fixing):")
    for code, b in summary["bugs"].items():
        print(f"   {code:<4} {b['count']:>2}/{summary['cvs']}  +{b['average_points_gain']:<5} {b['name']} ({b['status']})")


def write_outputs(results, out_json):
    summary = batch_summary(results)
    data = {"lab_version": LAB_VERSION, "scored_on": TODAY.isoformat(),
            "settings": {"profiles": ATS_PROFILES, "part_exponents": PART_EXP, "type_weight": TYPE_WEIGHT,
                         "severity_penalty": SEVERITY_PENALTY, "penalty_cap": PENALTY_CAP, "scale": SCALE,
                         "badge": BADGE},
            "bug_registry": [{k: v for k, v in b.items() if k != "detect"} for b in BUGS],
            "summary": summary, "results": results}
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    with open(os.path.splitext(out_json)[0] + ".csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cv", "mode", "job_title", "title_source", "keyword_quality", "readability", "job_match",
                    "overall", "label", "ready",
                    "greenhouse", "workday", "oracle", "readable_avg", "oracle_readable", "oracle_findable",
                    "oracle_matched", "oracle_penalty", "honesty"] + [b["code"] for b in BUGS]
                   + ["possible_new_bugs", "top_fix"])
        for r in results:
            a = r["ats"]
            w.writerow([r["cv"], r["mode"], r["job_title"], r["title_source"],
                        (r["keyword_quality"] or {}).get("level"), r["headline"]["readability"],
                        r["headline"]["job_match"], r["overall"], r["label"], r["ready_for_any_ats"],
                        a["greenhouse"]["total"], a["workday"]["total"], a["oracle"]["total"], r["readable_overall"],
                        a["oracle"]["readable"], a["oracle"]["findable"], a["oracle"]["matched"], a["oracle"]["penalty"],
                        r["honesty"]]
                       + ["FAIL" if b["found"] else "" for b in r["bugs"]]
                       + ["; ".join(f"{x['kind']}: {x['detail']}" for x in r["possible_new_bugs"]),
                          r["fix_plan"][0]["item"] if r["fix_plan"] else ""])
    return summary


def extract_folder(folder, model, refresh=False):
    """Keywords for every job .txt in a folder. Web pages / non-jobs are skipped with the reason."""
    for job in sorted(glob.glob(os.path.join(folder, "*.txt"))):
        name = os.path.basename(job)
        path = keywords_path(job)
        if refresh and os.path.exists(path):
            os.remove(path)               # only ever a _keywords_v3.json file, never the old _keywords.json
        try:
            kw = load_keywords(job, model)
        except NotAJob as e:
            print(f" SKIPPED {e}")
            continue
        n = len(kw["required_skills"]) + len(kw["preferred_skills"])
        flag = f"   <-- UNDER {KEYWORD_MIN}" if n < KEYWORD_MIN else ""
        print(f" {name}: {n} skills, title '{kw['title']}', quality {kw['quality']['level']}{flag}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="1000Jobs ATS Lab v3 (Greenhouse, Workday, Oracle)")
    ap.add_argument("--cv"); ap.add_argument("--job")
    ap.add_argument("--cvdir"); ap.add_argument("--jobdir")
    ap.add_argument("--profile"); ap.add_argument("--profiledir")
    ap.add_argument("--model"); ap.add_argument("--out", default="results_v3.json")
    ap.add_argument("--view", action="store_true", help="also print the plain text the ATS extracts")
    ap.add_argument("--role", help="CV evaluation mode (no job description): the target role, e.g. 'Logistics Coordinator'")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"),
                    help="what changed between two folders of CVs for the same users")
    ap.add_argument("--extract", metavar="FOLDER", help="extract keywords for every job .txt in FOLDER (needs --model)")
    ap.add_argument("--refresh", action="store_true", help="with --extract: redo existing _keywords_v3.json files")
    ap.add_argument("--truth", help="check detectors against a truth JSON (with --cvdir)")
    ap.add_argument("--truth-template", help="write a blank truth JSON for the CVs in --cvdir")
    a = ap.parse_args()

    if a.compare:
        pairs = compare_folders(*a.compare)
        print_compare(*a.compare, pairs)
        out = a.out if a.out != "results_v3.json" else "compare_{}_vs_{}.json".format(
            *(os.path.basename(os.path.normpath(x)) for x in a.compare))
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"before": a.compare[0], "after": a.compare[1], "made_on": TODAY.isoformat(), "cvs": pairs},
                      f, indent=2, ensure_ascii=False)
        print(f"\nSaved {out}")
    elif a.extract:
        extract_folder(a.extract, a.model, a.refresh)
    elif a.truth_template and a.cvdir:
        truth_template(a.cvdir, a.truth_template)
    elif a.truth and a.cvdir:
        check_truth(a.truth, a.cvdir)
    elif a.cvdir:
        results = []
        cvs = sorted(glob.glob(os.path.join(a.cvdir, "*.pdf")))
        print(f"Found {len(cvs)} CVs in {a.cvdir}")
        docs = {cv: extract_cv(cv) for cv in cvs}
        users = mark_shared_text(docs)            # B13: sentences found in 2+ different users' CVs
        print(f" {len(set(users.values()))} different users")
        for cv in cvs:
            name = os.path.splitext(os.path.basename(cv))[0]
            job = os.path.join(a.jobdir, name + ".txt") if a.jobdir else None
            if job and not os.path.exists(job):
                print(f" {name}: no job description -> Readable score and bugs only")
                job = None
            prof = os.path.join(a.profiledir, name + ".json") if a.profiledir else None
            print(f" Scoring {name} ...")
            try:
                res = score_cv(cv, job, a.model, prof, doc=docs[cv], role=a.role)
            except Exception as e:  # keep going if one file fails
                print(f" ERROR on {name}: {e}")
                continue
            print_report(res, a.view)
            results.append(res)
        if results:
            summary = write_outputs(results, a.out)
            print_summary(summary, results)
            print(f"\nSaved {a.out} and {os.path.splitext(a.out)[0]}.csv")
    elif a.cv:
        res = score_cv(a.cv, a.job, a.model, a.profile, role=a.role)
        print_report(res, a.view)
        write_outputs([res], a.out)
    else:
        sys.exit("Use --cvdir CVS --jobdir JobDe  (all CVs)  or  --cv file.pdf [--job file.txt]  (one CV).")


if __name__ == "__main__":
    main()


