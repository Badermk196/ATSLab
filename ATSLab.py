"""
1000Jobs ATS LAB v2  -  UAE ATS profiles: Greenhouse, Workday, Oracle
=====================================================================

Scores ORIGINAL CVs (PDF) against their job descriptions.

  READABLE (30%)  - can the ATS parser read it?
  FINDABLE (30%)  - would a recruiter's keyword search find it?
  MATCHED  (40%)  - how well does it fit the job?
  HONESTY GATE    - invented content = score 0 (only when a profile is given)

Each CV is scored 3 times, once per ATS profile:
  GREENHOUSE - lenient parser, word forms count, any common heading words
  WORKDAY    - strict parser, standard section names, dates weigh double
  ORACLE     - strict parser, EXACT keyword match (no word forms), standard section names
Overall = average of the 3.

USAGE (PowerShell, inside C:\\ATSLab)
-------------------------------------
  python -m pip install pdfplumber requests scikit-learn
  $env:OPENROUTER_API_KEY="your-key"

  # ALL CVs at once: pairs CVS\\Name.pdf with JobDe\\Name.txt
  python ATSLab.py --cvdir CVS --jobdir JobDe --model google/gemini-2.5-flash

  # ONE CV
  python ATSLab.py --cv CVS\\Name.pdf --job JobDe\\Name.txt --model google/gemini-2.5-flash

Job keywords are extracted once by AI and saved as JobDe\\Name_keywords.json.
Later runs reuse that file, so before/after comparisons stay fair.
Delete the file to extract again. You can also edit it by hand.

Outputs: a report per CV on screen, results.csv (one row per CV) and results.json.
"""

import argparse
import csv
import glob
import json
import os
import re
import sys
from datetime import date

import pdfplumber

WEIGHTS = {"readable": 0.30, "findable": 0.30, "matched": 0.40}

ATS_PROFILES = {
    "greenhouse": {"strict_parser": False, "stemming": True, "standard_headings": False, "date_weight": 1.0},
    "workday":    {"strict_parser": True,  "stemming": True, "standard_headings": True,  "date_weight": 2.0},
    "oracle":     {"strict_parser": True,  "stemming": False, "standard_headings": True, "date_weight": 1.5},
}

SECTION_WORDS = {
    "summary": ["summary", "profile", "objective", "about"],
    "experience": ["experience", "employment", "work history"],
    "education": ["education", "academic"],
    "skills": ["skills", "competencies", "technologies", "tools"],
}
STANDARD_HEADING_WORDS = [
    "summary", "profile", "objective", "experience", "employment", "work history", "education",
    "skills", "certification", "certificate", "license", "language", "project", "award",
    "achievement", "publication", "volunteer", "interest", "reference", "training", "competenc",
    "course", "contact", "honor", "activities", "conference",
]

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

MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DASH = r"[-\u2013\u2014\u00e2]+|to"
DATE_RANGE = re.compile(rf"({MONTH}\s*\d{{4}}|\d{{4}})\s*({DASH})\s*({MONTH}\s*\d{{4}}|\d{{4}}|present|current|now)", re.I)
MONTH_RANGE = re.compile(rf"{MONTH}\s*\d{{4}}\s*({DASH})\s*({MONTH}\s*\d{{4}}|present|current|now)", re.I)

BROKEN_PATTERNS = {
    "HTML code": r"<\s*/?\s*(span|div|br|p|b|i|strong)\b[^>]*>",
    "Markdown marks (**)": r"\*\*",
    "Placeholder text": r"\b(not specified|date not specified|tbd|lorem ipsum)\b",
    "Watermark text": r"prepared with 1000jobs",
    "Broken characters": r"\u00e2\u0080|\u00c2\u00b7|\u00e2(?=\s|\d)",
}


# ---------------------------------------------------------------------------
# Text extraction: strict parser vs modern parser
# ---------------------------------------------------------------------------
def extract_texts(pdf_path):
    strict, modern = [], []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            strict.append(page.extract_text(x_tolerance=1) or "")   # like pdftotext / older parsers
            modern.append(page.extract_text(x_tolerance=3) or "")   # merges letters into words
    return "\n".join(strict), "\n".join(modern)


def lines_of(text):
    return [l.strip() for l in text.splitlines() if l.strip()]


