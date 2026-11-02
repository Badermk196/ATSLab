"""
1000Jobs AI reviewer - reads a CV like a recruiter and returns findings (issue, severity, exact quote, why, fix).

- google/gemini-2.5-flash via OpenRouter, temperature 0 (ATSLab_v3.call_ai).
- A finding is kept only if its quote really is in the CV text (spaces, quotes and dashes normalized).
- type "content": feeds Content Quality in cv_score.py; type "unusual": listed as a possible new problem for a
  human to check (not scored).
- Saved per CV in cv_reviews\\ (key = the CV text + prompt version + model), so a CV is reviewed once.
"""

import hashlib
import json
import os
import re

import ATSLab_v3 as L

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "google/gemini-2.5-flash"
REVIEW_CACHE = os.path.join(HERE, "cv_reviews")
REVIEW_PROMPT_VERSION = 8      # 2: today's date; 3: no answered / removal / nitpicks; 4: timeline, no invented
#                                explanations; 6: only the timeline's conclusion (a full list confused the model);
#                                7: a real degree is never "irrelevant"; 8: at most 3 findings, only Important ones,
#                                never "add a number / more context" on a bullet that has numbers, no nitpicks
MAX_FINDINGS = 3
SEVERITIES = ("Critical", "Major", "Minor")
MIN_QUOTE_WORDS = 3

REVIEW_PROMPT = """You are an experienced recruiter reviewing a CV{target}. List the problems a recruiter would notice.
Today's date is {today}. A date up to today (and "Present" / "Current") is NOT in the future.
Return ONLY a JSON object, no other text:
{{"field": "", "findings": [{{"issue": "", "severity": "", "type": "", "quote": "", "why": "", "fix": ""}}]}}

Rules:
- field: the candidate's main professional field in 2-5 words (e.g. "media planning and buying").
- findings: AT MOST 3 REAL problems, most important first. Return fewer (or an empty list) when the CV is strong:
  a well-written CV needs no findings. Never invent a problem and never pad the list.
- issue: a short plain-English title, at most 8 words.
- severity: "Critical" (likely to get the CV rejected) or "Major" (Important: a recruiter would act on it). Do not
  report anything smaller than Major.
- type: "content" for writing and content problems (vague bullets, no results, unclear role or level, inconsistent
  dates or titles, spelling and grammar, irrelevant or risky personal details, unprofessional email, unexplained
  gaps, claims without proof, ...); "unusual" for anything that looks like a broken or wrongly generated CV
  (text about another person, placeholder text, repeated blocks, wrong name, mixed languages, garbled text,
  code or symbols in the text).
- quote: copy the EXACT words from the CV that show the problem, 5 to 25 words, same spelling and punctuation.
  Never paraphrase or shorten with "...". If something is missing, quote the line where it should be.
- why: one simple sentence: why it hurts the CV.
- fix: one simple sentence: how to fix it. Never suggest inventing experience, numbers or skills.
- Do NOT comment on layout, columns, fonts, colors, photos or ATS formatting: those are checked separately.
- NEVER flag something the quoted text already answers (if it says "Led a team of 5", the team size is clear).
- NEVER suggest removing real degrees, jobs, certifications or experience. NEVER call a real degree (or a job or
  certification) "irrelevant", "unrelated" or "not relevant": a degree in another field still counts. At most
  suggest how to present it (for example what it adds to this role).
- NEVER ask for "more context", "more detail" or "add a number / metric" on a bullet that already contains numbers
  or a clear result. Do not comment on the length of the summary.
- Only report problems a recruiter would act on when deciding whether to interview. Skip nitpicks (a single
  punctuation slip, a style preference, wording that is already clear, contact details repeated in a page header
  or footer, a page number).
- NEVER suggest inventing an explanation (for example "travel", "family time", "studies") for a gap or anything
  else. If something needs explaining, only suggest stating what really happened, if the candidate wishes.
- Employment gaps: report a gap ONLY if it is listed in "DATES CHECKED BY THE LAB" below (the Lab read every job
  and education date of the CV). If it says there are no gaps, do not report any gap.
{timeline}
CV:
"""


