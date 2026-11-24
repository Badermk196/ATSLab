"""
Speed: where the time goes. Cheap, always on, never changes a result.

  with TM.span("pdf reading"): ...      adds the seconds to the "pdf reading" line of this thread
  TM.snapshot()                         {name: (calls, seconds)} of this thread
  TM.reset()                            start a new count (a page run, a check)

The database layer (lab_db.py) adds every statement to the "database" line, so one page run says how many Neon calls it
made and how long they took. profile_speed.py prints the table.
"""

import contextlib
import threading
import time

_LOCAL = threading.local()
_ALL = {}                                   # the same lines for the whole process (the profile script reads these)
_ALL_LOCK = threading.Lock()


def _lines():
    if not hasattr(_LOCAL, "lines"):
        _LOCAL.lines = {}
    return _LOCAL.lines


def add(name, seconds):
    calls, total = _lines().get(name, (0, 0.0))
    _lines()[name] = (calls + 1, total + seconds)
    with _ALL_LOCK:
        calls, total = _ALL.get(name, (0, 0.0))
        _ALL[name] = (calls + 1, total + seconds)


@contextlib.contextmanager
def span(name):
    began = time.perf_counter()
    try:
        yield
    finally:
        add(name, time.perf_counter() - began)


def snapshot():
    return dict(_lines())


def reset():
    _lines().clear()


def snapshot_all():
    """The lines of every thread together (a page run happens in Streamlit's own thread)."""
    with _ALL_LOCK:
        return dict(_ALL)


def reset_all():
    with _ALL_LOCK:
        _ALL.clear()