def contains_term(term, text_lower, stemming=True):
    t = term.strip().lower()
    if not t:
        return False
    words = [re.escape(w) for w in t.split()]
    if stemming:
        words[-1] += r"(s|es|ed|ing)?"
    pattern = r"(?<![\w])" + r"[\s\-/]+".join(words) + r"(?![\w])"
    return re.search(pattern, text_lower) is not None


def count_term(term, text_lower):
    t = re.escape(term.strip().lower())
    return len(re.findall(rf"(?<![\w]){t}(?![\w])", text_lower))


def is_heading(line):
    return (len(line) <= 45 and len(line.split()) <= 7 and line.isupper()
            and re.search(r"[A-Z]{2}", line.replace(" ", "")) and not re.search(r"@|\d{3}", line))


# ---------------------------------------------------------------------------
# READABLE
# ---------------------------------------------------------------------------
def spaced_lines(lines):
    return [l for l in lines if len(l) <= 70 and re.search(r"(?:\b[A-Za-z]\s){4,}[A-Za-z]", l)]


def skills_content(lines):
    idx = [i for i, l in enumerate(lines)
           if len(l) <= 45 and len(l.split()) <= 6 and (l.isupper() or l.istitle())
           and re.search(r"skill|technolog|tools", l, re.I)]
    if not idx:
        return False, "no Skills heading found"
    for start in idx:
        block = []
        for l in lines[start + 1:start + 15]:
            if is_heading(l):
                break
            block.append(l)
        items = sum(len([x for x in re.split(r"[,;]", l.split(":", 1)[-1]) if x.strip()])
                    for l in block if re.search(r"[,;]", l) or re.search(r":\s*\S", l))
        if items >= 4:
            return True, f"{items} skill items found"
    return False, "Skills heading found, but no listed skills under it"


def score_readable(strict_text, modern_text, prof):
    s_lines, m_lines = lines_of(strict_text), lines_of(modern_text)
    head_lines = s_lines if prof["strict_parser"] else m_lines
    low = modern_text.lower()
    checks = {}  # name -> (passed, detail, weight)

    top = m_lines[:6]
    checks["R1 Name"] = (bool(top) and 2 <= len(top[0].split()) <= 6 and not re.search(r"[@\d]", top[0]),
                         top[0] if top else "no text extracted", 1)

    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", modern_text)
    checks["R2 Email"] = (bool(email), email.group(0) if email else "no email found", 1)

    phone = re.search(r"(\+?\d[\d\s\-()]{7,}\d)", modern_text)
    checks["R3 Phone with +country code"] = (bool(phone) and phone.group(1).strip().startswith("+"),
                                             phone.group(1).strip() if phone else "no phone found", 1)

    headline = next((l for l in top[1:4] if not re.search(r"@|\+?\d{6,}", l) and 2 <= len(l.split()) <= 20), None)
    checks["R4 Headline"] = (bool(headline), headline or "no headline under the name", 1)

    found = {sec: any(len(l) <= 45 and any(w in l.lower() for w in ws) for l in head_lines)
             for sec, ws in SECTION_WORDS.items()}
    spaced = spaced_lines(head_lines)
    missing = [k for k, v in found.items() if not v]
    if spaced:
        detail = f"{len(spaced)} letter-spaced heading(s), e.g. '{spaced[0][:40]}'"
    elif missing:
        detail = "not found: " + ", ".join(missing)
    else:
        detail = "Summary, Experience, Education, Skills all readable"
    checks["R5 Section headings readable"] = (not spaced and not missing, detail, 1)

    ranges = DATE_RANGE.findall(modern_text)
    durations = re.findall(r"\|\s*\d+\s*(years?|months?)\b", low)
    checks["R6 Jobs have date ranges"] = (
        len(ranges) >= 1 and not durations,
        f"{len(ranges)} date ranges" + (f", {len(durations)} durations instead of dates" if durations else ""),
        prof["date_weight"])

    edu_line = re.compile(r"universit|college|institut|school|academy|" + "|".join(p for _, p in DEGREE_PATTERNS), re.I)
    end = r"\s*\)?\s*$"
    job_lines = [l for l in m_lines if re.search(DATE_RANGE.pattern + end, l, re.I) and not edu_line.search(l)]
    with_month = [l for l in job_lines if re.search(MONTH_RANGE.pattern + end, l, re.I)]
    checks["R7 Job dates as 'Mon YYYY - Mon YYYY'"] = (
        bool(job_lines) and len(with_month) == len(job_lines),
        f"{len(with_month)} of {len(job_lines)} job date lines have months", prof["date_weight"])

    degree = next((lvl for lvl, pat in DEGREE_PATTERNS if re.search(pat, low)), None)
    after_edu = modern_text[low.find("education"):] if "education" in low else ""
    checks["R8 Education (degree + year)"] = (
        bool(degree and re.search(r"(19|20)\d{2}", after_edu)),
        f"degree: {degree or 'not found'}, year: {'yes' if re.search(r'(19|20)[0-9]{2}', after_edu) else 'no'}", 1)

    ok, why = skills_content(m_lines)
    checks["R9 Skills section has real skills"] = (ok, why, 1)

    broken = [n for n, p in BROKEN_PATTERNS.items() if re.search(p, low)]
    checks["R10 No broken text"] = (not broken, ", ".join(broken) if broken else "clean", 1)

    if prof["standard_headings"]:
        heads = [l for l in m_lines[3:] if is_heading(l) and len(l.split()) >= 2]
        odd = [h for h in heads if not any(w in h.lower() for w in STANDARD_HEADING_WORDS)]
        checks["R11 Only standard section names"] = (
            not odd, "non-standard: " + "; ".join(odd[:4]) if odd else "all section names standard", 1)

    score = 100 * sum(w for p, _, w in checks.values() if p) / sum(w for _, _, w in checks.values())
    return score, checks


