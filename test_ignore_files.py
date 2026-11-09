"""
Privacy: the folders that hold real user data must be listed in .gitignore AND .dockerignore, so nothing is ever
committed, packed into the web image or uploaded. This test reads both files (a repository or a build is not
needed) and fails when a rule is missing or is put back with "!".

  py -3.12 -m unittest test_ignore_files -v
"""

import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
IGNORE_FILES = (".gitignore", ".dockerignore")
# the private folders of the app: resumes, reports, the history, saved jobs, saved AI reviews and the test data
PRIVATE_FOLDERS = ("cv_reviews/", "dashboard_jobs/", "data/", "release-*/", "calib_*/",
                   "nextsteps-resumes/", "pretest_public/", "jdtest_public/")
ALSO_PRIVATE = (".streamlit/secrets.toml", ".env", ".work/", "outputs/")


def rules(name):
    """The patterns of an ignore file: comments and empty lines left out."""
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]


class TestIgnoreFiles(unittest.TestCase):
    def test_both_ignore_files_are_there(self):
        for name in IGNORE_FILES:
            self.assertTrue(os.path.exists(os.path.join(HERE, name)), f"{name} is missing")

    def test_every_private_folder_is_ignored_in_both_files(self):
        for name in IGNORE_FILES:
            lines = rules(name)
            for pattern in PRIVATE_FOLDERS:
                with self.subTest(file=name, pattern=pattern):
                    self.assertIn(pattern, lines, f"{pattern} is not in {name}")

    def test_the_secrets_and_the_working_folders_are_ignored_in_both_files(self):
        for name in IGNORE_FILES:
            lines = rules(name)
            for pattern in ALSO_PRIVATE:
                with self.subTest(file=name, pattern=pattern):
                    self.assertIn(pattern, lines, f"{pattern} is not in {name}")

    def test_nothing_puts_a_private_folder_back(self):
        """A "!something" line that re-includes a private folder would undo the rule above."""
        for name in IGNORE_FILES:
            for line in rules(name):
                if not line.startswith("!"):
                    continue
                for pattern in PRIVATE_FOLDERS:
                    with self.subTest(file=name, line=line):
                        self.assertNotIn(pattern.rstrip("/"), line, f"{line} puts {pattern} back in {name}")


if __name__ == "__main__":
    unittest.main()
