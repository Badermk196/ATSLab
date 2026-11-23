"""
Move the ATS Lab's data from this computer into the Postgres database (Neon).

What is moved: the report data only - History, Needs review, the Activity log, the settings, the daily check
counts, the wrong sign-in counters, the signed-in browsers and the teaching records.
What is NOT moved: the uploaded resume files. They stay on this computer: a resume is never stored in the
database (see lab_store.py), so the row keeps its score and its report and only the file stays here.

Usage (on the computer that holds the local data):
    py -3.12 migrate_to_neon.py                  shows what would be moved, changes nothing
    py -3.12 migrate_to_neon.py --go             really moves it
    py -3.12 migrate_to_neon.py --go --replace   also moves into a database that already has rows

DATABASE_URL is read from .streamlit/secrets.toml or the environment (never from the code), and it is never
printed. The tables are created if they are not there yet, so the first run on an empty Neon database is safe.
"""

import argparse
import os
import sqlite3
import sys

import lab_db
import lab_settings
import lab_store

TABLES = ("checks", "admin_log", "settings", "daily_checks", "login_guard", "admin_sessions", "training")
ID_TABLES = ("checks", "admin_log", "training")


def local_file(path=None):
    """The local database: the Lab's own data folder, unless another file is given."""
    return path or os.path.join(lab_settings.data_dir(), lab_store.DB_NAME)


def read_local(path, table):
    """Every row of one table of the local database, as dicts. The column names are the same on both sides."""
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(f"SELECT * FROM {table}")]
    finally:
        con.close()


def postgres_count(con, table):
    row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return row[0] if row else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Move the ATS Lab's data into Postgres (Neon).")
    parser.add_argument("--go", action="store_true", help="really move the data (without it nothing changes)")
    parser.add_argument("--replace", action="store_true", help="also move when the database already has rows")
    parser.add_argument("--local", default=None, help="the local database file (default: the Lab's data folder)")
    args = parser.parse_args(argv)

    if not lab_db.is_postgres():
        print("No DATABASE_URL was found, so there is nowhere to move the data to.")
        print("Add DATABASE_URL to .streamlit/secrets.toml (on a server: to the app's secrets), then run this again.")
        return 2

    source = local_file(args.local)
    if not os.path.exists(source):
        print(f"The local database was not found: {source}")
        return 2
    print(f"Local database: {source}")

    con = lab_db.connect(source)
    try:
        with con:
            con.executescript(lab_store.SCHEMA)
            for col, kind in lab_store.NEW_COLUMNS.items():
                con.execute(f"ALTER TABLE checks ADD COLUMN IF NOT EXISTS {col} {kind}")

        moved = {}
        skipped = []
        with con:
            for table in TABLES:
                rows = read_local(source, table)
                there = postgres_count(con, table)
                if there and not args.replace:
                    skipped.append((table, len(rows), there))
                    continue
                if not rows:
                    moved[table] = 0
                    continue
                cols = list(rows[0].keys())
                marks = ", ".join("%s" for _ in cols)
                sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({marks})"
                for row in rows:
                    con.execute(sql, [row[c] for c in cols])
                moved[table] = len(rows)

            for table in ID_TABLES:
                con.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                            f"COALESCE((SELECT MAX(id) FROM {table}), 1))")
    finally:
        con.close()

    print("")
    for table in TABLES:
        if table in moved:
            print(f"  {table:16} {moved[table]:6} rows")
    for table, rows, there in skipped:
        print(f"  {table:16} SKIPPED: Postgres already has {there} rows (the local file has {rows}). "
              f"Use --replace to move them as well.")
    print("")
    print("Done. The resume files were not moved: they stay on this computer." if args.go else
          "Nothing was changed (this was a dry run). Add --go to really move the data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
