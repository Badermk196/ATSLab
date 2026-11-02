"""
1000Jobs CV Score - one score for any CV, with or without a job description.

Built ON TOP of ATSLab_v3.py (v3 is only called, never changed; its ATS total and past results stay as they are).

  The 1000jobs CV standard is the reference for EVERY CV (an original, another generator's, or a 1000jobs one).
  CV Score = weighted geometric mean of the parts (0-100), so the weakest part limits the total:
                     no job   with a job
    Readability       35%     26.25%   v3 readable checks (3 ATS) minus layout-bug and design penalties
    Content           40%     30%      headline, summary paragraph, bullets (numbers, verbs, openers, tense),
                                       repeated numbers, labels, buzzwords / filler, abbreviations, old roles,
                                       a resume too short for the experience
    Structure         25%     18.75%   standard section names, only degrees under Education, +code phone, every
                                       job with title / company / location / Mon YYYY, email, LinkedIn, city, skills
    Job Match          -      25%      v3 Job Match (only with a job description)
  Then every failed standard costs points on the total (Important 4, Minor 1.5, at most 15).
  Design and layout problems (photo, sidebar, columns, icons, boxes, fonts, contrast, reading order, pages)
  are read from the PDF itself (cv_layout.py) and count in Readability.
  Content and Structure are judged on the page as a person reads it (column by column).
  Guardrail: no numbers in any bullet -> CV Score at most 70.
  "Excellent" only if all parts are 85+ and there is no Critical or Major issue.

  py -3.12 cv_score.py CV.pdf
  py -3.12 cv_score.py CV.pdf --job JobDe\\Name.txt
"""

import argparse
import json
import math
import os
import re
import sys

import ATSLab_v3 as L
import cv_cache as CC
import cv_layout as Y
import cv_review as R

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "google/gemini-2.5-flash"
# Raise this whenever the result format changes: the dashboard reloads an older loaded copy of this module and
# recalculates results made by an older version instead of crashing on missing data.
SCORE_VERSION = "2026-10-30.v1.3"
ROLE_CACHE = os.path.join(HERE, "role_skills")      # AI skill lists per target role (extracted once)

# The 1000jobs CV standard is the reference for every CV. Without a job description: 3 parts; with one, Job Match
# keeps its 25% and the other three keep their proportions.
PART_WEIGHT = {"readability": 0.35, "content": 0.40, "structure": 0.25}
PART_WEIGHT_JOB = {"readability": 0.2625, "content": 0.30, "structure": 0.1875, "job_match": 0.25}
PART_FLOOR = 0.01
CAP_NO_NUMBERS = 70            # guardrail: a CV with no numbers in its bullets
EXCELLENT_PARTS = 85           # every part must reach this for "Excellent"
# issue severity from the points it costs (v3 bugs keep their own severity)
SEVERITY_POINTS = [(8, "Critical"), (3, "Major"), (0, "Minor")]

# Readability: v3 bugs that are about layout / parsing (content bugs are scored in Content Quality)
READ_BUGS = ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B11", "B12")
# pages a CV may have for its years of experience (more = "too many pages"): 1 page over the limit is Minor, this
# many or more is Important (so such a resume is never "Excellent")
MAX_PAGES = [(3, 1), (10, 2), (99, 3)]
PAGES_OVER_MAJOR = 2
# a big overrun: this many times its page limit or more AND at least PAGES_CAP_MIN pages (e.g. 15 pages for 5 years;
# a 2- or 3-page resume is never capped): the total is at most CAP_PAGES
PAGES_CAP_TIMES = 3
PAGES_CAP_MIN = 4
CAP_PAGES = 75
MERGED_TITLE_RE = re.compile(r"\s/\s")          # 'Senior / Media Manager': two titles in one

# Content Quality sub-checks and their weights (sum 1.0)
CONTENT_WEIGHT = {"C15": 0.15, "C1": 0.16, "C4": 0.07, "C17": 0.03, "C16": 0.06, "C9": 0.05,
                  "C10": 0.06, "C11": 0.07, "C18": 0.06, "C5": 0.05, "C12": 0.05, "C13": 0.04, "C14": 0.05, "C6": 0.03, "C7": 0.02}
# removed checks (v1.1): their weight is always given in full, so their points are simply no longer taken off and
# every other check keeps its weight. C3 = bullet length.
RETIRED_WEIGHT = {"C3": 0.05}
# C8 = the AI recruiter review (cv_review.py). It can only LOWER Content: up to AI_WEIGHT x 100 points, each
# content finding costing its share of C8. Without a review (no key, or not asked) nothing is taken off.
AI_WEIGHT = 0.15
AI_PENALTY = {"Critical": 0.35, "Major": 0.15, "Minor": 0.05}
CONTENT_NAME = {"C15": "Headline with a target title", "C16": "The same result with different numbers", "C9": "The same number used more than twice",
                "C10": "Labels inside jobs", "C11": "Weak openers", "C12": "Abbreviations written in full once",
                "C13": "Old roles kept short", "C14": "Past jobs in past tense",
                "C8": "Recruiter review (AI)", "C1": "Bullets with numbers or results", "C2": "Bullets start with an action verb",
                "C4": "Summary over 150 words", "C17": "Summary written as bullets",
                "C18": "Enough detail about your roles",
                "C5": "No buzzwords or template phrases", "C6": "No repeated text",
                "C7": "Not too short for the experience"}
QUANT_TARGET = 0.5             # half of the bullets with a number = full marks
VERB_TARGET = 0.8              # 80% of bullets start with an action verb = full marks
# C7 (v1.1): only a resume that is too short for the experience is flagged, never a long one
SHORT_YEARS, SHORT_WORDS = 8, 350      # 8+ years of experience in fewer than 350 words
ONE_PAGE_YEARS = 10                    # 10+ years of experience on one page
SHORT_SCORE = 0.5
DETAIL_PER_ROLE, DETAIL_MIN, DETAIL_MAX = 3, 6, 15     # C18: bullets expected for the roles of the last 10 years
RECENT_DETAIL_YEARS = 10
# Completeness items and weights (sum 1.0)
STRUCT_WEIGHT = {"T1": 0.14, "T2": 0.09, "T3": 0.10, "T4": 0.22, "T5": 0.10, "T6": 0.08, "T7": 0.10,
                 "T8": 0.07, "T9": 0.05, "T10": 0.02, "T11": 0.02, "T12": 0.0, "T13": 0.0, "T14": 0.0,
                 "T15": 0.0, "T16": 0.01}
# a note only: it can cost its own (tiny) weight, never the extra points a failed standard costs
NOTE_ONLY = {"T16"}
STRUCT_NAME = {"T1": "Standard section names", "T2": "Only degrees under Education", "T3": "Phone in +code format",
               "T4": "Every job has title, company and Mon YYYY dates", "T5": "LinkedIn URL",
               "T6": "City", "T7": "Email", "T8": "Skills section", "T9": "Degree, school and year",
               "T10": "Visa status, driving licence or notice period (UAE)", "T11": "One title per job",
               "T12": "Capital I used as a separator", "T13": "Numbered section headings",
               "T14": "Standard bullet symbols", "T15": "Standard page format (portrait, one column)",
               "T16": "Job locations"}
COMPLETE_WEIGHT = {"P1": 0.15, "P2": 0.20, "P3": 0.10, "P4": 0.15, "P5": 0.30, "P6": 0.10}   # (older versions)
COMPLETE_NAME = {"P1": "LinkedIn profile link", "P2": "Skills section", "P3": "Certifications",
                 "P4": "Education details", "P5": "Every job has title, company and dates", "P6": "Location"}

ACTION_VERBS = set("""
accelerate accomplish achieve acquire adapt administer advise align allocate analyse analyze anchor architect
arrange assemble assess attain audit author automate balance benchmark boost brand broker budget build calculate
campaign capture catalogue centralise centralize chair champion clarify close coach code collaborate collect
commercialise commercialize communicate compile complete conceive conceptualise conceptualize conduct configure
consolidate construct consult contract contribute control convert coordinate co-founded cultivate curate customise
customize cut debug decrease define deliver deploy design detect develop devise diagnose digitise digitize direct
discover dispatch double draft drive earn edit educate eliminate enable engineer enhance establish evaluate
execute expand expedite facilitate finalise finalize forecast forge formulate found founded generate govern grow
guide halve harmonise harmonize head hire identify implement improve increase influence initiate innovate
inspect install institute integrate interview introduce invent investigate launch lead led leverage liaise
localise localize maintain manage map market master maximise maximize measure mediate mentor merge migrate
minimise minimize mobilise mobilize model modernise modernize monitor motivate navigate negotiate onboard
operate optimise optimize orchestrate organise organize originate outperform overhaul oversee own partner
perform pilot pioneer plan prepare present prioritise prioritize process procure produce program programme
project promote propose prototype provide publish purchase raise rank rebuild recommend reconcile recruit
redesign reduce re-engineer refine regulate reinforce relaunch remediate renegotiate reorganise reorganize
report research resolve restructure retain revamp review revise revitalise revitalize run safeguard save scale
schedule scope secure select sell serve set ship shape simplify solve source spearhead specify standardise
standardize steer streamline strengthen structure supervise support surpass synthesise synthesize systematise
systematize tailor target teach test track trade train transform translate triple troubleshoot turn uncover
unify upgrade upsell validate verify win write
""".split())
# Only real weak openers. A past-tense verb ('Built', 'Won', 'Used', 'Led', 'Managed', 'Delivered') is an action verb.
WEAK_OPENERS = re.compile(r"^(responsible for|was responsible for|were responsible for|helped|assisted|participated|"
                          r"worked on|involved in|tasked with|duties (?:included|include)|in charge of)\b", re.I)
BUZZWORDS = ["results-driven", "result-oriented", "results-oriented", "detail-oriented", "team player", "hard-working",
             "hardworking", "self-starter", "self-motivated", "go-getter", "dynamic", "synergy", "synergies",
             "think outside the box", "passionate", "highly motivated", "proven track record", "dedicated",
             "strategic thinker", "go-to person", "value-add", "best-in-class", "best of breed", "rockstar", "ninja",
             "guru", "seasoned", "visionary", "out-of-the-box", "results driven", "detail oriented", "motivated",
             "track record of success", "world-class", "cutting-edge", "game-changer", "thought leader"]
BULLET_START_RE = re.compile(r"^\s*([•▪●◦‣⁃·*\-–—➢►]|\d+[.)])\s+")
LABEL_RE = re.compile(r"^[A-Z][\w&/,'()\- ]{2,50}:\s+(?=[A-Z])")          # 'Portfolio Delivery Governance: Directed'
NUMBER_RE = re.compile(r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|twelve|hundred|thousand|million|"
                       r"billion|double[ds]?|tripled?|halved?)\b", re.I)


class ScoreError(ValueError):
    """Bad input for the CV Score (shown to the user as a message)."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def severity_for(points):
    return next(s for limit, s in SEVERITY_POINTS if points >= limit)


def weighted_geo(parts):
    """CV Score 0-100 from the parts (0-100 each): weighted geometric mean (the weakest part limits the total)."""
    weights = PART_WEIGHT_JOB if "job_match" in parts else PART_WEIGHT
    total = 100.0
    for k, w in weights.items():
        total *= max(PART_FLOOR, parts[k] / 100) ** w
    return total


def label_for(score, parts, issues):
    """v3 scale, but 'Excellent' only when every part is 85+ and no Critical / Major issue is left."""
    label = L.label_for(score)
    if label == "Excellent" and (min(parts.values()) < EXCELLENT_PARTS
                                 or any(i["severity"] in ("Critical", "Major") for i in issues)):
        label = "Strong"
    return label


ROLE_GENERIC = {L.stem(w) for w in ("head senior junior lead manager director associate executive officer "
                                     "specialist assistant chief vice president intern trainee principal staff "
                                     "of and the for in").split()}


def role_named(target, toks):
    """The target role is named near the top: exactly, or most of its specific words ('customer success')."""
    if not target:
        return False
    if L.match_level(target, toks) in ("exact", "variant"):
        return True
    want = {L.stem(t) for t in L.tokens(target)} - ROLE_GENERIC
    have = {L.stem(t) for t in toks}
    return bool(want) and len(want & have) >= 0.6 * len(want)


REGION_WORDS = {"emea", "mena", "menat", "gcc", "apac", "uae", "ksa", "global", "international", "regional",
                "middle", "east", "africa", "europe", "asia", "americas", "na", "latam"}


def clean_role(title):
    """'Head of Customer Success & Experience, EMEA' -> 'Head of Customer Success & Experience'."""
    t = re.sub(r"\([^)]*\)", "", title or "").strip()
    parts = [x.strip() for x in re.split(r",|\s[-\u2013\u2014|]\s", t) if x.strip()]
    while len(parts) > 1 and (all(w in REGION_WORDS for w in L.tokens(parts[-1])) or L.is_place(parts[-1])
                              or is_city(parts[-1])):
        parts.pop()
    return re.sub(r"\s+", " ", ", ".join(parts)).strip(" ,")


def detect_role(vdoc, vana):
    """The CV's own role: its headline (first part) when it names a job, else the most recent job title."""
    f = L.ats_fields(vdoc, vana)
    head = re.split(r"\s[|\u2022\u00b7]\s", f["headline"] or "")[0].strip()
    if head and L.TITLE_WORDS.search(head) and len(head.split()) <= 8:
        return clean_role(head)
    jobs = [(max((e for _, e in j["intervals"]), default=-1), i, j) for i, j in enumerate(vana["jobs"])]
    if not jobs:
        return None
    latest = max(jobs, key=lambda x: (x[0], -x[1]))[2]
    title = L.job_title_company(latest, [r["text"].strip() for s in vana["sections"] if s["kind"] == "experience"
                                         for r in s["rows"]])[0]
    return clean_role(title) or None


def check_role(role):
    role = (role or "").strip()
    if len(re.findall(r"[A-Za-z]", role)) < 3:
        raise ScoreError("Please type a real target role (at least 3 letters), for example: Logistics Coordinator.")
    return role


# ---------------------------------------------------------------------------
# The CV's structure (like ATSLab_v3.analyse), with every experience section read as jobs:
# "Early Work Experience", "Additional Experience", "Previous Experience", "Other Experience", ...
# ---------------------------------------------------------------------------
EXP_HEADING_RE = re.compile(r"(?:(?:early|earlier|additional|previous|prior|other|relevant|selected|recent|"
                            r"international|freelance|consulting|volunteer|volunteering|military|teaching|research|"
                            r"industry|professional|work|career|employment|related|further|more)\s+){0,3}"
                            r"(?:experience|experiences|employment|work history|career history|positions held)",
                            re.I)


def is_heading_cv(line):
    t = line.strip().rstrip(":")
    return L.is_heading(t) or (len(t.split()) <= 5 and bool(EXP_HEADING_RE.fullmatch(t)) and t[:1].isupper())


def analyse_cv(doc):
    """ATSLab_v3.analyse with the extra experience headings (v3 itself is not changed)."""
    rows = [r for r in doc["rows"] if not L.WATERMARK_RE.search(r["text"])]
    header, sections = [], []
    headline = L.headline_rows([r["text"] for r in rows])
    for i, r in enumerate(rows):
        t = r["text"].strip()
        if i > 0 and i not in headline and is_heading_cv(t):
            kind = "experience" if EXP_HEADING_RE.fullmatch(t.rstrip(":")) else                 "languages" if re.search(r"language", t, re.I) else L.section_kind(t)   # 'Language Skills' too
            sections.append({"title": t, "kind": kind, "rows": []})
        elif sections:
            sections[-1]["rows"].append(r)
        else:
            header.append(r)
    sections = L.synthesize_experience(sections)         # jobs under company names, no 'Experience' heading
    exp_lines = [r["text"].strip() for s in sections if s["kind"] == "experience" for r in s["rows"]]
    jobs = L.parse_jobs(exp_lines)
    recent_from = L.TODAY.year - L.RECENT_YEARS
    chunks = [(" ".join(r["text"] for r in header), L.OLD_LOCATION)]
    for s in sections:
        texts = [r["text"] for r in s["rows"]]
        if s["kind"] in ("skills", "competencies"):
            chunks.append((" ".join(texts), 1.0))
        elif s["kind"] == "experience":                  # as in v3: recent jobs count fully, older ones less
            starts = [j["line"] for j in jobs] + [len(exp_lines)]
            offset = sum(len(x["rows"]) for x in sections[:sections.index(s)] if x["kind"] == "experience")
            mine = [j for j in jobs if offset <= j["line"] < offset + len(texts)]
            if not mine:
                chunks.append((" ".join(texts), L.OLD_LOCATION))
                continue
            chunks.append((" ".join(texts[: mine[0]["line"] - offset]), L.OLD_LOCATION))
            for j in mine:
                nxt = next((x for x in starts if x > j["line"]), len(exp_lines))
                recent = j["end_year"] is not None and j["end_year"] >= recent_from
                chunks.append((" ".join(exp_lines[j["line"]: min(nxt, offset + len(texts))]),
                               1.0 if recent else L.OLD_LOCATION))
        else:
            chunks.append((" ".join(texts), L.OLD_LOCATION))
    return {"header": header, "sections": sections, "jobs": jobs,
            "chunks": [(L.tokens(t), m) for t, m in chunks if t.strip()]}


