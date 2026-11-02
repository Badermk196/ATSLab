"""cnamuangtoun train + test: jobs, labels per job, duplicates, TF-IDF signal per split, overlap of jobs."""
import sys
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import roc_auc_score

tr, te = pd.read_csv(sys.argv[1]), pd.read_csv(sys.argv[2])
for name, df in (("train", tr), ("test", te)):
    print(f"== {name}: rows {len(df)}, jobs {df.job_description_text.nunique()}, resumes {df.resume_text.nunique()}")
    print(df.label.value_counts().to_string())
    g = df.groupby("job_description_text").label.agg(lambda s: (s == "Good Fit").sum()).rename("good").to_frame()
    g["no"] = df.groupby("job_description_text").label.agg(lambda s: (s == "No Fit").sum())
    print("jobs with both Good and No Fit:", ((g.good > 0) & (g.no > 0)).sum(),
          " good/no in them:", g[(g.good > 0) & (g.no > 0)][["good", "no"]].sum().to_dict())
print("jobs in both splits:", len(set(tr.job_description_text) & set(te.job_description_text)))
print("resumes in both splits:", len(set(tr.resume_text) & set(te.resume_text)))
df = tr[tr.label != "Potential Fit"]
y = (df.label == "Good Fit").astype(int).values
vec = TfidfVectorizer(stop_words="english", sublinear_tf=True).fit(pd.concat([df.resume_text, df.job_description_text]))
cos = np.asarray(vec.transform(df.resume_text).multiply(vec.transform(df.job_description_text)).sum(1)).ravel()
print(f"\ntrain tfidf AUC {roc_auc_score(y, cos):.3f}")
good = tot = 0
for _, g in df.assign(x=cos, y=y).groupby("job_description_text"):
    s, r = g[g.y == 1].x.values, g[g.y == 0].x.values
    if len(s) and len(r):
        d = s[:, None] - r[None, :]
        good += (d > 0).sum() + .5 * (d == 0).sum(); tot += d.size
print(f"train pairwise same job {good / tot:.3f} over {tot} pairs")
# a few Good / No Fit pairs for one job, first lines of each resume
job = df.groupby("job_description_text").label.nunique().idxmax()
print("\n--- job:", job[:300])
for _, row in df[df.job_description_text == job].head(8).iterrows():
    print(f"[{row.label}] {row.resume_text[:160]!r}")
