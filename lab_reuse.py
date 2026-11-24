"""
Speed: the same file checked again gives the saved result, not a second scoring.

The key is the file's fingerprint (SHA-256 of its bytes) with everything else that decides the result: the job text and
title (or the target role), the mode, the scoring version, whether the AI review is on, and the modification time of
every Lab file. A change to any of them is a new key, so an old result is never shown after the rules changed, and
"same file, same job, same rules" gives the very same score (the score is never recalculated differently).

Only the app's pages use it (check_and_store and the User page); the tests and the golden / reference runs call
run_check directly, so they always score for real. The results are kept in memory (the last MAX_ENTRIES), shared by
all visitors of the server and kept across a reload of the Lab modules. Nothing is written to disk.
"""

import collections
import copy
import hashlib
import os
import threading

import cv_cache

MAX_ENTRIES = 24
ENABLED = os.environ.get("ATSLAB_REUSE", "1") != "0"

_STORE = cv_cache.shared("result_reuse", collections.OrderedDict)
_LOCK = threading.Lock()
STATS = cv_cache.shared("result_reuse_stats", lambda: {"hits": 0, "misses": 0})


def fingerprint(pdf_bytes):
    return hashlib.sha256(pdf_bytes or b"").hexdigest()


def key_for(pdf_bytes, with_job, text, job_title, version, ai_review, code_stamp):
    """Everything the result depends on, as one string."""
    parts = [fingerprint(pdf_bytes), "job" if with_job else "general",
             hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest(),
             " ".join((job_title or "").split()).lower(), str(version), "ai" if ai_review else "noai", str(code_stamp)]
    return "|".join(parts)


def run(check, pdf_bytes, filename, with_job, text, job_title=None, version="", ai_review=False, code_stamp=""):
    """check(pdf_bytes, filename, with_job, text, job_title=...) -> the result, or the saved one for the same
    file + job + rules. A check that raises (a wrong file, the AI busy) is never saved."""
    if not ENABLED or not pdf_bytes:
        return check(pdf_bytes, filename, with_job, text, job_title=job_title)
    key = key_for(pdf_bytes, with_job, text, job_title, version, ai_review, code_stamp)
    with _LOCK:
        hit = _STORE.get(key)
        if hit is not None:
            _STORE.move_to_end(key)
            STATS["hits"] += 1
            res = copy.deepcopy(hit)
        else:
            res = None
    if res is not None:
        res["cv"] = filename                        # the same file under another name: only the name differs
        if isinstance(res.get("v3"), dict):
            res["v3"]["cv"] = filename
        res["_uid"] = hashlib.sha1(os.urandom(12)).hexdigest()[:16]     # one result, one id (never shared)
        res["_reused"] = True
        return res
    res = check(pdf_bytes, filename, with_job, text, job_title=job_title)
    with _LOCK:
        STATS["misses"] += 1
        _STORE[key] = copy.deepcopy(res)
        while len(_STORE) > MAX_ENTRIES:
            _STORE.popitem(last=False)
    return res


def clear():
    with _LOCK:
        _STORE.clear()
        STATS.update(hits=0, misses=0)