# ---------------------------------------------------------------------------
# Bullets: the statements under each job (wrapped lines joined, job header lines left out)
# ---------------------------------------------------------------------------
def experience_statements(ana):
    """-> list of bullet / sentence texts from the Experience section."""
    return [t for t, _ in experience_items(ana)]


def experience_items(ana):
    """-> [(text, written as a bullet?)]: bullets, and the sentences of job intro paragraphs."""
    return [(t, b) for t, b, _ in experience_items_by_job(ana)]


def experience_items_by_job(ana):
    """-> [(text, written as a bullet?, job index or None)]."""
    lines = [r["text"].strip() for s in ana["sections"] if s["kind"] == "experience" for r in s["rows"]]
    skip = set()
    # the job lines, and job headers the job list missed (a long 'Title | Company, City, Mon YYYY - Mon YYYY'): a
    # bullet is never joined with them. Each with the short line under it (company / title).
    heads = {j["line"] for j in ana["jobs"]} | {i for i, l in enumerate(lines) if job_header(l)}
    for i in heads:
        skip.add(i)
        nxt = i + 1
        if nxt < len(lines) and (len(lines[nxt].split()) <= 9 or L.find_ranges(lines[nxt])) \
                and not lines[nxt].endswith(".") and not BULLET_START_RE.match(lines[nxt]):
            skip.add(nxt)
    job_at = {j["line"]: k for k, j in enumerate(ana["jobs"])}
    items, cur, is_bullet, job, cur_job = [], [], False, None, None     # items: (text, bullet?, job)
    for i, l in enumerate(lines):
        if i in job_at:
            job = job_at[i]
        if i in skip or L.date_only(l) or LABEL_LINE_RE.match(l):
            if cur:
                items.append((" ".join(cur), is_bullet, cur_job))
                cur = []
            continue
        marked = bool(BULLET_START_RE.match(l) or LABEL_RE.match(l))
        if cur and (marked or (cur[-1].endswith(".") and l[:1].isupper())):   # a new bullet / sentence starts
            items.append((" ".join(cur), is_bullet, cur_job))
            cur = []
        if not cur:
            is_bullet, cur_job = marked, job
        cur.append(BULLET_START_RE.sub("", l, count=1))
    if cur:
        items.append((" ".join(cur), is_bullet, cur_job))
    out = []
    for text, is_bullet, jk in items:
        if is_bullet:
            out.append((text.strip(), True, jk))
        else:                                            # a paragraph: one statement per sentence
            out += [(s.strip(), False, jk) for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text) if len(s.split()) >= 4]
    out = [(s, b, jk) for s, b, jk in out if len(s.split()) >= 4 and not is_name_list(s)]
    if not out and not lines:                            # no Experience section found: use the body text
        body = [r["text"].strip() for s in ana["sections"]
                if s["kind"] not in ("summary", "skills", "competencies", "education", "languages", "certifications")
                for r in s["rows"]]
        out = [(l, False, None) for l in body if len(l.split()) >= 6 and not heading_or_date(l)]
    return out


LABEL_LINE_RE = re.compile(r"^\s*(?:key\s+|main\s+|selected\s+)?(?:accomplishments|achievements|responsibilities|"
                           r"duties|highlights|results|tasks|key results|impact)\s*:?\s*$", re.I)
JOB_HEADER_WORDS = 25
HEADER_SEP_RE = re.compile(r"^\s*(?:[|,–—]|-\s)")


def job_header(line):
    """'Senior Project Manager | Northwind Construction LLC, Dubai, UAE, Jan 2018 - Dec 2022' or 'Jan 2018 - Dec 2022 |
    Title, Company': a title or company with its dates at the end of the line, or at the start followed by a
    separator. Not a bullet and not a sentence (a wrapped bullet ending in a full stop is not a header)."""
    l = line.strip()
    if BULLET_START_RE.match(l) or ICON_BULLET_RE.match(l) or l.endswith((".", ";", ",", ":")) \
            or len(l.split()) > JOB_HEADER_WORDS:
        return False
    ranges = list(L.RANGE_RE.finditer(l))
    if not ranges:
        return False
    if not l[ranges[-1].end():].strip(" )|"):
        return True                                      # the dates end the line
    return not l[:ranges[0].start()].strip(" (") and bool(HEADER_SEP_RE.match(l[ranges[0].end():]))



def is_name_list(statement):
    """'Clients: Epson, Lenovo, bayut, ...' is a list of names, not an achievement bullet."""
    m = LABEL_RE.match(statement)
    rest = statement[m.end():] if m else ""
    return bool(m) and rest.count(",") >= 3 and not is_action_verb(first_word(rest)[0])


def heading_or_date(line):
    return L.is_heading(line) or L.date_only(line) or bool(L.RANGE_RE.search(line) and len(line.split()) <= 8)


SUMMARY_MINOR, SUMMARY_IMPORTANT = 0.75, 0.4
SUMMARY_MAX_WORDS = 150


def summary_band(words):
    """Only a summary over 150 words is flagged (Minor): any shorter summary is fine."""
    if words > SUMMARY_MAX_WORDS:
        return f"over {SUMMARY_MAX_WORDS} words", SUMMARY_MINOR
    return "fine", 1.0


def summary_length_score(words):
    """Same rule as the v3 summary check: 40-90 words is best."""
    if words == 0:
        return 0.0
    if words < 40:
        return words / 40
    if words <= 90:
        return 1.0
    return max(0.0, 1 - (words - 90) / 180)


def job_lines(ana):
    lines = [r["text"].strip() for s in ana["sections"] if s["kind"] == "experience" for r in s["rows"]]
    return lambda j: lines[j["line"]] if j["line"] < len(lines) else j["title"]


def first_word(statement):
    s = LABEL_RE.sub("", statement, count=1)
    m = re.match(r"[A-Za-z][A-Za-z\-]*", s)
    return (m.group(0).lower() if m else ""), s


def is_action_verb(word):
    if not word:
        return False
    base = [word, word[:-1], word[:-2], word[:-3], re.sub(r"ied$", "y", word), re.sub(r"ies$", "y", word),
            re.sub(r"ing$", "", word), re.sub(r"ing$", "e", word), re.sub(r"ed$", "e", word)]
    return any(b in ACTION_VERBS for b in base if b)


def has_number(statement):
    t = L.RANGE_RE.sub(" ", statement)
    t = re.sub(rf"\b{L.MONTH}\s*{L.YEAR}\b|\b(19|20)\d\d\b", " ", t, flags=re.I)   # dates are not results
    return bool(NUMBER_RE.search(t)) or "%" in t or "$" in t


# ---------------------------------------------------------------------------
# Content Quality
# ---------------------------------------------------------------------------
def no_number_quotes(ana):
    """Bullets of the experience that show no number or result: only bullets (never the summary, an education line
    or a job line). A resume with no bullet marks: the sentences of its experience that are not such lines."""
    items = experience_items(ana)
    bullets = [t for t, b in items if b and not has_number(t)]
    if bullets:
        return bullets
    return [t for t, b in items if not b and not has_number(t) and len(t.split()) >= 6 and not is_degree(t)
            and not SCHOOL_WORDS_RE.search(t) and not L.find_ranges(t)]


def length_check(words, years, pages=None):
    """C7: only a resume that is too short for the experience is flagged (Minor): 8+ years in under 350 words, or
    10+ years on one page. A long resume is never flagged here."""
    if years >= SHORT_YEARS and words < SHORT_WORDS:
        return {"score": SHORT_SCORE, "evidence": [],
                "detail": f"{words} words for ~{years:.0f} years of experience (at least {SHORT_WORDS} expected)"}
    if years >= ONE_PAGE_YEARS and pages == 1:
        return {"score": SHORT_SCORE, "evidence": [],
                "detail": f"1 page for ~{years:.0f} years of experience (2 pages expected)"}
    on = f" on {pages} page{'s' if pages != 1 else ''}" if pages else ""
    return {"score": 1.0, "detail": f"{words} words{on} for ~{years:.0f} years of experience", "evidence": []}


def content_checks(doc, ana, res, target, years=None, pages=None):
    """-> {id: {"score": 0-1, "detail": str, "evidence": [quotes]}}. doc / ana: the page as a person reads it;
    pages: the number of pages of the file (None when unknown)."""
    st = experience_statements(ana)
    n = len(st)
    c = {}
    quant = [s for s in st if has_number(s)]
    share = len(quant) / n if n else 0.0
    c["C1"] = {"score": min(1.0, share / QUANT_TARGET),
               "detail": f"{len(quant)} of {n} bullets have a number or result",
               "evidence": no_number_quotes(ana)[:3], "quant_share": share, "bullets": n}
    weak = [s for s in st if WEAK_OPENERS.match(first_word(s)[1])]
    c["C2"] = {"score": 1.0 - (len(weak) / n if n else 0.0), "detail": f"{n - len(weak)} of {n} bullets do not "
               f"start with a weak opener (merged into C11)", "evidence": weak[:3]}
    rows = L.section_rows(ana, "summary")
    summary = " ".join(BULLET_START_RE.sub("", r["text"], count=1) for r in rows)
    bulleted = [r["text"] for r in rows if BULLET_START_RE.match(r["text"].strip())]
    words = len(summary.split())
    band, score = summary_band(words)
    c["C4"] = {"score": score, "words": words, "band": band,
               "detail": f"summary {words} words ({band})" if summary else "no summary",
               "evidence": [summary[:300]] if score < 1 else []}
    # rule 2: good, detailed content is rewarded. A recruiter needs about 3 bullets for each role of the last 10 years.
    recent = [j for j in ana["jobs"] if j["end_year"] is None or j["end_year"] >= L.TODAY.year - RECENT_DETAIL_YEARS]
    target = min(DETAIL_MAX, max(DETAIL_MIN, DETAIL_PER_ROLE * len(recent)))
    c["C18"] = {"score": min(1.0, n / target), "detail": f"{n} bullets for {len(recent)} role(s) of the last "
                f"{RECENT_DETAIL_YEARS} years (about {target} expected)", "evidence": [], "share": n / target}
    c["C17"] = {"score": 0.0 if len(bulleted) >= 2 else 1.0,
                "detail": f"summary written as {len(bulleted)} bullets" if len(bulleted) >= 2 else "no bullets in the summary",
                "evidence": [t.strip() for t in bulleted[:2]]}
    low = doc["modern"].lower()
    found = [b for b in BUZZWORDS if re.search(rf"\b{re.escape(b)}\b", low)]
    found += [p for p in L.TEMPLATE_PHRASES if p in low]
    found += [w for w in FILLER_WORDS if len(re.findall(rf"\b{re.escape(w)}\b", low)) >= 2]   # repeated filler
    quotes = []                                   # the sentence that holds the phrase (never a whole paragraph)
    for l in doc["modern"].splitlines():
        for b in found:
            m = re.search(rf"\b{re.escape(b)}\b", l, re.I)
            if m:
                q = sentence_of(l.strip(), m.group(0))
                if q not in quotes:
                    quotes.append(q)
                break
    quotes = quotes[:3]
    c["C5"] = {"score": max(0.0, 1 - 0.15 * len(found)),
               "detail": "buzzwords / template phrases / repeated filler: " + (", ".join(found) or "none"),
               "evidence": quotes}
    c.update(standard_content_checks(doc, ana))
    norm = lambda s: " ".join(re.findall(r"[a-z0-9]+", s.lower()))
    seen, dupes = set(), []
    for s in st:
        k = norm(s)
        if len(k.split()) >= 8:
            if k in seen:
                dupes.append(s)
            seen.add(k)
    bug = {b["code"]: b for b in res["bugs"]}
    penalty = 0.25 * len(dupes) + 0.4 * bug["B9"]["found"] + 0.5 * bug["B13"]["found"]
    ev = dupes[:2]                                       # quotes from the CV, never internal notes
    if bug["B9"]["found"]:
        ev += [x["text"] for x in L.section_rows(ana, "achievements")][:2]
    if bug["B13"]["found"]:
        ev += [t for t, _ in (doc.get("shared_text") or [])][:1]
    c["C6"] = {"score": max(0.0, 1 - penalty),
               "detail": f"{len(dupes)} repeated bullet(s); achievements repeat experience: "
                         f"{'yes' if bug['B9']['found'] else 'no'}; text shared with another CV: "
                         f"{'yes' if bug['B13']['found'] else 'no'}", "evidence": ev}
    years = res["experience_years"] if years is None else years
    c["C7"] = length_check(len(doc["modern"].split()), years, pages)
    return c


# checks that are shares with their own target (a few misses are not yet a failed standard)
SHARE_CHECKS = {"C1", "C6", "C7", "C18"}


# =====================================================================================================================
# THE SCORING RULES (2026-10-26). The same rules for every resume: no rule names a person, a file or a template.
# The reference resumes in reference_scores.json (checked by test_reference.py) lock how they score.
#
# 1. The file is scored as it is uploaded. An ATS reads the whole file, so every page counts. (A file with a designed
#    version and a text version gets a note, but the score is the score of the whole file.)
# 2. Three parts, and each one means one thing:
#    - Readability: can an ATS read it (layout, columns, images, fonts, reading order).
#    - Content: how strong the information is (headline, numbers, results, verbs, clarity). Good, detailed content
#      is rewarded here even on a bad template.
#    - Structure: is it built like a standard resume, the page format included (portrait, one column).
# 3. Layout limits (hard caps, LAYOUT_LIMITS below): a landscape page, or columns / a sidebar on any page, limit
#    Readability, Structure and the total. Strong content moves a resume up inside these limits, never past them.
#    A page that is an image (or mostly one) is an unreadable page: Readability counts only the readable pages.
# 4. Fixed severity (rule_severity below): Critical = the layout problems of rule 3; Important ("Major" in the code)
#    = no headline, few numbers, missing or year-only dates, missing email or phone; Minor = everything else.
#    AI findings are Important at most, and at most 3 (cv_review.py).
# 5. "Can reach about X" is at most 95 (MAX_PROMISE). With a layout limit, the sentence says "after moving to a
#    single-column, portrait resume" (dashboard.py).
# 6. Quotes are clean lines; never just the name; "Not found in your resume" when something is missing (dashboard.py).
# =====================================================================================================================
LAYOUT_LIMITS = {
    "landscape": {"readability": 50, "structure": 55, "total": 50},     # any landscape page
    "columns": {"readability": 45, "structure": 55, "total": 55},       # 2 or more columns, or a sidebar, on any page
    "both_total": 40,                                                    # a landscape page AND columns / a sidebar
}
LAYOUT_IDS = {"D3", "D4", "D10", "D12", "D13", "T15"}       # sidebar, columns, reading order, landscape, image page,
#                                                             page format: the Critical layout problems of rule 3
DATE_IDS = {"B11", "R6", "R7"}                              # missing or year-only job dates (the v3 checks)
EMAIL_IDS = {"T7", "B4", "R2"}                              # no email
# what each problem costs Readability, by its severity (layout bugs and design problems; one shared cap)
READ_PENALTY = {"Critical": 15, "Major": 10, "Minor": 5}


def rule_severity(iid, cc=None, pc=None, res=None, design=None):
    """Rule 4: the severity of an issue, the same on every resume (never from its points)."""
    c = (cc or {}).get(iid) or (pc or {}).get(iid) or {}
    if iid in LAYOUT_IDS or iid == "TPL":
        return "Critical"
    if iid == "D11":                                  # too many pages: Important from PAGES_OVER_MAJOR pages over
        return "Major" if ((design or {}).get("D11") or {}).get("over", 0) >= PAGES_OVER_MAJOR else "Minor"
    if iid == "C15":                                  # no headline with a target job title (a headline of areas too)
        return "Major"
    if iid == "K":                                    # a skill the job REQUIRES is missing: Important; preferred: Minor
        return "Major" if any(k["match"] == "missing" and k["type"] == "required"
                              for k in (res or {}).get("keywords", [])) else "Minor"
    if iid == "C1":                                   # few bullets with a number or result
        return "Major"
    if iid == "T4":                                   # Important when a job's dates are missing or year-only
        return "Major" if c.get("date_problems") else "Minor"
    if iid == "T3":                                   # no phone at all: Important; a phone in another format: Minor
        return "Major" if c.get("detail") == "no phone number" else "Minor"
    if iid in EMAIL_IDS or iid in DATE_IDS:
        return "Major"
    return "Minor"


