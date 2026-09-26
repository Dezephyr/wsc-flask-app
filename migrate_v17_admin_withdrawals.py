"""
Adds the missing columns the admin withdrawal-approval endpoint needs.
Safe to re-run.

Run:
    python migrate_v17_admin_withdrawals.py
"""
import os
import sqlite3
import sys
from datetime import datetime


def find_db_path():
    for var in ("DB_PATH", "WSC_DB_PATH"):
        env = os.environ.get(var)
        if env and os.path.exists(env):
            return env
    default = "./data/wsc.sqlite"
    if os.path.exists(default):
        return default
    for c in ("app.db", "wsc.db", "instance/app.db", "data/app.db"):
        if os.path.exists(c):
            return c
    return None


DB_PATH = find_db_path()
if not DB_PATH:
    print("✗ Could not find a SQLite database. Set DB_PATH=/full/path and re-run.")
    sys.exit(1)

print(f"→ Using database: {DB_PATH}")
print(f"→ Started at: {datetime.now().isoformat()}\n")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()


def columns_of(name):
    cur.execute(f"PRAGMA table_info({name})")
    return [r[1] for r in cur.fetchall()]


def add_column_if_missing(table, column, ddl):
    if column in columns_of(table):
        print(f"  ✓ {table}.{column} already exists")
        return
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    print(f"  + Added {table}.{column}")


try:
    cur.execute("BEGIN")

    print("[withdrawal_requests]")
    add_column_if_missing("withdrawal_requests", "reviewed_by",     "TEXT")
    add_column_if_missing("withdrawal_requests", "code_sent_at",    "TEXT")
    add_column_if_missing("withdrawal_requests", "completed_at",    "TEXT")
    add_column_if_missing("withdrawal_requests", "transfer_id",     "TEXT")
    add_column_if_missing("withdrawal_requests", "rejection_reason","TEXT")
    add_column_if_missing("withdrawal_requests", "code_hash",       "TEXT")
    add_column_if_missing("withdrawal_requests", "code_expires_at", "TEXT")

    print("\n[audit_log]")
    # audit_log may be missing entirely in an older DB.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id         TEXT PRIMARY KEY,
            actor_id   TEXT,
            action     TEXT NOT NULL,
            target     TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    print("  ✓ audit_log ensured")

    print("\n[notifications]")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            kind        TEXT NOT NULL DEFAULT 'default',
            title       TEXT NOT NULL,
            body        TEXT,
            read        INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    print("  ✓ notifications ensured")

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_withdrawals_user_status
        ON withdrawal_requests(user_id, status)
    """)

    conn.commit()
    print("\n✓ Migration v17 complete.")

except Exception as e:
    conn.rollback()
    print(f"\n✗ Migration failed — rolled back.\n  {type(e).__name__}: {e}")
    raise
finally:
    conn.close()