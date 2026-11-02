"""
1000Jobs CV layout checks - design problems seen in the PDF itself (photos, sidebars, columns, icons, boxes,
fonts, contrast, reading order), plus a column-by-column "page view" of the text and page images with the
problem areas marked. Used by cv_score.py and dashboard.py; ATSLab_v3.py is only called.

Colors and contrast are measured on the RENDERED page (pixels), because PDF fill values can be transparent
(a navy fill at 25% opacity looks light grey-blue on the page).
"""

import io
import re

import pdfplumber
import pypdfium2

import ATSLab_v3 as L
import cv_cache

# Design issues: id -> (short label on the page image, severity). Severity: Major = shown as "Important".
DESIGN = {
    "D1": ("Photo", "Minor"),            # photo or images
    "D2": ("Colored panel", "Minor"),    # colored background panels
    "D3": ("Sidebar", "Major"),          # a colored sidebar
    "D4": ("Column", "Major"),           # two or more columns
    "D5": ("Icon", "Minor"),             # icons for contact details
    "D6": ("Box / table", "Major"),      # text in shapes, boxes or tables
    "D7": ("Font", "Minor"),             # too many fonts, decorative fonts, very small text
    "D8": ("Low contrast", "Minor"),     # light text on a colored background / low contrast
    "D9": ("Only in sidebar", "Major"),  # contact details or skills only inside a sidebar
    "D10": ("Reading order", "Major"),   # reading order scrambled
    "D11": ("Pages", "Minor"),           # page count too high for the experience (decided in cv_score)
    "D12": ("Landscape page", "Major"),  # a landscape (wide) page: an ATS reads it as one very long line
    "D13": ("Image page", "Major"),      # a page that is an image (or mostly one): an ATS reads nothing on it
}
IMAGE_PAGE_SHARE = 0.5         # an image covering half of the page or more ...
IMAGE_PAGE_WORDS = 50          # ... with fewer words of real text than this: an image page
SMALL_PT = 9.0                 # text under 9 pt is too small
SMALL_SHARE = 0.25             # more than a quarter of the text that small -> flag
MAX_FAMILIES = 3
DECORATIVE_RE = re.compile(r"script|hand|brush|comic|pacifico|lobster|dancing|vibes|satisfy|signature|calligra|"
                           r"papyrus|curlz|chiller|jokerman|playball|parisienne|allura|sacramento|caveat|kaushan", re.I)
STYLE_RE = re.compile(r"[-,_ ]?(Bold|Italic|Oblique|Regular|Light|Medium|Semi[Bb]old|Demi[Bb]old|Extra[Bb]old|Black|"
                      r"Heavy|Thin|Condensed|Cond|Narrow|MT|PS|PSMT|Roman|Book|It|Bd|BoldItalic|BoldOblique)$")
LOW_CONTRAST = 3.0             # WCAG minimum for large text
RENDER_DPI = 100               # page images shown in the dashboard
CONTRAST_DPI = 150             # pixels used to measure text contrast
PHOTO_MIN_PT = 40              # an image at least 40 x 40 pt is a photo / picture, smaller ones are icons
ICON_MAX_PT = 30
MIN_COLUMN_SHARE = 0.06       # a column holds at least 6% of the words (a sparse contact / skills sidebar)
MIN_COLUMN_LINES = 4           # the right side of a column cut has text on at least 4 lines
MIN_COLUMN_GAP = 10            # pt between two columns on the same line (a word space is about 3 pt)
MIN_REGION_HEIGHT = 0.20       # a column runs down at least 20% of the page (a 'Title ... Dates' line is no column)
SHORT_REGION_HEIGHT = 0.08     # ... on a page that has columns, shorter two-column blocks are read side by side too
LANDSCAPE_RATIO = 1.05         # page wider than tall
COLORS = {"Major": (217, 119, 6), "Minor": (100, 116, 139)}
# Running headers / footers: page numbers, "(continued)", the name or contact line repeated on later pages.
# They are never jobs, headings, dates or font problems.
BAND = 0.09                    # the top / bottom 9% of a page is the header / footer area
PAGE_NUM_RE = re.compile(r"^\s*(?:page\s*[|:\-]?\s*\d+(?:\s*(?:of|/)\s*\d+)?|\d+\s*(?:of|/)\s*\d+|[-\u2013]\s*\d+\s*"
                         r"[-\u2013]|\d{1,3})\s*$", re.I)
