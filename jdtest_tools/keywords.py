"""Job keywords once per job (AI, saved next to the job file, as the dashboard saves them) and the job title the
user would type: the posting's first line when it looks like a title, else the title the AI copied from the posting.

  py -3.12 -P -E keywords.py <sample folder>
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, r"C:\ATSLab")
os.environ["ATSLAB_AI_REVIEW"] = "0"
import ATSLab_v3 as L
import dashboard as D

sample = sys.argv[1]
cache = os.path.join(sample, "lab_jobs")
os.makedirs(cache, exist_ok=True)
jobs = sorted(f[:-4] for f in os.listdir(os.path.join(sample, "jobs")) if f.endswith(".txt"))


def one(jid):
    with open(os.path.join(sample, "jobs", f"{jid}.txt"), encoding="utf-8") as f:
        text = f.read().strip()
    path = D.job_file(text, cache)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    kw = L.load_keywords(path, D.MODEL)
    raw = L.read_raw_keywords(L.keywords_path(path))
    first = L.title_from_first_line(text)
    title = first or (raw.get("title") or "").strip()
    return jid, {"title": title, "title_source": "first line" if first else "AI (copied from the posting)",
                 "job_file": os.path.basename(path), "n_required": len(kw["required_skills"]),
                 "n_preferred": len(kw["preferred_skills"]), "required": kw["required_skills"],
                 "preferred": kw["preferred_skills"], "degree": kw.get("degree_level"), "min_years": kw.get("min_years")}


with ThreadPoolExecutor(5) as ex:
    out = dict(ex.map(one, jobs))
with open(os.path.join(sample, "jobs.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
for jid, j in out.items():
    print(f"{jid} [{j['title_source'][:5]}] {j['title'][:50]:50} req {j['n_required']:2} pref {j['n_preferred']:2} "
          f"deg {j['degree']} yrs {j['min_years']}")
