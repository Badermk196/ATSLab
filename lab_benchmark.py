"""
The Benchmark: the user's original resume against the 1000Jobs resume made for each job (1 to 5 jobs), checked by three
checkers against that job's description:

    ATS Lab (Job match)  ·  Resume Matcher  ·  VeriWorkly (Job match)

Nothing here changes a Lab score: the Lab is only asked for its own Job match (parts["job_match"]) and the two second
opinions are asked the way the Second opinion cards ask them (lab_second.run).

  tables(data)     the tables to show (one per job, and "Across the N jobs"): pure, no Streamlit, no I/O
  table_html(...)  the same tables as HTML (the page, the History) - text_png / text_pdf: the download files
  start(...)       runs the whole benchmark in a background thread, with a progress message (see progress())

Never raises into the page: a checker that fails or is not ready gives None ("Not available") and the averages use
the others.
"""

import datetime as dt
import hashlib
import html
import io
import os
import threading
import time

import cv_cache

MAX_JOBS = 5
CHECKERS = ("lab", "matcher", "engine")
NAMES = {"lab": "ATS Lab", "matcher": "Resume Matcher", "engine": "VeriWorkly"}
LABEL = "Benchmark"                                  # the History label of a saved benchmark
RED_UNDER, GREEN_FROM = 50, 70                       # red under 50%, yellow 50-69%, green 70% and above
NOT_AVAILABLE = "Not available"

# why a checker had no number, in plain words (the note under the table)
WHY = {"installing": "it is still setting up, a one-time install of about a minute. Run the benchmark again in a minute",
       "node_missing": "this server has no Node.js", "node_too_old": "this server's Node.js is too old",
       "npm_missing": "this server has no npm", "npm_install_failed": "its one-time install failed",
       "npm_install_timeout": "its one-time install took too long", "not_installed": "it is not installed here",
       "no_text": "the resume has no readable text", "no_job": "there was no job description to read",
       "no_job_match": "it gave no Job match for this job", "failed": "it could not answer"}


# ---------------------------------------------------------------------------------------------------------
# The numbers
# ---------------------------------------------------------------------------------------------------------
def score_tone(value):
    """The colour of a score cell: 'bad' (red) under 50, 'warn' (yellow) 50-69, 'ok' (green) 70 and above."""
    if value is None:
        return ""
    return "bad" if value < RED_UNDER else "warn" if value < GREEN_FROM else "ok"


def change_tone(value):
    """The colour of a change cell: green when positive, red when negative."""
    if value is None or value == 0:
        return ""
    return "ok" if value > 0 else "bad"


def percent(value):
    return NOT_AVAILABLE if value is None else f"{int(value)}%"


def signed(value):
    """+11%, -5%, 0%; '-' when there is no change to show."""
    if value is None:
        return "-"
    return "0%" if value == 0 else f"{int(value):+d}%"


def mean(values):
    values = [v for v in values if v is not None]
    return int(sum(values) / len(values) + 0.5) if values else None          # half up: 47.5 -> 48


def _row(name, orig, new, bold=False):
    change = (new - orig) if orig is not None and new is not None else None
    return {"name": name, "orig": orig, "new": new, "change": change, "bold": bold}


def _average(pairs, name="Average"):
    """The Average row of the checkers that have a number for BOTH resumes (so the change compares like with like)."""
    both = [(o, n) for o, n in pairs if o is not None and n is not None]
    if not both:
        return _row(name, None, None, True)
    return _row(name, mean([o for o, _ in both]), mean([n for _, n in both]), True)


def _cell(job, side, checker):
    return ((job.get(side) or {}).get(checker) or {}).get("score")


def job_table(job):
    """One job's table: a row per checker and a bold Average row."""
    rows = [_row(NAMES[c], _cell(job, "orig", c), _cell(job, "new", c)) for c in CHECKERS]
    rows.append(_average([(r["orig"], r["new"]) for r in rows]))
    return {"title": job.get("title") or "Job", "rows": rows, "notes": notes_for(job, rows)}