def page_format_check(limits, design):
    """Rule 2: a standard resume page is portrait and in one column. Landscape pages, columns or a sidebar fail it
    (a Critical structure problem; its cost includes the Structure limit of rule 3)."""
    found = []
    if limits["landscape"]:
        found += (design.get("D12") or {}).get("evidence", [])[:2] or ["a landscape page"]
    if limits["columns"]:
        found += ((design.get("D4") or {}).get("evidence", []) + (design.get("D3") or {}).get("evidence", []))[:2]             or ["columns side by side"]
    what = [w for w, on in (("landscape pages", limits["landscape"]), ("columns or a sidebar", limits["columns"])) if on]
    return {"score": 0.0 if what else 1.0, "detail": ("not a standard page: " + " and ".join(what)) if what
            else "portrait, one column", "evidence": found[:3]}


def layout_limits(layout, design):
    """Rule 3 for this file: which limits apply and the caps they set (None = no cap)."""
    landscape = bool(layout and layout.get("landscape"))
    columns = bool(layout and layout.get("columns_found")) or bool((design or {}).get("D3", {}).get("found"))
    pages = (layout or {}).get("pages") or 1
    images = (layout or {}).get("image_pages") or 0
    caps = {"readability": None, "structure": None, "total": None}
    for on, name in ((landscape, "landscape"), (columns, "columns")):
        if on:
            for k, v in LAYOUT_LIMITS[name].items():
                caps[k] = v if caps[k] is None else min(caps[k], v)
    if landscape and columns:
        caps["total"] = min(caps["total"], LAYOUT_LIMITS["both_total"])
    return {"landscape": landscape, "columns": columns, "image_pages": images, "pages": pages,
            "readable_share": max(0.0, (pages - images) / pages), "caps": caps,
            "active": landscape or columns or images > 0}


def apply_limits(parts, limits, lifted=False):
    """The parts with the layout limits applied. lifted=True: the layout is fixed (a single-column, portrait resume
    without image pages), so no limit applies."""
    if lifted or not limits or not limits["active"]:
        return dict(parts)
    out = dict(parts)
    out["readability"] = parts["readability"] * limits["readable_share"]
    for k in ("readability", "structure"):
        if limits["caps"][k] is not None:
            out[k] = min(out[k], limits["caps"][k])
    return out


# A failed 1000jobs standard also costs its OWN part points (not the total): then fixing an issue can never add
# more to the Resume Score than the issue costs its part. Calibrated on 2026-10-21: Mohamed's original 64, Jibran's
# original 70, Shikha's original 51, Tareq 42 (targets 60-68, 50-70, 50-70, under 50; see TestCalibration).
PART_PENALTY = {"Critical": 15.0, "Major": 12.0, "Minor": 2.0}
PART_PENALTY_CAP = 35.0


def failed_standards(checks, weights):
    """-> {check: severity} for every failed standard among these checks (a share check fails below 0.75)."""
    out = {}
    for k in weights:
        if k in NOTE_ONLY:
            continue
        v = checks[k]["score"]
        if k == "C1":
            v = min(1.0, checks[k]["quant_share"] / QUANT_TARGET) if checks[k]["bullets"] else 0.0
        if v is not None and v < 1 and (k not in SHARE_CHECKS or v < 0.75):
            out[k] = rule_severity(k, checks, checks)
    return out


def standard_failed(cc, pc):
    return {**failed_standards(cc, CONTENT_WEIGHT), **(failed_standards(pc, STRUCT_WEIGHT) if pc else {})}


MINOR_CAP = None               # None = no cap (decision for v1.0). A number = Minor issues of one part cost that many points at most
HEADLINE_CAP = 20.0            # "No headline" (Important) takes 20 points at most from the total


def penalty_of(failed):
    return min(PART_PENALTY_CAP, sum(PART_PENALTY[v] for v in failed.values()))


def minor_excess(checks, weights, failed):
    """Points to give back so the Minor issues of this part cost MINOR_CAP at most: what a Minor check loses of its
    weight, plus the 2 points each failed Minor standard costs."""
    cost = sum(100 * w * (1 - checks[k]["score"]) for k, w in weights.items()
               if checks[k]["score"] is not None and rule_severity(k, checks, checks) == "Minor")
    cost += sum(PART_PENALTY["Minor"] for v in failed.values() if v == "Minor")
    return 0.0 if MINOR_CAP is None else max(0.0, cost - MINOR_CAP)


def part_value(checks, weights, cap=True, free=0.0):
    """The part from its checks. cap=False: without the Minor cap (what each issue would cost alone: the explanation
    scales these costs so they add up to the part's real loss). free: the weight of removed checks, always in full."""
    base = 100 * (free + sum(w * checks[k]["score"] for k, w in weights.items()))
    failed = failed_standards(checks, weights)
    pen = penalty_of(failed)
    return min(100.0, base - pen + (minor_excess(checks, weights, failed) if cap else 0.0))


def content_part(cc, cap=True):
    base = part_value(cc, CONTENT_WEIGHT, cap, sum(RETIRED_WEIGHT.values()))
    ai = (cc.get("C8") or {}).get("score")
    return max(0.0, base - (0 if ai is None else 100 * AI_WEIGHT * (1 - ai)))


def ai_check(findings):
    """C8 from the AI reviewer's content findings (None when there was no review)."""
    if findings is None:
        return {"score": None, "detail": "no AI review", "evidence": []}
    pen = sum(AI_PENALTY[f["severity"]] for f in findings)
    return {"score": max(0.0, 1 - pen), "detail": f"{len(findings)} problem(s) found by the AI reviewer",
            "evidence": [f["quote"] for f in findings][:3]}


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------
def contact_block(doc, around=3):
    """The lines near the email / phone (the contact details, wherever they are on the page)."""
    lines = [l.strip() for l in doc["modern"].splitlines() if l.strip()]
    hits = [i for i, l in enumerate(lines) if L.EMAIL_RE.search(l) or L.PHONE_RE.search(l)]
    keep = sorted({j for i in hits for j in range(max(0, i - around), min(len(lines), i + around + 1))})
    return [lines[j] for j in keep]


CONTACT_BITS_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s\-()]{7,}\d|(?:https?://)?(?:www\.)?\S+\.(?:com|net|org|io)"
                             r"\S*|\blinked\s?in\b:?", re.I)   # email, phone, links, 'LinkedIn' (left: the place)


SHORT_DEGREE_RE = re.compile(r"\b(?:B|M)\.\s?(?:S|A|E|Sc|Tech|Eng|Com)\b\.?", re.I)     # 'B.S. in Marketing', 'M.A.'


def is_city(segment):
    """'Dubai' / 'Abu Dhabi': a known city or region name alone is a location too."""
    words = L.tokens(segment)
    return 0 < len(words) <= 3 and all(w in L.PLACES - {"global", "international", "local", "regional"}
                                       for w in words)


def completeness_checks(doc, ana, res):
    f = L.ats_fields(doc, ana)
    c = {}
    c["P1"] = {"score": float(bool(f["linkedin"])), "detail": f["linkedin"] or "no LinkedIn link found"}
    c["P2"] = {"score": min(1.0, len(f["skills"]) / 8), "detail": f"{len(f['skills'])} skills listed"}
    certs = [r for s in ana["sections"] if s["kind"] == "certifications" for r in s["rows"]]
    c["P3"] = {"score": float(bool(certs)), "detail": f"{len(certs)} certification line(s)" if certs
               else "no certifications section"}
    edu = " ".join(r["text"] for r in L.section_rows(ana, "education")) or \
        " ".join(l for l in doc["modern"].splitlines() if any(re.search(p_, l.lower()) for _, p_ in L.DEGREE_PATTERNS)
                 or SHORT_DEGREE_RE.search(l))
    degree = any(re.search(p_, edu.lower()) for _, p_ in L.DEGREE_PATTERNS) or bool(SHORT_DEGREE_RE.search(edu))
    year = bool(re.search(L.YEAR, edu)) or L.experience_years(ana["jobs"]) >= L.SENIOR_YEARS
    c["P4"] = {"score": (0.5 * degree + 0.5 * year) * (1.0 if f["education"] else 0.5),
               "detail": f"degree {'found' if degree else 'not found'}, year {'found' if year else 'not found'}",
               "evidence": [r["text"] for r in L.section_rows(ana, "education")][:3]}
    jobs = f["jobs"]
    raw = job_lines(ana)
    ok = lambda j: j["title"] and j["company"] and j["dates"] and not j["title_problem"] \
        and not MERGED_TITLE_RE.search(j["title"])
    full = [j for j in jobs if ok(j)]
    bad = [(j, aj) for j, aj in zip(jobs, ana["jobs"]) if not ok(j)]
    why = lambda j: ("two titles in one" if MERGED_TITLE_RE.search(j["title"]) else j["title_problem"]
                     or ", ".join(x for x in ("title", "company", "dates") if not j[x]) + " missing")
    c["P5"] = {"score": len(full) / len(jobs) if jobs else 0.0,
               "detail": f"{len(full)} of {len(jobs)} jobs have a clean title, company and dates",
               "evidence": [f"{raw(aj)}" + (f" / {j['title']}" if j["title"] not in raw(aj) else "") + f"  ({why(j)})"
                            for j, aj in bad][:3]}
    location = f["location"]
    if not location:                                     # the lines around the email / phone count too (sidebar)
        location = next((seg.strip(" ,|-") for l in contact_block(doc) for seg in re.split(
                         r"\s[|•·]\s|\s{2,}|\|", CONTACT_BITS_RE.sub("  |  ", l))
                         if seg.strip(" ,|-") and (L.is_place(seg.strip(" ,|-")) or is_city(seg))), None)
    c["P6"] = {"score": float(bool(location)), "detail": location or "no location found"}
    return c


def completeness_part(pc):
    return 100 * sum(COMPLETE_WEIGHT[k] * pc[k]["score"] for k in COMPLETE_WEIGHT)



# ---------------------------------------------------------------------------
# The 1000jobs CV standard: content (headline, numbers, labels, openers, abbreviations, old roles, tense)
# ---------------------------------------------------------------------------
FILLER_WORDS = ["approximately", "various", "successfully", "effectively", "efficiently", "very", "highly",
                "seamlessly", "robust", "really", "basically", "etc"]
# business abbreviations a recruiter may not know: written in full at least once (e.g. "Customer Relationship
# Management (CRM)"); places, degrees and job titles are never on this list
ABBR_FULL = {"CRM": "customer relationship management", "KPI": "key performance indicator",
             "KPIs": "key performance indicators", "ROI": "return on investment", "SLA": "service level agreement",
             "SLAs": "service level agreements", "OKR": "objectives and key results",
             "OKRs": "objectives and key results", "SDLC": "software development life cycle",
             "ERP": "enterprise resource planning", "SEO": "search engine optimization",
             "SEM": "search engine marketing", "PPC": "pay per click", "B2B": "business to business",
             "B2C": "business to consumer", "SaaS": "software as a service", "CX": "customer experience",
             "UX": "user experience", "NPS": "net promoter score", "CSAT": "customer satisfaction",
             "QA": "quality assurance", "UAT": "user acceptance testing", "RFP": "request for proposal",
             "RFQ": "request for quotation", "MTTR": "mean time to resolution", "CAB": "change advisory board",
             "POD": "proof of delivery", "SOA": "statement of account", "3PL": "third-party logistics",
             "FMCG": "fast-moving consumer goods", "GTM": "go-to-market", "PMO": "project management office",
             "ETL": "extract, transform, load", "BI": "business intelligence", "NLP": "natural language processing",
             "LMS": "learning management system", "HRIS": "human resources information system",
             "ATS": "applicant tracking system", "P&L": "profit and loss", "EHS": "environment, health and safety",
             "HSE": "health, safety and environment", "CAPEX": "capital expenditure", "OPEX": "operating expenditure"}
# well-known abbreviations every recruiter reads: never flagged (only the less common ones are)
COMMON_ABBR = {"KPI", "KPIs", "UX", "UI", "AI", "CEO", "CFO", "COO", "CTO", "USD", "AED", "UAE", "GCC", "ROI", "ROAS",
               "CRM", "SEO", "B2B", "B2C", "HR", "IT", "PR", "P&L", "QA", "SaaS", "ERP", "BI", "ATS", "CX"}
RESULT_NUMBER_RE = re.compile(r"(?<![\w.])(?:[$\u20ac\u00a3]|AED\s?|USD\s?)?\d[\d,.]*(?:\s?(?:%|[KMB]\b|\+|x\b))?", re.I)
NOT_PRESENT = {"led", "founded", "co-founded", "set", "cut", "put", "read", "run", "spread", "found"}
OLD_YEARS = 10
OLD_MAX_BULLETS = 2


def is_present_tense(word):
    w = word.lower()
    if not w or w in NOT_PRESENT or w.endswith("ed"):
        return False
    if w in ACTION_VERBS:
        return True
    return (w.endswith("es") and w[:-2] in ACTION_VERBS) or (w.endswith("s") and w[:-1] in ACTION_VERBS) or \
        (w.endswith("ing") and is_action_verb(w))


def job_end(job):
    return max((e for _, e in job["intervals"]), default=None)


def headline_line(ana):
    """The line under the name that gives a target title ('Logistics Coordinator | Supply Chain'), or None."""
    for r in ana["header"][1:5]:
        t = r["text"].strip()
        if re.search(r"@|linkedin|https?:|www\.", t, re.I) or len(re.sub(r"\D", "", t)) >= 7:
            continue
        if L.TITLE_WORDS.search(t) and len(t.split()) <= 20:
            return t
    return None


RESULT_MONEY_RE = re.compile(r"(?:USD|AED|US\$|\$|\u20ac|\u00a3)\s?(\d[\d,]*(?:\.\d+)?)\s?(k|m|bn|b|million|billion)?(?![a-z])",
                             re.I)
RESULT_TIMES_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?x\b", re.I)
RESULT_PCT_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?%")
MONEY_MULT = {"k": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
# words every result sentence uses: they do not show two sentences are about the same result
RESULT_GENERIC = set("""revenue growth grow grew increase increased increasing drive drove driving driven generate
generated generating annual annually projected launch launched launches platform platforms feature features capability
capabilities support supported supporting deliver delivered delivery through with from margin introduce introduced
improve improved improving reduce reduced reducing user users team teams across while million over more than into their
this that which including result results performance customer customers business management strategy strategic lead led
leading managed manage managing within total year years month months first time based also achieved achieve add added
adding contributing contribute contributed rate rates cost costs saving savings value high higher new key major""".split())


def result_numbers(text):
    """{'money': {...}, 'times': {...}, 'percent': {...}} of one statement (money in plain units)."""
    money = {round(float(v.replace(",", "")) * MONEY_MULT.get((u or "").lower(), 1))
             for v, u in RESULT_MONEY_RE.findall(text)}
    return {"money": money, "times": {float(v) for v in RESULT_TIMES_RE.findall(text)},
            "percent": {float(v) for v in RESULT_PCT_RE.findall(text)}}


def topic_words(text):
    return {L.stem(t) for t in L.tokens(text) if len(t) >= 4 and t.isalpha() and t not in RESULT_GENERIC}


def result_statements(ana):
    """Every sentence that may state a result: summary, highlight boxes, achievements and experience."""
    out = []
    for s_ in ana["sections"]:
        if s_["kind"] not in ("summary", "glance", "achievements", "experience"):
            continue
        text = " ".join(BULLET_START_RE.sub("", r["text"].strip(), count=1) for r in s_["rows"])
        out += [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9$])|\s+[\u2022\u25aa\u25cf]\s+", text)
                if len(x.split()) >= 4]
    return out


# '... and maintaining 99% ...', '... while supporting 90% ...': a second result starts (not '... and projected ...')
SECOND_RESULT_RE = re.compile(r"\b(?:and|while|plus)\s+(?!projected|estimated|expected|annual)[a-z]+(?:ing|ed)\b", re.I)
RESULT_WINDOW = 12            # two numbers this close (in words, same clause) describe one result


