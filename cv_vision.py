"""What the rendered page really shows.

The Lab measures a resume itself, and its own rules can be wrong: a single-column page read as two columns, or
headings flagged as letter-spaced when the page looks normal. Before a layout card is shown (columns, a sidebar,
landscape, letter-spaced headings or a letter-spaced name) the page is measured here and must agree.

Everything happens on this computer: the PDF is opened, rendered and measured locally. Nothing is uploaded, and no
other service is called.

Layout decisions, and why:
  * columns   - a whitespace corridor down the page with real text on both sides. The corridor must run at least
               45% of the text height, so a single column with one wide gap, a right-aligned date column, or a
               highlight box row does not count. (Measured against the confirmed golden set: 4 files with columns
               found, 0 false alarms; and against 7 known layouts: one column, 2, 3 and 4 columns, both sidebars,
               landscape - all correct.)
  * sidebar   - the same corridor, but it starts in the left 40% of the page.
  * landscape - the page box is wider than it is tall.
  * letter spacing - the real gap between neighbouring letters, as a share of the font size. A normal font sits
               around 0.02-0.10; a spaced-out line is 0.25 or more, with most gaps wide. Measured on the golden
               set: one truly spaced name (0.27), 26 flagged heading cases measuring 0.06-0.08 (normal).
"""

import re
import statistics

import fitz
import numpy as np

COLUMN_CORRIDOR = 0.45     # the corridor must run this share of the text height
COLUMN_LEFT_X = 0.15       # text to the left of the corridor, as a share of the page width
COLUMN_RIGHT_X = 0.15      # text to the right of it
COLUMN_MIN_Y = 0.25        # and each side must be this tall, as a share of the text height
COLUMN_STEP = 4.0          # how far the corridor is moved along the page each time (points)
SPACED_RATIO = 0.25        # median letter gap / font size that counts as letter spacing
SPACED_BIG = 0.60          # this share of the letter gaps must be wide
SPACED_MIN_GAPS = 3
LANDSCAPE_RATIO = 1.05     # wider than tall by at least this much
INK_MAX = 200              # a grey value below this counts as ink on the page
DPI = 100                  # render resolution for the ink measurements

HEADING_WORDS = {
    "PROFESSIONALSUMMARY", "SUMMARY", "PROFILE", "EXECUTIVESUMMARY", "CAREERSUMMARY", "OBJECTIVE",
    "EXPERIENCE", "WORKEXPERIENCE", "PROFESSIONALEXPERIENCE", "RELEVANTEXPERIENCE", "EMPLOYMENTHISTORY",
    "CAREERHISTORY", "EDUCATION", "ACADEMICBACKGROUND", "SKILLS", "CORESKILLS", "TECHNICALSKILLS",
    "KEYSKILLS", "COMPETENCIES", "CORECOMPETENCIES", "EXPERTISE", "CERTIFICATIONS", "LICENSES",
    "CERTIFICATIONSANDLICENSES", "LANGUAGES", "LANGUAGESKILLS", "ACHIEVEMENTS", "KEYACHIEVEMENTS",
    "SELECTACHIEVEMENTS", "KEYACCOMPLISHMENTS", "PROJECTS", "INTERESTS", "REFERENCES", "TRAINING",
    "COURSES", "AWARDS", "PUBLICATIONS", "VOLUNTEERING", "ADDITIONALINFORMATION", "CAREERHIGHLIGHTS",
    "PROFESSIONALDEVELOPMENT", "EDUCATIONANDTRAINING", "CAREERIMPACTATAGLANCE", "TECHNOLOGIES", "TOOLS",
}

_cache = {}


def _line_chars(line):
    out = []
    for span in line.get("spans") or []:
        for ch in span.get("chars") or []:
            if ch["c"].strip():
                out.append((ch["bbox"], ch["c"], span["size"]))
    return out


def line_spacing(line):
    """The real gap between neighbouring letters, compared with the font size."""
    chars = _line_chars(line)
    if len(chars) < 4:
        return None
    gaps = [b2[0] - b1[2] for (b1, _, _), (b2, _, _) in zip(chars, chars[1:])]
    size = float(statistics.median([s for _, _, s in chars])) if chars else 0.0
    if not gaps or size <= 0:
        return None
    med = float(statistics.median(gaps))
    wide = sum(1 for g in gaps if g >= 0.18 * size) / len(gaps)
    return {"ratio": round(med / size, 3), "median_gap": round(med, 2), "font_size": round(size, 2),
            "wide_share": round(wide, 2), "letters": len(chars)}


def is_spaced(measure):
    return bool(measure and measure["ratio"] >= SPACED_RATIO and measure["wide_share"] >= SPACED_BIG
                and measure["letters"] >= SPACED_MIN_GAPS + 1)


