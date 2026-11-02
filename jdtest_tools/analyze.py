"""Job Match test: how well the Lab separates "Good Fit" from "No Fit" resumes for the same job.

  py -3.12 -P -E analyze.py <sample folder>
Writes <sample>/analysis.json and prints the summary.
"""
import collections
import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

S = sys.argv[1]
pairs = pd.read_csv(os.path.join(S, "pairs.csv"))
texts = pd.read_csv(os.path.join(S, "resumes.csv")).set_index("resume").text
jobs = json.load(open(os.path.join(S, "jobs.json"), encoding="utf-8"))
rows = {}
for l in open(os.path.join(S, "results.jsonl"), encoding="utf-8"):
    if l.strip():
        r = json.loads(l)
        rows[r["pair"]] = r
errors = collections.Counter(r["error"] for r in rows.values() if "error" in r)
df = pairs[pairs.pair.map(lambda p: p in rows and "error" not in rows[p])].copy()
CHECKS = {"F1": "skills found (F1)", "M1": "skills, weighted (M1)", "M2": "soft skills (M2)",
          "F2": "abbreviations (F2)", "F3": "job title (F3)", "F4": "past titles (F4)", "M3": "meaning match (M3)",
          "M4": "education (M4)", "M5": "experience level (M5)"}
df["job_match"] = df.pair.map(lambda p: rows[p]["job_match"])
df["score"] = df.pair.map(lambda p: rows[p]["score"])
for c in CHECKS:
    df[c] = df.pair.map(lambda p: (rows[p]["checks"].get(c) or {}).get("score"))
df["skills"] = (df.F1 + df.M1) / 2
# a plain text baseline: TF-IDF cosine between the resume text and the job text (what the labels allow)
jt = {j: open(os.path.join(S, "jobs", f"{j}.txt"), encoding="utf-8").read() for j in df.job.unique()}
vec = TfidfVectorizer(stop_words="english", sublinear_tf=True).fit(list(texts) + list(jt.values()))
R, J = vec.transform(df.resume.map(texts)), vec.transform(df.job.map(jt))
df["tfidf"] = np.asarray(R.multiply(J).sum(1)).ravel()


def pairwise(col, d=df):
    good = tot = 0
    for _, g in d.groupby("job"):
        a, b = g[g.fit == 1][col].dropna().values, g[g.fit == 0][col].dropna().values
        if len(a) and len(b):
            x = a[:, None] - b[None, :]
            good += (x > 0).sum() + 0.5 * (x == 0).sum()
            tot += x.size
    return good / tot if tot else None


def auc(col, d=df):
    d = d.dropna(subset=[col])
    return roc_auc_score(d.fit, d[col]) if len(d) and d.fit.nunique() == 2 else None


def rnd(x, n):
    return None if x is None or x != x else round(float(x), n)


def line(col, d=df):
    return {"fit_avg": rnd(d[d.fit == 1][col].mean(), 1), "nofit_avg": rnd(d[d.fit == 0][col].mean(), 1),
            "auc": rnd(auc(col, d), 3), "pairwise": rnd(pairwise(col, d), 3), "measured": int(d[col].notna().sum())}


out = {"pairs_scored": len(df), "errors": dict(errors), "jobs": df.job.nunique(), "fit": int(df.fit.sum()),
       "job_match": line("job_match"), "score": line("score"), "tfidf_baseline": line("tfidf"),
       "skills_combined": line("skills"), "checks": {}}
for c, name in CHECKS.items():
    out["checks"][c] = dict(name=name, **line(c), share_at_100=round((df[c] >= 99.9).mean(), 2),
                            share_at_0=round((df[c] <= 0.1).mean(), 2))
# the "good match" line: the score where most fit resumes start, and the line that separates best
fit_jm, no_jm = df[df.fit == 1].job_match, df[df.fit == 0].job_match
best = max(((t, (fit_jm >= t).mean() - (no_jm >= t).mean()) for t in np.arange(0, 100.5, 0.5)), key=lambda x: x[1])
out["good_match_line"] = {
    "p25_of_fit": round(fit_jm.quantile(.25), 1), "median_fit": round(fit_jm.median(), 1),
    "median_nofit": round(no_jm.median(), 1), "best_split": float(best[0]),
    "at_best": {"fit_above": round((fit_jm >= best[0]).mean(), 2), "nofit_above": round((no_jm >= best[0]).mean(), 2)}}
for t in (30, 35, 40, 45, 50, 55, 60):
    out["good_match_line"][f"at_{t}"] = {"fit_above": round((fit_jm >= t).mean(), 2),
                                         "nofit_above": round((no_jm >= t).mean(), 2)}