def notes_for(job, rows):
    """The small note under a table when a checker was not available (the average uses the others)."""
    out = []
    for c, row in zip(CHECKERS, rows):
        if row["orig"] is not None and row["new"] is not None:
            continue
        reasons = {WHY.get(((job.get(side) or {}).get(c) or {}).get("why"), "")
                   for side in ("orig", "new") if _cell(job, side, c) is None}
        reasons.discard("")
        why = f": {'; '.join(sorted(reasons))}" if reasons else ""
        left = [NAMES[k] for k in CHECKERS if k != c]
        out.append(f"{NAMES[c]} was not available{why}. The average uses {' and '.join(left)}.")
    return out


def across_table(jobs):
    """'Across the N jobs': each checker's average over the jobs it answered for both resumes, the overall average and
    the average change (the Change column)."""
    rows = []
    for c in CHECKERS:
        pairs = [(_cell(j, "orig", c), _cell(j, "new", c)) for j in jobs]
        both = [(o, n) for o, n in pairs if o is not None and n is not None]
        rows.append(_row(NAMES[c], mean([o for o, _ in both]), mean([n for _, n in both])))
    rows.append(_average([(r["orig"], r["new"]) for r in rows], "Average"))
    notes = []
    for c, row in zip(CHECKERS, rows):
        if row["orig"] is None:
            notes.append(f"{NAMES[c]} was not available for any job. The average uses the other checkers.")
        elif any(_cell(j, s, c) is None for j in jobs for s in ("orig", "new")):
            notes.append(f"{NAMES[c]} was not available for some jobs: its row uses only the jobs it answered.")
    return {"title": f"Across the {len(jobs)} jobs", "rows": rows, "notes": notes}


def tables(data):
    """Every table of a benchmark: one per job, then 'Across the N jobs' when there is more than one job."""
    jobs = data.get("jobs") or []
    out = [job_table(j) for j in jobs]
    if len(jobs) > 1:
        out.append(across_table(jobs))
    return out


def overall(data):
    """(original average, 1000Jobs average) over all jobs: the two numbers a History row shows."""
    last = tables(data)[-1]["rows"][-1] if data.get("jobs") else None
    return (last["orig"], last["new"]) if last else (None, None)


COLUMNS = ("Checker", "Original resume", "1000Jobs resume", "Change")


# ---------------------------------------------------------------------------------------------------------
# HTML (the page and the History): the old benchmark's table style, with the score colours
# ---------------------------------------------------------------------------------------------------------
def _esc(text):
    return html.escape(str(text if text is not None else "")).replace("$", "&#36;")


def _td(text, tone="", bold=False):
    cls = f' class="a-{tone}"' if tone else ""
    inner = f"<b>{_esc(text)}</b>" if bold else _esc(text)
    return f'<td{cls}>{inner}</td>'


def table_html(table):
    head = "".join(f"<th>{_esc(c)}</th>" for c in COLUMNS)
    body = ""
    for r in table["rows"]:
        body += ("<tr>" + _td(r["name"], bold=r["bold"])
                 + _td(percent(r["orig"]), score_tone(r["orig"]), r["bold"])
                 + _td(percent(r["new"]), score_tone(r["new"]), r["bold"])
                 + _td(signed(r["change"]), change_tone(r["change"]), r["bold"]) + "</tr>")
    notes = "".join(f'<div class="bm-note">{_esc(n)}</div>' for n in table["notes"])
    return (f'<div class="so-bench-head"><b>{_esc(table["title"])}</b></div>'
            f'<table class="so-bench bm-table" style="width:100%;border-collapse:collapse;font-size:0.9rem;margin:4px 0 2px">'
            f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{notes}')


def all_tables_html(data):
    return "".join(table_html(t) for t in tables(data))


# ---------------------------------------------------------------------------------------------------------
# The download: an image (PNG) and a PDF of the same picture, drawn with Pillow (no browser needed)
# ---------------------------------------------------------------------------------------------------------
INK = {"bg": "#FFFFFF", "text": "#111827", "muted": "#6B7280", "line": "#E5E7EB", "head": "#F3F4F6"}
TONE = {"bad": ("#FEE2E2", "#991B1B"), "warn": ("#FEF3C7", "#92400E"), "ok": ("#DCFCE7", "#166534"),
        "": ("#FFFFFF", "#111827")}
FONT_FILES = {False: ("arial.ttf", "DejaVuSans.ttf", "Arial.ttf", "LiberationSans-Regular.ttf"),
              True: ("arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf")}
FONT_DIRS = ("C:/Windows/Fonts", "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation",
             "/usr/share/fonts/dejavu", "/Library/Fonts", "/System/Library/Fonts/Supplemental")


def _font(size, bold=False):
    from PIL import ImageFont
    for folder in FONT_DIRS:
        for name in FONT_FILES[bold]:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
    return ImageFont.load_default(size=size)


def _wrap(text, font, width):
    """The lines of a text that fit `width` pixels in this font."""
    lines, line = [], ""
    for word in str(text).split():
        trial = (line + " " + word).strip()
        if line and font.getlength(trial) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])