# ---------------------------------------------------------------------------
# FINDABLE
# ---------------------------------------------------------------------------
def score_findable(cv_text, kw, profile, prof):
    low = cv_text.lower()
    head = "\n".join(lines_of(cv_text)[:15]).lower()
    stem = prof["stemming"]
    checks, parts = {}, {}

    hard = kw.get("hard_skills", [])
    found = [s for s in hard if contains_term(s, low, stem)]
    f1 = 100 * len(found) / len(hard) if hard else None
    checks["F1 Hard skills found" + ("" if stem else " (exact only)")] = (
        f1, f"{len(found)}/{len(hard)}; missing: {', '.join(s for s in hard if s not in found) or 'none'}")
    parts["F1"] = (f1, 0.50)

    pairs, both = [], 0
    for s in hard:
        key = s.strip().lower()
        other = ABBREVIATIONS.get(key) or next((a for a, f in ABBREVIATIONS.items() if f == key), None)
        if other:
            pairs.append(s)
            both += contains_term(s, low, stem) and contains_term(other, low, stem)
    f2 = 100 * both / len(pairs) if pairs else None
    checks["F2 Abbreviations in both forms"] = (
        f2, f"{both}/{len(pairs)} written both ways" if pairs else "no abbreviation terms in this job")
    parts["F2"] = (f2, 0.15)

    title = (kw.get("title") or "").strip()
    f3 = (100.0 if contains_term(title, head, stem) else 0.0) if title else None
    checks["F3 Exact job title near the top"] = (
        f3, f"'{title}' {'found' if f3 else 'NOT found'}" if title else "no job title extracted")
    parts["F3"] = (f3, 0.25)

    titles = (profile or {}).get("titles", [])
    if titles:
        changed = [t for t in titles
                   if not re.search(rf"{re.escape(t.lower())}(?!\s*[\u2014|\-/]\s*\w{{4,}})", low)]
        f4 = 100 * (len(titles) - len(changed)) / len(titles)
        checks["F4 Past titles unchanged"] = (f4, "changed/missing: " + (", ".join(changed) or "none"))
    else:
        f4 = None
        checks["F4 Past titles unchanged"] = (None, "skipped (no profile titles)")
    parts["F4"] = (f4, 0.10)
    return weighted(parts), checks


# ---------------------------------------------------------------------------
# MATCHED
# ---------------------------------------------------------------------------
def meaning_match(cv_text, job_text):
    if not job_text.strip():
        return None
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        return None
    m = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True).fit_transform([cv_text, job_text])
    return min(100.0, float(cosine_similarity(m[0], m[1])[0][0]) / 0.45 * 100)