def result_facts(text):
    """One result = two numbers of different kinds close together ('10x increase in reservations and projected
    revenue of $180,000') -> [(kind1, value1, kind2, value2, topic words around them)]."""
    hits = []
    for kind, rx in (("money", RESULT_MONEY_RE), ("times", RESULT_TIMES_RE), ("percent", RESULT_PCT_RE)):
        for m in rx.finditer(text):
            v = float(m.group(1).replace(",", ""))
            if kind == "money":
                v = round(v * MONEY_MULT.get((m.group(2) or "").lower(), 1))
            hits.append((len(text[:m.start()].split()), m.start(), m.end(), kind, v))
    words = text.split()
    facts = []
    for a in hits:
        for b in hits:
            if a[3] != b[3] and a[1] < b[1] and abs(b[0] - a[0]) <= RESULT_WINDOW and \
                    not re.search(r"[;.]\s|[,:|•·(]", text[a[2]:b[1]]) and \
                    not SECOND_RESULT_RE.search(text[a[2]:b[1]]):              # one clause, one result
                around = " ".join(words[max(0, min(a[0], b[0]) - 4): max(a[0], b[0]) + 5])
                for x, y in ((a, b), (b, a)):
                    facts.append((x[3], x[4], y[3], y[4], topic_words(around)))
    return facts


def same_result_conflicts(statements):
    """Pairs of statements that give the SAME result (one number equal, a topic word shared around it) with a
    DIFFERENT second number of the same kind ('10x ... reservations ... $180,000' vs '10x rise in reservations
    ... $15,000'). Numbers that only happen to be equal in unrelated results are left alone."""
    found, seen = [], set()
    info = [(st, result_facts(st), result_numbers(st)) for st in statements]
    for a in range(len(info)):
        for b in range(a + 1, len(info)):
            (sa, fa, na), (sb, fb, nb) = info[a], info[b]
            if " ".join(sa.lower().split()) == " ".join(sb.lower().split()):
                continue
            for k1, v1, k2, v2, ta in fa:
                hit = next((w2 for j1, w1, j2, w2, tb in fb if (j1, w1, j2) == (k1, v1, k2) and w2 != v2
                            and ta & tb and w2 not in na[k2] and v2 not in nb[k2]), None)
                if hit is not None:
                    key = (min(sa, sb), max(sa, sb))
                    if key not in seen:
                        seen.add(key)
                        found.append((sa, sb, [k2]))
                    break
    return found


REPEAT_MIN, REPEAT_MIN_HIGHLIGHT = 4, 3
SMALL_NUMBER = 10
MONTH_YEAR_RE = re.compile(rf"{L.MONTH}\.?\s*{L.YEAR}", re.I)
PLAIN_YEAR_RE = re.compile(r"(?<![\w.,$])(?:19|20)\d\d(?![\w%])")


SENTENCE_MAX = 220


def abbreviation_quotes(text, short):
    """The sentences that use an abbreviation never written in full (at most 2)."""
    out = []
    for l in text.splitlines():
        for a in short:
            m = re.search(rf"(?<![\w&]){re.escape(a)}(?![\w&])", l)
            if m:
                q = sentence_of(l.strip(), m.group(0))
                if q not in out:
                    out.append(q)
                break
    return out[:2]