def looks_like_heading(text):
    flat = re.sub(r"[^A-Z]", "", (text or "").upper())
    if len(flat) < 4:
        return False
    return flat in HEADING_WORDS or any(flat.startswith(w) and len(flat) <= len(w) + 4 for w in HEADING_WORDS)


def _groups(words, x):
    return [wd for wd in words if wd[2] <= x], [wd for wd in words if wd[0] >= x]


def _extent(ws):
    if not ws:
        return 0.0, 0.0
    return (max(w[2] for w in ws) - min(w[0] for w in ws),
            max(w[3] for w in ws) - min(w[1] for w in ws))


def _longest_gap(occupancy, top, bottom):
    if not occupancy:
        return bottom - top
    occ = sorted(occupancy)
    merged = [list(occ[0])]
    for y0, y1 in occ[1:]:
        if y0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], y1)
        else:
            merged.append([y0, y1])
    gap = merged[0][0] - top
    for (_a0, a1), (b0, _b1) in zip(merged, merged[1:]):
        gap = max(gap, b0 - a1)
    return max(gap, bottom - merged[-1][1])


def columns_in_words(words, width, height, corridor_frac=COLUMN_CORRIDOR, left_x=COLUMN_LEFT_X,
                     right_x=COLUMN_RIGHT_X, min_y_frac=COLUMN_MIN_Y, step=COLUMN_STEP):
    """-> the column decision for one page, from the exact position of every word on it."""
    if len(words) < 25:
        return {"columns": False, "sidebar": False, "reason": "too little text"}
    top = min(wd[1] for wd in words)
    bottom = max(wd[3] for wd in words)
    span = max(1.0, bottom - top)                      # the height of the text itself, not the page
    best = None
    x = min(wd[0] for wd in words) + 0.10 * width
    while x <= max(wd[2] for wd in words) - 0.10 * width:
        occupancy = [(wd[1], wd[3]) for wd in words if not (wd[2] < x - 2 or wd[0] > x + 2)]
        corridor = _longest_gap(occupancy, top, bottom)
        if corridor >= corridor_frac * span:
            left, right = _groups(words, x)
            lx, ly = _extent(left)
            rx, ry = _extent(right)
            if lx >= left_x * width and rx >= right_x * width \
                    and ly >= min_y_frac * span and ry >= min_y_frac * span:
                if best is None or corridor > best["corridor"]:
                    best = {"columns": True, "sidebar": bool(x <= 0.40 * width), "corridor": corridor,
                            "x_frac": round(x / width, 3), "corridor_frac": round(corridor / span, 3),
                            "left_x_frac": round(lx / width, 2), "right_x_frac": round(rx / width, 2)}
        x += step
    if best is None:
        return {"columns": False, "sidebar": False}
    best.pop("corridor", None)
    return best


def page_layout(pdf_path, max_pages=3, use_cache=True):
    """-> what the rendered pages really show, or {'ok': False} when the file cannot be measured.

    Fields: columns, sidebar, landscape, name_spaced, headings_spaced (list), readable (enough text to read).
    """
    key = str(pdf_path)
    if use_cache and key in _cache:
        return _cache[key]
    out = {"ok": False, "columns": False, "sidebar": False, "landscape": False, "name_spaced": False,
           "headings_spaced": [], "spaced_headings_checked": [], "words": 0, "pages": 0, "error": None}
    try:
        with fitz.open(key) as doc:
            out["pages"] = doc.page_count
            for pno in range(min(doc.page_count, max_pages)):
                page = doc[pno]
                rect = page.rect
                if rect.width > LANDSCAPE_RATIO * rect.height:
                    out["landscape"] = True
                if pno == 0:
                    cols = columns_in_words(page.get_text("words"), rect.width, rect.height)
                    out["columns"] = bool(cols.get("columns"))
                    out["sidebar"] = bool(cols.get("sidebar"))
                    out["columns_detail"] = cols
                    out["words"] = len((page.get_text("text") or "").split())
                    first = True
                    raw = page.get_text("rawdict")
                    for block in sorted(raw.get("blocks") or [], key=lambda b: (round(b["bbox"][1]), b["bbox"][0])):
                        if block.get("type") != 0:
                            continue
                        for line in block.get("lines") or []:
                            text = "".join(ch["c"] for span in (line.get("spans") or [])
                                           for ch in (span.get("chars") or [])).strip()
                            if not text:
                                continue
                            measure = line_spacing(line)
                            if first and re.search(r"[A-Za-z]", text):
                                first = False
                                out["name_spaced"] = is_spaced(measure)
                                out["name_spacing"] = measure
                                out["name_text"] = text[:60]
                                continue
                            if looks_like_heading(text) and measure:
                                out["spaced_headings_checked"].append(
                                    {"text": text[:40], "ratio": measure["ratio"]})
                                if is_spaced(measure):
                                    out["headings_spaced"].append(text[:40])
            out["readable"] = bool(out["words"] >= 80)
            out["ok"] = True
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    if use_cache:
        _cache[key] = out
    return out
