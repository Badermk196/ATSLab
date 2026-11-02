"""Job Match test sample (cnamuangtoun/resume-job-description-fit, train split).
50 jobs that the Lab accepts as job descriptions and that have 3+ "Good Fit" and 3+ "No Fit" resumes; 3 of each per
job (fixed seed) = 300 pairs. Each resume (text) becomes a plain one-column PDF for this test only.

  py -3.12 -P -E make_sample.py <train.csv> <out folder>
"""
import os
import re
import sys
import textwrap

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

sys.path.insert(0, r"C:\ATSLab")
import ATSLab_v3 as L

SEED, N_JOBS, PER_LABEL = 7, 50, 3
HEADINGS = ["Skills", "Education", "Summary", "Experience", "Education and Training", "Highlights",
            "Professional Summary", "Core Qualifications", "Professional Experience", "Qualifications", "Profile",
            "Work History", "Career Overview", "Work Experience", "Skill Highlights", "Professional Profile",
            "Areas of Expertise", "Technical Skills", "Computer Skills", "Professional Background", "Summary of Skills",
            "Technical Summary", "Educational Background", "Executive Profile", "Career Focus", "Executive Summary",
            "Core Strengths", "Education and Coursework", "Key Skills", "Credentials", "Additional Skills",
            "Other Skills", "Certifications", "Accomplishments", "Additional Information", "Interests", "Languages",
            "Affiliations", "Training", "Professional Affiliations", "Presentations", "Publications"]
HEADING_RE = re.compile(r"^(%s)(?=[A-Z\-:\u2022*])" % "|".join(sorted(map(re.escape, HEADINGS), key=len, reverse=True)))
DATE = r"(?:\d{1,2}/\d{4}|[A-Z][a-z]{2,8}\.? \d{4}|\d{4})"
# 'Accountant,08/2014-05/2015Aspirus – Owen,WI,Perform ...' (title, dates, company – city, state, then the text)
JOB_RE = re.compile(r"(?:^|(?<=[.;!?)\]]))\s*([A-Z][^,.;\n]{1,70}?)\s*,\s*(%s)\s*-\s*(%s|[Cc]urrent|[Pp]resent)\s*"
                    r"([^\n]{0,90}?),\s*([A-Z]{2})\s*,\s*" % (DATE, DATE), re.M)
# 'Code Corp-Software QA TesterBoston,MA,02/2015-PresentExcelled in ...' (company-title+city, state, dates, text)
JOB2_RE = re.compile(r"(?:^|(?<=[.;!?)\]]))\s*([A-Z][^\n|]{2,120}?),\s*([A-Z]{2}|[A-Z][A-Za-z]+)\s*,\s*(%s)\s*-\s*"
                     r"(%s|[Cc]urrent|[Pp]resent)" % (DATE, DATE), re.M)


def restore_lines(text):
    """The scraped text lost its line breaks: put the obvious ones back (a heading at the start of a paragraph on its
    own line; a job header 'Title | Company – City, ST | dates' on its own line). No word is added or removed."""
    text = text.replace("\r", "")
    text = "\n".join(HEADING_RE.sub(lambda m: m.group(1) + "\n", p.strip()) for p in text.split("\n"))
    text = JOB_RE.sub(lambda m: f"\n{m.group(1).strip()} | {m.group(4).strip(' ,')}, {m.group(5)} | "
                                f"{m.group(2)} - {m.group(3)}\n", text)
    text = JOB2_RE.sub(lambda m: f"\n{m.group(1).strip()}, {m.group(2)} | {m.group(3)} - {m.group(4)}\n", text)
    # any other date range inside a long line ('08/2011toPresentSoftware Engineering Manager...'): its own line
    return "\n".join(RANGE_RE.sub(lambda m: f"\n{m.group(1)} - {m.group(2)}\n", l) if len(l) > 150 else l
                     for l in text.split("\n"))


RANGE_RE = re.compile(r"(%s)\s*(?:-|to|–)\s*(%s|[Cc]urrent|[Pp]resent)" % (DATE, DATE))


def to_pdf(text, path):
    """Plain text, one column, Helvetica 10, A4, wrapped at the page width. Characters Helvetica cannot draw -> '?'."""
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    y = height - 50
    text = restore_lines(text).encode("cp1252", "replace").decode("cp1252")
    for para in text.split("\n"):
        for line in textwrap.wrap(para, 100) or [""]:
            if y < 50:
                c.showPage()
                y = height - 50
            c.setFont("Helvetica", 10)
            c.drawString(50, y, line)
            y -= 13
    c.save()


def main(src, out):
    for d in ("jobs", "resumes"):
        os.makedirs(os.path.join(out, d), exist_ok=True)
    df = pd.read_csv(src)
    df = df[df.label.isin(["Good Fit", "No Fit"])]
    counts = df.groupby("job_description_text").label.value_counts().unstack(fill_value=0)
    ok = counts[(counts["Good Fit"] >= PER_LABEL) & (counts["No Fit"] >= PER_LABEL)].index
    ok = [j for j in ok if L.not_a_job_reason(j) is None]
    print(f"jobs with {PER_LABEL}+ of each label and accepted by the Lab: {len(ok)}")
    jobs = pd.Series(sorted(ok)).sample(n=min(N_JOBS, len(ok)), random_state=SEED).tolist()
    resume_id, rows = {}, []
    for j, job in enumerate(jobs, 1):
        jid = f"J{j:02d}"
        with open(os.path.join(out, "jobs", f"{jid}.txt"), "w", encoding="utf-8") as f:
            f.write(job.strip())
        sub = df[df.job_description_text == job]
        for lab in ("Good Fit", "No Fit"):
            for _, r in sub[sub.label == lab].sample(n=PER_LABEL, random_state=SEED).iterrows():
                rid = resume_id.setdefault(r.resume_text, f"R{len(resume_id) + 1:03d}")
                rows.append({"pair": f"{jid}-{rid}", "job": jid, "resume": rid, "label": lab,
                             "fit": int(lab == "Good Fit")})
    for text, rid in resume_id.items():
        to_pdf(text, os.path.join(out, "resumes", f"{rid}.pdf"))
    pd.DataFrame(rows).to_csv(os.path.join(out, "pairs.csv"), index=False)
    pd.DataFrame([{"resume": rid, "text": t} for t, rid in resume_id.items()]).to_csv(
        os.path.join(out, "resumes.csv"), index=False)
    print(f"jobs {len(jobs)}, pairs {len(rows)} (fit {sum(r['fit'] for r in rows)}), resumes {len(resume_id)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