def sentence_of(text, token):
    """The sentence of a (joined) line that holds the token: a quote is a readable sentence, not a whole paragraph."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9~$])", text.strip())
    p_ = next((p for p in parts if token in p), text.strip())
    if len(p_) > SENTENCE_MAX:                       # a very long sentence: the words around the token
        i = p_.find(token)
        a, b = max(0, i - 90), min(len(p_), i + len(token) + 110)
        if a:
            a = p_.find(" ", a) + 1 or a
        if b < len(p_):
            b = p_.rfind(" ", 0, b) if p_.rfind(" ", 0, b) > i else b
        p_ = ("… " if a else "") + p_[a:b].strip() + (" …" if b < len(p_) else "")
    return p_


def repeated_results(ana):
    """-> [{"number", "count", "lines"}]: a result (a number worth 10 or more, with similar words around it) that
    is told 4+ times, or 3+ times when one of them is in a highlight section. Years, dates, phone numbers and small
    numbers are not results."""
    occ = []
    for s_ in ana["sections"]:
        if s_["kind"] not in ("summary", "experience", "achievements", "glance"):
            continue
        for r in s_["rows"]:
            t = L.RANGE_RE.sub(" ", r["text"])
            t = MONTH_YEAR_RE.sub(" ", t)
            t = PHONE_ANY_RE.sub(lambda m: " " if len(re.sub(r"\D", "", m.group(0))) >= 7 else m.group(0), t)
            t = PLAIN_YEAR_RE.sub(" ", t)
            for m in RESULT_NUMBER_RE.finditer(t):
                n = re.sub(r"[\s,]", "", m.group(0)).upper()
                digits = re.sub(r"\D", "", n)
                if not digits:
                    continue
                value = float(re.search(r"\d+(?:\.\d+)?", n).group(0))
                big_unit = bool(re.search(r"[KMB]$", n)) and bool(re.search(r"[$€£]|AED|USD", n))
                if value < SMALL_NUMBER and not big_unit:
                    continue
                words = topic_words(t[max(0, m.start() - 70): m.end() + 70])      # the words around this number
                occ.append({"n": n, "words": words, "hi": s_["kind"] in ("glance", "achievements"),
                            "line": sentence_of(r["text"], m.group(0).strip())})
    out = []
    for n in {o["n"] for o in occ}:
        mine = [o for o in occ if o["n"] == n]
        left = list(range(len(mine)))
        while left:                                      # one cluster = occurrences with similar words around
            comp, todo = {left[0]}, [left[0]]
            left.remove(left[0])
            while todo:
                a = todo.pop()
                for b in list(left):
                    shared = len(mine[a]["words"] & mine[b]["words"])
                    small = min(len(mine[a]["words"]), len(mine[b]["words"]))
                    if shared >= 2 or (small <= 3 and shared >= 1):
                        comp.add(b); todo.append(b); left.remove(b)
            group = [mine[k] for k in comp]
            need = REPEAT_MIN_HIGHLIGHT if any(o["hi"] for o in group) else REPEAT_MIN
            if len(group) >= need:
                out.append({"number": n, "count": len(group), "lines": list(dict.fromkeys(o["line"] for o in group))})
    return sorted(out, key=lambda g: (-g["count"], g["number"]))



FIELD_HEADLINE_SCORE = 0.0     # rule 4 (2026-10-26): a headline that names no job title counts as no headline


def standard_content_checks(doc, ana):
    c = {}
    pairs = same_result_conflicts(result_statements(ana))
    c["C16"] = {"score": max(0.0, 1 - 0.5 * len(pairs)),
                "detail": f"{len(pairs)} result(s) given with different numbers in different places",
                "evidence": [f"\"{a}\"  vs  \"{b}\"" for a, b, _ in pairs][:3]}
    head = headline_line(ana)
    named = next((r["text"].strip() for r in ana["header"][1:4]
                  if not L.CONTACT_LINE_RE.search(r["text"]) and 2 <= len(r["text"].split()) <= 20), None)
    # a headline that names areas instead of a job title is only a small issue; no headline at all is an Important one
    c["C15"] = {"score": 1.0 if head else FIELD_HEADLINE_SCORE if named else 0.0, "has_headline": bool(named),
                "detail": head or (f"headline names areas, not a job title: {named}" if named
                                   else "no headline with a target title under the name"),
                "evidence": [r["text"] for r in ana["header"][:3]]}
    # the same result repeated: 4+ times, or 3 times when one is in a highlight section (Career Impact, Achievements)
    groups = repeated_results(ana)
    rep_n = [g["number"] for g in groups]
    c["C9"] = {"score": max(0.0, 1 - 0.34 * len(groups)),
               "detail": "same result repeated: " + (", ".join(f"{g['number']} ({g['count']} times)" for g in groups)
                                                      or "none"),
               "evidence": [q for g in groups for q in g["lines"]][:3]}
    # labels inside jobs ("Key Accomplishments:", "Responsibilities:")
    exp = [r["text"].strip() for s_ in ana["sections"] if s_["kind"] == "experience" for r in s_["rows"]]
    labels = [l for l in exp if LABEL_LINE_RE.match(l)]
    c["C10"] = {"score": max(0.0, 1 - 0.25 * len(labels)), "detail": f"{len(labels)} label line(s) inside jobs",
                "evidence": labels[:3]}
    items = experience_items_by_job(ana)
    bullets = [(t, jk) for t, b, jk in items if b]
    weak = [t for t, _ in bullets if WEAK_OPENERS.match(LABEL_RE.sub("", t, count=1))]
    c["C11"] = {"score": max(0.0, 1 - 0.25 * len(weak)), "detail": f"{len(weak)} bullet(s) start with a weak opener",
                "evidence": weak[:3]}
    used = [a for a in ABBR_FULL if a not in COMMON_ABBR and re.search(rf"(?<![\w&]){re.escape(a)}(?![\w&])", doc["modern"])]
    flat = re.sub(r"[\s\-]+", " ", doc["modern"].lower())
    short = [a for a in used if re.sub(r"[\s\-]+", " ", ABBR_FULL[a]) not in flat]
    short = [a for a in short if not (a.endswith("s") and a[:-1] in ABBR_FULL and a[:-1] in short)]
    c["C12"] = {"score": max(0.0, 1 - 0.25 * len(short)),
                "detail": "never written in full: " + (", ".join(short) or "none"),
                "evidence": abbreviation_quotes(doc["modern"], short)}
    now = L.TODAY.year * 12 + L.TODAY.month - 1
    raw = job_lines(ana)
    per_job = {}
    for t, jk in bullets:
        if jk is not None:
            per_job.setdefault(jk, []).append(t)
    old = [(ana["jobs"][jk], ts) for jk, ts in per_job.items()
           if job_end(ana["jobs"][jk]) is not None and job_end(ana["jobs"][jk]) <= now - 12 * OLD_YEARS
           and len(ts) > OLD_MAX_BULLETS]
    c["C13"] = {"score": max(0.0, 1 - 0.34 * len(old)),
                "detail": f"{len(old)} role(s) that ended {OLD_YEARS}+ years ago have more than {OLD_MAX_BULLETS} "
                          f"bullets", "evidence": [f"{raw(j)}  ({len(ts)} bullets)" for j, ts in old][:3]}
    past = [t for t, jk in bullets if jk is not None and job_end(ana["jobs"][jk]) is not None
            and job_end(ana["jobs"][jk]) < now - 1 and is_present_tense(first_word(t)[0])]
    c["C14"] = {"score": max(0.0, 1 - 0.25 * len(past)),
                "detail": f"{len(past)} bullet(s) of past jobs in present tense", "evidence": past[:3]}
    return c


# ---------------------------------------------------------------------------
# The 1000jobs CV standard: structure (sections, education, contact, jobs, skills)
# ---------------------------------------------------------------------------
ALLOWED_SECTION_RE = re.compile(
    r"(?:(?:professional|executive|career|personal)\s+)?(?:summary|profile|objective)"
    r"|(?:(?:professional|work|relevant|career)\s+)?experience|(?:employment|work|career)\s+history"
    r"|education(?:\s+(?:and|&)\s+(?:training|qualifications|certifications))?|academic background"
    r"|(?:(?:core|key|technical|professional)\s+)?(?:skills|competencies|expertise)"
    r"(?:\s+(?:and|&)\s+(?:tools|expertise|competencies|technologies|systems|software))?"
    r"|certifications?(?:\s+(?:and|&)\s+(?:licenses|licences|training|courses))?|licen[cs]es(?:\s+(?:and|&)\s+"
    r"certifications)?|languages?(?:\s+skills)?|additional information", re.I)
NON_DEGREE_RE = re.compile(r"\b(certificate|certification|course|courses|program|programme|challenge|bootcamp|"
                           r"training|workshop|summit|competition|nanodegree|seminar|hackathon|fellowship)\b", re.I)
SCHOOL_RE = re.compile(r"\b(university|college|institute|school|academy|polytechnic)\b", re.I)
PHONE_ANY_RE = re.compile(r"[(+]?[(+\d][\d\s\-().]{7,}\d")
PHONE_OK_RE = re.compile(r"\+\d{1,4}[\s-]?\d[\d\s-]{6,}\d")


BARE_DEGREE_RE = re.compile(r"^\s*(?:MA|MS|BA|BS|BSc|MSc|BEng|MEng|MPhil|MFA|BFA|BBA|LLB|LLM)\b")      # 'MA Graphic Design'


def is_degree(text):
    return any(re.search(p_, text.lower()) for _, p_ in L.DEGREE_PATTERNS) or bool(SHORT_DEGREE_RE.search(text)) \
        or bool(BARE_DEGREE_RE.search(text)) \
        or bool(re.search(r"\b(degree|ph\.?d|doctorate|bachelor|master|associate of)\b", text, re.I))


CITY_COUNTRY_RE = re.compile(r"^[A-Z][\w.'-]+(?:\s[A-Z][\w.'-]+){0,2},\s*[A-Z][\w.'-]+(?:\s[A-Z][\w.'-]+){0,2}$")


def has_location(text):
    """A job line with a place: 'Dubai, UAE', 'Montreal, QC', 'Libreville, Gabon', '... - UAE'. Each line is
    checked on its own (a place at the end of one line is not at the end of the joined text)."""
    for line in text.splitlines():
        rest = L.RANGE_RE.sub(" ", L.norm_punct(line)).strip(" |,")
        segs = [x.strip(" ,") for x in re.split(r"\s[|\u2013\u2014-]\s|\|", rest) if x.strip(" ,")]
        parts = [x.strip() for seg in segs for x in re.split(r"[,()&/]", seg) if x.strip()]
        if any(L.is_place(x) or is_city(x) for x in parts) or L.COUNTRY_END_RE.search(rest) or \
                any(CITY_COUNTRY_RE.match(seg) for seg in segs):
            return True
    return False


def find_location_any(doc, f):
    location = f["location"]
    if not location:                                     # the lines around the email / phone count too (sidebar)
        location = next((seg.strip(" ,|-") for l in contact_block(doc) for seg in re.split(
                         r"\s[|\u2022\u00b7]\s|\s{2,}|\|", CONTACT_BITS_RE.sub("  |  ", l))
                         if seg.strip(" ,|-") and (L.is_place(seg.strip(" ,|-")) or is_city(seg))), None)
    return location


SCHOOL_WORDS_RE = re.compile(r"\b(?:universit[a-zé]*|universidad|college|institute|school|academy|polytechni[a-z]*|"
                             r"faculty|faculté|lycée|hochschule|école|ecole|escuela|sorbonne)\b", re.I)
SCHOOL_ACRONYM_RE = re.compile(r"(?:[—–|,(]\s*)([A-Z]{3,8})\b")       # '... - JDBIMS, Mumbai', '(LAU, 2009)'
NOT_SCHOOL_ACRONYM = {"MBA", "BSC", "MSC", "PHD", "BBA", "BCOM", "UAE", "USA", "GPA", "CGPA", "KSA", "GCC", "EMEA",
                      "MENA", "CPA", "CFA", "PMP", "ACCA", "CIMA", "LLB", "LLM", "AND", "THE", "FOR"}


def has_school(text):
    """A school in this text: 'University of ...', 'Université du Québec', or an acronym after a separator
    ('MBA, Finance - JDBIMS, Mumbai', '(LAU, 2009)')."""
    return bool(SCHOOL_WORDS_RE.search(text)) or \
        any(m.group(1) not in NOT_SCHOOL_ACRONYM for m in SCHOOL_ACRONYM_RE.finditer(text))


def education_entries(rows):
    """-> [{"rows", "school", "year"}]: one entry per degree. The rows of an entry run from its degree line to the
    next degree line (at most 4 rows), plus a school line right above it. A degree's name, school and year may be on
    the same line or on the next lines."""
    at = [k for k, t in enumerate(rows) if is_degree(t) and not BULLET_START_RE.match(t.strip())
          and not re.match(r"^[\w ]{2,25}:", t.strip())]
    out = []
    for n, k in enumerate(at):
        end = min(at[n + 1] if n + 1 < len(at) else len(rows), k + 4)
        above = bool(k) and has_school(rows[k - 1]) and not is_degree(rows[k - 1])
        window = rows[k - 1 if above else k: end]
        text = " ".join(window)
        out.append({"rows": window, "school": has_school(text), "year": bool(re.search(L.YEAR, text))})
    return out


def is_date_line(text):
    """'(2002-2004)', '2009', 'Graduated 2016', 'Sep 2013 - Jun 2016': nothing but a date (and 'expected' words)."""
    t = L.RANGE_RE.sub(" ", text)
    t = re.sub(r"(?i)\b(?:c?gpa|grade|score|percentage|marks)\s*[:\-]?\s*[\d.]+(?:\s*/\s*[\d.]+)?\s*%?", " ", t)
    t = re.sub(r"(?i)\b(?:expected|graduated|graduation|class of|completed|since|in|year)\b", " ", t)
    t = MONTH_YEAR_RE.sub(" ", L.POINT_RE.sub(" ", t))
    t = PLAIN_YEAR_RE.sub(" ", t)
    return bool(re.search(r"\d", text)) and not re.search(r"[A-Za-z]", t)


def structure_checks(doc, ana, res):
    f = L.ats_fields(doc, ana)
    c = {}
    # the headings as written (a heading whose jobs were read as Experience still counts; a company line such as
    # 'VIRGIN MEDIA O2 (LONDON, UK)' is not a section name)
    titles = [t for s_ in ana["sections"] for t in ([s_["title"]] if "merged_titles" not in s_ else
              [m for m in s_["merged_titles"] if not has_location(m)]) if not t.strip().endswith(".")]
    odd = [t for t in titles if not ALLOWED_SECTION_RE.fullmatch(re.sub(r"\s+", " ", t.strip(" :")))
           and not L.is_standard_section(t)]
    c["T1"] = {"score": 1 - len(odd) / len(titles) if titles else 0.0,
               "detail": "non-standard: " + ("; ".join(odd) or "none"), "evidence": odd[:4]}
    entries = []
    for r in L.section_rows(ana, "education"):
        t = r["text"].strip()
        if BULLET_START_RE.match(t) or re.match(r"^[\w ]{2,25}:", t):
            continue                                      # course lists / 'Relevant Courses:' under a degree
        first = re.split(r"\s[|\u2013\u2014-]\s|,", t)[0]
        if is_degree(t) or is_date_line(t):
            continue                                      # a year / date line under a degree belongs to that degree
        if NON_DEGREE_RE.search(first) or (L.POINT_RE.search(t) and not SCHOOL_RE.search(first)):
            entries.append(t)
    c["T2"] = {"score": max(0.0, 1 - 0.5 * len(entries)), "detail": f"{len(entries)} non-degree item(s) under Education",
               "evidence": entries[:3]}
    phones = [m.group(0).strip() for l in contact_block(doc) for m in PHONE_ANY_RE.finditer(l)
              if len(re.sub(r"\D", "", m.group(0))) >= 9 and not L.RANGE_RE.search(m.group(0))]
    ph = phones[0] if phones else None
    ok = bool(ph) and bool(PHONE_OK_RE.fullmatch(ph)) and "(" not in ph and ")" not in ph
    c["T3"] = {"score": float(ok), "detail": ph or "no phone number",
               "evidence": [l for l in contact_block(doc) if ph and ph in l][:1]}
    raw = job_lines(ana)
    jobs = f["jobs"]
    bad, dates_bad, only_dates, no_place = [], [], True, []
    for j, aj in zip(jobs, ana["jobs"]):
        line = raw(aj)
        nxt_lines = [r["text"] for s_ in ana["sections"] if s_["kind"] == "experience" for r in s_["rows"]]
        around = "\n".join(nxt_lines[max(0, aj["line"] - 1): aj["line"] + 3])
        title_why = "no title" if not j["title"] else None if MERGED_TITLE_RE.search(j["title"]) \
            else j["title_problem"]
        if not has_location(around):                  # a job location is NOT required: a note of its own (T16)
            no_place.append(line)
        miss = ([title_why] if title_why else []) + \
            [x + " missing" for x, okx in (("company", j["company"]),
                                           ("Mon YYYY dates", aj["has_range"] and aj["problem"] is None)) if not okx]
        if miss == ["Mon YYYY dates missing"] and aj["dates"]:      # only the dates are wrong: quote the date line
            dates_bad.append((aj["dates"], aj["problem"] or "no month"))
            bad.append((f"{aj['dates']}  ({aj['problem'] or 'no month'})", None))
        elif miss:
            only_dates = False
            bad.append((line + (f" / {j['title']}" if j["title"] and j["title"] not in line else ""), miss))
            if "Mon YYYY dates missing" in miss:
                dates_bad.append((aj["dates"], aj["problem"] or "no date"))
    c["T4"] = {"score": 1 - len(bad) / len(jobs) if jobs else 0.0,
               "detail": f"{len(jobs) - len(bad)} of {len(jobs)} jobs have title, company and Mon YYYY dates",
               "evidence": [l if m is None else f"{l}  ({', '.join(m)})" for l, m in bad][:3],
               "dates_only": bool(bad) and only_dates, "date_problems": [p_ for _, p_ in dates_bad],
               "date_lines": [d for d, _ in dates_bad if d]}
    c["T16"] = {"score": 1 - len(no_place) / len(jobs) if jobs else 1.0,
                "detail": f"{len(jobs) - len(no_place)} of {len(jobs)} jobs show a location",
                "evidence": [f"{l}  (location missing)" for l in no_place][:3]}
    li = L.LINKEDIN_RE.search(doc["modern"])
    c["T5"] = {"score": float(bool(li)), "detail": li.group(0) if li else "no LinkedIn URL (linkedin.com/in/...)",
               "evidence": [x["text"] for x in ana["header"][:3]]}
    loc = find_location_any(doc, f)
    city = bool(loc) and ("," in loc or is_city(loc.split(",")[0]))
    c["T6"] = {"score": float(city), "detail": loc or "no city", "evidence": [x["text"] for x in ana["header"][:3]]}
    c["T7"] = {"score": float(bool(f["email"])), "detail": f["email"] or "no email",
               "evidence": [x["text"] for x in ana["header"][:3]]}
    nskills = sum(L.count_skill_items(s_["rows"]) for s_ in ana["sections"] if s_["kind"] in ("skills", "competencies"))
    c["T8"] = {"score": min(1.0, nskills / 8), "detail": f"{nskills} skills listed",
               "evidence": [r["text"] for s_ in ana["sections"] if s_["kind"] in ("skills", "competencies")
                            for r in s_["rows"]][:2]}
    rows = [r["text"] for r in L.section_rows(ana, "education")] or \
        [l for l in doc["modern"].splitlines() if is_degree(l)]
    entries = education_entries(rows)
    senior = L.experience_years(ana["jobs"]) >= L.SENIOR_YEARS
    degree = bool(entries)
    school = any(e["school"] for e in entries)
    every_year = degree and all(e["year"] for e in entries)         # every degree has its year
    year = every_year or senior                        # 10+ years of experience: the year may be left out
    short = next((e for e in entries if not (e["school"] and e["year"])), None)
    c["T9"] = {"score": (degree + year + school) / 3, "every_year": every_year, "entries": len(entries),
               "year_hidden": degree and not every_year and senior,
               "detail": ", ".join(f"{k} {'found' if v else 'missing'}" for k, v in
                                   (("degree", degree), ("school", school))) +
               (", year hidden (10+ years of experience)" if degree and not every_year and senior else
                f", year {'found for every degree' if every_year else 'missing'}"),
               "evidence": (short["rows"] if short and not (year and school) else rows)[:3]}
    c["T10"] = uae_details_check(doc, f)
    title_lines = [x["text"].strip() for x in ana["header"][:6]] + [raw(aj) for aj in ana["jobs"]]
    i_sep = [t for t in title_lines if I_SEPARATOR_RE.search(t)]
    c["T12"] = {"score": 0.0 if i_sep else 1.0,
                "detail": f"{len(i_sep)} title line(s) use a capital I as a separator", "evidence": i_sep[:3]}
    merged = [raw(aj) for j, aj in zip(jobs, ana["jobs"]) if j["title"] and MERGED_TITLE_RE.search(j["title"])]
    c["T11"] = {"score": max(0.0, 1 - 0.5 * len(merged)),
                "detail": f"{len(merged)} job title(s) with two titles in one (\"Senior / Media Manager\")",
                "evidence": merged[:3]}
    return c


# 'Designer I Brand Lead': a capital I between two titles (a level like 'Engineer I' at the end is fine)
I_SEPARATOR_RE = re.compile(r"(?<=[a-z0-9)]) I (?=[A-Z0-9])")
UAE_RE = re.compile(r"\+\s?971|\bU\.?A\.?E\b|United Arab Emirates|\bDubai\b|Abu Dhabi|Sharjah|Ajman|Ras Al Khaimah|"
                    r"Fujairah|Umm Al Quwain|\bAl Ain\b", re.I)
VISA_RE = re.compile(r"\bvisa\b|residen(?:ce|cy)\b|work permit|golden visa|\bnationality\b", re.I)
LICENCE_RE = re.compile(r"driv(?:ing|er'?s?)\s+licen[cs]e", re.I)
NOTICE_RE = re.compile(r"notice period|available (?:to join )?(?:immediately|from)|immediate(?:ly)? (?:joiner|available)|"
                       r"\bavailability\b", re.I)


def uae_details_check(doc, f):
    """UAE employers screen on visa status, a UAE driving licence and the notice period: a UAE resume with none of
    the three anywhere gets a Minor issue (add them only if true)."""
    contact = " ".join(contact_block(doc)) + " " + (f.get("location") or "") + " " + (f.get("phone") or "")
    if not UAE_RE.search(contact):
        return {"score": 1.0, "detail": "not a UAE resume", "evidence": []}
    text = doc["modern"]
    have = [n for n, rx in (("visa status", VISA_RE), ("driving licence", LICENCE_RE), ("notice period", NOTICE_RE))
            if rx.search(text)]
    return {"score": 1.0 if have else 0.0,
            "detail": "mentions " + ", ".join(have) if have else "no visa status, driving licence or notice period",
            "evidence": [l for l in contact_block(doc)][:2]}


STANDARD_OWNS = ("R2", "R3", "R4", "R6", "R7", "R8", "R11", "R13")


# ---------------------------------------------------------------------------
# Common formats read as standard ones: '01 PROFESSIONAL SUMMARY' is the Summary section, an icon-font bullet
# (a private-use character such as U+F0B7) is a bullet. Each is only a Minor note.
# ---------------------------------------------------------------------------
NUMBERED_HEADING_RE = re.compile(r"^(\s*)(\d{1,2})[.):]?\s+(?=[A-Za-z])(.+)$")
COMPANY_LINE_RE = re.compile(r"\s[|—–-]\s")
ICON_BULLET_RE = re.compile(r"^(\s*)(?:[\ue000-\uf8ff]|(?:\(cid:\d+\)\s*)+)\s*")


def _normal_line(line, notes):
    m = ICON_BULLET_RE.match(line)
    if m:
        notes["icon_bullets"].append(line.strip())
        rest = line[m.end():]
        if "(cid:" in line[:m.end()] and COMPANY_LINE_RE.search(rest) and len(rest.split()) <= 10 \
                and not rest.rstrip().endswith("."):
            line = m.group(1) + rest                     # a marker before a 'Company - City' line is not a bullet
        else:
            line = m.group(1) + "\u2022 " + rest
    m = NUMBERED_HEADING_RE.match(line)
    if m and not re.search(r"\d", m.group(3)) and is_heading_cv(m.group(3)):
        notes["numbered"].append(line.strip())
        line = m.group(1) + m.group(3)
    return line


# ---------------------------------------------------------------------------
# A line that wraps onto the next one (a degree, a job title or a company name in a narrow column) is one line:
# joined before any check, so the wrap never causes a false alarm.
# ---------------------------------------------------------------------------
WRAP_OPEN_RE = re.compile(r"(?:[,&/|(\-–—]|\b(?:and|of|in|for|the|at|to|with|on|by|an?|or|de|du|des|la|le))$", re.I)
DEGREE_WORD_RE = re.compile(r"\b(?:bachelor|master|mba|b\.?\s?sc|m\.?\s?sc|b\.\s?[a-z]{1,4}|m\.\s?[a-z]{1,4}|"
                            r"ph\.?d|doctorate|diploma|associate)\b", re.I)
WRAP_GAP = 0.6          # lines closer than this many line heights are one block of text
WRAP_FULL = 0.08        # a line that reaches the column's right edge (within 8% of its width) may continue


def _text_ends_item(t):
    return t[-1] in ".:;!?"


def _joins(a, b, colmax, cluster):
    """True when row b continues row a (the same column, the same size, no gap) and a looks unfinished."""
    for k in ("x0", "x1", "top", "bottom"):
        if k not in a or k not in b:
            return False
    if a["page"] != b["page"] or abs(a["x0"] - b["x0"]) > 3:
        return False
    a_top, a_bottom = a.get("_last_top", a["top"]), a.get("_last_bottom", a["bottom"])    # the last line of a
    h = max(a_bottom - a_top, 1.0)
    if abs(h - (b["bottom"] - b["top"])) > 1.2 or not -1.0 <= b["top"] - a_bottom <= WRAP_GAP * h:
        return False
    if (a.get("font"), a.get("size")) != (b.get("font"), b.get("size")) and None not in (a.get("font"), b.get("font")):
        return False                                          # a bold title and a plain company line are two lines
    ta, tb = a["text"].strip(), b["text"].strip()
    if not ta or not tb or _text_ends_item(ta) or len(a["cells"]) > 1 and len(b["cells"]) > 1:
        return False
    both = ta + " " + tb
    if any(m.start() < len(ta) < m.end() for m in L.RANGE_RE.finditer(both)):
        return True                                           # a date range cut in two: 'Jan 2021 -' + 'Present'
    if re.search(r"[|—–-]$", ta) and L.date_only(tb):
        return True                                           # 'Job title |' + 'Jan 2020 - Present'
    tail = bool(WRAP_OPEN_RE.search(ta)) and len(tb.split()) <= 3      # 'Ras Al Khaimah,' + 'UAE' is one line
    for t in (ta, tb):
        if BULLET_START_RE.match(t) or ICON_BULLET_RE.match(t) or L.date_only(t) or L.CONTACT_LINE_RE.search(t) \
                or (is_heading_cv(t) and not (tail and t is tb)):
            return False
    if L.RANGE_RE.search(ta):                                 # 'Title | Jan 2020 - Present' is complete
        return False
    last_x1 = a.get("_last_x1", a["x1"])
    # a line wrapped when the next word would not have fitted on it: it ends within one word of the column's edge
    char_w = (b["x1"] - b["x0"]) / max(len(tb), 1)
    first = tb.split()[0]
    full = cluster >= 3 and colmax - a["x0"] >= 60 and last_x1 + (len(first) + 1) * char_w > colmax - 1.0
    opened = bool(WRAP_OPEN_RE.search(ta)) or tb[:1].islower()
    degree = bool(DEGREE_WORD_RE.search(ta)) and not SCHOOL_RE.search(ta) and not re.search(L.YEAR, ta) \
        and not DEGREE_WORD_RE.match(tb) and tb[:1].isupper() and len(tb.split()) <= 8
    return full or opened or degree


NAME_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'.\-]{1,24}")
BANNER_RE = re.compile(r"(?i)applicant tracking|\bATS\b.*(?:version|optimi[sz]ation|information)")


def _name_split(a, b):
    """A name written on two lines ('ROWAN' / 'ELATRACHE'): the first two lines are one word each, the same size,
    and neither is a heading word."""
    ta, tb = a["text"].strip(), b["text"].strip()
    if not (NAME_WORD_RE.fullmatch(ta) and NAME_WORD_RE.fullmatch(tb)) or a.get("page") != b.get("page"):
        return False
    if any(L.HEADING_VOCAB.fullmatch(t) or L.section_kind(t) != "other" or t.lower() in L.STANDARD_HEADING_WORDS
           for t in (ta, tb)):
        return False
    if "top" in a and "top" in b:
        ha, hb = max(a["bottom"] - a["top"], 1.0), max(b["bottom"] - b["top"], 1.0)
        # the same style, the second line may be set smaller to fit; no gap between them
        if max(ha, hb) > 2.0 * min(ha, hb) or not -1.0 <= b["top"] - a["bottom"] <= 0.5 * max(ha, hb):
            return False
    return True


def drop_banner(doc):
    """A first line that is a note, not the resume ('Additional Detailed Information for (ATS) Applicant Tracking
    System Optimisation' above the name): taken out, so the name is the first line."""
    rows = doc.get("rows") or []
    if len(rows) < 2 or not BANNER_RE.search(rows[0]["text"]):
        return doc
    first = rows[0]["text"].strip()
    def cut(text):
        lines, done = text.split("\n"), False
        out = []
        for l in lines:
            if not done and l.strip() == first:
                done = True
                continue
            out.append(l)
        return "\n".join(out)
    return dict(doc, rows=rows[1:], strict=cut(doc["strict"]), modern=cut(doc["modern"]))


def join_wrapped(doc):
    """-> doc with every wrapped line joined to the line it continues (rows and the text fields). The very same
    document when nothing wraps."""
    rows = doc.get("rows") or []
    if not rows:
        return doc
    right = {}
    for r in rows:
        if "x0" in r:
            key = (r["page"], round(r["x0"] / 3))
            right.setdefault(key, []).append(r)
    def column(r):
        near = [x for k in ((r["page"], round(r["x0"] / 3) + d) for d in (-1, 0, 1)) for x in right.get(k, [])
                if abs(x["x0"] - r["x0"]) <= 3]
        top = max(x["x1"] for x in near)
        # the right edge is real when several lines end near it (a paragraph or a wrapped column), not one long line
        return top, sum(x["x1"] >= top - 0.1 * (top - r["x0"]) for x in near)
    out, groups = [], []
    for r in rows:
        if out and "x0" in r and "x0" in out[-1]:
            colmax, cluster = column(out[-1])
            if (len(out) > 1 and _joins(out[-1], r, colmax, cluster)) or (len(out) == 1 and _name_split(out[0], r)):
                a = out[-1]
                cells = a["cells"][:-1] + [(a["cells"][-1] + " " + r["cells"][0]).strip()] + r["cells"][1:]
                groups[-1].append(r["text"])
                out[-1] = dict(a, text=(a["text"].rstrip() + " " + r["text"].lstrip()).strip(), cells=cells,
                               x1=max(a["x1"], r["x1"]), bottom=r["bottom"], _last_x1=r["x1"],
                               _last_top=r["top"], _last_bottom=r["bottom"])
                continue
        out.append(r)
        groups.append([r["text"]])
    joined = [g for g in groups if len(g) > 1]
    if not joined:
        return doc
    rows = [{k: v for k, v in r.items() if not k.startswith("_last_")} for r in out]
    return dict(doc, rows=rows, strict=_join_text(doc["strict"], joined), modern=_join_text(doc["modern"], joined))


def _join_text(text, groups):
    """Join the consecutive text lines that are the pieces of one wrapped row (compared without spaces)."""
    flat = lambda s: re.sub(r"\s+", "", s)
    lines = text.split("\n")
    out, i = [], 0
    by_first = {}
    for g in groups:
        by_first.setdefault(flat(g[0]), []).append(g)
    while i < len(lines):
        for g in by_first.get(flat(lines[i]), []):
            n = len(g)
            if i + n <= len(lines) and all(flat(lines[i + k]) == flat(g[k]) for k in range(n)):
                out.append(" ".join(l.strip() for l in lines[i:i + n]))
                i += n
                break
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)