CONTINUED_RE = re.compile(r"\(\s*continued\s*\)|\bcont(?:inued|'d)\b", re.I)
SHADE_BAR_H = (6, 40)            # a shading bar behind one or two lines of text (pt high)
SHADE_BAR_W = 0.35             # ... at least 35% of the page wide
SHADE_MIN = 200                # a fill lighter than this (every RGB channel) is background shading, not a box
HEADING_WORDS_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in L.STANDARD_HEADING_WORDS) + r")", re.I)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _lum(rgb):
    def ch(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def is_whiteish(rgb):
    return min(rgb[:3]) >= 240


def _box(obj):
    return (obj["x0"], obj["top"], obj["x1"], obj["bottom"])


def _inside(w, box, pad=1):
    return w["x0"] >= box[0] - pad and w["x1"] <= box[2] + pad and w["top"] >= box[1] - pad and w["bottom"] <= box[3] + pad


def _area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def page_crop(page, box):
    """page.crop for any box: clamped to the page's own area and never strict. A page does not always start at
    (0, 0): some PDFs have a shifted mediabox / cropbox (e.g. top = -7.8), and a box built from 0 would not fit."""
    px0, ptop, px1, pbottom = page.bbox
    x0, top = min(max(box[0], px0), px1), min(max(box[1], ptop), pbottom)
    x1, bottom = max(x0, min(box[2], px1)), max(top, min(box[3], pbottom))
    return page.crop((x0, top, x1, bottom), strict=False)


def _main_color(img, box, scale, origin=(0, 0)):
    """Most frequent color of the rendered page inside box (pt). origin: the page's top-left corner (pt), which is
    the image's (0, 0)."""
    x0, y0, x1, y1 = (int((v - origin[k % 2]) * scale) for k, v in enumerate(box))
    crop = img.crop((max(0, x0), max(0, y0), max(x0 + 1, x1), max(y0 + 1, y1)))
    colors = crop.getcolors(maxcolors=crop.width * crop.height + 1) or [(1, (255, 255, 255))]
    return max(colors)[1]


def family(fontname):
    name = fontname.split("+")[-1]
    prev = None
    while prev != name:
        prev, name = name, STYLE_RE.sub("", name)
    return name.lower()


def is_contact_line(text):
    """Email, LinkedIn, or a phone number (9+ digits, not a date range like '2023 - 2025')."""
    t = text.strip()
    if L.EMAIL_RE.search(t) or re.search(r"linkedin", t, re.I):
        return True
    m = L.PHONE_RE.search(t)
    return bool(m) and len(re.sub(r"\D", "", m.group(1))) >= 9 and not L.RANGE_RE.search(m.group(1))


def heading_like(line):
    """A section heading in either reading: the v3 rule, or a short line made of a standard heading word."""
    l = line.strip().rstrip(":")
    if not l or len(l) > 40 or re.search(r"\d|@|[.,;|]", l):
        return False
    return L.is_heading(l) or (len(l.split()) <= 3 and bool(HEADING_WORDS_RE.match(l)) and l[:1].isupper())


def nospace(text):
    return re.sub(r"\s+", "", text or "").lower()


def in_band(top, bottom, height, origin=0):
    """In the header / footer area of a page `height` tall whose top is at `origin` (not always 0)."""
    return top - origin < BAND * height or bottom - origin > (1 - BAND) * height


def find_running(pdf):
    """-> {page number: set of line texts (no spaces, lower case)} that are running headers / footers."""
    pages = [pg.extract_text_lines() for pg in pdf.pages]
    first = nospace(pages[0][0]["text"]) if pages and pages[0] else ""
    run, seen = {}, {}
    for pno, (pg, lines) in enumerate(zip(pdf.pages, pages)):
        for ln in lines:
            if not in_band(ln["top"], ln["bottom"], pg.height, pg.bbox[1]):
                continue
            t, k = ln["text"].strip(), nospace(ln["text"])
            top = ln["top"] - pg.bbox[1] < BAND * pg.height
            seen.setdefault(re.sub(r"\d", "", k), set()).add(pno)
            if PAGE_NUM_RE.match(t) or (pno > 0 and top and (CONTINUED_RE.search(t) or is_contact_line(t)
                                                              or (first and k.startswith(first[:12])))):
                run.setdefault(pno, set()).add(k)
    for pno, (pg, lines) in enumerate(zip(pdf.pages, pages)):     # the same line in the header / footer area of
        for ln in lines:                                            # 2+ pages (not the real name on page 1)
            k = nospace(ln["text"])
            top = ln["top"] - pg.bbox[1] < BAND * pg.height
            if in_band(ln["top"], ln["bottom"], pg.height, pg.bbox[1]) and len(seen.get(re.sub(r"\d", "", k), ())) >= 2 \
                    and not (pno == 0 and top):
                run.setdefault(pno, set()).add(k)
    return run


def extract_clean(pdf_path, running, pages=None):
    """Like ATSLab_v3.extract_cv, without the running header / footer lines (pages: only these, 0-based)."""
    return cv_cache.cached("clean", pdf_path, (str(sorted((k, sorted(v)) for k, v in running.items())),
                                               None if pages is None else tuple(sorted(pages))),
                           lambda: _extract_clean(pdf_path, running, pages))


def _extract_clean(pdf_path, running, pages=None):
    strict, modern, rows = [], [], []
    keep = lambda pno, text: nospace(text) not in running.get(pno, set())
    with cv_cache.open_pdf(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages):
            if pages is not None and pno not in pages:
                continue
            for out, tol in ((strict, 1), (modern, 3)):
                out.append("\n".join(l for l in (page.extract_text(x_tolerance=tol) or "").splitlines() if keep(pno, l)))
            rows += [r for r in L.page_rows(page, pno) if keep(pno, r["text"])]
    return {"strict": "\n".join(strict), "modern": "\n".join(modern), "rows": rows}


WORD_GAP = 1.8              # a gap this many times the usual letter gap (or a space) ends a word


def spaced_line_text(pdf_path, row):
    """A letter-spaced line ('S A N A M A L I K , P M P ®') read again from its letters: the words come back where
    the PDF has a space or a gap clearly wider than the gaps between letters -> 'SANA MALIK, PMP®'. None when the
    line cannot be read again."""
    if not all(k in row for k in ("page", "top", "bottom", "x0", "x1")):
        return None
    with cv_cache.open_pdf(pdf_path) as pdf:
        if row["page"] >= len(pdf.pages):
            return None
        chars = sorted((c for c in pdf.pages[row["page"]].chars
                        if row["top"] - 1 <= (c["top"] + c["bottom"]) / 2 <= row["bottom"] + 1
                        and row["x0"] - 1 <= c["x0"] <= row["x1"] + 1), key=lambda c: c["x0"])
    ink = [c for c in chars if c["text"].strip()]
    if len(ink) < 2:
        return None
    gaps = sorted(b["x0"] - a["x1"] for a, b in zip(ink, ink[1:]))
    letter = max(gaps[len(gaps) // 2], 0.0)                  # the median gap: the gap between two letters
    out, prev = "", None
    for c in chars:
        if not c["text"].strip():
            out += " "
        else:
            if prev is not None and c["x0"] - prev["x1"] > WORD_GAP * letter + 1.0:
                out += " "
            out += c["text"]
            prev = c
    return re.sub(r"\s+", " ", out).strip() or None


SKIPPED_NOTE = ("Page{s} {pages} could not be read for the layout checks, so those checks were skipped there; every "
                "other check ran.")


class PageRenderer:
    """Page images for one PDF: the document is opened ONCE and always closed (also when a check fails), so no
    file handle is left open (on Windows an open handle stops the dashboard from deleting its temp file).
    Same rendering as pdfplumber's page.to_image(...).original."""

    NOTE = ("The page images could not be made on this computer, so the colour and contrast checks were skipped; "
            "every other check ran.")

    def __init__(self, pdf_path):
        self.failed = False
        try:
            self.doc = pypdfium2.PdfDocument(pdf_path)
        except Exception:                       # e.g. OSError [WinError -1073741795]: an unsupported CPU instruction
            self.doc, self.failed = None, True

    def image(self, page_ix, resolution, size=None):
        """The page as an RGB image; a plain white page (no colours to check) when it cannot be rendered."""
        if self.doc is not None:
            try:
                return self._render(page_ix, resolution)
            except Exception:
                self.failed = True
        from PIL import Image
        w, h = size or (612, 792)
        return Image.new("RGB", (max(1, int(w * resolution / 72)), max(1, int(h * resolution / 72))), "white")

    def _render(self, page_ix, resolution):
        page = self.doc[page_ix]
        try:
            bitmap = page.render(scale=resolution / 72, no_smoothtext=True, no_smoothpath=True,
                                 no_smoothimage=True, prefer_bgrx=True)
            try:
                return bitmap.to_pil().convert("RGB")
            finally:
                bitmap.close()
        finally:
            page.close()

    def close(self):
        if self.doc is not None:
            self.doc.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _norm(s):
    return re.sub(r"\s+", " ", s.strip().lower())


# ---------------------------------------------------------------------------
# columns
# ---------------------------------------------------------------------------
def _vertical_cut(ws, box, page_h, min_h=MIN_REGION_HEIGHT):
    """Where a region splits into two columns: an x almost no word crosses (a few allowed, e.g. a wide name), a
    real gap on every shared line, text on both sides down most of the region, and the right side starting at one
    edge. -> x or None."""
    x0, y0, x1, y1 = box
    if len(ws) < 12 or (y1 - y0) < min_h * page_h:
        return None
    # a few words may cross a tall column gap (a wide name); a short block is only cut where nothing crosses
    allowed = max(2, 0.02 * len(ws)) if (y1 - y0) >= MIN_REGION_HEIGHT * page_h else 0
    best, run = None, []
    for x in range(int(x0) + 4, int(x1) - 4, 2):
        if sum(1 for w in ws if w["x0"] < x < w["x1"]) > allowed:
            run = []
            continue
        run.append(x)
        left = [w for w in ws if w["x1"] <= x]
        right = [w for w in ws if w["x0"] >= x]
        if len(left) < max(4, MIN_COLUMN_SHARE * len(ws)) or len(right) < max(4, MIN_COLUMN_SHARE * len(ws)):
            continue
        if any(all(re.fullmatch(r"[\W_]{1,3}", w["text"]) for w in part) for part in (left, right)):
            continue                                       # a column of bullet symbols is the bullets of a list
        span = lambda part: max(w["bottom"] for w in part) - min(w["top"] for w in part)
        # both sides run down most of the region; a shorter column (a last column with one job) only when no word
        # at all crosses the gap
        need = 0.35 if any(w["x0"] < x < w["x1"] for w in ws) else 0.12
        if span(left) < need * (y1 - y0) or span(right) < need * (y1 - y0):
            continue
        rows = {}
        for w in ws:
            rows.setdefault(round(w["top"] / 3), []).append(w)
        gaps, starts = [], []
        for line in rows.values():
            l_ = [w for w in line if w["x1"] <= x]
            r_ = [w for w in line if w["x0"] >= x]
            if r_:
                starts.append(min(w["x0"] for w in r_))
            if l_ and r_:
                gaps.append(min(w["x0"] for w in r_) - max(w["x1"] for w in l_))
        if gaps and min(gaps) < MIN_COLUMN_GAP:
            continue
        if min_h >= MIN_REGION_HEIGHT and len(starts) < MIN_COLUMN_LINES:
            continue                                       # a few line ends past a gap are not a column
        edge = sorted(starts)[len(starts) // 2] if starts else 0
        if sum(1 for st in starts if abs(st - edge) <= 6) < 0.5 * len(starts):
            continue
        width = len(run)                                  # prefer the widest empty channel
        if best is None or width > best[1]:
            best = (x - (len(run) - 1), width, x)
    if best is None:
        return None
    first, _, last = best                                  # the middle of the empty channel found
    return (first + last) / 2


def _horizontal_cuts(ws, box, widest_only=False):
    """y positions of the clear horizontal gaps (wider than a normal line gap) across the whole region.
    widest_only: only the widest gap(s), then recurse (used on pages that have columns, so loose line spacing does
    not slice a two-column zone into thin bands)."""
    tops = sorted((w["top"], w["bottom"]) for w in ws)
    heights = sorted(b - t for t, b in tops)
    line_h = heights[len(heights) // 2] if heights else 10
    gaps, reach = [], None
    for t, b in tops:
        if reach is not None and t - reach > max(4.0, 0.6 * line_h):
            gaps.append((t - reach, (reach + t) / 2))
        reach = b if reach is None else max(reach, b)
    if not gaps:
        return []
    if not widest_only:
        return [y for _, y in gaps]
    widest = max(g for g, _ in gaps)
    return [y for g, y in gaps if g >= 0.85 * widest]


def xy_regions(words, box, page_h, depth=0, min_h=MIN_REGION_HEIGHT):
    """-> [(x0, top, x1, bottom), ...] the text regions in reading order: a region with columns is read column by
    column (left to right, each top to bottom); a column made of bands is read band by band."""
    mid = lambda w: ((w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2)     # a word belongs where its middle is
    ws = [w for w in words if box[0] <= mid(w)[0] <= box[2] and box[1] <= mid(w)[1] <= box[3]]
    if not ws or depth > 30:
        return ([box], 1) if ws else ([], 0)
    # the words' box, never past the cut lines (a word crossing a column gap must not pull in the next column)
    tight = (max(box[0], min(w["x0"] for w in ws)), max(box[1], min(w["top"] for w in ws)),
             min(box[2], max(w["x1"] for w in ws)), min(box[3], max(w["bottom"] for w in ws)))
    x = _vertical_cut(ws, tight, page_h, min_h)
    if x is not None:
        # words crossing the gap all in a top (or bottom) band, e.g. a full-width headline: cut that band off first
        crossing = [w for w in ws if w["x0"] < x < w["x1"]]
        if crossing:
            cuts = _horizontal_cuts(ws, tight)              # the nearest gap below the headline
            low, high = max(w["bottom"] for w in crossing), min(w["top"] for w in crossing)
            y = next((c for c in cuts if c > low), None) if low < (tight[1] + tight[3]) / 2 else \
                next((c for c in reversed(cuts) if c < high), None)
            if y is not None:
                top, nt = xy_regions(ws, (tight[0], tight[1], tight[2], y), page_h, depth + 1, min_h)
                bottom, nb = xy_regions(ws, (tight[0], y, tight[2], tight[3]), page_h, depth + 1, min_h)
                if max(nt, nb) > 1:
                    return top + bottom, max(nt, nb)
    if x is not None:                                       # columns side by side: their counts add up
        left, nl = xy_regions(ws, (tight[0], tight[1], x, tight[3]), page_h, depth + 1, min_h)
        right, nr = xy_regions(ws, (x, tight[1], tight[2], tight[3]), page_h, depth + 1, min_h)
        return left + right, nl + nr
    cuts = _horizontal_cuts(ws, tight, min_h < MIN_REGION_HEIGHT)
    bands, top = [], tight[1]
    for c in cuts + [tight[3] + 1]:
        bands.append((tight[0], top, tight[2], min(c, tight[3])))
        top = c
    parts = [xy_regions(ws, b, page_h, depth + 1, min_h) for b in bands] if cuts else []
    if not any(n > 1 for _, n in parts):                    # no band has columns: read this region as one block
        return [tight], 1
    return [r for regs, _ in parts for r in regs], max(n for _, n in parts)


def find_regions(words, width, height, origin=(0, 0)):
    """Column-aware reading of one page. -> (regions in reading order, number of columns side by side). Without any
    column on the page: one region (the whole page), so a single-column page is read exactly as before.
    origin: the page's top-left corner (page.bbox), which is not always (0, 0)."""
    page = (origin[0], origin[1], origin[0] + width, origin[1] + height)
    if len(words) < 30:
        return [page], 1
    regions, n = xy_regions(words, page, height)
    if n < 2:
        return [page], 1
    # the page has columns: read it again allowing shorter column blocks too (a two-column zone that a gap across
    # both columns splits into bands); never on a single-column page, so a short skills grid there stays as it is
    regions = xy_regions(words, page, height, min_h=SHORT_REGION_HEIGHT)[0]
    pad = [(max(page[0], a[0] - 1), max(page[1], a[1] - 1), min(page[2], a[2] + 1), min(page[3], a[3] + 1))
           for a in regions]
    return pad, n


# words that make up resume headings, to put a letter-spaced heading back together ('C R E AT I V E S K I L L S'
# -> 'CREATIVE SKILLS'); longest words first
HEADING_PARTS = sorted("""about accomplishments achievements additional affiliations awards career certificates
certifications certification competencies contact core courses creative details education employment experience
expertise history hobbies info information interests key languages language links me memberships objective personal
portfolio professional profile projects publications qualifications references relevant selected skills skill
social software summary technical tools training volunteering volunteer work and""".split(), key=len, reverse=True)


def unspace_heading(line):
    """'E D U C AT I O N' -> 'EDUCATION', 'C O R E S K I L L S' -> 'CORE SKILLS' (letters joined, then split into
    heading words when they all are). Other lines are returned unchanged."""
    toks = line.split()
    if not (L.SPACED_RE.search(line) or (len(toks) >= 3 and all(len(t) <= 2 for t in toks)
                                         and sum(len(t) == 1 for t in toks) >= 0.7 * len(toks))):
        return line
    flat = re.sub(r"\s+", "", line)
    words, rest = [], flat.lower()
    while rest:
        w = next((h for h in HEADING_PARTS if rest.startswith(h)), None)
        if not w:
            return re.sub(r"(?<=\S) (?=\S)", "", line) if re.fullmatch(r"(?:\S ?)+", line.strip()) else line
        words.append(flat[len(flat) - len(rest): len(flat) - len(rest) + len(w)])
        rest = rest[len(w):]
    return " ".join(words)


def repair_heading(line):
    """'PROFI LE' -> 'PROFILE', 'CRE AT I VE SKI LLS' -> 'CREATIVE SKILLS', 'I N FO' -> 'INFO': a heading broken into
    pieces by wide kerning is put back together when its letters make heading words. Other lines are unchanged."""
    t = line.strip()
    if not re.fullmatch(r"[A-Z][A-Z ]{3,44}", t):
        return line
    flat, words = t.replace(" ", ""), []
    rest = flat.lower()
    while rest:
        w = next((h for h in HEADING_PARTS if rest.startswith(h)), None)
        if not w:
            return line
        words.append(flat[len(flat) - len(rest): len(flat) - len(rest) + len(w)])
        rest = rest[len(w):]
    return " ".join(words)


def find_text_version(pdf_path):
    return cv_cache.cached("split", pdf_path, (), lambda: _find_text_version(pdf_path))


def _find_text_version(pdf_path):
    """A PDF with a designed version (pages with columns or a big image) followed by a text version of the same
    resume (plain pages that start again with the contact line and a section heading).
    -> {"start": first page of the text version, "designed": [page numbers before it]} (0-based) or None."""
    info = []
    with cv_cache.open_pdf(pdf_path) as pdf:
        n = len(pdf.pages)
        if n < 2:
            return None
        for page in pdf.pages:
            W, H = page.width, page.height
            words = page.extract_words()
            try:
                n_cols = find_regions(words, W, H, page.bbox[:2])[1] if len(words) >= 30 else 1
            except Exception:
                n_cols = 1
            image = max([(im["x1"] - im["x0"]) * (im["bottom"] - im["top"]) for im in page.images] or [0]) / (W * H)
            lines = [l.strip() for l in (page.extract_text() or "").splitlines() if l.strip()][:8]
            info.append({"designed": n_cols > 1 or image >= 0.5 or (len(words) < 5 and bool(page.images)),
                         "email": any(L.EMAIL_RE.search(l) for l in lines[:5]),
                         "image_page": image >= 0.5,
                         "summary": any(SUMMARY_START_RE.match(l) for l in lines)})
    # the text version starts again with the contact line and a Summary; the pages before it are designed
    for k in range(1, n):
        if info[k]["email"] and info[k]["summary"] and not info[k]["designed"] \
                and not any(i["image_page"] for i in info[k:]) and any(i["designed"] for i in info[:k]):
            return {"start": k, "designed": list(range(k)), "pages": n}
    return None


SUMMARY_START_RE = re.compile(r"(?i)^\W*(?:\d+\W*)?(?:professional |executive |career |personal )?"
                              r"(?:summary|profile|objective)\b")


def find_columns(words, width, height):
    """-> list of (x0, x1) column bands. A split needs a vertical gap no word crosses (a few allowed, e.g. a
    full-width name), real text on both sides, and both sides covering at least 35% of the page height."""
    if len(words) < 30:
        return [(0, width)]
    ok = []
    for x in range(int(width * 0.18), int(width * 0.82), 2):
        cross = sum(1 for w in words if w["x0"] < x < w["x1"])
        if cross > max(2, 0.02 * len(words)):
            continue
        left = [w for w in words if w["x1"] <= x]
        right = [w for w in words if w["x0"] >= x]
        if len(left) < MIN_COLUMN_SHARE * len(words) or len(right) < MIN_COLUMN_SHARE * len(words):
            continue
        span = lambda ws: max(w["bottom"] for w in ws) - min(w["top"] for w in ws)
        if span(left) < 0.35 * height or span(right) < 0.35 * height:
            continue
        # a real column gap, not a word space: on lines with text on both sides the sides are far apart,
        # and the right-hand lines start at the same place (a column edge), unlike a ragged right margin
        rows = {}
        for w in words:
            rows.setdefault(round(w["top"] / 3), []).append(w)
        gaps, starts = [], []
        for ws in rows.values():
            l_ = [w for w in ws if w["x1"] <= x]
            r_ = [w for w in ws if w["x0"] >= x]
            if r_:
                starts.append(min(w["x0"] for w in r_))
            if l_ and r_:
                gaps.append(min(w["x0"] for w in r_) - max(w["x1"] for w in l_))
        if gaps and min(gaps) < MIN_COLUMN_GAP:
            continue
        if min_h >= MIN_REGION_HEIGHT and len(starts) < MIN_COLUMN_LINES:
            continue                                       # a few line ends past a gap are not a column
        edge = sorted(starts)[len(starts) // 2] if starts else 0
        if sum(1 for s in starts if abs(s - edge) <= 6) < 0.5 * len(starts):
            continue
        ok.append(x)
    if not ok:
        return [(0, width)]
    groups, cur = [], [ok[0]]
    for x in ok[1:]:
        if x - cur[-1] <= 2:
            cur.append(x)
        else:
            groups.append(cur)
            cur = [x]
    groups.append(cur)
    best = max(groups, key=len)
    split = (best[0] + best[-1]) / 2
    return [(0, split), (split, width)]


# ---------------------------------------------------------------------------
# the analysis
# ---------------------------------------------------------------------------
def _finding(fid):
    return {"id": fid, "label": DESIGN[fid][0], "severity": DESIGN[fid][1], "found": False, "detail": "",
            "evidence": [], "boxes": []}


BULLET_GLYPH_RE = re.compile(r"(?:\(cid:\d+\))+|[-•▪●◦‣·]+")


def analyse_layout(pdf_path, doc=None, pages=None):
    """-> {"pages", "columns_found", "visual_doc", "findings": {id: finding}, "reading": {...}}.
    pages: only these page numbers (0-based), e.g. the text version of a two-version file.
    Kept by the file's fingerprint (cv_cache): the same file's layout is analysed once."""
    if doc is not None:
        return _analyse_layout(pdf_path, doc, pages)
    return cv_cache.cached("layout", pdf_path, (None if pages is None else tuple(sorted(pages)),),
                           lambda: _analyse_layout(pdf_path, doc, pages))


def _analyse_layout(pdf_path, doc=None, pages=None):
    f = {k: _finding(k) for k in DESIGN}
    vis_rows, vis_text, ext_lines = [], [], []
    families, decorative, sizes, small_lines = {}, set(), [], []
    low_words, light_on_color = [], []
    contact_words, skills_heads = [], []
    sidebars, image_pages, skipped = [], [], []
    columns_any = False
    n_columns, landscape = 1, False
    with cv_cache.open_pdf(pdf_path) as pdf, PageRenderer(pdf_path) as render:
        n_pages = len(pdf.pages) if pages is None else len([p for p in range(len(pdf.pages)) if p in pages])
        running = find_running(pdf)
        for pno, page in enumerate(pdf.pages):
            if pages is not None and pno not in pages:
                continue
            try:
                runs = running.get(pno, set())
                W, H = page.width, page.height
                ox, oy = page.bbox[0], page.bbox[1]        # the page's own top-left corner: not always (0, 0)
                page_area = W * H
                words = page.extract_words(extra_attrs=["fontname", "size"])
                img = render.image(pno, 72, (W, H))
                hi = render.image(pno, CONTRAST_DPI, (W, H))
                s_hi = CONTRAST_DPI / 72

                # landscape page
                if W > LANDSCAPE_RATIO * H:
                    landscape = True
                    f["D12"]["found"] = True
                    f["D12"]["evidence"].append(f"Page {pno + 1} is landscape ({W:.0f} x {H:.0f} pt)")
                # columns + the page view (column by column, each top to bottom, left to right)
                cols, n = find_regions(words, W, H, (ox, oy))
                if len(cols) > 1:
                    columns_any = True
                    n_columns = max(n_columns, n)
                    f["D4"]["found"] = True
                    for i, (x0, y0, x1, y1) in enumerate(cols, 1):
                        f["D4"]["boxes"].append((pno, x0 + 2, y0 + 2, x1 - 2, y1 - 2, f"Column {i}"))
                        first = (page_crop(page, (x0, y0, x1, y1)).extract_text() or "").strip().splitlines()[:1]
                        if first and len(f["D4"]["evidence"]) < 4:
                            f["D4"]["evidence"].append(f"Part {i} starts with: \"{first[0]}\"")
                for x0, y0, x1, y1 in cols:
                    crop = page_crop(page, (x0, y0, x1, y1))
                    vis_rows += [r for r in L.page_rows(crop, pno) if nospace(r["text"]) not in runs]
                    vis_text.append("\n".join(l for l in (crop.extract_text(x_tolerance=3) or "").splitlines()
                                              if nospace(l) not in runs))

                # filled shapes: sidebar / colored panels (color from the rendered page)
                fills = [r for r in page.rects + page.curves if r.get("fill") and _area(_box(r)) > 0.02 * page_area]
                for r in fills:
                    box = _box(r)
                    color = _main_color(img, box, 1.0, (ox, oy))
                    if is_whiteish(color):
                        continue
                    w, h = box[2] - box[0], box[3] - box[1]
                    edge = box[0] - ox <= 0.05 * W or box[2] - ox >= 0.95 * W
                    inside = [x for x in words if _inside(x, box)]
                    quote = " ".join(x["text"] for x in inside[:14])
                    if h >= 0.6 * H and 0.12 * W <= w <= 0.45 * W and edge:
                        f["D3"]["found"] = True
                        f["D3"]["boxes"].append((pno, *box, "Sidebar"))
                        sidebars.append((pno, box))
                        if quote:
                            f["D3"]["evidence"].append(f"Text in the sidebar: \"{quote}\"")
                    elif _area(box) < 0.95 * page_area or not is_whiteish(color):
                        f["D2"]["found"] = True
                        f["D2"]["boxes"].append((pno, *box, "Colored panel"))
                        if quote:
                            f["D2"]["evidence"].append(f"Text on a colored panel: \"{quote}\"")

                # light shading bars behind lines of text (gray bars behind job titles): a Minor colored-background issue
                for r in page.rects:
                    box = _box(r)
                    w, h = box[2] - box[0], box[3] - box[1]
                    if not r.get("fill") or r.get("stroke") or not (SHADE_BAR_H[0] <= h <= SHADE_BAR_H[1])                         or w < SHADE_BAR_W * W:
                        continue
                    color = _main_color(img, box, 1.0, (ox, oy))
                    inside = [x for x in words if _inside(x, box)]
                    if min(color[:3]) >= 252 or not inside:
                        continue                                   # white, or an empty bar (a rule)
                    f["D2"]["found"] = True
                    f["D2"]["boxes"].append((pno, *box, "Shading"))
                    if len(f["D2"]["evidence"]) < 4:
                        f["D2"]["evidence"].append(f"Shading behind: \"{' '.join(x['text'] for x in inside[:14])}\"")

                # photo / images and icons
                icons = [im for im in page.images if im["width"] <= ICON_MAX_PT and im["height"] <= ICON_MAX_PT]
                icons += [c for c in page.curves if c.get("fill") and (c["x1"] - c["x0"]) <= ICON_MAX_PT
                          and (c["bottom"] - c["top"]) <= ICON_MAX_PT]
                big = max([_area(_box(im)) for im in page.images] or [0]) / page_area
                if big >= IMAGE_PAGE_SHARE and len(words) < IMAGE_PAGE_WORDS:
                    image_pages.append(pno)
                    f["D13"]["found"] = True
                    f["D13"]["boxes"].append((pno, *page.bbox, "Image page"))
                    f["D13"]["evidence"].append(f"Page {pno + 1} is an image: an ATS reads no text on it")
                for im in page.images:
                    if image_pages and image_pages[-1] == pno:
                        break                                      # the whole page is the image: said once, above
                    if im["width"] >= PHOTO_MIN_PT and im["height"] >= PHOTO_MIN_PT:
                        f["D1"]["found"] = True
                        f["D1"]["boxes"].append((pno, *_box(im), "Photo"))
                        near = [x["text"] for x in words if abs(x["top"] - im["bottom"]) < 40 and x["x0"] < im["x1"]
                                and x["x1"] > im["x0"]][:6]
                        f["D1"]["evidence"].append(f"Image of {im['width']:.0f} x {im['height']:.0f} pt on page {pno + 1}"
                                                   + (f", above \"{' '.join(near)}\"" if near else ""))

                # the ATS reads whole lines across the page (columns mixed): that is the reading order
                for ln in page.extract_text_lines():
                    if nospace(ln["text"]) in runs:
                        continue
                    ext_lines.append({"page": pno, "text": ln["text"].strip(), "x0": ln["x0"], "x1": ln["x1"],
                                      "top": ln["top"], "col": next((i for i, (a, t, b, u) in enumerate(cols)
                                                                     if a - 1 <= ln["x0"] < b and t - 1 <= ln["top"] < u),
                                                                    0)})
                # contact words, icons, skills headings and fonts: read inside each column (lines not mixed)
                lines = [ln for x0, y0, x1, y1 in cols
                         for ln in page_crop(page, (x0, y0, x1, y1)).extract_text_lines(return_chars=True)]
                for ln in lines:
                    if nospace(ln["text"]) in runs:
                        continue
                    place = L.is_place(ln["text"].strip())          # a location line can carry an icon too
                    if is_contact_line(ln["text"]):
                        contact_words.append((pno, (ln["x0"], ln["top"], ln["x1"], ln["bottom"]), ln["text"].strip()))
                    if is_contact_line(ln["text"]) or place:
                        parts = [ic for ic in icons if ln["top"] - 6 <= (ic["top"] + ic["bottom"]) / 2 <= ln["bottom"] + 6
                                 and -45 <= ln["x0"] - ic["x1"] <= 45 and ic["x0"] < ln["x0"]]
                        if parts:                             # an icon is often several small shapes: one box per line
                            f["D5"]["found"] = True
                            f["D5"]["boxes"].append((pno, min(i["x0"] for i in parts), min(i["top"] for i in parts),
                                                     max(i["x1"] for i in parts), max(i["bottom"] for i in parts), "Icon"))
                            f["D5"]["evidence"].append(f"Icon before \"{ln['text'].strip()}\"")
                    if heading_like(ln["text"]) and re.search(r"skill|competenc", ln["text"], re.I):
                        skills_heads.append((pno, (ln["x0"], ln["top"], ln["x1"], ln["bottom"]), ln["text"].strip()))
                    # fonts and sizes (never in the header / footer area: page numbers, running headers)
                    if in_band(ln["top"], ln["bottom"], H, oy):
                        continue
                    chars = [c for c in ln["chars"] if c["text"].strip()]
                    for c in chars:
                        fam = family(c["fontname"])
                        families[fam] = families.get(fam, 0) + 1
                        if DECORATIVE_RE.search(c["fontname"]):
                            decorative.add(c["fontname"].split("+")[-1])
                        sizes.append(c["size"])
                    if chars and sum(c["size"] for c in chars) / len(chars) < SMALL_PT:
                        small_lines.append((sum(c["size"] for c in chars) / len(chars), ln["text"].strip()))

                # text in boxes and tables (not the page background, sidebars or colored panels)
                big_fills = [b[1:5] for b in f["D3"]["boxes"] + f["D2"]["boxes"] if b[0] == pno]
                for r in page.rects:
                    box = _box(r)
                    if _area(box) < 600 or _area(box) > 0.9 * page_area or any(_area(box) >= 0.8 * _area(b) and
                                                                             _inside(r, b, 3) for b in big_fills):
                        continue
                    inside = [x for x in words if _inside(x, box)]
                    color = _main_color(img, box, 1.0, (ox, oy))
                    shading = r.get("fill") and not r.get("stroke") and min(color[:3]) >= SHADE_MIN
                    # a light background color behind normal text is shading, not a text box
                    if len(inside) >= 3 and not shading and (r.get("stroke") or not is_whiteish(color)):
                        f["D6"]["found"] = True
                        f["D6"]["boxes"].append((pno, *box, "Box"))
                        box_lines = [l for l in (page_crop(page, box).extract_text() or "").splitlines() if l.strip()][:2]
                        f["D6"]["evidence"].append("Text in a box: \"" + " / ".join(box_lines) + "\"")
                try:
                    tables = page.find_tables()
                except Exception:
                    tables = []
                ruled = [l for l in page.lines] + [r for r in page.rects if r.get("stroke")]
                for t in tables:
                    rows = [[(c or "").strip() for c in row] for row in t.extract()]
                    rows = [r for r in rows if any(r)]
                    x0, y0, x1, y1 = t.bbox                        # a real table has drawn lines, not just shading
                    lines_in = [l for l in ruled if l["x0"] >= x0 - 2 and l["x1"] <= x1 + 2 and l["top"] >= y0 - 2
                                and l["bottom"] <= y1 + 2]
                    if len(rows) >= 2 and max(len(r) for r in rows) >= 2 and len(lines_in) >= 3:
                        f["D6"]["found"] = True
                        f["D6"]["boxes"].append((pno, *t.bbox, "Table"))
                        f["D6"]["evidence"].append("Table row: \"" + " | ".join(c for c in rows[0] if c) + "\"")

                # contrast, measured on the rendered page
                for w in words:
                    box = (w["x0"], w["top"], w["x1"], w["bottom"])
                    if in_band(w["top"], w["bottom"], H, oy) or BULLET_GLYPH_RE.fullmatch(w["text"]):
                        continue                               # a bullet symbol is not text to read
                    x0, y0, x1, y1 = (int((v - (ox, oy)[k % 2]) * s_hi) for k, v in enumerate(box))
                    crop = hi.crop((max(0, x0), max(0, y0), max(x0 + 1, x1), max(y0 + 1, y1)))
                    cols_px = crop.getcolors(maxcolors=crop.width * crop.height + 1) or []
                    if not cols_px:
                        continue
                    bg = max(cols_px)[1]
                    fg = max(cols_px, key=lambda c: contrast(c[1], bg))[1]
                    ratio = contrast(fg, bg)
                    if ratio < LOW_CONTRAST:
                        low_words.append((pno, box, w["text"], ratio))
                    elif _lum(fg) > _lum(bg) and not is_whiteish(bg):
                        light_on_color.append((pno, box, w["text"]))

            except Exception:                  # never stop the check: skip this page's layout checks, say so
                skipped.append(pno + 1)
    # fonts
    total = sum(families.values()) or 1
    fams = [k for k, v in sorted(families.items(), key=lambda kv: -kv[1]) if v >= 0.01 * total]
    small = sum(1 for s in sizes if s < SMALL_PT) / max(1, len(sizes))
    reasons = []
    if len(fams) > MAX_FAMILIES:
        reasons.append(f"{len(fams)} different fonts ({', '.join(fams[:5])})")
    if decorative:
        reasons.append(f"decorative font: {', '.join(sorted(decorative))[:60]}")
    if small > SMALL_SHARE and small_lines:
        common = max(set(round(s) for s in sizes if s < SMALL_PT), key=lambda v: sum(1 for s in sizes if round(s) == v))
        reasons.append(f"{small:.0%} of the text is under {SMALL_PT:g} pt (mostly about {common} pt)")
    if reasons:
        f["D7"]["found"] = True
        f["D7"]["detail"] = "; ".join(reasons)
        f["D7"]["evidence"] = [f"{size:.1f} pt: \"{t}\"" for size, t in sorted(small_lines)[:2]] or [f["D7"]["detail"]]

    # contrast
    if len(low_words) + len(light_on_color) >= 5:
        f["D8"]["found"] = True
        for pno, box, t, *_ in (low_words + [(*x, 0) for x in light_on_color])[:40]:
            f["D8"]["boxes"].append((pno, *box, "Low contrast"))
        sample = [t for _, _, t, *_ in (low_words + [(*x, 0) for x in light_on_color])[:12]]
        f["D8"]["evidence"] = [f"Hard-to-read words: \"{' '.join(sample)}\""]

    # contact details / skills only in a sidebar (or a narrow side column)
    side = list(sidebars)
    if not side and columns_any:
        pass
    for pno, sbox in side:
        in_side = [c for c in contact_words if c[0] == pno and _inside({"x0": c[1][0], "x1": c[1][2], "top": c[1][1],
                                                                         "bottom": c[1][3]}, sbox, 4)]
        if contact_words and len(in_side) == len(contact_words):
            f["D9"]["found"] = True
            f["D9"]["evidence"] += [f"Contact only in the sidebar: \"{c[2]}\"" for c in in_side[:3]]
            for c in in_side:
                f["D9"]["boxes"].append((c[0], *c[1], "Contact in sidebar"))
        for s in skills_heads:
            if s[0] == pno and _inside({"x0": s[1][0], "x1": s[1][2], "top": s[1][1], "bottom": s[1][3]}, sbox, 4):
                f["D9"]["found"] = True
                f["D9"]["evidence"].append(f"Skills only in the sidebar: \"{s[2]}\"")
                f["D9"]["boxes"].append((s[0], *s[1], "Skills in sidebar"))

    # reading order: the order an ATS reads (top to bottom across the page) vs the page view (column by column)
    ext_order = list(ext_lines)                            # pdfplumber gives lines top to bottom per page
    visual = "\n".join(vis_text)
    ext_heads = [l["text"] for l in ext_order if heading_like(l["text"])]
    vis_heads = [l for l in visual.splitlines() if heading_like(l)]
    vrank = {}
    for i, h in enumerate(vis_heads):
        vrank.setdefault(_norm(h), i)
    seq = [vrank.get(_norm(h), -1) for h in ext_heads]
    keep = _lis([s for s in seq if s >= 0])
    out_of_order = []
    k = 0
    for h, s in zip(ext_heads, seq):
        if s >= 0 and k < len(keep) and s == keep[k]:
            k += 1
        elif s >= 0:
            out_of_order.append(h)
    switches = []
    for a, b in zip(ext_order, ext_order[1:]):
        if a["page"] == b["page"] and a["col"] != b["col"]:
            switches.append((a, b))
    if columns_any and (out_of_order or len(switches) >= 4):
        f["D10"]["found"] = True
        f["D10"]["detail"] = (f"{len(switches)} jumps between columns; "
                              + (f"out of order: {', '.join(out_of_order)}" if out_of_order else "headings in order"))
        if switches:
            a, b = switches[0] if len(switches) == 1 else switches[1]
            f["D10"]["evidence"].append(f"The ATS reads \"{a['text']}\" and then jumps to \"{b['text']}\"")
        for h in out_of_order[:2]:
            f["D10"]["evidence"].append(f"\"{h}\" is read at position {ext_heads.index(h) + 1}, but on the page it is "
                                        f"section {vrank[_norm(h)] + 1}")
    if f["D3"]["found"] and not columns_any:
        # a colored strip on a single-column resume is background shading, not a sidebar with its own text column
        f["D2"]["found"] = True
        f["D2"]["boxes"] += [(*b[:5], "Colored panel") for b in f["D3"]["boxes"]]
        f["D2"]["evidence"] += [e.replace("Text in the sidebar", "Text on a colored panel")
                                for e in f["D3"]["evidence"]]
        f["D3"].update(found=False, boxes=[], evidence=[], detail="")
        f["D9"].update(found=False, boxes=[], evidence=[], detail="")
    for k_, v in f.items():
        if v["found"] and not v["detail"]:
            v["detail"] = "; ".join(v["evidence"][:1]) or v["label"]
    if columns_any:                     # the page as a person reads it: letter-spaced headings read as words
        fix = lambda t: repair_heading(unspace_heading(t))
        visual = "\n".join(fix(l) for l in visual.splitlines())
        vis_rows = [dict(r, text=fix(r["text"]), cells=[fix(c) for c in r["cells"]]) for r in vis_rows]
    vdoc = {"strict": visual, "modern": visual, "rows": vis_rows}
    if f["D4"]["found"]:
        f["D4"]["detail"] = f"{n_columns} columns side by side" + (f"; {f['D4']['evidence'][0]}"
                                                                   if f["D4"]["evidence"] else "")
    notes = [PageRenderer.NOTE] if render.failed else []
    if skipped:
        notes.append(SKIPPED_NOTE.format(pages=", ".join(map(str, skipped)), s="s" if len(skipped) > 1 else ""))
    return {"notes": notes, "skipped_pages": skipped,
            "pages": n_pages, "columns_found": columns_any, "n_columns": n_columns if columns_any else 1,
            "landscape": landscape, "visual_doc": vdoc, "findings": f,
            "running": {k: sorted(v) for k, v in running.items()},
            "pages_used": None if pages is None else sorted(pages), "image_pages": len(image_pages),
            "reading": {"ats_lines": [{"page": l["page"], "text": l["text"], "col": l["col"]} for l in ext_order],
                        "ats_headings": ext_heads, "page_headings": vis_heads, "out_of_order": out_of_order,
                        "switches": len(switches)}}


def _lis(seq):
    """Longest increasing subsequence (values), to find the headings that are out of order."""
    if not seq:
        return []
    best = [[seq[0]]]
    for v in seq[1:]:
        cands = [b + [v] for b in best if b[-1] < v] + [[v]]
        best.append(max(cands, key=len))
    return max(best, key=len)


# ---------------------------------------------------------------------------
# page images with the problem areas marked
# ---------------------------------------------------------------------------
def render_pages(pdf_path, findings, dpi=RENDER_DPI):
    """-> list of PNG bytes, one per page, with a colored box and a short label for every design problem."""
    from PIL import ImageDraw
    out = []
    scale = dpi / 72
    with cv_cache.open_pdf(pdf_path) as pdf, PageRenderer(pdf_path) as render:
        for pno, page in enumerate(pdf.pages):
            img = render.image(pno, dpi)
            draw = ImageDraw.Draw(img)
            ox, oy = page.bbox[0], page.bbox[1]
            used = []                                     # label boxes already drawn: never on top of each other
            for fd in findings.values():
                if not fd["found"]:
                    continue
                color = COLORS[fd["severity"]]
                for b in fd["boxes"]:
                    if b[0] != pno:
                        continue
                    x0, y0, x1, y1 = ((v - (ox, oy)[k % 2]) * scale for k, v in enumerate(b[1:5]))
                    draw.rectangle((x0, y0, x1, y1), outline=color, width=3)
                    label = b[5]
                    tw = draw.textlength(label) + 8
                    ty = max(0, y0 - 14) if y0 > 14 else y0
                    while any(x0 < u[2] and x0 + tw > u[0] and ty < u[3] and ty + 14 > u[1] for u in used):
                        ty += 15
                    used.append((x0, ty, x0 + tw, ty + 14))
                    draw.rectangle((x0, ty, x0 + tw, ty + 14), fill=color)
                    draw.text((x0 + 4, ty + 1), label, fill=(255, 255, 255))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            out.append(buf.getvalue())
    return out
