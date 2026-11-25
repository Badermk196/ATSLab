"""
Speed: load the AI model (the meaning match, ~28 s the first time in a fresh server) in the background as soon as the
server has its first visitor, so the first check does not wait for it.

Before this the first check after every start (and after Streamlit Cloud woke the app up) paid for the safety probe
(a second process that loads the model once), the load itself, and on a clean server the download. Now a background
thread does it while the visitor reads the page and picks a file. Checks that start before it ends wait for it, so
the model is never loaded twice. Nothing here touches a score: it only calls the Lab's own loaders, once.
"""

import os
import sys
import threading
import time

_LOCK = threading.Lock()
_STATE = {"started": False, "done": threading.Event(), "seconds": None, "error": None}


def start():
    """Begin the warm-up (once per server; later calls do nothing). Never during the tests (a module reload in a
    background thread would disturb them), and ATSLAB_WARMUP=0 switches it off."""
    if os.environ.get("ATSLAB_WARMUP") == "0" or any(name.startswith("test_") for name in list(sys.modules)):
        return False
    with _LOCK:
        if _STATE["started"]:
            return False
        _STATE["started"] = True
    try:
        import lab_node
        lab_node.ensure()                       # VeriWorkly's one-time npm install, in its own background thread
    except Exception:
        pass
    threading.Thread(target=_work, name="atslab-warmup", daemon=True).start()
    return True


def _work():
    began = time.perf_counter()
    try:
        import dashboard as D
        D.fresh_modules()                       # the Lab modules are reloaded once, here, not during a visitor's check
        import ATSLab_v3 as L
        if L.embedder_ok():                     # the Lab's own safety probe (saved after the first time)
            L._embedder()                       # loads the model into the shared holder
    except BaseException as e:                  # a failure here never hurts: the first check then loads it itself
        _STATE["error"] = f"{type(e).__name__}: {e}"[:200]
    finally:
        _STATE["seconds"] = time.perf_counter() - began
        _STATE["done"].set()


def wait(timeout=180):
    """Block until the warm-up has finished (at most `timeout` seconds). Does nothing when it never started, or when
    it is already done: a check then goes straight on."""
    if _STATE["started"] and not _STATE["done"].is_set():
        _STATE["done"].wait(timeout)


def status():
    """-> {"started", "done", "seconds", "error"} (for the timing table)."""
    return {"started": _STATE["started"], "done": _STATE["done"].is_set(), "seconds": _STATE["seconds"],
            "error": _STATE["error"]}
