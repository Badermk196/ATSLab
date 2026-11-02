# Pre-launch re-test, ATS Lab v1.2 (2026-10-29)

Run with `py -3.12` on this computer. The app tests used a separate test server (port 8600, a test admin account, a
test data folder) in a real browser (Edge, through Playwright). Each test visitor had its own address
(`X-Forwarded-For`, as a proxy in front of the server sends it).

## 1. Robustness: 200 public resumes

Hugging Face set `d4rk3r/resumes-raw-pdf` (MIT licence), a fixed random sample of 200 (`pretest_public\`). Most are
Vietnamese resumes in designed templates, with the contact details removed by the data set.

| | v1.1 | v1.2 |
|---|---|---|
| Crashes / hangs | 0 / 0 | 0 / 0 |
| Checks over 60 s | 1 (63.5 s) | 0 (slowest 15.6 s) |
| Whole run | 19 min | 6 min |
| Scored | 171 | 97 |
| "No text found" (image only) | 29 | 29 |
| "We currently check resumes in English" | - | 72 |
| "This doesn't look like a resume" | - | 2 (bilingual Vietnamese, no English headings, no contact details, no date ranges) |
| Score spread of the scored ones | 3.6 / median 9.8 / 64.0 | 3.6 / median 15.1 / 64.0 |
| "Too many pages" card | 74% (44 of 56 two-page resumes) | 46% (no two-page resume) |

Issues on more than 70% of the scored v1.2 resumes: email missing (100%), no LinkedIn (100%), phone format (99%)
(all three removed by the data set), education details (89%), Mon YYYY job dates (86%), few numbers (83%), section
names (81%, Vietnamese headings), no city (76%), template hard for ATS (74%), page not standard (72%).

## 2. Edge cases (the check itself and the User page in the browser)

| File | v1.2 result |
|---|---|
| Scanned, image only | "No text found in '...'. It may be a scanned image: an ATS cannot read it either." |
| Arabic resume | "We currently check resumes in English. Please upload an English version." |
| Locked with a password | "This PDF is locked with a password. Save it without a password and upload it again." |
| 15 pages | scored, "Strong" (not Excellent): "Too many pages" is Important |
| Over 10 MB | refused by the upload box: "File must be 10.0MB or smaller." (the server checks it too) |
| Word file (.docx), also renamed to .pdf | "Please save your resume as a PDF and upload it again." |
| Invoice | "This doesn't look like a resume. Please upload your resume as a PDF." |
| Damaged PDF | "We could not open 'damaged.pdf'. The file may be damaged. Please save it as a PDF again and upload it again." |
| Empty file | "This file is empty." |

## 3. Security: 31 of 31 passed

- User page: no fixes, points, per-ATS details, AI review, download or admin content; another visitor never sees a
  result; `/admin` shows only the sign-in form.
- Daily limit: checks 1-3 scored, the 4th refused with the message; the same browser from another IP refused; another
  browser from the same IP refused; a new visitor not affected. Messages do not use up a check.
- Admin: wrong password refused; right password with a wrong name refused; after 5 wrong tries even the right password
  waits; the wait survives a reload; it holds for the name from another IP, and for one IP guessing many names.
- HTML / script code in a resume or a job title is never run (User page and Admin report).
- The AI key and the admin password are on no page, in no log, in no database (1,806 files searched).
- First run: 30 of 31. The one failure was the test's own order (it mixed two names from one address, so the address
  locked first and the name never reached 5 counted tries). The order was fixed and the whole test run again: 31 of 31.

## 4. Load: 10 checks at the same time (AI reviewer on)

| | v1.1 (no queue) | v1.2 (3 at a time) |
|---|---|---|
| Page opens | 24 s | 6.5-6.9 s (10 tabs at once) |
| First 3 visitors: score after | 132-154 s | 19.5-20.3 s |
| Others | 132-154 s | 31.8-53.4 s, after "6 people ahead of you" ... "You're next" |
| Errors | 0 crashes, 7 health checks failed | 0 crashes, 0 health checks failed |
| Server log | 40,713 lines (1,104 watcher errors, 42 favicon errors) | 16 lines, no error |
