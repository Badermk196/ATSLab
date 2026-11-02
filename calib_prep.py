"""
Calibration test, step 1: prepare the Huntr resumes (images). Nothing here changes a scoring rule.

- Exact copies (same bytes) are removed. Files with the same Reddit post id (the end of the file name) are the PAGES of one
  resume (page 1 has the header, the others continue it), so each group becomes ONE resume.
- Every page is read with OCR (pytesseract, used only here) and the text is written into a plain text PDF (one PDF page
  per image) so the Lab can read it. Marked "image": the real layout cannot be judged.
- Template resumes (placeholder names such as "First Last") and sample data (111-111-1111, example.com) are marked.

  py -3.12 calib_prep.py
"""

import glob
import hashlib
import json
import os
import re

import pytesseract
from PIL import Image, ImageOps
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
Image.MAX_IMAGE_PIXELS = None
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "calib_huntr")
WORK = os.path.join(HERE, "calib_work")
OUT = os.path.join(WORK, "huntr_pdfs")
SCALE = 2.5
FONT, LEAD = "Helvetica", 12
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def post_id(path):
    """The Reddit post id: the last 6 characters of the random id at the end of the name ('...-v0-26absn3meauh1')."""
    stem = re.sub(r"\s*\(\d+\)$", "", os.path.splitext(os.path.basename(path))[0])
    return stem[-6:]


def ocr(path):
    img = Image.open(path).convert("L")
    img = img.resize((int(img.width * SCALE), int(img.height * SCALE)), Image.LANCZOS)
    img = ImageOps.autocontrast(img)
    text = pytesseract.image_to_string(img, config="--psm 3 --oem 1 -c preserve_interword_spaces=1")
    return "\n".join(l.rstrip() for l in text.splitlines())


def employer_no(text):
    nums = [int(n) for n in re.findall(r"(?:Employer|School)\s+(\d+)", text)]
    return min(nums) if nums else 99


def has_header(text):
    top = [l for l in text.splitlines() if l.strip()][:8]
    return any(EMAIL.search(l) or re.search(r"linkedin|github\.com|\(?\d{3}\)?[ .-]?\d{3}[ .-]\d{4}\b", l, re.I)
               for l in top) or any(re.fullmatch(r"First Last", l.strip()) for l in top)


def write_pdf(pages, path):
    """One PDF page per image, plain text lines in reading order; the page is wide enough for its longest line."""
    c = None
    for text in pages:
        lines = text.splitlines()
        widest = max([stringWidth(l, FONT, 10) for l in lines] or [400])
        w = max(612.0, widest + 90)
        h = max(792.0, w * 1.294, len(lines) * LEAD + 100)
        if c is None:
            c = canvas.Canvas(path, pagesize=(w, h))
        c.setPageSize((w, h))
        c.setFont(FONT, 10)
        y = h - 50
        for l in lines:
            if not l.strip():
                y -= LEAD * 0.5
                continue
            c.drawString(45, y, l.replace("\t", " "))
            y -= LEAD
        c.showPage()
    c.save()


def main():
    os.makedirs(OUT, exist_ok=True)
    files = sorted(glob.glob(os.path.join(SRC, "*")))
    seen, dups, unique = {}, [], []
    for p in files:
        h = hashlib.md5(open(p, "rb").read()).hexdigest()
        if h in seen:
            dups.append((os.path.basename(p), seen[h]))
        else:
            seen[h] = os.path.basename(p)
            unique.append(p)
    groups = {}
    for p in unique:
        groups.setdefault(post_id(p), []).append(p)
    resumes = []
    for n, (gid, paths) in enumerate(sorted(groups.items()), 1):
        texts = {p: ocr(p) for p in paths}
        order = sorted(paths, key=lambda p: (0 if has_header(texts[p]) else 1, employer_no(texts[p]), p))
        pages = [texts[p] for p in order]
        full = "\n".join(pages)
        lines = [l.strip() for l in pages[0].splitlines() if l.strip()]
        name = next((l for l in lines[:6] if re.fullmatch(r"[A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){1,3}", l)), "")
        label = re.sub(r"-v0-.*$", "", os.path.basename(order[0]))
        label = label if "-v0-" in os.path.basename(order[0]) else f"post {gid}"
        key = f"H{n:02d}"
        template = bool(re.search(r"^\s*First Last\s*$", full, re.M)) or bool(re.search(r"\bEmployer \d\b", full)) \
            or bool(re.search(r"\bSchool \d\b", full))
        sample = bool(re.search(r"111-111-1111|@example\.com|example\.com/|\w+123\w*@", full))
        pdf = os.path.join(OUT, f"{key}.pdf")
        write_pdf(pages, pdf)
        open(os.path.join(OUT, f"{key}.txt"), "w", encoding="utf-8").write("\n\n----- page break -----\n\n".join(pages))
        resumes.append({"key": key, "post": gid, "label": label, "name": name, "pages": [os.path.basename(p) for p in order],
                        "template": template, "sample_data": sample, "pdf": os.path.relpath(pdf, HERE)})
        print(key, gid, len(paths), "page(s)", "TEMPLATE" if template else "", "SAMPLE" if sample else "", "|", label[:55],
              "|", name)
    json.dump({"files": len(files), "exact_duplicates_removed": dups, "resumes": resumes},
              open(os.path.join(WORK, "huntr_prep.json"), "w", encoding="utf-8"), indent=1)
    print(f"\n{len(files)} files, {len(dups)} exact copy removed, {len(unique)} images -> {len(resumes)} resumes")


if __name__ == "__main__":
    main()