def normalize_doc(doc):
    """-> (doc with numbered headings and icon bullets written as standard ones, notes of what was changed)."""
    notes = {"icon_bullets": [], "numbered": []}
    if not doc:
        return doc, notes
    fix = lambda text: "\n".join(_normal_line(l, {"icon_bullets": [], "numbered": []}) for l in text.split("\n"))
    rows = []
    for r in doc["rows"]:
        text = _normal_line(r["text"], notes)
        cells = [_normal_line(c, {"icon_bullets": [], "numbered": []}) for c in r["cells"]]
        rows.append(dict(r, text=text, cells=cells))
    if not notes["icon_bullets"] and not notes["numbered"]:
        return doc, notes                                  # nothing to change: the very same document
    return dict(doc, strict=fix(doc["strict"]), modern=fix(doc["modern"]), rows=rows), notes


def format_notes(notes):
    num, icons = notes["numbered"], notes["icon_bullets"]
    return {"T13": {"score": 0.0 if num else 1.0, "detail": f"{len(num)} numbered section heading(s)",
                    "evidence": num[:3]},
            "T14": {"score": 0.0 if icons else 1.0,
                    "detail": f"{len(icons)} bullet(s) use a symbol that may not display in every ATS; use standard "
                              f"bullets (\u2022 or -)",
                    "evidence": icons[:2]}}


def structure_part(sc, cap=True):
    return max(0.0, part_value(sc, STRUCT_WEIGHT, cap))


# ---------------------------------------------------------------------------
# Readability and Job Match, recomputed from v3's per-ATS checks (so a fix can be simulated)
# ---------------------------------------------------------------------------
def _part_score(checks, part, fixed=()):
    use = [(1.0 if n in fixed else c["score"] / 100, c["weight"]) for n, c in checks.items()
           if c["part"] == part and c["score"] is not None]
    return sum(s * w for s, w in use) / sum(w for _, w in use) if use else 0.0


def readability_part(res, fixed_checks=(), fixed_bugs=(), design=None, fixed_design=(), skip_bugs=(), cap=True):
    """v3 readable checks (average of the 3 ATS) minus layout-bug and design penalties (one shared cap).
    cap=False: no penalty cap and no floor at 0, so the cost of each problem adds up (for the score explanation)."""
    r = sum(_part_score(res["ats"][p]["checks"], "R", fixed_checks) for p in L.ATS_PROFILES) / len(L.ATS_PROFILES)
    pen = sum(0 if b["owns_checks"] else READ_PENALTY[rule_severity(b["code"])] for b in res["bugs"]
              if b["found"] and b["code"] in READ_BUGS and b["code"] not in fixed_bugs and b["code"] not in skip_bugs)
    pen += sum(READ_PENALTY[rule_severity(k, design=design)] for k, d in (design or {}).items()
               if d["found"] and k not in fixed_design)
    if not cap:
        return 100 * r - pen
    return max(0.0, 100 * r - min(L.PENALTY_CAP, pen))


def job_match_part(res, fixed_checks=()):
    vals = []
    for p in L.ATS_PROFILES:
        ch = res["ats"][p]["checks"]
        vals.append(L.job_match_of({"F": _part_score(ch, "F", fixed_checks), "M": _part_score(ch, "M", fixed_checks)}))
    return 100 * sum(vals) / len(vals)


# ---------------------------------------------------------------------------
# Role Fit without a job description: the target role's common skills (AI, saved per role)
# ---------------------------------------------------------------------------
ROLE_PROMPT_VERSION = 2       # saved role lists made with an older prompt are made again
ROLE_PROMPT = """You list the hard skills recruiters type into an ATS search when hiring for one EXACT job title
at its EXACT level of seniority.
Return ONLY a JSON object, no other text:
{"seniority": "", "field": "", "core_skills": [], "common_skills": []}

Steps and rules:
- seniority: decide it from the title: intern / entry, junior, mid-level, senior, lead or manager, director or head,
  VP or C-level. If the title gives no level, assume mid-level. If it names two areas ("Admin and HR"), cover both.
  ALWAYS answer with the JSON, even for a broad or unusual title.
- field: the industry or profession of this title in 2-4 words (e.g. "media agency", "supply chain").
- The skills must be what a person in THIS title and THIS level is expected to have.
  For lead, manager, director, head, VP and C-level titles: strategy, planning, budgets, P&L, team leadership,
  partner / agency / vendor / client management, the field's main methods, and the tools leaders use.
  Leave out hands-on production work done by junior staff or by other professions (for example a Media Director
  is NOT expected to do graphic design, copywriting or video editing; a Logistics Manager does not drive trucks).
  For intern, entry and junior titles: the hands-on tools and methods of the field.
- Do not add skills of neighbouring professions (a media role is not a creative or design role; a software role is
  not a data-science role) unless the title names them.
- core_skills: the 10 most searched hard skills for this exact title and level.
- common_skills: 5-10 more hard skills often asked for this exact title and level.
- Each skill is a 1-3 word noun phrase a recruiter would type into an ATS search box
  (e.g. "Media Planning", "Agency Management", "Freight Forwarding", "Python", "Google Ads").
- NO soft skills ("communication", "teamwork"), NO job titles, NO sentences, NO generic words ("management").
- Use the most common spelling used in job postings.
"""
FIT_SIMILARITY = 0.45         # a role skill "fits" the CV when its meaning is this close to some part of the CV
FIT_SHARE = 0.5               # under half of the list fits the CV's field -> a career change: show the real gap


def role_slug(role):
    return re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-")


def role_skills_path(role, cache=None):
    return os.path.join(cache or ROLE_CACHE, role_slug(role) + ".json")


def _ask_role_skills(role, model):
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise ScoreError("The OpenRouter API key is missing, so the skills for this role cannot be listed. "
                         "Run  $env:OPENROUTER_API_KEY=\"your-key\"  first.")
    prompt = ROLE_PROMPT + "\nJOB TITLE: " + role
    runs, info = [], []
    for _ in range(L.AI_RUNS):
        a = L.call_ai(prompt, model) or L.call_ai(prompt, model)
        if a:
            runs.append({"required_skills": a.get("core_skills") or [], "preferred_skills": a.get("common_skills") or []})
            info.append({"seniority": a.get("seniority"), "field": a.get("field")})
    if not runs:
        raise ScoreError("The AI gave no skill list for this role. Please try again.")
    return runs, info


def role_skills(role, model=MODEL, cache=None):
    """-> {"required_skills": core, "preferred_skills": common, "seniority", "field"} for this exact title and
    level. 3 AI answers at temperature 0, voted like job keywords (a skill stays if 2 of 3 answers have it);
    saved per role, so it is asked once."""
    path = role_skills_path(role, cache)
    data = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("prompt_version") != ROLE_PROMPT_VERSION:
            data = None                                   # made with an older prompt: ask again
    if data is None:
        runs, info = _ask_role_skills(role, model)
        data = {"role": role, "prompt_version": ROLE_PROMPT_VERSION, "model": model,
                "created": L.TODAY.isoformat(), "temperature": 0, "ai_runs": runs, "ai_info": info}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    voted = L.vote_keywords(data["ai_runs"])
    clean = lambda lst: [L.tidy_skill(s) for s in lst if L.tidy_skill(s) and len(L.tidy_skill(s).split()) <= 3]
    info = data.get("ai_info") or [{}]
    most = lambda k: max((i.get(k) for i in info if i.get(k)), key=lambda v: [i.get(k) for i in info].count(v),
                         default=None)
    return {"required_skills": clean(voted["required_skills"])[:12],
            "preferred_skills": clean(voted["preferred_skills"])[:10],
            "seniority": most("seniority"), "field": most("field")}


def cv_field_name(vdoc, vana, review=None):
    """The CV's own field in a few words: from the AI reviewer, else its headline or most recent job title."""
    if review and review.get("field"):
        return review["field"]
    f = L.ats_fields(vdoc, vana)
    head = re.split(r"\s[|\u2022\u00b7]\s", f["headline"] or "")[0].strip()
    title = head or next((j["title"] for j in f["jobs"] if j["title"]), "")
    return f"{title} roles" if title else "another field"


def skills_fit(skills, vdoc, vana):
    """-> (share of the role skills that fit this CV's field, the ones that do not). A skill fits when the CV has
    it (exact / close wording) or something close in meaning (local embedding model, same as the meaning match)."""
    terms = skills["required_skills"] + skills["preferred_skills"]
    if not terms:
        return 1.0, []
    _, recs = role_fit_from_skills(vana, {"required_skills": skills["required_skills"],
                                          "preferred_skills": skills["preferred_skills"]}, vdoc["modern"])
    present = {r["term"] for r in recs if r["hits"] or r["soft"]}
    rest = [t for t in terms if t not in present]
    if rest:
        try:
            cv = L._embed(vdoc["modern"])
            vec = L._embedder().encode(rest, normalize_embeddings=True, show_progress_bar=False)
            close = {t for t, sims in zip(rest, vec @ cv.T) if sims.max() >= FIT_SIMILARITY}
        except Exception:                                 # no local model: judge on the words only
            close = set()
        rest = [t for t in rest if t not in close]
    return 1 - len(rest) / len(terms), rest


ROLE_CLOSE_CREDIT = 0.7     # role list only: all words of the skill within a few words of each other
ROLE_PARTIAL_CREDIT = 0.4   # role list only: half the specific words appear ('freight' for 'Freight Forwarding')
ROLE_WINDOW = 8
GENERIC_SKILL_WORDS = {L.stem(w) for w in (
    "management operations operation strategy strategies planning analysis software tools tool systems system "
    "skills skill process processes services service data development solutions solution support relations "
    "business general office administration documentation reporting optimization coordination control").split()}


def soft_role_credit(term, stems):
    """A generic AI skill list is not the employer's wording, so close wording gets some credit."""
    want = [L.stem(t) for t in L.content_tokens(term)]
    if not want:
        return 0.0
    pos = {}
    for i, s in enumerate(stems):
        if s in want:
            pos.setdefault(s, []).append(i)
    if len(pos) == len(set(want)):
        starts = sorted(i for p in pos.values() for i in p)
        for i in starts:
            if all(any(i <= j < i + ROLE_WINDOW for j in pos[w]) for w in set(want)):
                return ROLE_CLOSE_CREDIT
    specific = {w for w in want if w not in GENERIC_SKILL_WORDS}
    hit = specific & set(pos)                            # at least half of the specific words, and one or more
    return ROLE_PARTIAL_CREDIT if hit and len(hit) * 2 >= len(specific) else 0.0


def role_fit_from_skills(ana, skills, cv_text=""):
    """Weighted like job keywords: core 3, common 1.5; exact / variant / abbreviation credit with location
    (as for a job), plus close / partial credit because the role list is generic."""
    kw = {**skills, "soft_skills": []}
    recs = L.keyword_records(kw, ana, " ".join(kw["required_skills"] + kw["preferred_skills"]))
    if not recs:
        return 0.0, recs
    stems = [L.stem(t) for t in L.tokens(cv_text)] if cv_text else \
        [L.stem(t) for toks, _ in ana["chunks"] for t in toks]
    for r in recs:
        r["soft"] = soft_role_credit(r["term"], stems)
    cov = []
    for prof in L.ATS_PROFILES.values():
        cov.append(sum(r["weight"] * max(L.best_credit(r, prof), r["soft"]) for r in recs)
                   / sum(r["weight"] for r in recs))
    return 100 * sum(cov) / len(cov), recs


# ---------------------------------------------------------------------------
# The CV Score
# ---------------------------------------------------------------------------
AI_TOPICS = [  # (words in the AI finding, the Lab's own check that can confirm it)
    (re.compile(r"quantif|metric|number|measurable|result|achievement|impact", re.I), "numbers"),
    (re.compile(r"action verb|weak verb|passive|responsible for|duties", re.I), "verbs"),
    (re.compile(r"buzzword|clich|generic|template|filler", re.I), "buzzwords"),
    (re.compile(r"repeat|duplicat|redundan", re.I), "repeats"),
    (re.compile(r"\bdates?\b|timeline|chronolog", re.I), "dates"),
    (re.compile(r"summary.*(too long|too short|length|wordy|lengthy)|(too long|too short|lengthy).*summary", re.I),
     "summary"),
]
GAP_MONTHS = 6


def ai_confirmed(f, cc, ana):
    """True when one of the Lab's own rule checks sees the same problem in the same place. The topic is read
    from the finding's TITLE only (a 'why' that mentions results does not make every finding about results)."""
    text, q = f["issue"], f.get("quote_full") or f["quote"]
    for pat, topic in AI_TOPICS:
        if not pat.search(text):
            continue
        if topic == "summary" and cc["C4"]["score"] < 1:
            return True
        if topic == "numbers" and cc["C1"]["score"] < 1 and len(q.split()) >= 6 and not has_number(q):
            return True
        if topic == "verbs" and bool(WEAK_OPENERS.match(first_word(q)[1])):
            return True
        if topic == "buzzwords" and any(b in q.lower() for b in BUZZWORDS + L.TEMPLATE_PHRASES):
            return True
        if topic == "repeats" and cc["C6"]["score"] < 1:
            return True
        if topic == "dates" and any(L.make_job("", line, 0)["problem"] for line in q.splitlines()
                                    if L.POINT_RE.search(line) or L.DURATION_RE.search(line)):
            return True                                   # checked on the QUOTED dates, not anywhere in the CV
    return False


def timeline(vana):
    """The Lab's own timeline: jobs and education as month intervals, and gaps of more than GAP_MONTHS empty
    months between them. v1.1: gaps are no longer checked or scored (every AI gap finding is dropped, cv_review.py);
    the timeline's conclusion is still sent to the AI reviewer unchanged, so the saved reviews stay valid."""
    items = [("job", short_name(j.get("title") or "job"), a, b) for j in vana["jobs"] for a, b in j["intervals"]]
    study = (L.section_rows(vana, "education") if "sections" in vana else [])
    # a degree with its dates anywhere else (under a company-like heading, in a list of courses) covers its months too
    study += [r for s_ in vana.get("sections", []) if s_["kind"] != "education" for r in s_["rows"]
              if is_degree(r["text"]) and L.find_ranges(r["text"])
              and r["text"] not in {x["text"] for x in study}]
    for r in study:
        text = r["text"]
        ranges = L.find_ranges(text)
        for g in ranges:
            items.append(("education", short_name(text), g["start"], g["end"]))
        if not ranges:
            for m in L.POINT_RE.finditer(text):                    # a single date: studies ending then
                end = L._month_index(m.group(0), True)
                items.append(("education", short_name(text), end - 11, end))
    spans = sorted((a, b) for _, _, a, b in items)
    gaps, reach = [], None
    for a, b in spans:
        if reach is not None and a - reach - 1 > GAP_MONTHS:
            gaps.append((reach + 1, a - 1))
        reach = b if reach is None else max(reach, b)
    return {"items": items, "gaps": gaps}


