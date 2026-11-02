"""
Calibration test, step 2: score the interview resumes the way the dashboard does (run_check, with the AI reviewer).
No scoring rule is changed here, and nothing is added to the reference set.

  Next steps: C:\\ATSLab\\nextsteps-resumes\\nextsteps-cvs   without a job description (all), and WITH the job description
              for the resumes that have one in descriptions-check.md (Job Match shown).
  Huntr:      the OCR text PDFs made by calib_prep.py, without a job description.

  py -3.12 calib_score.py
"""

import json
import os
import re
import sys
import time
import traceback

import dashboard as D

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "calib_work")
NEXT = os.path.join(HERE, "nextsteps-resumes", "nextsteps-cvs")
RESULTS = os.path.join(WORK, "calib_results.json")


def table_rows(md, header_start):
    """Rows of the first markdown table whose header starts with `header_start`."""
    out, on = [], False
    for line in md.splitlines():
        if line.startswith("|") and header_start in line and not on:
            on = True
            continue
        if on:
            if not line.startswith("|"):
                break
            if set(line.replace("|", "").strip()) <= set("-: "):
                continue
            out.append([c.strip().strip("`") for c in line.strip().strip("|").split("|")])
    return out


def nextsteps_list():
    """Every resume with its job and outcome (manifest.md + next-steps-details.md) and its job description when we
    have one (descriptions-check.md)."""
    manifest = open(os.path.join(NEXT, "manifest.md"), encoding="utf-8").read()
    details = open(os.path.join(NEXT, "next-steps-details.md"), encoding="utf-8").read()
    desc = open(os.path.join(NEXT, "descriptions-check.md"), encoding="utf-8").read()
    notes = {}                                        # (customer, company) -> [(role, note, date)]
    for sec in re.split(r"\n## ", details)[1:]:
        cust = re.sub(r"\s*\(\d+\)\s*$", "", sec.splitlines()[0]).strip()
        for company, role, note, date in [r for r in table_rows(sec, "Company") if len(r) == 4]:
            notes.setdefault((cust, company), []).append((role, note.strip('"'), date))
    jobs = {}
    for m in re.finditer(r"## (.+?) \W+ (.+?)\n\n\*\*(.+?)\*\*.*?CV generated: \**(\w+)\**.*?```\n(.*?)\n```", desc, re.S):
        jobs[(m.group(1).strip(), m.group(2).strip())] = {"role": m.group(3), "text": m.group(5)}
    rows = []
    for customer, company, role, fname in [r for r in table_rows(manifest, "Customer") if len(r) == 4]:
        cust = customer
        hit = next((x for x in notes.get((cust, company), []) if x[0].startswith(role.strip()[:20])), None)
        path = next(os.path.join(dp, fname) for dp, _, fs in os.walk(NEXT) if fname in fs)
        note, date = (hit[1], hit[2]) if hit else ("", "")
        jd = jobs.get((customer, company))
        rows.append({"id": fname[:-4], "customer": customer, "company": company, "role": hit[0] if hit else role,
                     "outcome": note if note and note != "—" else "(no note)", "date": date if date != "—" else "",
                     "path": path, "job": jd["text"] if jd else None})
    return rows


def card_record(c, r):
    return {"key": c["key"], "name": c["name"], "tag": c["tag"], "part": D.card_part(c), "points": round(c["points"], 1),
            "ai": bool(c.get("ai")), "ids": sorted({i["id"] for i in c["issues"]}),
            "quote": (D.before_after(c, r)[1] or [""])[0][:140]}


def score(item, with_job, text):
    t0 = time.time()
    rec = {"set": item["set"], "id": item["id"], "file": item["file"], "mode": "with job" if with_job else "without job",
           "type": item["type"], "template": item.get("template", False), "sample_data": item.get("sample_data", False)}
    try:
        with open(item["path"], "rb") as f:
            r = D.run_check(f.read(), item["file"], with_job, text, None, None, job_title=item.get("role"))
        cards = D.issue_cards(r)
        rec.update(score=r["score"], label=r["label"], parts={k: round(v, 1) for k, v in r["parts"].items()},
                   cards=[card_record(c, r) for c in cards], notes=list(r.get("notes") or []), gates=list(r.get("gates") or []),
                   ai_ran=r.get("ai_review") is not None, pages=(r.get("layout") or {}).get("pages"),
                   layout_limits=bool((r.get("layout_limits") or {}).get("active")),
                   target=r.get("target"), seconds=round(time.time() - t0, 1))
        if with_job:
            rec["keywords_missing"] = [k["term"] for k in r["v3"]["keywords"] if k["match"] == "missing" and k["type"] == "required"][:12]
    except Exception as e:                                           # a crash or a reading problem: reported with the name
        rec.update(error=f"{type(e).__name__}: {e}", seconds=round(time.time() - t0, 1))
        traceback.print_exc(limit=-2)
    return rec


def main():
    os.environ.pop("ATSLAB_AI_REVIEW", None)
    D.AI_REVIEW = True
    print("AI reviewer on:", D.AI_REVIEW, "| key set:", bool(os.environ.get("OPENROUTER_API_KEY")), flush=True)
    todo = []
    for it in nextsteps_list():
        base = {"set": "nextsteps", "id": it["id"], "file": it["id"] + ".pdf", "path": it["path"], "type": "pdf",
                "role": it["role"]}
        todo.append((base, False, ""))
        if it["job"]:
            todo.append((base, True, it["job"]))
    prep = json.load(open(os.path.join(WORK, "huntr_prep.json"), encoding="utf-8"))
    for h in prep["resumes"]:
        todo.append(({"set": "huntr", "id": h["key"], "file": h["label"][:60] + ".pdf", "path": os.path.join(HERE, h["pdf"]),
                      "type": "image", "template": h["template"], "sample_data": h["sample_data"]}, False, ""))
    only = set(sys.argv[1:])                          # e.g. "huntr": score only that set, keep the other results
    old = json.load(open(RESULTS, encoding="utf-8")) if only and os.path.exists(RESULTS) else []
    out = [r for r in old if r["set"] not in only]
    todo = [t for t in todo if not only or t[0]["set"] in only]
    for n, (item, with_job, text) in enumerate(todo, 1):
        rec = score(item, with_job, text)
        out.append(rec)
        print(f"[{n}/{len(todo)}] {rec['set']} {rec['id']} {rec['mode']}: "
              + (rec["error"] if "error" in rec else f"{rec['score']} {rec['parts']} ({rec['seconds']}s)"), flush=True)
        json.dump(out, open(RESULTS, "w", encoding="utf-8"), indent=1)
    print("done", len(out), "runs; errors:", [r["id"] for r in out if "error" in r])


if __name__ == "__main__":
    main()
