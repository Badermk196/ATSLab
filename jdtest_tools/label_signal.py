"""Is there any signal in the labels? Simple text baselines (TF-IDF resume vs job, resume names the role, length):
AUC overall and on pairs that share a job description. Also: does the reason match the resume's role?"""
import sys
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import roc_auc_score

df = pd.read_csv(sys.argv[1])
if "resume_text" in df.columns:                       # cnamuangtoun: No Fit / Potential Fit / Good Fit
    print("rows", len(df), "columns", list(df.columns))
    print(df.label.value_counts().to_string())
    print("job descriptions:", df.job_description_text.nunique(),
          " words median:", df.job_description_text.str.split().str.len().median(),
          " resume words median:", df.resume_text.str.split().str.len().median())
    df = df[df.label != "Potential Fit"].rename(columns={"resume_text": "Resume", "job_description_text": "Job_Description"})
    df["Decision"] = np.where(df.label == "Good Fit", "select", "reject")
    df["Role"] = ""
    df["Reason_for_decision"] = ""
    print("\n--- a resume\n", df.Resume.iloc[0][:700], "\n--- a job\n", df.Job_Description.iloc[0][:700])
df = df.dropna(subset=["Resume", "Job_Description", "Decision"])
y = (df.Decision.str.lower() == "select").astype(int).values
vec = TfidfVectorizer(stop_words="english", sublinear_tf=True).fit(pd.concat([df.Resume, df.Job_Description]))
R, J = vec.transform(df.Resume), vec.transform(df.Job_Description)
cos = np.asarray(R.multiply(J).sum(1)).ravel()
names_role = np.array([r.lower() in s.lower()[:400] for r, s in zip(df.Role, df.Resume)]).astype(float)
words = df.Resume.str.split().str.len().values
for name, x in (("tfidf resume-vs-job", cos), ("role named near top", names_role), ("resume length", words)):
    print(f"{name:22} AUC {roc_auc_score(y, x):.3f}")

def pairwise(x):
    good = tot = 0
    for _, g in df.assign(x=x, y=y).groupby("Job_Description"):
        s, r = g[g.y == 1].x.values, g[g.y == 0].x.values
        if len(s) and len(r):
            d = s[:, None] - r[None, :]
            good += (d > 0).sum() + 0.5 * (d == 0).sum()
            tot += d.size
    return good / tot, tot
acc, n = pairwise(cos)
print(f"pairwise (same job) tfidf: {acc:.3f} over {n} pairs")
# reasons: do 'select' reasons mention things the job is about?
ml = df.Reason_for_decision.str.contains("machine learning|AI and ML", case=False, na=False)
print("\n'ML/AI' reasons by role (top 8):")
print(df[ml].Role.value_counts().head(8).to_string())