def picture(data, scale=2):
    """The whole benchmark as one image (a PIL image): a title, then each table. -> PIL.Image"""
    from PIL import Image, ImageDraw
    s = scale
    width, pad = 1000 * s, 40 * s
    cols = [0.34, 0.22, 0.22, 0.22]
    f_title, f_sub, f_head, f_cell, f_bold, f_note = (_font(26 * s, True), _font(14 * s), _font(15 * s, True),
                                                      _font(16 * s), _font(16 * s, True), _font(13 * s))
    row_h, gap = 40 * s, 26 * s
    items = tables(data)
    text_width = width - 2 * pad
    notes = [[line for n in t["notes"] for line in _wrap(n, f_note, text_width)] for t in items]
    height = pad * 2 + 78 * s + sum(34 * s + (len(t["rows"]) + 1) * row_h + len(ls) * 22 * s + gap
                                    for t, ls in zip(items, notes)) + 30 * s
    img = Image.new("RGB", (width, height), INK["bg"])
    d = ImageDraw.Draw(img)
    y = pad
    d.text((pad, y), f"Benchmark: {data.get('name') or 'Resume'}", font=f_title, fill=INK["text"])
    y += 38 * s
    n = len(data.get("jobs") or [])
    when = (data.get("created") or "")[:10]
    d.text((pad, y), f"The original resume against the 1000Jobs resume for {n} job{'s' if n != 1 else ''}"
           + (f"  ·  {when}" if when else "") + "  ·  1000Jobs ATS Lab", font=f_sub, fill=INK["muted"])
    y += 40 * s
    inner = width - 2 * pad
    xs = [pad]
    for c in cols:
        xs.append(xs[-1] + int(inner * c))
    for t, note_lines in zip(items, notes):
        d.text((pad, y), t["title"], font=_font(18 * s, True), fill=INK["text"])
        y += 34 * s
        d.rectangle([pad, y, pad + inner, y + row_h], fill=INK["head"])
        for i, name in enumerate(COLUMNS):
            d.text((xs[i] + 12 * s, y + 11 * s), name, font=f_head, fill=INK["muted"])
        y += row_h
        for r in t["rows"]:
            font = f_bold if r["bold"] else f_cell
            cells = [(r["name"], ""), (percent(r["orig"]), score_tone(r["orig"])),
                     (percent(r["new"]), score_tone(r["new"])), (signed(r["change"]), change_tone(r["change"]))]
            for i, (text, tone) in enumerate(cells):
                bg, fg = TONE[tone]
                if tone:
                    d.rectangle([xs[i], y, xs[i + 1], y + row_h], fill=bg)
                d.text((xs[i] + 12 * s, y + 10 * s), text, font=font, fill=fg if tone else INK["text"])
            d.line([pad, y + row_h, pad + inner, y + row_h], fill=INK["line"], width=max(1, s))
            y += row_h
        for note in note_lines:
            d.text((pad, y + 5 * s), note, font=f_note, fill=INK["muted"])
            y += 22 * s
        y += gap
    return img