def cv_years(cv_text):
    total, now = 0.0, date.today().year
    for m in DATE_RANGE.finditer(cv_text):
        ys = re.findall(r"((?:19|20)\d{2})", m.group(0))
        if ys:
            start, end = int(ys[0]), int(ys[1]) if len(ys) > 1 else now
            if end >= start:
                total += max(0.25, end - start)
    return total


def score_matched(cv_text, job_text, kw, prof):
    low, jlow = cv_text.lower(), job_text.lower()
    stem = prof["stemming"]
    checks, parts = {}, {}

    hard = kw.get("hard_skills", [])
    if hard:
        w = {s: max(1, count_term(s, jlow)) for s in hard}
        got = sum(w[s] for s in hard if contains_term(s, low, stem))
        m1 = 100 * got / sum(w.values())
        checks["M1 Hard skills coverage (weighted)"] = (m1, f"{got}/{sum(w.values())} weighted points")
    else:
        m1 = None
        checks["M1 Hard skills coverage (weighted)"] = (None, "no hard skills extracted")
    parts["M1"] = (m1, 0.50)

    soft = kw.get("soft_skills", [])
    m2 = 100 * sum(contains_term(s, low, stem) for s in soft) / len(soft) if soft else None
    checks["M2 Soft skills coverage"] = (
        m2, ("missing: " + (", ".join(s for s in soft if not contains_term(s, low, stem)) or "none")) if soft else "none extracted")
    parts["M2"] = (m2, 0.10)

    m3 = meaning_match(cv_text, job_text)
    checks["M3 Meaning match (TF-IDF)"] = (m3, "CV vs job similarity" if m3 is not None else "needs job text + scikit-learn")
    parts["M3"] = (m3, 0.25)

    need = str(kw.get("degree_level") or "none").lower()
    have = next((lvl for lvl, pat in DEGREE_PATTERNS if re.search(pat, low)), "none")
    if need in DEGREE_RANK and need != "none":
        m4 = 100.0 if DEGREE_RANK.get(have, 0) >= DEGREE_RANK[need] else 0.0
        checks["M4 Education level"] = (m4, f"job needs {need}, CV shows {have}")
    else:
        m4 = None
        checks["M4 Education level"] = (None, "job sets no degree level")
    parts["M4"] = (m4, 0.075)

    try:
        need_y = float(kw.get("min_years") or 0)
    except (TypeError, ValueError):
        need_y = 0
    if need_y:
        have_y = cv_years(cv_text)
        m5 = min(100.0, 100 * have_y / need_y)
        checks["M5 Experience level"] = (m5, f"job needs {need_y:g}+ years, CV shows ~{have_y:.1f}")
    else:
        m5 = None
        checks["M5 Experience level"] = (None, "job sets no minimum years")
    parts["M5"] = (m5, 0.075)
    return weighted(parts), checks


# ---------------------------------------------------------------------------
# HONESTY GATE
# ---------------------------------------------------------------------------
def honesty_gate(cv_text, kw, profile):
    if not profile or not profile.get("text"):
        return None, "skipped (no profile text given)"
    low, plow = cv_text.lower(), profile["text"].lower()
    invented = [s for s in kw.get("hard_skills", []) if contains_term(s, low) and not contains_term(s, plow)]
    return (not invented), ("invented: " + ", ".join(invented)) if invented else "all job skills in the CV exist in the profile"


# ---------------------------------------------------------------------------
# Keywords (AI extraction, saved for reuse)
# ---------------------------------------------------------------------------
KEYWORD_PROMPT = """You are extracting ATS keywords from a job description.
Return ONLY a JSON object, no other text:
{"title": "", "hard_skills": [], "soft_skills": [], "degree_level": "none", "min_years": 0}

Rules:
- title: the exact job title as written in the posting.
- hard_skills: 10-25 concrete skills a recruiter would search for: tools, software,
  programming languages, technical methods, certifications, domain knowledge
  (e.g. "Python", "Financial modelling", "Salesforce", "Go-to-market strategy").
  Each 1-4 words, spelled EXACTLY as in the posting. NO sentences, NO generic
  phrases like "setting up team goals", "1:1s", "maintenance".
- soft_skills: up to 8 personal qualities as single words or short phrases
  (e.g. "Communication", "Leadership"). NO adjectives like "continuous".
- degree_level: one of none, diploma, bachelor, master, phd (minimum required).
- min_years: minimum years of experience required as a number, 0 if not stated.

JOB DESCRIPTION:
"""