# keyword count per job vs pairwise accuracy
df["n_kw"] = df.job.map(lambda j: jobs[j]["n_required"] + jobs[j]["n_preferred"])
for name, d in (("jobs with < 10 skills", df[df.n_kw < 10]), ("jobs with 10+ skills", df[df.n_kw >= 10])):
    out.setdefault("by_keyword_count", {})[name] = {"jobs": d.job.nunique(), "pairwise_job_match": rnd(pairwise(
        "job_match", d), 3), "pairwise_tfidf": rnd(pairwise("tfidf", d), 3)}
# per job: which jobs the Lab gets wrong
per_job = []
for j, g in df.groupby("job"):
    per_job.append({"job": j, "title": jobs[j]["title"], "n_kw": int(g.n_kw.iloc[0]),
                    "pairwise": rnd(pairwise("job_match", g), 2), "fit_avg": round(g[g.fit == 1].job_match.mean(), 1),
                    "nofit_avg": round(g[g.fit == 0].job_match.mean(), 1)})
out["per_job"] = sorted(per_job, key=lambda x: (x["pairwise"] is None, x["pairwise"] or 0))
# keywords that match No Fit resumes as often as Fit ones (too generic to separate)
kw = collections.defaultdict(lambda: [0, 0, 0, 0])            # fit hits, fit n, nofit hits, nofit n
for p in df.itertuples():
    for k in rows[p.pair]["keywords"]:
        if k["type"] == "soft":
            continue
        rec = kw[(p.job, k["term"])]
        hit = k["match"] != "missing"
        if p.fit:
            rec[0] += hit; rec[1] += 1
        else:
            rec[2] += hit; rec[3] += 1
terms = collections.defaultdict(lambda: [0, 0, 0, 0])
for (j, t), v in kw.items():
    for i in range(4):
        terms[t.lower()][i] += v[i]
vague = [{"term": t, "fit_hit": round(v[0] / v[1], 2), "nofit_hit": round(v[2] / v[3], 2), "n": v[1] + v[3]}
         for t, v in terms.items() if v[1] + v[3] >= 12 and v[3] and v[2] / v[3] >= 0.5]
out["vague_keywords"] = sorted(vague, key=lambda x: -x["nofit_hit"])[:20]
allk = [(v[0] / v[1] if v[1] else 0, v[2] / v[3] if v[3] else 0) for v in kw.values()]
out["keyword_hit_rate"] = {"fit": round(np.mean([a for a, _ in allk]), 2), "nofit": round(np.mean([b for _, b in allk]), 2)}
# which weights would separate best: logistic regression on the checks, scored on jobs it did not see (5 folds)
X = df[list(CHECKS)].fillna(0).values / 100
folds = {j: k % 5 for k, j in enumerate(sorted(df.job.unique()))}
pred = np.zeros(len(df))
for k in range(5):
    tr = df.job.map(folds).values != k
    m = LogisticRegression(max_iter=1000).fit(X[tr], df.fit.values[tr])
    pred[~tr] = m.decision_function(X[~tr])
df["refit"] = pred
out["refit_on_checks"] = {"auc": rnd(auc("refit"), 3), "pairwise": rnd(pairwise("refit"), 3),
                          "weights_all_data": dict(zip(CHECKS, np.round(LogisticRegression(max_iter=1000).fit(
                              X, df.fit.values).coef_[0], 2)))}
# the most wrong pairs: a Fit resume with the lowest Job Match, a No Fit resume with the highest
line_ = best[0]
df["wrong_by"] = np.where(df.fit == 1, line_ - df.job_match, df.job_match - line_)
worst = []
for p in df.sort_values("wrong_by", ascending=False).head(10).itertuples():
    r = rows[p.pair]
    ks = [k for k in r["keywords"] if k["type"] != "soft"]
    worst.append({"pair": p.pair, "label": p.label, "job_title": jobs[p.job]["title"], "job_match": p.job_match,
                  "score": p.score, "checks": {c: getattr(p, c) for c in CHECKS},
                  "matched": [k["term"] for k in ks if k["match"] != "missing"],
                  "missing": [k["term"] for k in ks if k["match"] == "missing"],
                  "resume_start": texts[p.resume][:300], "years": r["experience_years"],
                  "job_years": jobs[p.job]["min_years"], "job_degree": jobs[p.job]["degree"]})
out["worst"] = worst
json.dump(out, open(os.path.join(S, "analysis.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False,
          default=lambda o: o.item() if hasattr(o, "item") else str(o))
print(json.dumps({k: v for k, v in out.items() if k not in ("worst", "per_job")}, indent=1, ensure_ascii=False,
                 default=lambda o: o.item() if hasattr(o, "item") else str(o)))
print("\nper job (worst 12):")
for x in out["per_job"][:12]:
    print(x)
