"""
Calibration test, step 3: the report (tables, statistics, common issues) from calib_work\\calib_results.json.
Writes C:\\ATSLab\\calib_report.md. No scoring rule is changed here.

  py -3.12 calib_report.py
"""

import json
import os
from collections import Counter

import calib_score as S

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "calib_work", "calib_results.json")
OUT = os.path.join(HERE, "calib_report.md")
CONTACT_IDS = {"T3", "T5", "T6", "T7", "B4"}          # email, phone, LinkedIn, city, name: sample data in Huntr examples
WEIGHT = {"content": 0.40, "structure": 0.25}         # the dashboard's own weights, without Readability
COMMON = 0.60


def is_contact(card):
    return card["key"] in ("phone", "email", "linkedin", "location", "contact") or set(card["ids"]) <= CONTACT_IDS


def cs_score(parts):
    """Content and Structure only, with the dashboard's own weights (the layout of an image cannot be judged)."""
    return round(sum(parts[k] * w for k, w in WEIGHT.items()) / sum(WEIGHT.values()), 1)


def shown(rec):
    """The score used for the set statistics: the dashboard total for a PDF, Content + Structure for an image."""
    return cs_score(rec["parts"]) if rec["type"] == "image" else rec["score"]


def cards_of(rec, image_ok=True):
    """The issue cards the dashboard shows (an image resume: no Readability cards, its layout was not judged)."""
    out = [c for c in rec["cards"] if not (rec["type"] == "image" and c["part"] == "readability")]
    return out


def top3(rec):
    return "; ".join(f'{c["name"]} ({c["tag"]}{", AI" if c["ai"] else ""})' for c in cards_of(rec)[:3]) or "none"


def stats(recs):
    ok = [r for r in recs if "error" not in r]
    sc = [(shown(r), r) for r in ok]
    lo, hi = min(sc, key=lambda x: x[0]), max(sc, key=lambda x: x[0])
    return {"n": len(ok), "avg": round(sum(s for s, _ in sc) / len(sc), 1), "lo": lo, "hi": hi,
            "n75": sum(s >= 75 for s, _ in sc)}


def stats_line(recs, label):
    s = stats(recs)
    return (f"**{label}** ({s['n']} resumes): average **{s['avg']}**, lowest **{s['lo'][0]}** ({s['lo'][1]['id']}), "
            f"highest **{s['hi'][0]}** ({s['hi'][1]['id']}), **{s['n75']}** of {s['n']} score 75 or more.")


def common_issues(recs, skip=lambda r, c: False):
    """Issue name -> number of resumes that have it (a resume counts once; AI findings have free names: left out)."""
    n, cnt = 0, Counter()
    for r in recs:
        if "error" in r:
            continue
        n += 1
        names = {c["name"] for c in cards_of(r) if not c["ai"] and not skip(r, c)}
        cnt.update(names)
    return n, cnt.most_common(10)


def issue_table(n, rows):
    lines = ["| # | Issue | Resumes | Share | |", "|---|---|---:|---:|---|"]
    for i, (name, k) in enumerate(rows, 1):
        flag = "**over 60%: may be too strict**" if k / n > COMMON else ""
        lines.append(f"| {i} | {name} | {k} of {n} | {k / n:.0%} | {flag} |")
    return "\n".join(lines)


