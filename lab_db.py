"""
Where the ATS Lab's data lives, in one place.

- On a server (Streamlit Cloud, Render): a Postgres database (Neon). Set DATABASE_URL in the app's secrets.
  Nothing else in the Lab changes.
- On a computer with no DATABASE_URL: the local SQLite file (data/atslab.db), exactly as before, so development
  and the tests need nothing installed and no internet.
- Resume files are NEVER stored in the database: only the report data. The uploaded file stays next to the
  database on disk (see lab_store.Store).

lab_store.py keeps its SQL as it is: both databases are used through the same small connection object
(`execute(sql, args)` with "?" placeholders, `with con:` for one transaction, rows readable by name or position).
Only the few real differences between SQLite and Postgres are translated here, in pg_sql(), and each one is
tested in test_postgres_layer.py.

The Postgres driver is imported only when a DATABASE_URL is set, so a computer without it needs no driver.
"""

import os
import re
import time

import lab_timing as _timing

# Tables whose new id is wanted after an INSERT (checks.add_check uses it; the others are harmless).
INSERT_RETURNING_ID = ("checks", "training", "admin_log", "bugs")
_INSERT_TABLE = re.compile(r"^\s*insert\s+into\s+([a-z_]+)", re.I)
_PRAGMA_TABLE = re.compile(r"^\s*pragma\s+table_info\(\s*([a-z_]+)\s*\)", re.I)


_LOCAL_ONLY = None


def local_only():
    """True when the Lab must never use the server database, whatever DATABASE_URL says.

    Two cases: a test run (some tests clear the data - test_reset_data really calls clear_data - and they would
    wipe the real History), and ATSLAB_LOCAL_DB=1 for a tool that must stay on this computer. The answer is
    worked out once and kept."""
    global _LOCAL_ONLY
    if _LOCAL_ONLY is None:
        import sys
        forced = os.environ.get("ATSLAB_LOCAL_DB") == "1"
        testing = any(name.startswith("test_") for name in list(sys.modules))
        _LOCAL_ONLY = forced or testing
    return _LOCAL_ONLY


def pick(mapping, key):
    """One value out of a secrets mapping: the top level first, then inside any section. A connection string
    written under another section by mistake (e.g. under [admins]) must still be found, so the Lab never fails
    to start over the place of one line."""
    try:
        value = mapping[key]
    except Exception:
        value = None
    if value:
        return str(value)
    try:
        for section in mapping.values():
            if isinstance(section, dict) and section.get(key):
                return str(section[key])
    except Exception:
        pass
    return None


def url():
    """DATABASE_URL from the app's secrets, else from .streamlit/secrets.toml, else from the environment, else
    None (then the local file is used). It is never written in the code, and it is never printed or logged.

    Both secret places are needed: Streamlit's own secrets only load inside a running app, and the migration
    script and the tests run from the command line. A test run always gets None: see local_only()."""
    if local_only():
        return None
    try:
        import streamlit as st
        value = pick(st.secrets, "DATABASE_URL")
        if value:
            return value
    except Exception:
        pass
    value = secrets_file_value("DATABASE_URL")
    if value:
        return value
    return os.environ.get("DATABASE_URL") or None


