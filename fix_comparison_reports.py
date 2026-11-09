"""
Rebuild the client comparison reports in the History that read the two files the wrong way round.

A check made before 2026-11-02 (the role fix) can hold a comparison report that describes the 1000Jobs resume as if
it were the user's own resume: the 1000Jobs resume's own issues and quotes then appear under "Improved" and under
"Issues in the original resume" (a "Career Impact at a Glance" heading, ** marks, "No city in the contact details").
Those reports were made by the app while it was running the older code (the app is started with
`fileWatcherType = "none"`, so it keeps the code it loaded at start-up until it is restarted) - the code itself is
fixed, but the reports already saved keep their old text.

This command finds those reports and rebuilds them from the two files:

    py -3.12 fix_comparison_reports.py                 # look only: what would be rebuilt (nothing is written)
    py -3.12 fix_comparison_reports.py --apply          # rebuild them and save
    py -3.12 fix_comparison_reports.py --apply --also "C:\\folder"     # look there too for the other file

For each report: the row's own kept file is read again, the other file is looked up by name among the files the app
kept (or in a folder given with --also), the roles are decided by the 1000Jobs marks (dashboard.client_pair) and the
report is rebuilt with dashboard.client_document. The old report is saved to `.work/fixed_reports/backup-<id>.html`
before anything is written, so nothing is lost. Scores, dates and every other field of the row stay as they are.

Reports of checks made with a job description are left alone: rebuilding them needs the job text (the row does not
keep it), so they are listed as "re-run this one in the app". The rebuilt report shows today's date in its header.
"""

import argparse
import os
import shutil
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["ATSLAB_AI_REVIEW"] = "0"                   # rebuilding a stored report never needs the AI reviewer
os.environ.pop("OPENROUTER_API_KEY", None)

import dashboard as D                                  # noqa: E402
import lab_settings as S                               # noqa: E402
import lab_store as H                                  # noqa: E402

BACKUP = os.path.join(HERE, ".work", "fixed_reports")
WRONG_MARKS = ("career impact", "select achievements", "prepared with 1000jobs", "**")


def looks_wrong(doc):
    """True when a stored comparison report quotes the 1000Jobs layout as a problem of the user's own resume."""
    flat = " ".join((doc or "").lower().split())
    return any(m in flat for m in WRONG_MARKS)


def kept_file(name):
    """The file the app kept for a resume name ('12_Name_CV.pdf' is the kept copy of 'Name_CV.pdf')."""
    folder = os.path.join(S.data_dir(), H.FILES)
    if not os.path.isdir(folder):
        return None
    for f in os.listdir(folder):
        if "_" in f and f.split("_", 1)[1] == name:
            return os.path.join(folder, f)
    return None


def rows_with_comparison(db):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(
            "SELECT id, created_at, file_name, compared_with, with_job, comparison_doc FROM checks "
            "WHERE comparison_doc IS NOT NULL AND compared_with IS NOT NULL ORDER BY id")]
    finally:
        con.close()


def rebuild(row, also, apply_it):
    """-> (what happened, the new report or None)."""
    mine = kept_file(row["file_name"])
    other = kept_file(row["compared_with"]) or next(
        (os.path.join(f, row["compared_with"]) for f in also if os.path.isfile(os.path.join(f, row["compared_with"]))),
        None)
    if not (mine and other):
        return "the two files are not here any more (the other resume was not kept): re-run this one in the app", None
    with open(mine, "rb") as f:
        ours = f.read()
    with open(other, "rb") as f:
        theirs = f.read()
    res = D.run_check(ours, row["file_name"], False, "")
    prev = D.run_check(theirs, row["compared_with"], False, "")
    swap = None                                        # the 1000Jobs marks decide the roles
    doc = D.client_document(res, prev, swap)
    if not apply_it:
        return "would be rebuilt", doc
    os.makedirs(BACKUP, exist_ok=True)
    with open(os.path.join(BACKUP, f"backup-{row['id']}.html"), "w", encoding="utf-8") as f:
        f.write(row["comparison_doc"] or "")
    store = H.Store(S.data_dir())
    store._run("UPDATE checks SET comparison_doc = ? WHERE id = ?", (doc, row["id"]))
    return "rebuilt (the old report is in .work/fixed_reports)", doc


def main():
    ap = argparse.ArgumentParser(description="Rebuild stored client comparison reports that read the files the "
                                             "wrong way round (look only without --apply).")
    ap.add_argument("--apply", action="store_true", help="write the rebuilt reports (without it: look only)")
    ap.add_argument("--also", action="append", default=[], help="another folder to look in for the other file")
    args = ap.parse_args()

    db = os.path.join(S.data_dir(), H.DB_NAME)
    rows = rows_with_comparison(db)
    print(f"{len(rows)} stored comparison report(s) in {db}")
    todo = wrong = 0
    for row in rows:
        if not looks_wrong(row["comparison_doc"]):
            print(f"  id={row['id']} {row['created_at']}  fine (the two files are read the right way round)")
            continue
        wrong += 1
        if row["with_job"]:
            print(f"  id={row['id']} {row['created_at']}  read the wrong way round, but the check had a job "
                  f"description: re-run it in the app")
            continue
        what, doc = rebuild(row, args.also, args.apply)
        if doc:
            todo += 1
        print(f"  id={row['id']} {row['created_at']}  {what}")
    print(f"\n{wrong} report(s) read the two files the wrong way round; "
          f"{todo} {'rebuilt' if args.apply else 'would be rebuilt'}")
    if wrong and not args.apply:
        print("run again with --apply to write them (the old reports are backed up first)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