def gap_summary(tl):
    """The timeline's conclusion, as sent to the AI reviewer (the full list confused the model)."""
    if not tl["gaps"]:
        return f"every job and education date was checked: no gaps of more than {GAP_MONTHS} months."
    return (f"gaps of more than {GAP_MONTHS} months with no job or education: "
            + "; ".join(f"{month_name(a)} to {month_name(b)}" for a, b in tl["gaps"]) + ".")


def short_name(text):
    """A whole, readable name for the timeline: the part before the first ' | ', never cut mid-word."""
    name = re.split(r"\s[|•]\s", L.RANGE_RE.sub("", text or "").strip())[0].strip(" ,-")
    words = name.split()
    return " ".join(words[:12]) + (" ..." if len(words) > 12 else "") if words else "item"


def month_name(m):
    return f"{L.MONTHS[m % 12].capitalize()} {m // 12}"


def timeline_text(tl):
    lines = [f"- {kind}: {name}: {month_name(a)} to {month_name(b)}" for kind, name, a, b in sorted(
        tl["items"], key=lambda x: -x[3])]
    gaps = ", ".join(f"{month_name(a)} to {month_name(b)}" for a, b in tl["gaps"]) or "none"
    return "\n".join(lines) + f"\nGaps of more than {GAP_MONTHS} months with no job or education: {gaps}"


def total_from(parts, cc, pc=None, limits=None, lifted=False, pages_ok=False):
    """The Resume Score from the parts: weighted geometric mean, then the guardrails (no numbers at all, far too many
    pages) and the layout limit on the total (rule 3; lifted = after moving to a single-column, portrait resume;
    pages_ok = after cutting the resume to its page limit)."""
    score = weighted_geo(parts)
    gates = []
    c15 = cc.get("C15")
    if c15 and c15["score"] is not None and c15["score"] < 1:      # what the total would be with a good headline
        gain = content_part({**cc, "C15": {**c15, "score": 1.0}}) - content_part(cc)
        with_headline = weighted_geo(dict(parts, content=min(100.0, parts["content"] + gain)))
        if with_headline - score > HEADLINE_CAP:
            score = with_headline - HEADLINE_CAP
    cap = None if lifted or not limits else limits["caps"]["total"]
    if cap is not None and score > cap:
        score = cap
        gates.append(f"layout limit -> max {cap}")
    if not pages_ok and limits and limits.get("pages_cap") is not None and score > limits["pages_cap"]:
        score = limits["pages_cap"]
        gates.append(f"{PAGES_CAP_TIMES} times the page limit or more -> max {limits['pages_cap']}")   # 'page limit': pages_held
    if cc["C1"]["bullets"] == 0 or cc["C1"]["quant_share"] == 0:
        score = min(score, CAP_NO_NUMBERS)
        gates.append(f"no numbers in any bullet -> max {CAP_NO_NUMBERS}")
    return score, gates


# Readability problems that the template alone causes: inside the template card
TEMPLATE_IDS = {"D3", "D4", "D9", "D10", "D12", "D13", "B1", "N1", "R1", "R4", "R5"}


def template_reasons(layout, design, b1):
    """Why the template is hard for an ATS: 2+ columns, a sidebar, a landscape page, letter-spaced headings."""
    out = []
    if layout and layout.get("columns_found"):
        out.append(f"{layout.get('n_columns', 2)} columns side by side")
    if design.get("D3", {}).get("found"):
        out.append("a sidebar")
    if design.get("D12", {}).get("found"):
        out.append("a landscape page")
    if b1["found"] and not b1["detail"].startswith("name only"):
        out.append("letter-spaced headings")
    if design.get("D13", {}).get("found"):
        out.append("a page that is an image")
    if out and design.get("N1", {}).get("found"):     # a letter-spaced name alone is its own Minor card (N1)
        out.append("a letter-spaced name")
    return out


TWO_VERSIONS_NOTE = ("This file has a designed version and a text version. For online applications, upload only the "
                     "text version.")
DESIGN_PHRASE = {"D13": "a page that is an image", "D1": "images or a photo", "D2": "colored backgrounds", "D3": "a sidebar",
                 "D5": "icons for contact details", "D6": "text in boxes or tables", "D7": "small or decorative fonts",
                 "D8": "low-contrast text", "D10": "text that is read out of order", "D12": "landscape pages"}


def two_versions(cv_path, split, designed):
    """The note for a file with a designed version and a text version: the layout problems of the designed pages are
    listed in it (they are not separate cards: only the text version is scored)."""
    issues = []
    if designed["findings"]["D4"]["found"]:
        issues.append(f"{designed.get('n_columns', 2)} columns side by side")
    issues += [phrase for k, phrase in DESIGN_PHRASE.items() if designed["findings"][k]["found"]]
    text = L.extract_cv(cv_path, pages=set(split["designed"]))["strict"]
    if L.spaced_lines(text) or any(Y.repair_heading(l.strip()) != l.strip() for l in text.splitlines()):
        issues.append("letter-spaced or broken headings")
    first, last = split["designed"][0] + 1, split["designed"][-1] + 1
    where = f"page {first}" if first == last else f"pages {first} to {last}"
    note = TWO_VERSIONS_NOTE + (f" The designed {where} {'has' if first == last else 'have'} these layout problems: "
                                f"{', '.join(issues)}." if issues else "")
    return {"start_page": split["start"] + 1, "designed_pages": [p + 1 for p in split["designed"]],
            "issues": issues, "note": note}


SAFE_NOTE = ("This resume was checked in safe mode: the design and layout checks were skipped because a library "
             "could not run on this computer; every other check ran.")


def part_explain(parts, issues):
    """'Why <score>?' for each part: what each issue of that part costs it, so that the costs add up to the
    part's loss (100 - part). Each cost is the scorer's own counterfactual for that part; when the costs add up to
    more than the loss (the shared readability penalty cap, a floor at 0), they are scaled down together.
    -> {part: {"loss", "items": [{"id", "name", "points"}] biggest first, "other": loss not tied to one issue}}.
    Each issue also gets "part_points" (its share of its own part)."""
    out = {}
    for part, value in parts.items():
        loss = round(100 - round(value, 1), 1)
        mine = [i for i in issues if i["part"] == part and i["_cost"] > 0]
        total = sum(i["_cost"] for i in mine)
        # the costs are scaled so that they add up to the part's loss exactly (shared caps and limits make single
        # counterfactuals add up to a little more or less): every point lost is tied to an issue
        k = loss / total if total > 0 else 1.0
        items = []
        for i in mine:
            i["part_points"] = round(i["_cost"] * k, 1)
            if i["part_points"] > 0:
                items.append({"id": i["id"], "name": i["name"], "points": i["part_points"]})
        items.sort(key=lambda x: -x["points"])
        out[part] = {"loss": loss, "items": items, "other": round(loss - sum(x["points"] for x in items), 1)}
    for i in issues:
        i.setdefault("part_points", 0.0)
        i.pop("_cost", None)
    return out


def read_name_line(cv_path, vana):
    """The first line (the name) read again from its letters when it is letter-spaced ('S A N A M A L I K , P M P ®'
    -> 'SANA MALIK, PMP®'), else None. A reading problem never stops the score."""
    head = vana["header"][0] if vana["header"] else None
    if not head or not L.spaced_lines(head["text"]):
        return None
    try:
        return Y.spaced_line_text(cv_path, head)
    except Exception:
        return None


def years_from_dates(text):
    """Years covered by the date ranges anywhere in the text (merged, as for jobs), for a resume whose jobs could not
    be read: the page limit then still has an experience to go by. None when the text has no date range at all."""
    ranges = L.find_ranges(text)
    if not ranges:
        return None
    return L.experience_years([{"intervals": [(r["start"], r["end"]) for r in ranges], "duration_months": 0}])


# ---------------------------------------------------------------------------
# Before a score: is the file a resume, and is it in English? The same for every file: a file that fails is not
# scored, the dashboard says why (run_check).
# ---------------------------------------------------------------------------
# contact details: an email, a LinkedIn link, an international phone number, or a labelled one ('Mobile: 050 ...')
CONTACT_RE = re.compile(r"linkedin\.com/|(?:\+|\b00)\d[\d\s\-().]{7,}\d|"
                        r"\b(?:phone|mobile|mob|tel|cell|whatsapp)\b\.?\s*:?\s*\+?\d[\d\s\-().]{6,}\d", re.I)


def resume_signs(doc):
    """What makes a file a resume: an experience or education section, job dates (date ranges), contact details.
    -> the signs found ("section", "dates", "contact"); none at all = not a resume."""
    text = doc["modern"]
    signs = []
    if any(s["kind"] in ("experience", "education") for s in analyse_cv(normalize_doc(doc)[0])["sections"]):
        signs.append("section")
    if L.find_ranges(text):
        signs.append("dates")
    if L.EMAIL_RE.search(text) or CONTACT_RE.search(text):
        signs.append("contact")
    return signs


LATIN_RE = re.compile(r"[A-Za-zÀ-ɏḀ-ỿ]")
MIN_LATIN = 0.5                # under half of the letters in the Latin alphabet (Arabic, Cyrillic, Chinese ...)
MIN_LETTERS = 50               # too little text to judge the language
MIN_OTHER_WORDS = 15           # common words of another language: at least this many, and more than English ones
ENGLISH_WORDS = frozenset("""
the and of to in for with on at by from as is are was were be been an or my our your their this that these those
which who will would can into over across through including within while after before during about under than more
most new all each other such also not its it we he she they them have has had led managed developed delivered
responsible worked work team teams management manager experience education skills skill project projects customer
customers business company sales data development support service services marketing years year university bachelor
master degree senior lead leading built improved increased reduced achieved strategy planning operations client
clients training communication professional summary profile objective certifications languages present
""".split())
OTHER_WORDS = frozenset("""
le la les des du et pour avec dans une sur aux est sont par ou nous vous ses leur expérience formation compétences
gestion développement entreprise poste années chez stage diplôme
el los las del y con para por una que es como su sus experiencia formación habilidades empresa desarrollo años puesto
da das com em experiência gestão anos
der die das und mit für von im zu bei eine ein ist sind auf als berufserfahrung ausbildung kenntnisse erfahrung
unternehmen jahre
di yang untuk dengan dari ke pada sebagai dalam pengalaman pendidikan keahlian kerja perusahaan tahun
và của các trong với cho là được những một có không tại từ đến năm người công việc này để theo về khi nhiều đã sẽ hơn
như quản lý phát triển kinh nghiệm thời gian học vấn kỹ năng mục tiêu dự án nhân viên trường đại hệ thống khách hàng
sản phẩm
ve bir için ile olarak deneyim eğitim şirket
il della delle degli che nel esperienza formazione competenze azienda
""".split()) - ENGLISH_WORDS


def language_signs(text):
    """-> {"letters", "latin" (share of letters in the Latin alphabet), "english", "other" (common words)}."""
    letters = [c for c in text if c.isalpha()]
    words = re.findall(r"[^\W\d_]{2,}", text.lower())
    return {"letters": len(letters),
            "latin": sum(1 for c in letters if LATIN_RE.match(c)) / len(letters) if letters else 1.0,
            "english": sum(w in ENGLISH_WORDS for w in words), "other": sum(w in OTHER_WORDS for w in words)}


def not_english(text):
    """Most of the text is not English: most letters are not Latin (Arabic, ...), or another language's common words
    outnumber English ones. Too little text is never judged."""
    s = language_signs(text)
    if s["letters"] < MIN_LETTERS:
        return False
    return s["latin"] < MIN_LATIN or (s["other"] >= MIN_OTHER_WORDS and s["other"] > s["english"])


def score_cv(cv_path, *args, **kwargs):
    """-> CV Score result. With job_path: Role Fit = v3 Job Match; else role is required (target role).
    review=True: the AI recruiter review (saved per CV) feeds Content Quality; off by default (tests, batches).
    safe=True: without the parts that run native code beyond reading the text (page layout and images, the
    meaning-match model), for a computer where one of them fails; the result says so in "notes".
    The PDF is parsed once for all its readings (cv_cache.one_parse)."""
    if not os.path.isfile(cv_path):
        return _score_cv(cv_path, *args, **kwargs)
    with CC.one_parse(cv_path):
        return _score_cv(cv_path, *args, **kwargs)