def secrets_file_value(key):
    """One value from .streamlit/secrets.toml (the file next to the app). None when the file or the key is not
    there. Nothing is printed: a connection string is a secret."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.toml")
    if not os.path.exists(path):
        return None
    try:
        import tomllib
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except Exception:
        return None
    return pick(data, key)


def is_postgres():
    """True when the Lab must use Postgres (a DATABASE_URL is set), False for the local SQLite file."""
    return bool(url())


def connect(path):
    """A connection to the database the Lab must use. `path` is the local SQLite file, used only when no
    DATABASE_URL is set."""
    link = url()
    if link:
        return PgConnection(link)
    import sqlite3
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def pg_sql(sql):
    """The same SQL in Postgres. Only the differences the Lab really uses are translated:

    - "?" placeholders become "%s" (Postgres).
    - SQLite's two-argument MAX(a, b) becomes Postgres' GREATEST(a, b).
    - "INTEGER PRIMARY KEY AUTOINCREMENT" becomes "BIGSERIAL PRIMARY KEY".
    - SQLite's BLOB becomes Postgres' BYTEA (the same bytes).
    - "BEGIN IMMEDIATE" becomes "BEGIN" (the same meaning: this transaction takes the write lock now).
    """
    out = sql.replace("?", "%s")
    out = re.sub(r"\bMAX\(\s*0\s*,", "GREATEST(0,", out, flags=re.I)
    out = re.sub(r"\bINTEGER PRIMARY KEY AUTOINCREMENT\b", "BIGSERIAL PRIMARY KEY", out, flags=re.I)
    out = re.sub(r"\bBEGIN\s+IMMEDIATE\b", "BEGIN", out, flags=re.I)
    out = re.sub(r"\bBLOB\b", "BYTEA", out, flags=re.I)
    return out


class Row:
    """One row, readable by name (row["score"]) or by position (row[0]), exactly like the SQLite rows the rest
    of the Lab already uses. dict(row) and set(row) work too."""

    __slots__ = ("_names", "_values", "_at")

    def __init__(self, names, values):
        self._names = list(names)
        self._values = tuple(values)
        self._at = {n: i for i, n in enumerate(self._names)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._at[key]]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return list(self._names)

    def get(self, key, default=None):
        at = self._at.get(key)
        return default if at is None else self._values[at]

    def items(self):
        return list(zip(self._names, self._values))

    def __repr__(self):
        return "Row(" + ", ".join(f"{k}={v!r}" for k, v in self.items()) + ")"


class PgCursor:
    """A cursor that returns Row objects, so callers keep using row["name"] and row[0]."""

    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid

    def _names(self):
        return [d.name for d in (self._cur.description or [])]

    def fetchall(self):
        names = self._names()
        return [Row(names, row) for row in self._cur.fetchall()]

    def fetchone(self):
        names = self._names()
        row = self._cur.fetchone()
        return None if row is None else Row(names, row)

    def __iter__(self):
        return iter(self.fetchall())


class PgConnection:
    """A Postgres connection that speaks the same small language as the SQLite one used before, so lab_store.py
    and the pages do not have to know which database is behind them.

    - `with con:` is one transaction (commit on success, rollback on error). The connection is NOT closed there:
      the callers close it themselves, as they always did.
    - Setting `isolation_level = None` (the SQLite way of saying "I control the transactions myself") switches the
      connection to autocommit, so the explicit BEGIN / COMMIT / ROLLBACK of Store._atomic really run.
    """

    def __init__(self, link):
        import psycopg
        self._con = psycopg.connect(link, connect_timeout=15)
        self.is_postgres = True

    # --- the same small language as sqlite3 ---
    @property
    def isolation_level(self):
        return None if self._con.autocommit else "default"

    @isolation_level.setter
    def isolation_level(self, value):
        self._con.autocommit = value is None

    def execute(self, sql, args=()):
        table = _PRAGMA_TABLE.match(sql)
        if table:                       # SQLite asks the schema with PRAGMA; Postgres keeps it in a view
            cur = self._con.cursor()
            cur.execute("SELECT column_name AS name FROM information_schema.columns WHERE table_name = %s",
                        (table.group(1),))
            return PgCursor(cur)
        text = pg_sql(sql)
        wanted_id = False
        insert = _INSERT_TABLE.match(text)
        if insert and insert.group(1).lower() in INSERT_RETURNING_ID and "returning" not in text.lower():
            text += " RETURNING id"
            wanted_id = True
        began = time.perf_counter()
        cur = self._con.cursor()
        cur.execute(text, tuple(args))
        _timing.add("database", time.perf_counter() - began)
        out = PgCursor(cur)
        if wanted_id:
            row = cur.fetchone()
            out.lastrowid = row[0] if row else None
        return out

    def executescript(self, script):
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._con.commit()
        else:
            self._con.rollback()
        return False

    keep_open = False           # the Store sets it on the connection it reuses: close() then does nothing

    def close(self):
        if self.keep_open:
            return
        self.force_close()

    def force_close(self):
        try:
            self._con.close()
        except Exception:
            pass

    @property
    def closed(self):
        """True once the connection is closed (or broken), so a cached connection can be replaced."""
        try:
            return bool(self._con.closed)
        except Exception:
            return True