def review_prompt(target=None, timeline=None):
    t = f" for the target role: {target}" if target else ""
    tl = f"\nDATES CHECKED BY THE LAB (not part of the CV): {timeline}\n" if timeline else ""
    return REVIEW_PROMPT.format(target=t, today=L.TODAY.strftime("%d %B %Y"), timeline=tl)


def norm(text):
    """Text for quote matching: lower case, one kind of dash and quote, no line breaks or double spaces."""
    t = L.norm_punct(text).lower().replace("“", '"').replace("”", '"').replace("•", " ")
    t = re.sub(r"[ \s]+", " ", t)
    return t.strip(" .,;:'\"")


def quote_in_cv(quote, cv_texts):
    q = norm(quote or "")
    if len(q.split()) < MIN_QUOTE_WORDS or "..." in q or "…" in q:
        return False
    cv = [norm(t) for t in cv_texts if t]
    if any(q in t for t in cv):
        return True
    # a quote over several lines (e.g. two job lines that are apart in the CV): every line must be in the CV
    parts = [norm(p) for p in re.split(r"\n+", quote or "") if norm(p)]
    return len(parts) > 1 and all(any(p in t for t in cv) for p in parts)


def cache_path(cv_text, target, model=MODEL, cache=None, timeline=None):
    key = hashlib.sha256(f"{model}|{REVIEW_PROMPT_VERSION}|{target or ''}|{timeline or ''}|{cv_text}"
                         .encode("utf-8")).hexdigest()[:24]
    return os.path.join(cache or REVIEW_CACHE, key + ".json")


def clean(raw, cv_texts):
    """Keep the findings whose quote is really in the CV; tidy severity and type. v1.1: every employment gap finding
    is rejected (the Lab does not check gaps)."""
    kept, rejected = [], []
    for f in (raw or {}).get("findings") or []:
        if not isinstance(f, dict):
            continue
        item = {k: str(f.get(k) or "").strip() for k in ("issue", "severity", "type", "quote", "why", "fix")}
        item["severity"] = next((s for s in SEVERITIES if s.lower() == item["severity"].lower()), "Minor")
        if item["severity"] == "Critical":
            item["severity"] = "Major"                           # an AI finding is Important at most, never Critical
        item["type"] = "unusual" if item["type"].lower() == "unusual" else "content"
        if item["severity"] == "Minor" or is_nitpick(item) or is_gap_finding(item):   # Important only, no nitpicks,
            rejected.append(item)                                                      # no gaps
            continue
        same = any(norm(k["issue"]) == norm(item["issue"]) for k in kept)        # one card per problem
        if item["issue"] and quote_in_cv(item["quote"], cv_texts) and not false_future(item) \
                and not already_answered(item) and not same and not calls_degree_irrelevant(item):
            words = item["quote"].split()
            if len(words) > SHOW_QUOTE_WORDS:            # shown shortened; the full quote was checked against the CV
                item["quote_full"] = item["quote"]
                item["quote"] = " ".join(words[:SHOW_QUOTE_WORDS]) + " …"
            kept.append(item)
        elif not same:
            rejected.append(item)
    rank = {s: n for n, s in enumerate(SEVERITIES)}
    kept = sorted(kept, key=lambda k: rank[k["severity"]])       # most severe first (the order is kept within a level)
    return kept[:MAX_FINDINGS], rejected + kept[MAX_FINDINGS:]


MORE_RE = re.compile(r"more (?:context|detail|specific)|lacks? (?:context|detail)|add (?:a |more |some )?(?:number|metric|"
                     r"figure|result|data)|quantif|measurable|no (?:number|metric)s?|no context|needs? context", re.I)
SUMMARY_LENGTH_RE = re.compile(r"summary|profile", re.I)
LENGTH_WORDS_RE = re.compile(r"(?<!\w)(too long|too short|long|short|length|lengthy|wordy|brief|concise|word count|dense)(?!\w)",
                             re.I)