def _score_cv(cv_path, job_path=None, role=None, model=MODEL, doc=None, role_cache=None, review=False,
              review_cache=None, safe=False, job_title=None):
    role_source = "user" if (role or "").strip() else "cv"
    if not job_path and role_source == "user":
        role = check_role(role)
    run_notes = []                                    # parts that could not run on this computer, said plainly
    two = None                                        # a designed version + a text version of the resume in one file
    split = Y.find_text_version(cv_path) if os.path.isfile(cv_path) and not safe else None
    layout = Y.analyse_layout(cv_path) if os.path.isfile(cv_path) and not safe else None    # rule 1: every page
    if split:                                         # rule 1: a note for the user; the score stays the whole file's
        two = two_versions(cv_path, split, Y.analyse_layout(cv_path, pages=set(split["designed"])))
        run_notes.append(two["note"])
    if layout:
        run_notes += layout.get("notes", [])
    elif safe:
        run_notes.append(SAFE_NOTE)
    embed_off = L.EMBED_OFF
    if safe:
        L.EMBED_OFF = True
    if layout:                                        # page numbers, "(continued)", running headers: left out
        doc = Y.extract_clean(cv_path, layout["running"], pages=layout.get("pages_used"))
    doc = doc or L.extract_cv(cv_path)
    doc, notes = normalize_doc(doc)                   # numbered headings and icon bullets read as standard ones
    doc = join_wrapped(drop_banner(doc))              # a line that wraps onto the next is one line
    ana = analyse_cv(doc)
    # the page as a person reads it: column by column when the CV has columns, else the extracted text
    vdoc = join_wrapped(drop_banner(normalize_doc(layout["visual_doc"])[0])) if layout and layout["columns_found"]         else doc
    vana = analyse_cv(vdoc) if vdoc is not doc else ana
    if split:
        # rule 1b: a designed version + a text version. Readability and the layout limits read every page (an ATS
        # does), but Content and Structure read the text version, which an ATS reads cleanly and which holds the full
        # details (headline, job titles with months, bullets, results). The cards quote it too.
        tdoc, notes = normalize_doc(Y.extract_clean(cv_path, layout["running"],
                                                    pages=set(range(split["start"], split["pages"]))))
        vdoc = join_wrapped(drop_banner(tdoc))
        vana = analyse_cv(vdoc)
    if not job_path and role_source == "cv":
        role = detect_role(vdoc, vana)                    # shown only: without a job there is no Role Fit
    res = L.score_cv(cv_path, job_path, model, doc=doc, role=None, job_title=job_title if job_path else None)
    years = L.experience_years(vana["jobs"])
    design = {k: dict(v) for k, v in layout["findings"].items()} if layout else {}
    page_years = years if any(j["intervals"] for j in vana["jobs"]) else years_from_dates(vdoc["modern"])
    if layout and page_years is not None:            # no dates at all: the experience is unknown, no page limit
        limit = next(p for y, p in MAX_PAGES if page_years < y)
        if layout["pages"] > limit:
            span = "less than a year" if page_years < 1 else f"about {page_years:.0f} years"
            design["D11"].update(found=True, over=layout["pages"] - limit, limit=limit,
                                 detail=f"{layout['pages']} pages for {span} of experience (at most {limit})",
                                 evidence=[f"This resume has {layout['pages']} pages for {span} of experience."])
    # side-by-side highlight boxes are a case of columns / text in boxes: counted once, as the design problem
    skip = ["B8"] if layout and (layout["columns_found"] or design["D6"]["found"]) else []
    # judged by the 1000jobs standard checks instead (one card each): email T7, phone T3, headline C15,
    # job dates T4, degree T9, section names T1, summary C4
    skip += ["B4", "B11"]
    # With columns, the ATS reads the text out of order and then misses dates, sections, the summary...: those
    # readable checks belong to the column card (one cause, one card, Readability only). Without columns they are
    # judged by the 1000jobs standard checks (Content / Structure) instead.
    col_owner = next((k for k in ("D4", "D3", "D10") if design.get(k, {}).get("found")), None) \
        if layout and layout["columns_found"] else None
    col_checks = (STANDARD_OWNS + ("R12",)) if col_owner else ()
    base_fixed = [x for x in STANDARD_OWNS if x not in col_checks]
    b1 = next(b for b in res["bugs"] if b["code"] == "B1")
    if b1["found"] and b1["detail"].startswith("name only"):
        # only the NAME is letter-spaced: one root cause ("Name has letter spacing"), not a headings problem,
        # and the name / headline checks it breaks are part of the same card
        skip.append("B1")
        base_fixed += ["R1", "R4", "R5"]
        name_line = next((x for x in L.spaced_lines(doc["strict"])), "")
        design["N1"] = {"id": "N1", "label": "Name has letter spacing", "severity": "Minor", "found": True,
                        "detail": "the name is written with spaces between the letters",
                        "evidence": [name_line] if name_line else [], "boxes": []}
    b2 = next(b for b in res["bugs"] if b["code"] == "B2")
    named = re.search(r"'([^']+)'", b2["detail"] or "")
    if b2["found"] and named and re.search(r"language", named.group(1), re.I):
        skip.append("B2")                             # 'Language Skills' is a languages list, not the skills section
    comp_skills = sum(L.count_skill_items(s_["rows"]) for s_ in vana["sections"]
                      if s_["kind"] in ("skills", "competencies"))
    if comp_skills >= 8:                              # skills listed under "Core Competencies" count as skills
        base_fixed.append("R9")
    target = res["job_title"] if job_path else role
    tl = timeline(vana)
    rev = R.review_cv(vdoc["modern"], target, model, review_cache, also_texts=(doc["modern"],),
                      timeline=gap_summary(tl)) if review else None
    ai_content = None if rev is None else [f for f in rev["findings"] if f["type"] == "content"]
    cc = content_checks(vdoc, vana, res, target, years, layout["pages"] if layout else None)
    cc["C8"] = ai_check(ai_content)
    pc = structure_checks(vdoc, vana, res)
    pc.update(format_notes(notes))
    limits = layout_limits(layout, design)            # rule 3
    d11 = design.get("D11") or {}
    limits["pages_cap"] = CAP_PAGES if d11.get("found") and layout["pages"] >= max(PAGES_CAP_TIMES * d11["limit"],
                                                                                  PAGES_CAP_MIN) else None
    pc["T15"] = page_format_check(limits, design)     # rule 2: the page format is part of Structure
    missing = [k["term"] for k in res["keywords"] if k["match"] == "missing" and k["type"] != "soft"] \
        if job_path else []
    missing_required = [k["term"] for k in res["keywords"] if k["match"] == "missing" and k["type"] == "required"] \
        if job_path else []
    def read(fixed_checks=(), fixed_bugs=(), fixed_design=(), cap=True):
        return readability_part(res, tuple(base_fixed) + tuple(fixed_checks), fixed_bugs, design, fixed_design,
                                tuple(skip), cap)
    raw = {"readability": read(), "content": content_part(cc), "structure": structure_part(pc)}
    if job_path:
        raw["job_match"] = res["headline"]["job_match"]
    parts = apply_limits(raw, limits)                 # rule 3: the layout limits
    score, gates = total_from(parts, cc, pc, limits)
    cap = limits["caps"]["total"]
    if cap is not None and cc["C8"]["score"] is not None and score < cap:
        # the AI reviewer is an opinion on top of the rules: when the rules alone reach the layout limit, its findings
        # stay inside that limit and never take the score below it
        no_ai = dict(raw, content=content_part({**cc, "C8": ai_check(None)}))
        if total_from(apply_limits(no_ai, limits), cc, pc, limits)[0] >= cap:
            score = cap

    def parts_with(fix):
        """The parts with a fix applied (from the parts before the layout limits; a layout fix lifts them)."""
        fix = fix or {}
        c2 = {**cc, **fix.get("cc", {})}
        s2 = {**pc, **fix.get("pc", {})}
        p = dict(raw, **fix.get("parts", {}))
        if fix.get("cc") and "content" not in fix.get("parts", {}):
            p["content"] = content_part(c2)
        if fix.get("pc") and "structure" not in fix.get("parts", {}):
            p["structure"] = structure_part(s2)
        return apply_limits(p, limits, fix.get("layout")), c2, s2

    def total_with(fix=None):
        """CV Score with a fix applied. fix = {"parts": {part: new value}, "cc": {content check: new check},
        "pc": {structure check: new check}, "layout": True when it moves to a single-column, portrait resume,
        "pages": True when it is cut to its page limit}."""
        p, c2, s2 = parts_with(fix)
        return total_from(p, c2, s2, limits, (fix or {}).get("layout"), (fix or {}).get("pages"))[0]

    issues = []

    def add(iid, part, name, fix, detail, evidence, severity=None, raw=None, **extra):
        """raw: what the problem costs its part without the shared penalty cap (readability), else the part's
        own counterfactual: the part's value with the fix minus its value now."""
        gain = total_with(fix) - score
        if raw is None and part in ("content", "structure") and fix and not fix.get("layout")                 and not fix.get("parts") and (fix.get("cc") or fix.get("pc")):
            # what this issue costs its part ALONE, without the Minor cap (with the cap on, fixing one Minor issue
            # of ten can gain nothing): the explanation scales these costs to the part's real loss
            c2, s2 = {**cc, **fix.get("cc", {})}, {**pc, **fix.get("pc", {})}
            raw = (content_part(c2, False) - content_part(cc, False)) if part == "content"                 else (structure_part(s2, False) - structure_part(pc, False))
        cost = raw if raw is not None else parts_with(fix)[0][part] - parts[part]
        issues.append({"id": iid, "part": part, "name": name, "points": round(max(0.0, gain), 1),
                       "severity": severity if iid == "TPL" or iid.startswith("AI")
                       else rule_severity(iid, cc, pc, res, design),
                       "detail": detail,
                       "evidence": [e for e in evidence if e][:3], "_fix": fix, "_cost": max(0.0, cost), **extra})

    # readability: found layout bugs (with the checks they own), readable checks below 100, design problems
    owned = set()
    for b in res["bugs"]:
        if b["found"] and b["code"] in READ_BUGS and b["code"] not in skip:
            owned |= set(b["owns_checks"])
            add(b["code"], "readability", b["name"],
                {"parts": {"readability": read(fixed_checks=b["owns_checks"], fixed_bugs=(b["code"],))},
                 "read": (tuple(b["owns_checks"]), (b["code"],), ())},
                b["detail"], [], b["severity"],
                raw=read(fixed_checks=b["owns_checks"], fixed_bugs=(b["code"],), cap=False) - read(cap=False))
    for n, c in res["ats"]["oracle"]["checks"].items():
        if c["part"] == "R" and n not in owned and n not in base_fixed and n not in col_checks \
                and c["score"] is not None \
                and c["score"] < 100:
            add(n, "readability", c["name"], {"parts": {"readability": read(fixed_checks=(n,))},
                                              "read": ((n,), (), ())}, c["detail"], [],
                raw=read(fixed_checks=(n,), cap=False) - read(cap=False))
    for k, d in design.items():
        if d["found"]:
            fc = col_checks if k == col_owner else ()
            add(k, "readability", d["label"], {"parts": {"readability": read(fixed_checks=fc, fixed_design=(k,))},
                                                "read": (fc, (), (k,)), "pages": k == "D11"},
                d["detail"], d["evidence"], d["severity"],
                raw=read(fixed_checks=fc, fixed_design=(k,), cap=False) - read(cap=False))
    # One card for the template: columns, a sidebar, a landscape page or letter-spaced headings. The problems the
    # template alone causes (reading order, name / headings / skills hard to read, what the ATS misses in columns)
    # are points inside this card, not separate cards.
    tpl_ids = TEMPLATE_IDS | ({"B2", "R9"} if comp_skills >= 8 else set())
    reasons = template_reasons(layout, design, b1)
    tpl = [i for i in issues if i["part"] == "readability" and i["id"] in tpl_ids] if reasons else []
    if tpl:
        reads = [set(), set(), set()]
        for i in tpl:
            for k, v in enumerate(i["_fix"].get("read") or ((), (), ())):
                reads[k] |= set(v)
        reads = tuple(tuple(sorted(x)) for x in reads)
        quotes = [e for i in tpl if i["id"] in ("D4", "D12") for e in i["evidence"]][:2]    # clean lines only
        quotes += [l for l in L.spaced_lines(doc["strict"])][:1]
        for i in tpl:
            issues.remove(i)
        rebuild = limits["active"]                    # columns / sidebar / landscape / image pages: a new layout
        add("TPL", "readability", "Template is hard for ATS to read",
            {"parts": {"readability": read(*reads)}, "read": reads, "layout": rebuild}, "; ".join(reasons), quotes,
            "Critical" if rebuild else "Minor",
            raw=None if rebuild else read(*reads, cap=False) - read(cap=False), covers=[i["name"] for i in tpl],
            reasons=reasons)
    # content
    for k in CONTENT_WEIGHT:
        if cc[k]["score"] < 1:
            new = {**cc[k], "score": 1.0}
            if k == "C1":
                new.update(quant_share=1.0, bullets=max(1, cc["C1"]["bullets"]))
            add(k, "content", CONTENT_NAME[k], {"cc": {k: new}}, cc[k]["detail"], cc[k]["evidence"],
                None)
    # AI review: one issue per content finding, in its own words; points = C8 without that finding.
    # An AI finding is "Important" (Major) at most unless one of the Lab's own rule checks confirms it.
    for n, f in enumerate(ai_content or [], 1):
        rest = [g for g in ai_content if g is not f]
        ok = ai_confirmed(f, cc, vana)
        sev = "Major" if f["severity"] == "Critical" else f["severity"]       # an AI finding is Important at most
        add(f"AI{n}", "content", f["issue"], {"cc": {"C8": ai_check(rest)}, "ai": n}, f["why"], [f["quote"]], sev,
            ai={"why": f["why"], "fix": f["fix"], "confirmed": ok})
    # job match (only with a job description)
    if job_path:
        if missing:
            best = job_match_part(res, ("F1", "M1"))
            add("K", "job_match", "Missing skills for the job", {"parts": {"job_match": best}, "jm": ("F1", "M1")},
                ", ".join(missing), [])
        for n in ("F2", "F3", "F4", "M3", "M4", "M5"):
            c = res["ats"]["oracle"]["checks"].get(n)
            if c and c["score"] is not None and c["score"] < 100:
                add(n, "job_match", c["name"], {"parts": {"job_match": job_match_part(res, (n,))}, "jm": (n,)},
                    c["detail"], [])
    # structure
    b2 = any(b["found"] and b["code"] == "B2" and "B2" not in skip for b in res["bugs"])
    for k in STRUCT_WEIGHT:
        if k == "T8" and b2:
            continue                                      # the skills section card already says it
        if pc[k]["score"] < 1:
            add(k, "structure", STRUCT_NAME[k], {"pc": {k: {**pc[k], "score": 1.0}}, "layout": k == "T15"},
                pc[k]["detail"], pc[k].get("evidence", []))

    # A fix worth ~0 points because ANOTHER part holds the score down (e.g. a very low Readability, or the
    # no-numbers cap): say what blocks it and what it adds once that is fixed.
    blockers = {
        "readability": {"parts": {"readability": read(fixed_checks=tuple(res["ats"]["oracle"]["checks"]),
                                                       fixed_bugs=READ_BUGS, fixed_design=tuple(design))},
                        "layout": True, "pages": True},
        "content": {"cc": {k: {**cc[k], "score": 1.0, "quant_share": 1.0, "bullets": max(1, cc["C1"]["bullets"])}
                           if k == "C1" else {**cc[k], "score": 1.0} for k in CONTENT_WEIGHT}},
        "structure": {"pc": {k: {**pc[k], "score": 1.0} for k in STRUCT_WEIGHT}},
        "numbers": {"cc": {"C1": {**cc["C1"], "quant_share": max(cc["C1"]["quant_share"], 1e-6),
                                  "bullets": max(1, cc["C1"]["bullets"])}}},
    }

    def merged(a, b):
        out = {"parts": {**a.get("parts", {}), **b.get("parts", {})}, "cc": {**a.get("cc", {})},
               "pc": {**a.get("pc", {}), **b.get("pc", {})}, "layout": bool(a.get("layout") or b.get("layout")),
               "pages": bool(a.get("pages") or b.get("pages"))}
        for k, v in b.get("cc", {}).items():                  # both change a check: keep the better one
            old = out["cc"].get(k)
            out["cc"][k] = v if old is None or (v.get("score") or 0) >= (old.get("score") or 0) else \
                {**old, **{x: v[x] for x in ("quant_share", "bullets") if x in v and x in old and v[x] > old[x]}}
        return out

    if job_path:
        blockers["job_match"] = {"parts": {"job_match": job_match_part(res, ("F1", "M1"))}}
    fix_of = {i["id"]: i["_fix"] for i in issues}

    def score_with(ids):
        """The Resume Score with several issues fixed TOGETHER (not the sum of their points: parts overlap,
        caps and the weakest part limit the total). For the report's 'can reach X by fixing N issues'."""
        both = {"parts": {}, "cc": {}, "pc": {}}
        reads, jm, ai_gone = [set(), set(), set()], set(), set()
        for iid in ids:
            f = fix_of[iid]
            both = merged(both, f)
            for k, v in enumerate(f.get("read") or ((), (), ())):
                reads[k] |= set(v)
            jm |= set(f.get("jm") or ())
            if f.get("ai"):
                ai_gone.add(f["ai"])
        if any(reads):
            both["parts"]["readability"] = read(*[tuple(x) for x in reads])
        if jm:
            both["parts"]["job_match"] = job_match_part(res, tuple(jm))
        if ai_gone:
            both["cc"]["C8"] = ai_check([g for n, g in enumerate(ai_content or [], 1) if n not in ai_gone])
        return round(max(score, total_with(both)), 1)

    for i in issues:
        fix = i.pop("_fix")
        if i["points"] >= 0.5:
            continue
        best = None
        for name, b in blockers.items():
            if name == i["part"] or (name == "numbers" and not gates):
                continue
            base2 = total_with(b)
            gain2 = total_with(merged(b, fix)) - base2
            if base2 > score + 0.5 and (best is None or gain2 > best[1]):
                best = (name, gain2)
        if best and best[1] >= 1:
            i["blocked_by"], i["points_after"] = best[0], round(best[1], 1)
    L.EMBED_OFF = embed_off
    if job_path and (safe or not L.embedder_ok()):
        run_notes.append(L.EMBED_NOTE)
    explain = part_explain(parts, issues)
    pages_held = any("page limit" in g for g in gates)
    for i in issues:                  # 'if fixed' never more than what the issue costs its part (the 70 cap aside)
        if i["id"] == "D11" and pages_held:
            continue                  # cutting the pages also lifts the page cap on the total
        if i["part_points"] > 0:
            i["points"] = round(min(i["points"], i["part_points"]), 1)
            if i.get("points_after"):
                i["points_after"] = round(min(i["points_after"], i["part_points"]), 1)
    rank = {"Critical": 0, "Major": 1, "Minor": 2}
    issues.sort(key=lambda i: (-i["points"], rank[i["severity"]]))
    return {"version": SCORE_VERSION, "part_explain": explain, "_score_with": score_with, "notes": run_notes, "two_versions": two,
            "cv": os.path.basename(cv_path), "mode": "job" if job_path else "role", "target": target,
            "score": round(score, 1), "label": label_for(score, parts, issues), "gates": gates,
            "parts": {k: round(v, 1) for k, v in parts.items()},
            "parts_before_limits": {k: round(v, 1) for k, v in raw.items()},
            "layout_limits": {k: v for k, v in limits.items()},
            "content_checks": cc, "structure_checks": pc, "issues": issues,
            "missing_skills": missing, "missing_required": missing_required, "experience_years": round(years, 1), "role_source": role_source,
            "name_line": read_name_line(cv_path, vana) if layout else None, "_doc": doc,
            "layout": None if not layout else {"pages": layout["pages"], "columns_found": layout["columns_found"],
                                                "n_columns": layout.get("n_columns", 1),
                                                "landscape": layout.get("landscape", False),
                                               "findings": design, "reading": layout["reading"]},
            "_vdoc": vdoc, "role_skills": None,
            "ai_review": None if rev is None else
            {"field": rev["field"], "findings": rev["findings"], "rejected": len(rev["rejected"]),
             "unusual": [f for f in rev["findings"] if f["type"] == "unusual"], "cached": rev["cached"]},
            "v3": res}


def main():
    ap = argparse.ArgumentParser(description="1000Jobs CV Score (with or without a job description)")
    ap.add_argument("cv")
    ap.add_argument("--job")
    ap.add_argument("--role")
    a = ap.parse_args()
    try:
        r = score_cv(a.cv, a.job, a.role)
    except ScoreError as e:
        sys.exit(f"ERROR: {e}")
    print(f"\n{r['cv']}  ->  CV Score {r['score']} ({r['label']})   target: {r['target']}")
    print("   " + "   ".join(f"{k} {v}" for k, v in r["parts"].items()) + (f"   gates: {r['gates']}" if r["gates"] else ""))
    for i in r["issues"][:10]:
        print(f"   +{i['points']:<5} [{i['severity']}] {i['name']}: {i['detail'][:90]}")


if __name__ == "__main__":
    main()
