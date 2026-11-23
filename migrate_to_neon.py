"""
Move the ATS Lab's data from this computer into the Postgres database (Neon).

What is moved: the report data only - History, Needs review, the Activity log, the settings, the daily check
counts, the wrong sign-in counters, the signed-in browsers and the teaching records.
What is NOT moved: the uploaded resume files. They stay on this computer: a resume is never stored in the
database (see lab_store.py), so the row keeps its score and its report and only the file stays here.

Usage (on the computer that holds the local data):
    py -3.12 migrate_to_neon.py                  shows what would be moved, changes nothing
    py -3.12 migrate_to_neon.py --go             really moves it
    py -3.12 migrate_to_neon.py --go --replace   replaces what the database already holds with the local data

Without --go this script moves no row: it only creates the tables when they are missing (it has to, to count
what is already there). With --go it moves the rows table by table inside one transaction, so a refusal leaves
the database exactly as it was.

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


def postgres_kinds(con, table):
    """{column: type} of one table as Postgres has it. The target decides the type, not the local file: SQLite
    lets a column declared INTEGER hold text, and Postgres does not."""
    rows = con.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = %s",
                       (table,)).fetchall()
    return {r["column_name"]: (r["data_type"] or "").upper() for r in rows}


def upgrade_old_columns(con):
    """One-time changes for a database created by an earlier version of this file.

    training.check_id holds a reference to a check that is not a number (a hash), so it must be text: otherwise
    Postgres refuses the row and the reference would be lost."""
    kinds = postgres_kinds(con, "training")
    if "check_id" in kinds and "TEXT" not in kinds["check_id"] and "CHARACTER" not in kinds["check_id"]:
        con.execute("ALTER TABLE training ALTER COLUMN check_id TYPE TEXT")


def as_column(kind, value):
    """One value in the type the Postgres column expects. SQLite is loosely typed: a column declared INTEGER can
    hold text there, and Postgres refuses it, so a value that is not a number becomes empty instead of stopping
    the whole move. Nothing is invented: a text value never becomes a number."""
    if value is None:
        return None
    if "INT" in kind:
        for convert in (int, float):
            try:
                return int(convert(str(value).strip()))
            except (TypeError, ValueError):
                continue
        return None
    if "REAL" in kind or "FLOA" in kind or "DOUB" in kind or "NUM" in kind:
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None
    return value if isinstance(value, str) else str(value)


def postgres_count(con, table):
    row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return row[0] if row else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Move the ATS Lab's data into Postgres (Neon).")
    parser.add_argument("--go", action="store_true", help="really move the data (without it nothing changes)")
    parser.add_argument("--replace", action="store_true",
                        help="replace what the database already holds with the local data")
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

    rows = {table: read_local(source, table) for table in TABLES}

    con = lab_db.connect(source)
    try:
        with con:                                   # the tables are created if they are missing
            con.executescript(lab_store.SCHEMA)
            for col, kind in lab_store.NEW_COLUMNS.items():
                con.execute(f"ALTER TABLE checks ADD COLUMN IF NOT EXISTS {col} {kind}")
        kinds = {table: postgres_kinds(con, table) for table in TABLES}
        there = {table: postgres_count(con, table) for table in TABLES}

        if not args.go:
            print("")
            for table in TABLES:
                print(f"  {table:16} local {len(rows[table]):6}    in the database now {there[table]:6}")
            print("")
            print("Nothing was changed (this is a dry run). Add --go to really move the data.")
            return 0

        moved, skipped = {}, []
        with con:                                   # one transaction: a refusal leaves the database untouched
            upgrade_old_columns(con)
            kinds = {table: postgres_kinds(con, table) for table in TABLES}
            for table in TABLES:
                if there[table] and not args.replace:
                    skipped.append((table, len(rows[table]), there[table]))
                    continue
                if there[table]:
                    con.execute(f"DELETE FROM {table}")     # --replace: the local data is the truth
                if not rows[table]:
                    moved[table] = 0
                    continue
                cols = list(rows[table][0].keys())
                marks = ", ".join("%s" for _ in cols)
                sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({marks})"
                for row in rows[table]:
                    values = [as_column(kinds[table].get(c, ""), row[c]) for c in cols]
                    try:
                        con.execute(sql, values)
                    except Exception as exc:
                        raise SystemExit(f"\n{table}: one row was refused by Postgres, so nothing was moved.\n"
                                         f"  {exc}\n  The row is id={row.get('id')!r}. Nothing else was changed.")
                moved[table] = len(rows[table])

            for table in ID_TABLES:                 # the next new row continues after the moved ones
                con.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                            f"COALESCE((SELECT MAX(id) FROM {table}), 1))")
    finally:
        con.close()

    print("")
    for table in TABLES:
        if table in moved:
            print(f"  {table:16} {moved[table]:6} rows moved")
    for table, count, already in skipped:
        print(f"  {table:16} SKIPPED: the database already has {already} rows (the local file has {count}). "
              f"Use --replace to move them as well.")
    print("")
    print("Done. The resume files were not moved: they stay on this computer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