def png_bytes(data):
    out = io.BytesIO()
    picture(data).save(out, format="PNG", optimize=True)
    return out.getvalue()


def pdf_bytes(data):
    out = io.BytesIO()
    picture(data).save(out, format="PDF", resolution=144.0, title=f"Benchmark - {data.get('name') or 'Resume'}")
    return out.getvalue()


def guess_name(pdf, filename=""):
    """The user's name when none was typed: the first line of the resume if it looks like a name (2-4 words, letters
    only), else the file name ('Sara_Ali_CV.pdf' -> 'Sara Ali Cv'). Never raises."""
    try:
        import dashboard as D
        for line in (D.pdf_head_text(pdf, pages=1) or "").splitlines():
            words = line.replace(",", " ").split()
            if 2 <= len(words) <= 4 and all(w.replace("-", "").replace(".", "").replace("'", "").isalpha() and len(w) <= 20
                                            for w in words):
                return " ".join(words).title() if line.isupper() or line.islower() else " ".join(words)
            if line.strip():
                break
    except Exception:
        pass
    stem = os.path.splitext(os.path.basename(filename or ""))[0].replace("_", " ").replace("-", " ").strip()
    return stem.title() if stem else "Resume"


def file_stem(data):
    name = "".join(ch for ch in (data.get("name") or "Resume") if ch.isalnum() or ch in " -_").strip() or "Resume"
    return f"1000Jobs Benchmark - {name} - {(data.get('created') or '')[:10]}".rstrip(" -")


# ---------------------------------------------------------------------------------------------------------
# Running it (in the background)
# ---------------------------------------------------------------------------------------------------------
_ANSWERS = cv_cache.shared("benchmark_answers", dict)       # (checker, resume text, job text) -> a finished answer
_RUNS = cv_cache.shared("benchmark_runs", dict)             # run id -> its progress
_LOCK = threading.Lock()
_ONE_AT_A_TIME = threading.Lock()
MAX_ANSWERS = 300


def check_resume(pdf, filename, job_text, job_title):
    """The ATS Lab's own check of a resume against a job (a saved result is reused for a file checked before)."""
    import dashboard as D
    return D.run_check_reusing(pdf, filename, True, job_text, job_title=job_title)


def ask(checker, res, job_text):
    """-> {"score": whole number or None, "why": reason when None}. A finished answer is kept and reused (same resume
    text, same job): a failure is never kept, so the next run asks again."""
    import lab_second as SO
    if checker == "lab":
        value = (res.get("parts") or {}).get("job_match")
        return {"score": None if value is None else round(value), "why": "" if value is not None else "failed"}
    text = SO.text_of(res)
    key = (checker, hashlib.sha256(text.encode("utf-8")).hexdigest(),
           hashlib.sha256((job_text or "").strip().encode("utf-8")).hexdigest())
    with _LOCK:
        hit = _ANSWERS.get(key)
    if hit is not None:
        return dict(hit)
    out = SO.run(checker, res, job_text)
    score = out.get("score")
    if out.get("state") == SO.DONE and score is not None and (checker != "engine" or out.get("compares") == "job_match"):
        answer = {"score": round(score), "why": ""}
        with _LOCK:
            if len(_ANSWERS) >= MAX_ANSWERS:
                _ANSWERS.pop(next(iter(_ANSWERS)))
            _ANSWERS[key] = answer
        return dict(answer)
    why = out.get("why") or ("no_job_match" if out.get("state") == SO.DONE else out.get("state") or "failed")
    return {"score": None, "why": str(why)}