def extract_keywords_ai(job_text, model):
    import requests
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("ERROR: OPENROUTER_API_KEY is not set. Run:  $env:OPENROUTER_API_KEY=\"your-key\"")
    r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": model, "temperature": 0,
                            "messages": [{"role": "user", "content": KEYWORD_PROMPT + job_text}]},
                      timeout=180)
    if r.status_code != 200:
        sys.exit(f"ERROR from OpenRouter ({r.status_code}): {r.text[:300]}")
    text = re.sub(r"```json|```", "", r.json()["choices"][0]["message"]["content"])
    return json.loads(text[text.find("{"): text.rfind("}") + 1])


def load_keywords(job_path, model):
    kw_path = os.path.splitext(job_path)[0] + "_keywords.json"
    if os.path.exists(kw_path):
        with open(kw_path, encoding="utf-8") as f:
            return json.load(f)
    if not model:
        sys.exit(f"ERROR: {kw_path} not found. Add --model to extract keywords with AI.")
    with open(job_path, encoding="utf-8", errors="ignore") as f:
        kw = extract_keywords_ai(f.read(), model)
    with open(kw_path, "w", encoding="utf-8") as f:
        json.dump(kw, f, indent=2, ensure_ascii=False)
    print(f"   (keywords saved to {kw_path})")
    return kw


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def weighted(parts):
    usable = [(v, w) for v, w in parts.values() if v is not None]
    return sum(v * w for v, w in usable) / sum(w for _, w in usable) if usable else 0.0


def score_cv(cv_path, job_path, model=None, profile_path=None):
    strict, modern = extract_texts(cv_path)
    with open(job_path, encoding="utf-8", errors="ignore") as f:
        job_text = f.read()
    kw = load_keywords(job_path, model)
    profile = json.load(open(profile_path, encoding="utf-8")) if profile_path and os.path.exists(profile_path) else None
    honest, h_detail = honesty_gate(modern, kw, profile)

    per_ats = {}
    for name, prof in ATS_PROFILES.items():
        r, rc = score_readable(strict, modern, prof)
        fi, fc = score_findable(modern, kw, profile, prof)
        m, mc = score_matched(modern, job_text, kw, prof)
        total = r * WEIGHTS["readable"] + fi * WEIGHTS["findable"] + m * WEIGHTS["matched"]
        if honest is False:
            total = 0.0
        per_ats[name] = {"total": round(total, 1), "readable": round(r, 1), "findable": round(fi, 1),
                         "matched": round(m, 1), "checks": {**rc, **fc, **mc}}
    overall = round(sum(a["total"] for a in per_ats.values()) / len(per_ats), 1)
    return {"cv": os.path.basename(cv_path), "job_title": kw.get("title", ""), "overall": overall,
            "ats": per_ats, "honesty": {None: "not checked", True: "pass", False: "FAIL"}[honest],
            "honesty_detail": h_detail}


def fmt(val):
    if isinstance(val, bool):
        return "PASS" if val else "FAIL"
    return " -- " if val is None else f"{val:4.0f}"


def print_report(res):
    a = res["ats"]
    print("\n" + "=" * 74)
    print(f" {res['cv']}   ->   {res['job_title']}")
    print("=" * 74)
    print(f" OVERALL: {res['overall']}   |  Greenhouse {a['greenhouse']['total']}  |  "
          f"Workday {a['workday']['total']}  |  Oracle {a['oracle']['total']}   (Honesty: {res['honesty']})")
    print(f" Strictest view (Oracle):  Readable {a['oracle']['readable']}  Findable {a['oracle']['findable']}  "
          f"Matched {a['oracle']['matched']}")
    print("-" * 74)
    seen = set()
    for prof in ("oracle", "workday", "greenhouse"):   # strictest first, show each check once
        for name, v in a[prof]["checks"].items():
            base = name.split(" (exact")[0]
            if base in seen:
                continue
            seen.add(base)
            print(f" [{fmt(v[0])}] {name}\n          {v[1]}")