def main():
    res = json.load(open(RESULTS, encoding="utf-8"))
    nx = {r["id"]: r for r in S.nextsteps_list()}
    prep = {h["key"]: h for h in json.load(open(os.path.join(HERE, "calib_work", "huntr_prep.json"), encoding="utf-8"))["resumes"]}
    ns_no = [r for r in res if r["set"] == "nextsteps" and r["mode"] == "without job"]
    ns_job = [r for r in res if r["set"] == "nextsteps" and r["mode"] == "with job"]
    hu = [r for r in res if r["set"] == "huntr"]
    out = ["# Calibration test: resumes that got interviews", "",
           "Scored the way the dashboard does (with the AI reviewer). No rule was changed. Nothing was added to the "
           "reference set.", ""]

    out += ["## Set 1: Next steps (real 1000Jobs users), without a job description", "",
            "| File | Job | What happened | Score | Readability | Content | Structure | Top 3 issues |",
            "|---|---|---|---:|---:|---:|---:|---|"]
    for r in ns_no:
        if "error" in r:
            out.append(f"| {r['id']} | | | ERROR | | | | {r['error']} |")
            continue
        x = nx[r["id"]]
        p = r["parts"]
        out.append(f"| {r['id']} | {x['customer']}: {x['company']}, {x['role'][:38]} | {x['outcome'][:50]} | {r['score']} | "
                   f"{p['readability']} | {p['content']} | {p['structure']} | {top3(r)} |")
    out += ["", stats_line(ns_no, "Next steps, without a job description"), ""]

    out += ["### With the job description (6 resumes that have one on file)", "",
            "| File | Job | Score | Readability | Content | Structure | Job Match | Top 3 issues |",
            "|---|---|---:|---:|---:|---:|---:|---|"]
    for r in ns_job:
        if "error" in r:
            out.append(f"| {r['id']} | | ERROR | | | | | {r['error']} |")
            continue
        x, p = nx[r["id"]], r["parts"]
        out.append(f"| {r['id']} | {x['company']}, {x['role'][:34]} | {r['score']} | {p['readability']} | {p['content']} | "
                   f"{p['structure']} | {p.get('job_match', '')} | {top3(r)} |")
    out += ["", stats_line(ns_job, "Next steps, with the job description"), ""]
    both = {r["id"]: r for r in ns_no}
    out += ["Same resumes, without the job description: " + ", ".join(
        f"{r['id'].split('_')[0]}_{r['id'].split('_')[1]} {both[r['id']]['score']}" for r in ns_job if r["id"] in both), ""]
    n, rows = common_issues(ns_no)
    out += ["### The 10 most common issues (Next steps, without a job description)", "", issue_table(n, rows), ""]
    cust = [r for r in ns_no if "internal" not in nx[r["id"]]["customer"]]
    out += ["13 of the 25 resumes are one internal person's (Allan Abbas), built from the same base content. The same view "
            "for the 12 resumes of real customers only:", "", stats_line(cust, "Next steps, customers only"), ""]
    n, rows = common_issues(cust)
    out += [issue_table(n, rows), ""]

    out += ["## Set 2: Huntr (interview examples, images read with OCR), without a job description", "",
            "Type **image**: the layout cannot be judged, so Readability is not reported and the score is **Content + Structure "
            "only** (the dashboard's own weights, without Readability). The column *Marks* shows **template** (placeholder name "
            "or placeholder employers such as \"Employer 1\") and **sample** (fake contact details such as 111-111-1111).", "",
            "| ID | Resume (post) | Pages | Marks | Score (C+S) | Content | Structure | Top 3 issues |",
            "|---|---|---:|---|---:|---:|---:|---|"]
    for r in hu:
        h = prep[r["id"]]
        marks = ", ".join(m for m, on in (("template", h["template"]), ("sample", h["sample_data"])) if on) or "-"
        if "error" in r:
            out.append(f"| {r['id']} | {h['label'][:50]} | {len(h['pages'])} | {marks} | ERROR | | | {r['error']} |")
            continue
        p = r["parts"]
        out.append(f"| {r['id']} | {h['label'][:50]} | {len(h['pages'])} | {marks} | {shown(r)} | {p['content']} | {p['structure']} | "
                   f"{top3(r)} |")
    real = [r for r in hu if not r["template"]]
    out += ["", stats_line(hu, "Huntr, all"), stats_line(real, "Huntr, without the template resumes"), ""]
    n, rows = common_issues(hu, skip=lambda r, c: r["sample_data"] and is_contact(c))
    out += ["### The 10 most common issues (Huntr, Readability not judged; contact-detail issues on sample data left out)", "",
            issue_table(n, rows), ""]
    n2, rows2 = common_issues(hu)
    contact = [(nm, k) for nm, k in Counter(c["name"] for r in hu if "error" not in r for c in cards_of(r)
                                            if not c["ai"] and is_contact(c)).most_common()]
    out += ["Contact-detail issues counted on all Huntr resumes (they are artifacts of the fake contact lines): "
            + ("; ".join(f"{nm} {k} of {n2}" for nm, k in contact) or "none"), ""]

    t4 = Counter(c["tag"] for r in hu if "error" not in r for c in cards_of(r) if c["key"] == "job_details")
    out += ["Of the Huntr resumes flagged for job details: " + ", ".join(f"{k} {v}" for k, v in sorted(t4.items())) + ".", ""]
    errors = [r for r in res if "error" in r]
    notes = [(r["id"], r["notes"]) for r in res if r.get("notes")]
    out += ["## Crashes and reading problems", ""]
    out += [f"- **{r['set']} / {r['id']} ({r['mode']})**: {r['error']}" for r in errors] or ["- No crash."]
    out += [f"- {i}: {n}" for i, n in notes]
    out += ["- **Job descriptions are cut**: descriptions-check.md keeps only the first 1,400 characters of each description "
            "(the full ones are 1,785 to 4,862). The with-job scores use that part only. Two of them (Aryan_ALBACORP_ahtdjp, "
            "Aryan_Kraken_9junyi) are only the company introduction, so the dashboard refuses them as \"not a job description\".",
            "- **Only 6 resumes have a job description on file** (Ali Maher x2, Aryan x4). The ALBA CORP resume of "
            "rashaadnmohammed has none (the same posting as Aryan's, but it is not in the file, so it was not assumed).",
            "- **10x_Team_AlanAbbas_1776796911610.pdf has 31 pages**: after the normal 3 pages, the skills section runs on for "
            "28 pages of lines such as \"_My Data Lake Metrics_\" and a markdown table (\":-----\"). It is a generator problem; "
            "the Lab scored it (60.5).",
            "- **OCR could not read the large name at the top** of H01, H03, H04, H08, H11, H16, H22 and H23 (stylised or light "
            "text), so their name and headline lines are garbled. H09 has the name over two lines. Their headline issues may be "
            "OCR errors.",
            "- **Contact lines of the Huntr examples are placeholders** (111-111-1111, example.com, \"Location | Number | Email\"). "
            "The phone, city, LinkedIn and email issues on them are not meaningful; H06, H12 and H26 get Structure 0 to 16 mostly "
            "for this.",
            "- Pages of one Huntr resume are separate images with the same post id (not copies). They were joined into one resume "
            "each: 54 images became 26 resumes. Only 1 exact copy existed (\"6eyl37t71hwh1 (1).png\")."]
    open(OUT, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
