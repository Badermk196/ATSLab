"""
Which version is running: "Version: <short commit hash> · <date>".

The hash and the date come from git (the commit the server checked out), so the Admin page proves which commit
Streamlit really deployed. Where git is not available (a Docker image without .git) the line says so: the numbers are
read from .git files directly as a second try, and the text "unknown" is the last answer. Never raises, never slow
(worked out once per server start).
"""

import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE = []


def _git(*args):
    out = subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, timeout=5)
    return out.stdout.strip() if out.returncode == 0 else ""


def _from_git_files():
    """The commit hash without the git program: .git/HEAD (and packed-refs). The date is not known this way."""
    head_path = os.path.join(HERE, ".git", "HEAD")
    with open(head_path, encoding="utf-8") as f:
        head = f.read().strip()
    if not head.startswith("ref:"):
        return head[:7], ""
    ref = head.split(None, 1)[1]
    try:
        with open(os.path.join(HERE, ".git", *ref.split("/")), encoding="utf-8") as f:
            return f.read().strip()[:7], ""
    except OSError:
        with open(os.path.join(HERE, ".git", "packed-refs"), encoding="utf-8") as f:
            for line in f:
                if line.strip().endswith(" " + ref):
                    return line.split()[0][:7], ""
    return "", ""


def info():
    """-> (short hash, date as YYYY-MM-DD), each "" when unknown. Worked out once."""
    if _CACHE:
        return _CACHE[0]
    found = ("", "")
    try:
        text = _git("log", "-1", "--format=%h|%cs")
        if "|" in text:
            found = tuple(text.split("|", 1))
    except Exception:
        pass
    if not found[0]:
        try:
            found = _from_git_files()
        except Exception:
            pass
    _CACHE.append(found)
    return found


def line():
    """The grey line at the bottom of the Admin page."""
    short, date = info()
    if not short:
        return "Version: unknown (no git information on this server)"
    return f"Version: {short} · {date}" if date else f"Version: {short}"