def run_side(pdf, filename, job, step):
    """The three numbers for one resume against one job. step(text) reports progress."""
    cells = {}
    res = None
    try:
        step("ATS Lab")
        res = check_resume(pdf, filename, job["text"], job["title"])
    except Exception as e:                           # a CheckError (not a PDF, no text ...) or anything unexpected
        why = str(e) or type(e).__name__
        cells = {c: {"score": None, "why": "failed", "message": why[:160]} for c in CHECKERS}
        for c in CHECKERS[1:]:
            step(NAMES[c])
        return cells
    cells["lab"] = ask("lab", res, job["text"])
    for c in CHECKERS[1:]:
        step(NAMES[c])
        try:
            cells[c] = ask(c, res, job["text"])
        except (Exception, SystemExit) as e:
            cells[c] = {"score": None, "why": "failed", "message": type(e).__name__}
    return cells


def run_benchmark(inputs, progress=None):
    """inputs: {"name", "original": (pdf bytes, file name), "jobs": [{"title", "text", "pdf", "filename"}]}.
    -> the benchmark data (see tables). progress(done, total, message) is called as it goes."""
    jobs = inputs["jobs"][:MAX_JOBS]
    total = len(jobs) * 2 * len(CHECKERS)
    state = {"done": 0}

    def reporter(job_no, side):
        def step(checker_name):
            if progress:
                progress(state["done"], total, f"Job {job_no} of {len(jobs)} · {side} · {checker_name}")
            state["done"] += 1
        return step

    out_jobs = []
    for n, job in enumerate(jobs, start=1):
        orig = run_side(inputs["original"][0], inputs["original"][1], job, reporter(n, "original resume"))
        new = run_side(job["pdf"], job["filename"], job, reporter(n, "1000Jobs resume"))
        out_jobs.append({"title": job["title"], "orig": orig, "new": new, "file": job.get("filename") or ""})
    if progress:
        progress(total, total, "Done")
    return {"name": inputs.get("name") or "", "created": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "original_file": inputs["original"][1], "jobs": out_jobs}


def any_number(data):
    return any(c.get("score") is not None for j in data["jobs"] for side in ("orig", "new")
               for c in (j[side] or {}).values())


def _warm():
    """True when the AI model is ready (or no warm-up runs, as in the tests)."""
    try:
        import lab_warmup
        status = lab_warmup.status()
        return (not status["started"]) or status["done"]
    except Exception:
        return True


def start(inputs, who, save=None):
    """Run the benchmark in a background thread and return its id. progress(id) says where it is. When it finishes
    `save(data)` (the History) is called once, in the thread, so a visitor who leaves the page loses nothing."""
    run_id = hashlib.sha1(os.urandom(12)).hexdigest()[:12]
    jobs = len(inputs["jobs"])
    info = {"state": "running", "done": 0, "total": jobs * 2 * len(CHECKERS), "message": "Starting", "data": None,
            "error": "", "history_id": None, "who": who, "began": time.time()}
    with _LOCK:
        _RUNS[run_id] = info

    def progress(done, total, message):
        info.update(done=done, total=total, message=message)

    def work():
        try:
            progress(0, info["total"], "Waiting for the AI model to load" if not _warm() else "Starting")
            with _ONE_AT_A_TIME:                       # one benchmark at a time: they share the Lab's model
                import lab_warmup
                lab_warmup.wait()                      # the model is loading in the background: wait, never load twice
                data = run_benchmark(inputs, progress)
                if not any_number(data):
                    raise RuntimeError("No checker could read these resumes. Check that the files are PDFs with text.")
                info["data"] = data
                if save is not None:
                    try:
                        info["history_id"] = save(data)
                    except Exception as e:             # the tables are still shown when the History could not save
                        info["save_error"] = type(e).__name__
                info["state"] = "done"
        except BaseException as e:
            info.update(state="error", error=str(e)[:300] or type(e).__name__)

    threading.Thread(target=work, name=f"atslab-benchmark-{run_id}", daemon=True).start()
    return run_id


def progress(run_id):
    """The run's state: {"state": running | done | error, "done", "total", "message", "data", "error", ...} or None."""
    with _LOCK:
        info = _RUNS.get(run_id)
        return dict(info) if info else None


def forget(run_id):
    with _LOCK:
        _RUNS.pop(run_id, None)
