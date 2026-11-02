"""
Speed: the slow, pure readings of a PDF (its text and its layout) are kept by the file's fingerprint (SHA-256 of its
bytes), so the same resume is never read twice in one run, whatever its path or name. The dashboard and the tests
both check the same files again and again (another mode, another job, another test).

- A cached answer is a copy, so a caller can never change what the next caller gets.
- A change to cv_layout.py or ATSLab_v3.py changes the key: an old reading is never used after the rules changed.
- The store and the meaning-match model live in sys.modules, so they survive a reload of the Lab modules.
- ATSLAB_CACHE=0 switches it off; clear() empties it (a test that changes how a PDF is read calls it).

One parse per check: a PDF full of vector drawings can take 20+ seconds to parse, and one check reads the file in
several ways (text, running headers, text version, layout). Inside `one_parse(path)` every open_pdf(path) gives the same
parsed PDF (pdfplumber keeps each page's parsed objects), so the file is parsed once. Per thread: checks running at the
same time never share one.
"""

import collections
import contextlib
import copy
import hashlib
import os
import sys
import threading
import types

import pdfplumber

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_FILES = ("cv_layout.py", "ATSLab_v3.py")
MAX_ENTRIES = 200
ENABLED = os.environ.get("ATSLAB_CACHE", "1") != "0"

SHARED = sys.modules.setdefault("_atslab_shared", types.ModuleType("_atslab_shared"))   # survives reloads
_STORE = SHARED.__dict__.setdefault("read_cache", collections.OrderedDict())
STATS = SHARED.__dict__.setdefault("read_cache_stats", {"hits": 0, "misses": 0})


def shared(name, make):
    """One object per run for things that are slow to build (the meaning-match model, its answers), kept across a
    reload of the Lab modules."""
    return SHARED.__dict__.setdefault(name, make())


def fingerprint(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def code_key():
    return tuple(os.path.getmtime(os.path.join(HERE, n)) for n in CODE_FILES)


def cached(kind, path, args, compute):
    """compute() for this kind of reading of this file, or the copy kept from the last time."""
    if not ENABLED:
        return compute()
    key = (kind, fingerprint(path), args, code_key())
    if key in _STORE:
        _STORE.move_to_end(key)
        STATS["hits"] += 1
        return copy.deepcopy(_STORE[key])
    STATS["misses"] += 1
    value = compute()
    _STORE[key] = copy.deepcopy(value)
    while len(_STORE) > MAX_ENTRIES:
        _STORE.popitem(last=False)
    return value


def clear():
    _STORE.clear()
    STATS.update(hits=0, misses=0)


_OPEN = threading.local()


def _opened():
    if not hasattr(_OPEN, "pdfs"):
        _OPEN.pdfs = {}
    return _OPEN.pdfs


@contextlib.contextmanager
def one_parse(path):
    """Inside this block, open_pdf(path) gives one shared parsed PDF (opened here, closed at the end). Nested blocks
    for the same file reuse the outer one."""
    key, pdfs = os.path.abspath(path), _opened()
    if key in pdfs:
        yield pdfs[key]
        return
    with pdfplumber.open(path) as pdf:
        pdfs[key] = pdf
        try:
            yield pdf
        finally:
            pdfs.pop(key, None)


@contextlib.contextmanager
def open_pdf(path):
    """pdfplumber.open(path), or the PDF already parsed by an enclosing one_parse(path) block (left open for it)."""
    shared_pdf = _opened().get(os.path.abspath(path))
    if shared_pdf is not None:
        yield shared_pdf
        return
    with pdfplumber.open(path) as pdf:
        yield pdf
