"""What-if (offline, no code change): Job Match rebuilt from the saved check scores (average of the 3 ATS) with
other weights, and its AUC / same-job pairwise accuracy. First line: the rebuild with today's weights."""
import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

S = sys.argv[1]
pairs = pd.read_csv(os.path.join(S, "pairs.csv")).set_index("pair")
jobs = json.load(open(os.path.join(S, "jobs.json"), encoding="utf-8"))
rows = [json.loads(l) for l in open(os.path.join(S, "results.jsonl"), encoding="utf-8") if l.strip()]
W = {n: c["weight"] for r in rows for n, c in r["checks"].items()}
print("today's weights:", W)


def jm(r, w, smooth=0):
    ch = {n: c for n, c in r["checks"].items() if c["score"] is not None and w.get(n, 0) > 0}
    part = {}
    for P in "FM":
        use = [(c["score"] / 100, w[n]) for n, c in ch.items() if c["part"] == P]
        if smooth and P == "F" and "F1" in ch:
            # few job skills: one hit should not count as much (coverage pulled toward 0.25 like 4 extra half-skills)
            n_kw = len([k for k in r["keywords"] if k["type"] != "soft"])
            f1 = (ch["F1"]["score"] / 100 * n_kw + 0.25 * smooth) / (n_kw + smooth)
            use = [(f1 if n == "F1" else c["score"] / 100, w[n]) for n, c in ch.items() if c["part"] == P]
        part[P] = sum(s * x for s, x in use) / sum(x for _, x in use) if use else 0.0
    return 100 * (max(.01, part["F"]) ** .3 * max(.01, part["M"]) ** .4) ** (1 / .7)


def measure(vals):
    d = pd.DataFrame({"x": vals, "fit": [pairs.loc[r["pair"]].fit for r in rows],
                      "job": [pairs.loc[r["pair"]].job for r in rows]})
    good = tot = 0
    for _, g in d.groupby("job"):
        a, b = g[g.fit == 1].x.values, g[g.fit == 0].x.values
        x = a[:, None] - b[None, :]
        good += (x > 0).sum() + .5 * (x == 0).sum(); tot += x.size
    return roc_auc_score(d.fit, d.x), good / tot


real = [r["job_match"] for r in rows]
rebuilt = [jm(r, W) for r in rows]
print(f"rebuild vs real: correlation {np.corrcoef(real, rebuilt)[0, 1]:.3f}")
variants = {
    "real Job Match (Lab)": real,
    "rebuilt, today's weights": rebuilt,
    "job title (F3) weight halved": [jm(r, dict(W, F3=W["F3"] / 2)) for r in rows],
    "no job title (F3)": [jm(r, dict(W, F3=0)) for r in rows],
    "meaning match (M3) weight x2": [jm(r, dict(W, M3=W["M3"] * 2)) for r in rows],
    "no education/years (M4, M5)": [jm(r, dict(W, M4=0, M5=0)) for r in rows],
    "F1 smoothed for few skills": [jm(r, W, smooth=4) for r in rows],
    "F3 halved + M3 x2 + smoothing": [jm(r, dict(W, F3=W["F3"] / 2, M3=W["M3"] * 2), smooth=4) for r in rows],
}
for name, v in variants.items():
    a, p = measure(v)
    print(f"{name:34} AUC {a:.3f}  same-job pairs {p:.3f}")