def check_value(v):
    if isinstance(v, bool):
        return "PASS" if v else "FAIL"
    return "" if v is None else round(v)


def write_outputs(results, out_csv):
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        check_names = []
        for r in results:
            for n in r["ats"]["oracle"]["checks"]:
                if n not in check_names:
                    check_names.append(n)
        w.writerow(["cv", "job_title", "overall", "greenhouse", "workday", "oracle",
                    "oracle_readable", "oracle_findable", "oracle_matched", "honesty"] + check_names)
        for r in results:
            a = r["ats"]
            row = [r["cv"], r["job_title"], r["overall"], a["greenhouse"]["total"], a["workday"]["total"],
                   a["oracle"]["total"], a["oracle"]["readable"], a["oracle"]["findable"], a["oracle"]["matched"],
                   r["honesty"]]
            row += [check_value(a["oracle"]["checks"][n][0]) if n in a["oracle"]["checks"] else "" for n in check_names]
            w.writerow(row)
    with open(os.path.splitext(out_csv)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)


def print_summary(results):
    n = len(results)
    avg = lambda key: round(sum(r["ats"][key]["total"] for r in results) / n, 1)
    print("\n" + "#" * 74)
    print(f" SUMMARY: {n} CVs")
    print("#" * 74)
    print(f" Average OVERALL {round(sum(r['overall'] for r in results) / n, 1)}   |   "
          f"Greenhouse {avg('greenhouse')}   Workday {avg('workday')}   Oracle {avg('oracle')}")
    print("\n Scores per CV (sorted, lowest first):")
    for r in sorted(results, key=lambda x: x["overall"]):
        a = r["ats"]
        print(f"   {r['overall']:5}  GH {a['greenhouse']['total']:5}  WD {a['workday']['total']:5}  "
              f"OR {a['oracle']['total']:5}   {r['cv']}")
    fails = {}
    for r in results:
        for name, v in r["ats"]["oracle"]["checks"].items():
            if v[0] is False or (isinstance(v[0], (int, float)) and not isinstance(v[0], bool) and v[0] < 50):
                fails[name] = fails.get(name, 0) + 1
    print("\n Most common problems (strict Oracle view; numeric checks count when below 50):")
    for name, c in sorted(fails.items(), key=lambda x: -x[1]):
        print(f"   {c:>2}/{n}  {name}")


def main():
    ap = argparse.ArgumentParser(description="1000Jobs ATS Lab v2 (Greenhouse, Workday, Oracle)")
    ap.add_argument("--cv"); ap.add_argument("--job")
    ap.add_argument("--cvdir"); ap.add_argument("--jobdir")
    ap.add_argument("--profile"); ap.add_argument("--profiledir")
    ap.add_argument("--model"); ap.add_argument("--out", default="results.csv")
    a = ap.parse_args()

    if a.cvdir and a.jobdir:
        results = []
        cvs = sorted(glob.glob(os.path.join(a.cvdir, "*.pdf")))
        print(f"Found {len(cvs)} CVs in {a.cvdir}")
        for cv in cvs:
            name = os.path.splitext(os.path.basename(cv))[0]
            job = os.path.join(a.jobdir, name + ".txt")
            if not os.path.exists(job):
                print(f" SKIPPED {name}: no {job}")
                continue
            prof = os.path.join(a.profiledir, name + ".json") if a.profiledir else None
            print(f" Scoring {name} ...")
            try:
                res = score_cv(cv, job, a.model, prof)
            except Exception as e:  # keep going if one file fails
                print(f" ERROR on {name}: {e}")
                continue
            print_report(res)
            results.append(res)
        if results:
            print_summary(results)
            write_outputs(results, a.out)
            print(f"\nSaved {a.out} and {os.path.splitext(a.out)[0]}.json")
    elif a.cv and a.job:
        res = score_cv(a.cv, a.job, a.model, a.profile)
        print_report(res)
        write_outputs([res], a.out)
    else:
        sys.exit("Use --cvdir CVS --jobdir JobDe  (all CVs)  or  --cv file.pdf --job file.txt  (one CV).")


if __name__ == "__main__":
    main()
