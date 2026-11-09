# Job Match test on a public labelled set (2026-10-30, Lab v1.3, no scoring change)

Question: does Job Match (with a job description) give "fit" resumes a higher score than "no fit" resumes?
Run with `py -3.12`. Scripts: `jdtest_tools\` (the order: `make_sample.py`, `keywords.py`, `score.py`, `analyze.py`;
the rest are the checks below). Data and results: `jdtest_public\` (in `.gitignore` and `.dockerignore`).

## 1. Data sets

| | AzharAli05/Resume-Screening-Dataset (asked for) | cnamuangtoun/resume-job-description-fit (used) |
|---|---|---|
| Licence | MIT | **none stated** (no dataset card) |
| How the labels were made | not stated; the data is AI-written (77% of resumes start "Here's a professional resume for ..."); the same 5 reasons are each used ~700 times for any role | not stated |
| Language | English | English |
| Rows | 10,174 (select 5,060 / reject 5,114) | 8,000: train 6,241 + test 1,759 (Good Fit / Potential Fit / No Fit) |
| Job descriptions | 3,446, median **18 words** (one sentence); the 700 long ones have 1 resume each | 351, median 308 words, real US postings |
| Signal in the labels (plain text similarity, AUC) | **0.47** (a coin toss is 0.50): **not usable** | 0.68 (train) |

The asked-for set was not used: its labels do not follow the text, so any scorer lands near 50%. The second set has
no licence: used here for an internal test only, never shipped or shared. Its resumes look like the public LiveCareer
scrape ("Jessica Claire", "City, STATE"), with line breaks lost ("SummaryProfessional ...").

## 2. Sample

50 jobs (train split, accepted by the Lab, 3+ of each label), 3 "Good Fit" + 3 "No Fit" each = **300 pairs**
(150 fit), 196 different resumes, 9 fit-vs-no-fit pairs per job. Fixed seed. Potential Fit left out.
Each resume -> a plain one-column PDF (Helvetica 10). The lost line breaks were put back (a heading at the start of a
paragraph, a job line, a date range in a long line on its own line); no word added or removed. After that the Lab reads
a dated job in 91% of the resumes. Job keywords: AI once per job, saved (`sample\lab_jobs\`). Job title typed: the
first line when it is a title (1 job), else the title the AI copied from the posting (49). AI reviewer off.

## 3. Results

| | Fit avg | No fit avg | AUC | Fit beats no fit, same job |
|---|---:|---:|---:|---:|
| **Job Match** | **17.3** | **10.7** | **0.68** | **70%** |
| Resume Score (total) | 26.3 | 22.4 | 0.63 | 65% |
| Plain text similarity (baseline) | | | 0.65 | 66% |
| Skills (F1 found, M1 weighted) | 14.0 / 15.0 | 7.2 / 7.4 | 0.65 / 0.66 | 67% / 67% |
| Meaning match (M3) | 39.9 | 26.3 | 0.64 | 63% |
| Experience level (M5) | 88.0 | 84.5 | 0.57 | 57% |
| Education (M4) | 66.9 | 59.5 | 0.56 | 57% |
| Job title (F3) | 2.0 | 2.7 | 0.50 | 50% (98% score 0: these resumes have no title line) |

Not measured here: past titles (F4, needs a candidate profile), abbreviations (F2, only 8 pairs).
No errors, 300 of 300 scored (11 min, 4 at a time).

- Skills separate best, then the meaning match. Job Match beats the plain text baseline.
- Why the numbers are low: "Good Fit" resumes hold only 14% of the job's skills ("No Fit" 6%). Checked one by one:
  87% of the job skills are really not in the resume, 3% only inside glued words, about 0.3% missed by the Lab.
- The labels are noisy: e.g. a Sales Associate resume is "Good Fit" for a Senior Electrical Engineer; a Sr. Data
  Engineer is "No Fit" for a Data Engineer job.
- Other weights tried offline (same 300 pairs): every change moves the result by 1 point or less (best: M3 x2, 71%
  same-job). Weights learned from the data, tested on unseen jobs: AUC 0.66 (no better than today's 0.68).

**"Good match" line:** on this set the best split is Job Match **6** (77% of fit above, 49% of no fit above); a
quarter of fit resumes are under 6.1; median fit 14.0, no fit 5.8. This reflects resumes not written for the job; it is
not a line to show users.

## 4. Most wrong pairs (5 of each kind)

| Pair | Label | Job | Job Match | Why |
|---|---|---|---:|---|
| J47-R087 | No fit | Data Engineer | 53.7 | Sr. Data Engineer with 8+ years: label doubtful; skills, title, years all match |
| J24-R117 | No fit | Staff Accountant | 46.8 | only 2 job skills ("Accounting", "MPI"): one generic hit = 67% of skills |
| J11-R059 | No fit | Principal Data Engineer | 46.8 | BI developer with Snowflake, Python, SQL, ETL, AWS: generic data skills match |
| J37-R155 | No fit | Senior Software Engineer | 41.8 | Java developer with 7+ years for a 10-year job: the Lab counts 15.7 years from its dates |
| J05-R028 | No fit | Data Analyst | 41.1 | epidemiologist with SQL, Tableau, "data analysis": generic skills |
| J21-R013 | Fit | Software Developer | 1.0 | job skills are Ansible / DevOps / Jenkins; resume is Java web; 2 junk skills ("Software DeveloperLocation", "TXDuration") |
| J21-R106 | Fit | Software Developer | 1.0 | SQA engineer, none of the job's skills |
| J03-R012 | Fit | Software Developer | 1.5 | data analyst for an Ansible / DevOps job: label doubtful |
| J34-R065 | Fit | Manager | 3.2 | posting title is only "Manager"; 12 web / 3D skills, none in the resume |
| J42-R172 | Fit | Senior Electrical Engineer | 3.3 | Sales Associate resume: label wrong; 2 glued skills ("obtainProject Management") |

## 5. Suggestions

1. **Applied in v1.3.** Keywords: split or drop skills that are glued words from a pasted posting ("Software
   DeveloperLocation", "PADuration", "JMockitMockito", "Wiring DesignSchematic"): 9 such skills in 6 of 50 jobs.
2. **Applied in v1.3.** Keywords: 14 of 50 jobs ended with under 10 skills (one with 0, one with 2). With few skills,
   one generic hit gives a big share: lean more on the meaning match when there are under 10.
3. Weights: no strong change justified by this set. If anything: meaning match (M3) a bit higher; keep M4 and M5
   (without them same-job accuracy drops from 70% to 68%). Keep the job title check for real CVs (here it is 0 for
   98% only because these resumes have no headline).
4. Set the "good match" line on 1000Jobs resumes with known outcomes (interviews), not on this set.

## 6. After the v1.3 fixes (same 300 pairs, same saved AI answers)

| | Before | After |
|---|---:|---:|
| Job Match: fit / no fit average | 17.3 / 10.7 | 18.1 / 11.4 |
| Job Match AUC | 0.678 | 0.684 |
| Fit beats no fit, same job | 70.2% | 71.9% |
| ... jobs with under 10 skills | 68.3% (14 jobs) | 71.4% (13 jobs) |
| Skills (F1 / M1), same job | 66.7% / 67.2% | 68.5% / 70.0% |

6 jobs lost their glued skills. The "Staff Accountant" pair where "Accounting" alone counted 67% left the most-wrong
list. Side effect: in a few-skill job, a no-fit resume with a close meaning match rises (J03-R015: 34.5 -> 52.6).
Before: `sample\results_before_fixes.jsonl`, `analysis_before_fixes.json`; after: `results.jsonl`, `analysis.json`.
