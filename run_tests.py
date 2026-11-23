"""
Run the Lab's tests and show how long they took.

  py -3.12 run_tests.py --quick       everything except the two slow calibration tests (test_strong, test_reference)
  py -3.12 run_tests.py --reference   only the reference test (every reference resume stays in its range)
  py -3.12 run_tests.py --full        every test (the default)
  py -3.12 run_tests.py --quick test_jobmode test_pdf    only these test files (also with --full)
  add -f to stop at the first failure

The same resume is read only once per run (cv_cache.py), which is what makes --quick fast.
"""

import argparse
import glob
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SLOW = ("test_strong", "test_reference")

# The tests must never touch the server database: some of them clear the data (test_reset_data really calls
# clear_data), and with DATABASE_URL in the secrets that would wipe the real History. lab_db.py also refuses
# Postgres whenever a test module is loaded; this line says it out loud.
os.environ.setdefault("ATSLAB_LOCAL_DB", "1")


def modules(args):
    every = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(HERE, "test_*.py")))
    if args.files:
        names = [f[:-3] if f.endswith(".py") else f for f in args.files]
        unknown = [n for n in names if n not in every]
        if unknown:
            sys.exit(f"no such test file: {', '.join(unknown)}")
        return names
    if args.reference:
        return ["test_reference"]
    if args.quick:
        return [m for m in every if m not in SLOW]
    return every


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true", help="all tests except test_strong and test_reference")
    mode.add_argument("--full", action="store_true", help="every test (default)")
    mode.add_argument("--reference", action="store_true", help="only test_reference")
    ap.add_argument("-f", "--failfast", action="store_true")
    ap.add_argument("files", nargs="*", help="test files to run (without .py)")
    args = ap.parse_args()
    os.chdir(HERE)
    sys.path.insert(0, HERE)
    names = modules(args)
    label = "quick" if args.quick else "reference" if args.reference else "full" if not args.files else "chosen"
    print(f"Running the {label} tests: {len(names)} file(s)", flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    t0 = time.time()
    result = unittest.TextTestRunner(verbosity=1, failfast=args.failfast).run(suite)
    secs = time.time() - t0
    try:
        import cv_cache
        hits, misses = cv_cache.STATS["hits"], cv_cache.STATS["misses"]
        print(f"Readings of PDFs: {misses} made, {hits} reused from the cache")
    except Exception:
        pass
    print(f"TIME: {secs:.0f} s ({secs / 60:.1f} min) for {result.testsRun} tests, "
          f"{len(result.failures)} failed, {len(result.errors)} errors")
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