def is_nitpick(item):
    """Not worth a card: 'add a number / more context' on a quote that already has numbers, or the length of the
    summary (only a summary over 150 words is flagged, by the Lab itself)."""
    text = item["issue"] + " " + item["why"] + " " + item["fix"]
    if MORE_RE.search(text) and re.search(r"\d", item["quote"]):
        return True
    return bool(SUMMARY_LENGTH_RE.search(item["issue"]) and LENGTH_WORDS_RE.search(item["issue"] + " " + item["why"]))


ANSWERED_RE = re.compile(r"\b(unclear|missing|no|not (?:stated|specified|clear)|lacks?|vague)\b.*"
                         r"\b(size|number|how many|count|headcount|amount)\b", re.I)
SHOW_QUOTE_WORDS = 35


def already_answered(item):
    """'Unclear team size' while the quote says 'Led a team of 5': the quote already answers it."""
    return bool(ANSWERED_RE.search(item["issue"])) and bool(re.search(r"\d", item["quote"]))


IRRELEVANT_RE = re.compile(r"\birrelevant\b|\bunrelated\b|\bnot relevant\b|\bnot related\b", re.I)
DEGREE_WORDS_RE = re.compile(r"\b(degree|bachelor|master|mba|ph\.?d|doctorate|diploma|b\.?\s?sc|m\.?\s?sc|b\.?\s?a\b|"
                             r"m\.?\s?a\b|b\.?\s?eng|m\.?\s?eng|university|college|graduat)", re.I)


def calls_degree_irrelevant(item):
    """'Irrelevant Master's degree': a real degree is never irrelevant (rejected even if the prompt is ignored)."""
    return bool(IRRELEVANT_RE.search(item["issue"] + " " + item["why"])) and \
        bool(DEGREE_WORDS_RE.search(item["quote"] + " " + item["issue"]))


GAP_RE = re.compile(r"(?<!skills )(?<!skill )\bgaps?\b|career break|break in (?:employment|career)|"
                    r"time (?:off|out) (?:between|from)", re.I)


def is_gap_finding(item):
    """'Unexplained employment gap', 'Career break not explained': the Lab does not check gaps (v1.1)."""
    return bool(GAP_RE.search(item["issue"] + " " + item["why"]))


FUTURE_RE = re.compile(r"\bfuture\b|not (?:yet )?started|hasn't started|has not started", re.I)


def false_future(item):
    """The AI says a date is in the future: check it. False claim = every date in the quote is today or earlier."""
    if not FUTURE_RE.search(item["issue"] + " " + item["why"]):
        return False
    now = L.TODAY.year * 12 + L.TODAY.month - 1
    q = L.norm_punct(item["quote"])
    ends = [r["end"] for r in L.find_ranges(q)] + [r["start"] for r in L.find_ranges(q)]
    ends += [L._month_index(m.group(0), False) for m in L.POINT_RE.finditer(L.RANGE_RE.sub(" ", q))]
    return bool(ends) and max(ends) <= now


def review_cv(cv_text, target=None, model=MODEL, cache=None, also_texts=(), timeline=None):
    """-> {"field", "findings" (quote checked), "rejected", "cached"} or None when no API key is set.
    cv_text: the CV as a person reads it; also_texts: other readings a quote may come from (the ATS text);
    timeline: the Lab's job + education timeline as text (sent to the AI)."""
    path = cache_path(cv_text, target, model, cache, timeline)
    texts = [cv_text, *also_texts]
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        kept, rejected = clean(data.get("raw"), texts)
        return {"field": (data.get("raw") or {}).get("field"), "findings": kept, "rejected": rejected, "cached": True}
    if not os.environ.get("OPENROUTER_API_KEY"):
        return None
    prompt = review_prompt(target, timeline) + cv_text
    raw = L.call_ai(prompt, model) or L.call_ai(prompt, model)
    if raw is None:
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"model": model, "prompt_version": REVIEW_PROMPT_VERSION, "temperature": 0, "target": target,
                   "created": L.TODAY.isoformat(), "raw": raw}, f, indent=2, ensure_ascii=False)
    kept, rejected = clean(raw, texts)
    return {"field": raw.get("field"), "findings": kept, "rejected": rejected, "cached": False}
