"""
A clean start for the ATS Lab app (the Admin page and the User page): empty History, Needs review,
Activity log and daily check counts, and no kept resume file. The settings and the admin accounts stay.

  py -3.12 reset_data.py                show what will go, ask, then clear it
  py -3.12 reset_data.py --dry-run      only show what would go (nothing is deleted, no question)
  py -3.12 reset_data.py --yes          clear it without the question (a script or a scheduled job)
  py -3.12 reset_data.py --caches       also clear cv_reviews\\ and dashboard_jobs\\ (see below)
  py -3.12 reset_data.py --keep-caches  the default: keep both cache folders
  py -3.12 reset_data.py --folder D:\\other\\data    another data folder (default: the app's data folder)

WHAT IT CLEARS
  * History             every check saved by the team or by the User page, and its report
  * Needs review        the same rows, so their notes and their "Reviewed by" go too
  * Activity log        who signed in, checked, reviewed, deleted, exported, changed a setting
  * Daily check counts  so the 3-checks-a-day limit starts fresh for everybody
  * Sign-in locks       the wrong-password counters of the Admin page (one minute locks)
  * Kept resume files   every PDF in the data folder's resumes\\ folder
  * The counters are reset, so a new check starts again as number 1

WHAT IT KEEPS
  * the database file and its tables (the structure never changes)
  * the settings: links, days to keep files, daily limit, the "Needs review" rules
  * the admin accounts and the AI key (they come from the secrets, never from the database)
  * the two cache folders, unless --caches is given: cv_reviews\\ holds the AI's saved reviews and
    dashboard_jobs\\ the saved job descriptions. Both hold text from real users, so clear them when you
    want a clean machine. Note: with cv_reviews\\ empty, the two slow reference tests (test_reference,
    test_strong) need the AI key again, and with dashboard_jobs\\ empty one dashboard test checks its
    resume without a job.

WHERE IT LOOKS
  * the data folder: ATSLAB_DATA_DIR, or the "data" folder next to this script (the app's default)
  * the two cache folders: next to this script
  Nothing else on this computer is read or deleted, and nothing is sent anywhere.
"""

import argparse
import os
import shutil
import sys

import lab_settings as S
import lab_store as H

KEEP_TEXT = ("kept: the database structure, the settings (links, days, limits, review rules) and the admin "
             "accounts (from the secrets)")


def data_folder(folder=None):
    """The data folder to clean: the argument, else the folder the app itself uses."""
    return os.path.abspath(folder) if folder else S.data_dir()


def look(store, caches=()):
    """What is in the app now, as counts (nothing is changed)."""
    out = {"checks": 0, "notes": 0, "reviewed": 0, "activity": 0, "daily": 0, "sign_in": 0, "files": 0,
           "settings": 0, "caches": {}}
    con = store.db()
    try:
        one = lambda sql: con.execute(sql).fetchone()[0]          # noqa: E731
        out["checks"] = one("SELECT COUNT(*) FROM checks")
        out["notes"] = one("SELECT COUNT(*) FROM checks WHERE review_note IS NOT NULL AND review_note <> ''")
        out["reviewed"] = one("SELECT COUNT(*) FROM checks WHERE reviewed_by IS NOT NULL")
        out["activity"] = one("SELECT COUNT(*) FROM admin_log")
        out["daily"] = one("SELECT COUNT(*) FROM daily_checks")
        out["sign_in"] = one("SELECT COUNT(*) FROM login_guard")
        out["settings"] = one("SELECT COUNT(*) FROM settings")
    finally:
        con.close()
    out["files"] = len([n for n in os.listdir(store.files) if os.path.isfile(os.path.join(store.files, n))])
    out["caches"] = {os.path.basename(c): count_files(c) for c in caches}
    return out


def count_files(folder):
    if not os.path.isdir(folder):
        return 0
    return len([n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))])


def reset(folder=None, caches=(), dry_run=False):
    """Clear the app's data (`folder`, the app's own data folder by default).

    `caches` is a list of absolute folders to empty too (cv_reviews, dashboard_jobs). With `dry_run` nothing is
    changed: the call only says what is there. -> {"folder", "before", "after", "removed", "caches", "done"}.
    """
    folder = data_folder(folder)
    store = H.Store(folder)                     # makes the folder, the database and the tables when new
    before = look(store, caches)
    out = {"folder": folder, "before": before, "after": None, "removed": None, "caches": list(caches),
           "done": False}
    if dry_run:
        return out
    out["removed"] = store.clear_data()
    for c in caches:
        if os.path.isdir(c):
            for name in os.listdir(c):
                path = os.path.join(c, name)
                if os.path.isfile(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
    out["after"] = look(store, caches)
    out["done"] = True
    return out


def show(out, dry_run=False):
    """The plain-English summary of what was (or would be) removed."""
    b = out["before"]
    print(f"Data folder: {out['folder']}")
    print(f"  {'would be removed' if dry_run else 'removed'}:")
    print(f"    History: {b['checks']} check(s) - with {b['notes']} note(s) and {b['reviewed']} 'Reviewed by'")
    print(f"    Activity log: {b['activity']} line(s)")
    print(f"    Daily check counts: {b['daily']} row(s) (the daily limit starts fresh)")
    print(f"    Sign-in locks: {b['sign_in']} row(s)")
    print(f"    Kept resume files: {b['files']} file(s)")
    for name, n in (b["caches"] or {}).items():
        print(f"    Cache {name}: {n} file(s)")
    print(f"  kept: {b['settings']} saved setting(s) - links, days, limits, review rules")
    print(f"  {KEEP_TEXT}")
    if out["done"]:
        a = out["after"]
        left = a["checks"] + a["activity"] + a["daily"] + a["files"]
        print(f"Now: History {a['checks']}, Activity log {a['activity']}, daily counts {a['daily']}, "
              f"kept files {a['files']}, saved settings {a['settings']}")
        print("Clean start ready." if left == 0 else "Something is still there: check the numbers above.")
    elif dry_run:
        print("Nothing was deleted (--dry-run).")


def main(argv=None):
    ap = argparse.ArgumentParser(description="A clean start: empty History, Needs review, Activity log, daily "
                                             "counts and no kept resume file. The settings and the admin accounts "
                                             "stay. See the top of this file for the details.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="no question, clear it now")
    ap.add_argument("--dry-run", action="store_true", help="only show what would go")
    ap.add_argument("--caches", action="store_true", help="also clear cv_reviews\\ and dashboard_jobs\\")
    ap.add_argument("--keep-caches", action="store_true", help="keep both cache folders (the default)")
    ap.add_argument("--data-folder", "--folder", dest="folder", default=None,
                    help="the data folder to clean (default: the app's own, ATSLAB_DATA_DIR or data\\)")
    args = ap.parse_args(argv)
    if args.keep_caches and args.caches:
        ap.error("--caches and --keep-caches cannot be used together")
    caches = [os.path.join(S.HERE, name) for name in ("cv_reviews", "dashboard_jobs")] if args.caches else []
    before = reset(folder=args.folder, caches=caches, dry_run=True)
    show(before, dry_run=True)
    if args.dry_run:
        return 0
    if not args.yes:
        answer = input("\nDelete all of this? Type yes to continue: ").strip().lower()
        if answer not in ("y", "yes"):
            print("Stopped. Nothing was deleted.")
            return 1
    out = reset(folder=args.folder, caches=caches, dry_run=False)
    show(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
