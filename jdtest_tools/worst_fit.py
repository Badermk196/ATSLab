"""The Good Fit pairs with the lowest Job Match: their checks, skills, and the start of the resume."""
import json
import os
import sys

import pandas as pd

S = sys.argv[1]
pairs = pd.read_csv(os.path.join(S, "pairs.csv")).set_index("pair")
texts = pd.read_csv(os.path.join(S, "resumes.csv")).set_index("resume").text
jobs = json.load(open(os.path.join(S, "jobs.json"), encoding="utf-8"))
rows = [json.loads(l) for l in open(os.path.join(S, "results.jsonl"), encoding="utf-8") if l.strip()]
fit = sorted((r for r in rows if pairs.loc[r["pair"]].fit == 1), key=lambda r: r["job_match"])[:int(sys.argv[2])]
for r in fit:
    p = pairs.loc[r["pair"]]
    ks = [k for k in r["keywords"] if k["type"] != "soft"]
    print(r["pair"], "| job:", jobs[p.job]["title"], "| JM", r["job_match"], "score", r["score"], "| yrs",
          r["experience_years"], "job yrs", jobs[p.job]["min_years"])
    print("   checks", {c: v["score"] for c, v in r["checks"].items() if v["score"] is not None})
    print("   matched", [k["term"] for k in ks if k["match"] != "missing"])
    print("   missing", [k["term"] for k in ks if k["match"] == "missing"][:16])
    print("   start", repr(texts[p.resume][:260]))
