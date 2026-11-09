# ATS Lab v1.5-frozen (9 November 2026)

This version is **frozen**. The scoring rules and the checks are locked.

## What "frozen" means

1. **No new rules and no score changes.** Weights, thresholds, severities, caps, gates and the card texts stay
   exactly as they are in this tag.
2. **Real bug fixes only.** A change is allowed when a check is wrong on the rendered page (a false alarm, a missed
   case, a crash, a wording mistake) - never to make a score go up or down.
3. **Every fix must pass both suites before it is used:**
   - `py -3.12 run_tests.py --quick`
   - `py -3.12 run_tests.py --reference`
   A fix that moves a reference resume outside its range must be shown to the team, with the conflict, instead of
   forcing the range.
4. **The golden set is the referee.** Any change to a check is measured against `golden_truth.json` (85 resumes whose
   truth was read from the rendered pages). A check must stay at 90% or better, or it stops changing the score and
   appears on the admin page as "To verify by the team".

## What is in this tag

- The Lab code: `ATSLab_v3.py`, `cv_score.py`, `cv_layout.py`, `cv_vision.py`, `cv_review.py`, the dashboard and the
  admin/user pages.
- The tests, including the golden-set test (`test_golden_set.py`) and the reference ranges (`test_reference.py`,
  `reference_scores.json`).
- The golden-set truth (`golden_truth.json`, `golden_set_manifest.json`) - the labels only, never a resume.
- The deployment kit (`deploy/`, `DEPLOY.md`, `DEPLOY_LIVE.md`) and the two reset commands (`reset_data.py`,
  `fix_comparison_reports.py`).

## What is deliberately NOT in this tag

Real resumes and anything that quotes them: the resume folders, `data/`, `cv_reviews/`, `dashboard_jobs/`, the
generated fixtures, the session working files and the reports. Secrets are never in the repo; `deploy/.env.example`
holds placeholders only. `.gitignore` and `.dockerignore` carry the full list, and `test_ignore_files.py` checks it.

## The measured state at the freeze

| Check | Shown on 85 golden resumes | Right | False alarms | Accuracy |
|---|---|---|---|---|
| No city in the contact details | 18 | 18 | 0 | 100% |
| No experience section found | 7 | 7 | 0 | 100% |
| Printed code or HTML in the text | 3 | 3 | 0 | 100% |
| Job dates missing | 5 | 5 | 0 | 100% |
| Job dates not written as Mon YYYY | 4 | 4 | 0 | 100% |

Tests at the freeze: `run_tests.py --reference` 16 tests OK; `run_tests.py --quick` 592 tests OK (4 skipped).

Two weak-set resumes (`FaisalMicheal_PublicisGroupeHoldingsBV.pdf`, `hanish_Jobgether.pdf`) are outside the 60 cap by
a written team decision: they fail for real reasons only and no false alarm is left in them. The reason is recorded in
`reference_scores.json` (`sets[].exclude_note`) and guarded by `test_reference.py::TestDocumentedExclusions`.
