"""
History of every resume checked (Admin page and User page), in one SQLite file, and the uploaded resume files.
The same file keeps the daily check counts of the User page and the wrong admin sign-ins (counted on the server, so a
page reload never resets them).

- One row per check: date, candidate, who checked it (an admin's name, or "user"), with / without job, job title,
  score, label, the parts, the issues (name, severity, points), why it needs review, and the report itself (so any
  past report can be opened again).
- The uploaded resume file is kept next to the database for `file_days` days (a setting, 30 by default), then
  deleted by cleanup_files(); the row and its report stay.
- No Streamlit here, so it can be tested directly. The folder comes from lab_settings.data_dir() (any server).
"""

import datetime as dt
import json
import os
import re
import sqlite3
import threading

import lab_text as T

DB_NAME = "atslab.db"
FILES = "resumes"
REVIEW_SCORE = 55                 # "Needs review": a score under this (the default; a setting: review_score)
DEFAULT_RULES = {"score": REVIEW_SCORE, "critical": False, "contact": False}
USER = "user"                     # who checked it, for a check made on the User page
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
CLEAN_EVERY = 600                 # seconds: cleanup_files() runs at most this often per store (see maybe_cleanup)

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  checked_by TEXT NOT NULL,
  candidate TEXT,
  file_name TEXT,
  file_path TEXT,
  file_deleted_at TEXT,
  with_job INTEGER NOT NULL DEFAULT 0,
  job_title TEXT,
  score REAL,
  label TEXT,
  parts TEXT,
  issues TEXT,
  review_reasons TEXT,
  reviewed_by TEXT,
  reviewed_at TEXT,
  compared_with TEXT,
  report_body TEXT,
  report_doc TEXT,
  comparison_doc TEXT,
  lead_name TEXT,
  lead_email TEXT,
  review_note TEXT,
  review_facts TEXT
);
CREATE TABLE IF NOT EXISTS admin_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  admin TEXT NOT NULL,
  kind TEXT NOT NULL,
  target TEXT,
  details TEXT
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT,
  changed_by TEXT,
  changed_at TEXT
);
CREATE TABLE IF NOT EXISTS daily_checks (
  day TEXT NOT NULL,
  who TEXT NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, who)
);
CREATE TABLE IF NOT EXISTS login_guard (
  who TEXT PRIMARY KEY,
  tries INTEGER NOT NULL DEFAULT 0,
  locked_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admin_sessions (
  token TEXT PRIMARY KEY,
  admin TEXT NOT NULL,
  created_at TEXT NOT NULL,
  seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS training (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  admin TEXT NOT NULL,
  check_id INTEGER,
  cv TEXT,
  job_title TEXT,
  score REAL,
  issue_id TEXT,
  issue_name TEXT,
  card TEXT,
  reason TEXT,
  note TEXT,
  evidence TEXT
);
"""
KEEP_COUNT_DAYS = 7               # daily check counts older than this are deleted
SESSION_DAYS = 30                 # an admin who stays signed in: the cookie lasts this long without a visit
NEW_COLUMNS = {"review_note": "TEXT", "review_facts": "TEXT"}     # added to a database made by v1.3 or older


def now():
    return dt.datetime.now().replace(microsecond=0)


class Store:
    def __init__(self, folder):
        self.folder = folder
        self.files = os.path.join(folder, FILES)
        os.makedirs(self.files, exist_ok=True)
        self.path = os.path.join(folder, DB_NAME)
        self._last_clean = None
        self._lock = threading.Lock()
        con = self.db()
        try:
            with con:
                con.executescript(SCHEMA)
                have = {r["name"] for r in con.execute("PRAGMA table_info(checks)")}
                for col, kind in NEW_COLUMNS.items():          # an older database: add the new columns, keep the rows
                    if col not in have:
                        con.execute(f"ALTER TABLE checks ADD COLUMN {col} {kind}")
        finally:
            con.close()

    def db(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def _run(self, sql, args=()):
        con = self.db()
        try:
            with con:
                return con.execute(sql, args)
        finally:
            con.close()

    def _all(self, sql, args=()):
        con = self.db()
        try:
            return [dict(r) for r in con.execute(sql, args).fetchall()]
        finally:
            con.close()

    def _atomic(self, work):
        """work(con) inside one write transaction (BEGIN IMMEDIATE): a read and the write that depends on it are
        never split by another check, in this process or another one."""
        with self._lock:
            con = self.db()
            con.isolation_level = None
            try:
                con.execute("BEGIN IMMEDIATE")
                try:
                    out = work(con)
                except BaseException:
                    con.execute("ROLLBACK")
                    raise
                con.execute("COMMIT")
                return out
            finally:
                con.close()

    # --- the free check limit (User page) --------------------------------------------------------------------------
    def reserve_check(self, keys, limit, at=None):
        """Count one check for every key (e.g. the browser and the IP address) when none of them has used
        `limit` checks in total. A visitor gets `limit` free checks, not `limit` per day. -> True when counted,
        False when the limit is reached (nothing counted)."""
        day = (at or now()).date().isoformat()

        def work(con):
            used = [con.execute("SELECT COALESCE(SUM(n), 0) FROM daily_checks WHERE who = ?", (k,)).fetchone()
                    for k in keys]
            if any(u is not None and u[0] >= limit for u in used):
                return False
            for k in keys:
                con.execute("INSERT INTO daily_checks (day, who, n) VALUES (?, ?, 1) "
                            "ON CONFLICT(day, who) DO UPDATE SET n = n + 1", (day, k))
            return True
        return self._atomic(work)

    def release_check(self, keys, at=None):
        """Give back a counted check (it ended with a message, not a score)."""
        self._atomic(lambda con: [con.execute(
            "UPDATE daily_checks SET n = MAX(0, n - 1) WHERE rowid = "
            "(SELECT rowid FROM daily_checks WHERE who = ? ORDER BY day DESC, rowid DESC LIMIT 1)", (k,))
            for k in keys])

    def checks_today(self, keys, at=None):
        """The most checks any of the keys has used in total (the name is kept for older callers)."""
        rows = [self._all("SELECT COALESCE(SUM(n), 0) AS n FROM daily_checks WHERE who = ?", (k,)) for k in keys]
        return max([r[0]["n"] for r in rows if r] or [0])

    # --- wrong admin passwords (per name and per IP address, on the server) -------------------------------------
    def login_wait(self, keys, at=None):
        """Seconds until a sign-in may be tried again for these keys (0: now)."""
        t = at if at is not None else dt.datetime.now().timestamp()
        rows = [self._all("SELECT locked_until FROM login_guard WHERE who = ?", (k,)) for k in keys]
        return max([r[0]["locked_until"] - t for r in rows if r] + [0])

    def login_failed(self, keys, max_tries, lock_seconds, at=None):
        """One more wrong try for every key; the key that reaches `max_tries` tries in a row waits `lock_seconds`."""
        t = at if at is not None else dt.datetime.now().timestamp()

        def work(con):
            for k in keys:
                con.execute("INSERT INTO login_guard (who, tries) VALUES (?, 1) "
                            "ON CONFLICT(who) DO UPDATE SET tries = tries + 1", (k,))
                if con.execute("SELECT tries FROM login_guard WHERE who = ?", (k,)).fetchone()[0] >= max_tries:
                    con.execute("UPDATE login_guard SET tries = 0, locked_until = ? WHERE who = ?",
                                (t + lock_seconds, k))
        self._atomic(work)

    def login_ok(self, keys):
        """A right sign-in: the wrong tries of these keys are forgotten."""
        self._atomic(lambda con: [con.execute("DELETE FROM login_guard WHERE who = ?", (k,)) for k in keys])

    # --- checks -----------------------------------------------------------------------------------------------
    def add_check(self, rec, pdf_bytes=None, when=None):
        """Save one check (`rec` from record_of) and its resume file. -> the new row id."""
        rec = dict(rec, created_at=(when or now()).strftime(TIME_FORMAT))
        for k in ("parts", "issues", "review_reasons", "review_facts"):
            rec[k] = json.dumps(rec.get(k) or ([] if k in ("issues", "review_reasons") else {}))
        cols = [c for c in rec if c in COLUMNS]
        con = self.db()
        try:
            with con:
                cid = con.execute(f"INSERT INTO checks ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                  [rec[c] for c in cols]).lastrowid
                if pdf_bytes:
                    name = f"{cid}_{safe_name(rec.get('file_name'))}"
                    with open(os.path.join(self.files, name), "wb") as f:
                        f.write(pdf_bytes)
                    con.execute("UPDATE checks SET file_path = ? WHERE id = ?", (name, cid))
        finally:
            con.close()
        return cid

    def get(self, cid):
        rows = self._all("SELECT * FROM checks WHERE id = ?", (cid,))
        return decode(rows[0]) if rows else None

    def history(self, limit=1000, rules=None):
        """Every check, newest first (without the report text: the table needs only the summary). Each row's
        review_reasons follow the "Needs review" rules of now (`rules`, default DEFAULT_RULES)."""
        rows = [decode(r) for r in self._all(
            f"SELECT {', '.join(c for c in COLUMNS if c not in HEAVY)}, id FROM checks ORDER BY id DESC LIMIT ?",
            (limit,))]
        for r in rows:
            r["review_reasons"] = reasons_for(facts_of(r), rules)
        return rows

    def needs_review(self, rules=None):
        """Checks with a reason to look at them (under `rules`) that nobody has marked "Reviewed" yet, newest first."""
        return [r for r in self.history(rules=rules) if r["review_reasons"] and not r["reviewed_by"]]

    def mark_reviewed(self, cid, who, note=""):
        """'Reviewed by' who and when, with a note of what was done."""
        self._run("UPDATE checks SET reviewed_by = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
                  (who, now().strftime(TIME_FORMAT), " ".join((note or "").split()) or None, cid))

    def delete_check(self, cid):
        """Remove a check for good: its row (score, report) and its resume file. -> the removed row, or None."""
        row = self.get(cid)
        if row is None:
            return None
        if row["file_path"]:
            try:
                os.remove(os.path.join(self.files, row["file_path"]))
            except FileNotFoundError:
                pass
        self._run("DELETE FROM checks WHERE id = ?", (cid,))
        return row

    def set_lead(self, cid, name, email):
        self._run("UPDATE checks SET lead_name = ?, lead_email = ? WHERE id = ?", (name, email, cid))

    def file_of(self, cid):
        """The kept resume file's bytes, or None (deleted after `file_days`, or never kept)."""
        r = self.get(cid)
        path = r and r["file_path"] and os.path.join(self.files, r["file_path"])
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
        return None

    # --- the 30-day cleanup -----------------------------------------------------------------------------------
    def cleanup_files(self, days, at=None):
        """Delete the resume files of checks older than `days` days. The row (score, report) stays.
        -> how many files were deleted."""
        at = at or now()
        cutoff = (at - dt.timedelta(days=days)).strftime(TIME_FORMAT)
        old = self._all("SELECT id, file_path FROM checks WHERE file_path IS NOT NULL AND created_at < ?", (cutoff,))
        for r in old:
            try:
                os.remove(os.path.join(self.files, r["file_path"]))
            except FileNotFoundError:
                pass
            self._run("UPDATE checks SET file_path = NULL, file_deleted_at = ? WHERE id = ?",
                      (at.strftime(TIME_FORMAT), r["id"]))
        kept = {r["file_path"] for r in self._all("SELECT file_path FROM checks WHERE file_path IS NOT NULL")}
        for name in os.listdir(self.files):            # a file no row points to (e.g. a check that failed midway)
            path = os.path.join(self.files, name)
            if name not in kept and os.path.getmtime(path) < (at - dt.timedelta(days=days)).timestamp():
                os.remove(path)
        self._last_clean = at
        return len(old)

    def maybe_cleanup(self, days):
        """cleanup_files() at most once every CLEAN_EVERY seconds (it runs when a page opens)."""
        with self._lock:
            if self._last_clean is None or (now() - self._last_clean).total_seconds() >= CLEAN_EVERY:
                return self.cleanup_files(days)
        return 0

    # --- the activity log (what the team does) ---------------------------------------------------------------
    def log(self, admin, kind, target="", details="", when=None):
        self._run("INSERT INTO admin_log (at, admin, kind, target, details) VALUES (?, ?, ?, ?, ?)",
                  ((when or now()).strftime(TIME_FORMAT), admin, kind, target or "", details or ""))

    def activity(self, limit=2000):
        """Every logged action, newest first."""
        return self._all("SELECT * FROM admin_log ORDER BY at DESC, id DESC LIMIT ?", (limit,))

    # --- what the team teaches the Lab (the X on an issue card) ----------------------------------------------
    def add_training(self, admin, check_id, cv, job_title, score, card, reason, note="", evidence="", when=None):
        """One issue the team set aside, with the reason. This is the Lab's teaching record: the same issue
        coming back on other resumes is what shows a check needs fixing. -> the new row id."""
        ids = [i.get("id") for i in (card.get("issues") or []) if i.get("id")]
        self._run("INSERT INTO training (at, admin, check_id, cv, job_title, score, issue_id, issue_name, card, "
                  "reason, note, evidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  ((when or now()).strftime(TIME_FORMAT), admin or "", check_id, cv or "", job_title or "", score,
                   ",".join(ids), card.get("name") or "", card.get("key") or "", reason or "",
                   " ".join((note or "").split()), " ".join((evidence or "").split())[:500]))

    def training(self, limit=5000):
        """Every teaching record, newest first."""
        return self._all("SELECT * FROM training ORDER BY at DESC, id DESC LIMIT ?", (limit,))

    def training_counts(self):
        """One row per issue the team set aside: how many times, why, and when it last happened.
        Newest teaching first by count. -> list of dicts."""
        rows = self._all("SELECT issue_id, issue_name, reason, at, cv FROM training")
        out = {}
        for r in rows:
            d = out.setdefault(r["issue_id"] or "", {"issue_id": r["issue_id"] or "", "issue": r["issue_name"] or "",
                                                     "times": 0, "reasons": {}, "last": "", "last_cv": ""})
            d["times"] += 1
            d["reasons"][r["reason"] or ""] = d["reasons"].get(r["reason"] or "", 0) + 1
            if (r["at"] or "") >= d["last"]:
                d["last"], d["last_cv"] = r["at"] or "", r["cv"] or ""
        return sorted(out.values(), key=lambda d: (-d["times"], d["issue"]))

    def delete_training(self, tid):
        self._run("DELETE FROM training WHERE id = ?", (tid,))

    def clear_training(self):
        """Forget every teaching record (the checks, the settings and the accounts stay)."""
        return self._empty("training")["training"]

    # --- settings an admin saved ------------------------------------------------------------------------------
    def saved_settings(self):
        return {r["key"]: r["value"] for r in self._all("SELECT key, value FROM settings")}

    def save_setting(self, key, value, who):
        self._run("INSERT INTO settings (key, value, changed_by, changed_at) VALUES (?, ?, ?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET value = excluded.value, changed_by = excluded.changed_by, "
                  "changed_at = excluded.changed_at", (key, str(value), who, now().strftime(TIME_FORMAT)))

    def clear_setting(self, key):
        self._run("DELETE FROM settings WHERE key = ?", (key,))

    # --- a clean start (reset_data.py) -----------------------------------------------------------------------
    DATA_TABLES = ("checks", "admin_log", "daily_checks", "login_guard", "training")

    def _remove_files(self):
        """Remove every kept resume file (and any file nobody points to). -> how many were removed."""
        gone = 0
        for name in sorted(os.listdir(self.files)):
            path = os.path.join(self.files, name)
            if os.path.isfile(path):
                try:
                    os.remove(path)
                    gone += 1
                except OSError:
                    pass
        return gone

    def _empty(self, *tables):
        """Remove every row of these tables. -> {table: rows removed}. New rows start at 1 again."""
        with self._lock:
            con = self.db()
            try:
                with con:
                    gone = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
                    for t in tables:
                        con.execute(f"DELETE FROM {t}")
                    try:
                        marks = ", ".join("?" for _ in tables)
                        con.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({marks})", tables)
                    except sqlite3.OperationalError:
                        pass
            finally:
                con.close()
        return gone

    def clear_checks(self):
        """A fresh History and Needs review: every check goes, with its kept resume file.
        What stays: the settings, the Activity log, the daily counts and the admin accounts.
        -> {"checks": rows removed, "files": files removed}"""
        gone = self._empty("checks")
        gone["files"] = self._remove_files()
        self._last_clean = None
        return gone

    def clear_log(self):
        """A fresh Activity log (the admin's own action is written after this). -> rows removed."""
        return self._empty("admin_log")["admin_log"]

    def clear_data(self):
        """A clean start: empty History and Needs review (their notes and "Reviewed by" go with the rows), empty
        Activity log, no daily check counts (the daily limit starts fresh for everybody), no sign-in lock counters,
        and no kept resume file.

        What stays: the database file and its tables (Structures never change), the settings an admin saved on the
        Settings view (links, days, limits, the "Needs review" rules) and the admin accounts (they come from the
        secrets, not from here). Nothing is written to the activity log: it must stay empty.

        -> {table: rows removed, ..., "files": files removed}.
        """
        gone = self._empty(*self.DATA_TABLES)
        gone["files"] = self._remove_files()
        self._last_clean = None
        return gone

    # --- staying signed in (a cookie that lasts, so the password is typed once) -------------------------------
    def remember_admin(self, token, admin):
        """Keep this browser signed in as `admin`: only a random token is stored, never a password."""
        stamp = now().strftime(TIME_FORMAT)
        self._run("INSERT INTO admin_sessions (token, admin, created_at, seen_at) VALUES (?, ?, ?, ?) "
                  "ON CONFLICT(token) DO UPDATE SET admin = excluded.admin, seen_at = excluded.seen_at",
                  (token, admin, stamp, stamp))

    def admin_of_token(self, token, days=SESSION_DAYS):
        """The admin this token belongs to, or None (an unknown token, or one that has not been used for `days`).
        A visit keeps the token alive."""
        if not token:
            return None
        rows = self._all("SELECT admin, seen_at FROM admin_sessions WHERE token = ?", (token,))
        if not rows:
            return None
        try:
            seen = dt.datetime.strptime(rows[0]["seen_at"], TIME_FORMAT)
        except (TypeError, ValueError):
            seen = now()
        if (now() - seen).days >= days:
            self.forget_token(token)
            return None
        self._run("UPDATE admin_sessions SET seen_at = ? WHERE token = ?", (now().strftime(TIME_FORMAT), token))
        return rows[0]["admin"]

    def forget_token(self, token):
        """Sign one browser out (the cookie is cleared by the page as well)."""
        if token:
            self._run("DELETE FROM admin_sessions WHERE token = ?", (token,))

    def forget_all_tokens(self):
        """Sign every browser out (used by reset_data.py: a clean start, a fresh sign in). -> rows removed."""
        return self._empty("admin_sessions")["admin_sessions"]


COLUMNS = ("created_at", "checked_by", "candidate", "file_name", "file_path", "file_deleted_at", "with_job",
           "job_title", "score", "label", "parts", "issues", "review_reasons", "reviewed_by", "reviewed_at",
           "compared_with", "report_body", "report_doc", "comparison_doc", "lead_name", "lead_email", "review_note",
           "review_facts")
HEAVY = {"report_body", "report_doc", "comparison_doc"}


def decode(row):
    row = dict(row)
    for k, empty in (("parts", {}), ("issues", []), ("review_reasons", []), ("review_facts", {})):
        if k in row:
            try:
                row[k] = json.loads(row[k]) if row[k] else empty
            except ValueError:
                row[k] = empty
    return row


def safe_name(name):
    name = re.sub(r"[^\w.\- ]+", "_", os.path.basename(name or "resume.pdf")).strip(" .") or "resume.pdf"
    return name[-80:] if name.lower().endswith(".pdf") else name[:76] + ".pdf"


# ---------------------------------------------------------------------------
# From a checked resume to a history row
# ---------------------------------------------------------------------------
def review_facts(r, cards):
    """What the "Needs review" rules look at, kept with the check (the rules can change later in Settings)."""
    sc = r.get("structure_checks") or {}
    return {"score": r["score"], "critical": [c["name"] for c in cards if c["severity"] == "Critical"],
            "no_email": (sc.get("T7") or {}).get("score") == 0,
            "no_phone": (sc.get("T3") or {}).get("detail") == "no phone number"}


def facts_of(row):
    """The facts of a saved check. A check saved before v1.4 has none: they come from its score, its issues and the
    reasons it was saved with."""
    if row.get("review_facts"):
        return row["review_facts"]
    old = row.get("review_reasons") or []
    return {"score": row.get("score") or 0,
            "critical": [i["name"] for i in row.get("issues") or [] if i.get("severity") == "Critical"],
            "no_email": "No email" in old, "no_phone": "No phone" in old}


def reasons_for(facts, rules=None):
    """Why the team should look at this check, under the rules (settings): a score under `score` (the only
    default trigger), and when switched on: a Critical issue, no email or no phone."""
    rules = rules or DEFAULT_RULES
    out = []
    if facts.get("score") is not None and facts["score"] < rules["score"]:
        out.append(T.REVIEW_TEXT["score"].format(n=rules["score"]))
    if rules["critical"] and facts.get("critical"):
        out.append(T.REVIEW_TEXT["critical"].format(names="; ".join(facts["critical"][:3])))
    if rules["contact"]:
        out += [T.REVIEW_TEXT[k] for k in ("no_email", "no_phone") if facts.get(k)]
    return out


def review_reasons(r, cards, rules=None):
    """Why the team should look at this check: by default only a score under 55 (a Critical issue and a missing
    email or phone are options in Settings)."""
    return reasons_for(review_facts(r, cards), rules)


def record_of(r, checked_by, job_title=None, previous=None, client=False, swap=None):
    """The history row of one check (the full report included, so it can be opened again)."""
    import dashboard as D
    cards = D.issue_cards(r)
    rec = {"checked_by": checked_by, "candidate": D.candidate_name(r) or "", "file_name": r.get("cv") or "",
           "with_job": int(r["mode"] == "job"), "job_title": (job_title or r.get("target") or "") if r["mode"] == "job"
           else "", "score": r["score"], "label": r["label"], "parts": r["parts"],
           "issues": [{"name": c["name"], "severity": c["tag"], "points": round(c["points"], 1)} for c in cards],
           "review_reasons": review_reasons(r, cards), "review_facts": review_facts(r, cards),
           "compared_with": previous.get("cv") if previous is not None else None,
           "report_body": D.report_body(r, cards, all_open=True), "report_doc": D.report_document(r, cards)}
    if client and previous is not None:
        rec["comparison_doc"] = D.client_document(r, previous, swap)   # the roles, decided once (see client_pair)
    return rec
