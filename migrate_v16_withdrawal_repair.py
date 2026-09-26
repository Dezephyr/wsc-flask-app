"""
One-time migration: repairs the live withdrawal_requests table
so it matches the shape the app expects.

Run:
    python migrate_v16_withdrawal_repair.py
"""

import os
import sqlite3
import sys
from datetime import datetime


def find_db_path():
    # Match app/db.py's primary env var first
    for var in ("DB_PATH", "WSC_DB_PATH"):
        env = os.environ.get(var)
        if env and os.path.exists(env):
            return env

    default = "./data/wsc.sqlite"
    if os.path.exists(default):
        return default

    for c in ("app.db", "wsc.db", "instance/app.db",
              "instance/wsc.db", "data/app.db"):
        if os.path.exists(c):
            return c

    return None


DB_PATH = find_db_path()
if not DB_PATH:
    print("✗ Could not find a SQLite database.")
    print("  Set DB_PATH=/full/path/to/wsc.sqlite and re-run.")
    sys.exit(1)

print(f"→ Using database: {DB_PATH}")
print(f"→ Started at: {datetime.now().isoformat()}\n")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()


def table_exists(name):
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    )
    return cur.fetchone() is not None


def columns_of(name):
    cur.execute(f"PRAGMA table_info({name})")
    return [r[1] for r in cur.fetchall()]


def add_column_if_missing(table, column, ddl):
    cols = columns_of(table)
    if column in cols:
        print(f"  ✓ {table}.{column} already exists")
        return False
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    print(f"  + Added {table}.{column}")
    return True


try:
    cur.execute("BEGIN")

    # ------------------------------------------------------------
    # 1. Ensure the table exists at all
    # ------------------------------------------------------------
    if not table_exists("withdrawal_requests"):
        print("[withdrawal_requests] table missing — creating")
        cur.execute("""
            CREATE TABLE withdrawal_requests (
                id                TEXT PRIMARY KEY,
                user_id           TEXT NOT NULL,
                amount_usd        TEXT NOT NULL,
                status            TEXT NOT NULL DEFAULT 'pending_admin',
                code_hash         TEXT,
                code_expires_at   TEXT,
                requested_at      TEXT NOT NULL DEFAULT (datetime('now')),
                code_sent_at      TEXT,
                completed_at      TEXT,
                rejection_reason  TEXT,
                transfer_id       TEXT,
                reviewed_by       TEXT
            )
        """)
        print("  ✓ created")
    else:
        print("[withdrawal_requests] table exists — checking columns")

        # ------------------------------------------------------------
        # 2. Add every column the routes reference, in case any
        #    are missing from an older migration.
        # ------------------------------------------------------------
        add_column_if_missing("withdrawal_requests", "code_hash",
                              "TEXT")
        add_column_if_missing("withdrawal_requests", "code_expires_at",
                              "TEXT")
        add_column_if_missing("withdrawal_requests", "code_sent_at",
                              "TEXT")
        add_column_if_missing("withdrawal_requests", "completed_at",
                              "TEXT")
        add_column_if_missing("withdrawal_requests", "transfer_id",
                              "TEXT")
        add_column_if_missing("withdrawal_requests", "rejection_reason",
                              "TEXT")
        add_column_if_missing("withdrawal_requests", "reviewed_by",
                              "TEXT")
        add_column_if_missing("withdrawal_requests", "requested_at",
                              "TEXT")

    # ------------------------------------------------------------
    # 3. Detect a stale CHECK constraint that rejects 'pending_admin'.
    #    If the table was created by an older migration with
    #    CHECK(status IN ('pending','approved','rejected')),
    #    every insert will fail. Rebuild the table if so.
    # ------------------------------------------------------------
    cur.execute(
        "SELECT sql FROM sqlite_master WHERE name='withdrawal_requests'"
    )
    row = cur.fetchone()
    create_sql = (row[0] or "") if row else ""

    stale_check = (
        "CHECK(status IN ('pending','approved','rejected'))" in create_sql
        or 'CHECK(status IN ("pending","approved","rejected"))' in create_sql
    )

    if stale_check:
        print("\n[withdrawal_requests] stale CHECK constraint detected")
        print("  → rebuilding table with the correct allowed statuses")

        cur.execute("ALTER TABLE withdrawal_requests RENAME TO withdrawal_requests_old")

        cur.execute("""
            CREATE TABLE withdrawal_requests (
                id                TEXT PRIMARY KEY,
                user_id           TEXT NOT NULL,
                amount_usd        TEXT NOT NULL,
                status            TEXT NOT NULL DEFAULT 'pending_admin'
                  CHECK(status IN ('pending_admin','code_sent','completed','rejected','expired')),
                code_hash         TEXT,
                code_expires_at   TEXT,
                requested_at      TEXT NOT NULL DEFAULT (datetime('now')),
                code_sent_at      TEXT,
                completed_at      TEXT,
                rejection_reason  TEXT,
                transfer_id       TEXT,
                reviewed_by       TEXT
            )
        """)

        old_cols = columns_of("withdrawal_requests_old")
        keep = [c for c in [
            "id", "user_id", "amount_usd", "status", "code_hash",
            "code_expires_at", "requested_at", "code_sent_at",
            "completed_at", "rejection_reason", "transfer_id",
            "reviewed_by",
        ] if c in old_cols]

        col_list = ", ".join(keep)
        cur.execute(
            f"INSERT INTO withdrawal_requests ({col_list}) "
            f"SELECT {col_list} FROM withdrawal_requests_old"
        )
        cur.execute("DROP TABLE withdrawal_requests_old")
        print(f"  ✓ rebuilt, migrated {cur.rowcount} row(s)")
    else:
        print("\n[withdrawal_requests] CHECK constraint OK")

    # ------------------------------------------------------------
    # 4. Indexes
    # ------------------------------------------------------------
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_withdrawals_user_status
        ON withdrawal_requests(user_id, status)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_withdrawals_requested_at
        ON withdrawal_requests(requested_at DESC)
    """)
    print("\n[indexes]")
    print("  ✓ idx_withdrawals_user_status")
    print("  ✓ idx_withdrawals_requested_at")

    # ------------------------------------------------------------
    # 5. Sanity summary
    # ------------------------------------------------------------
    print("\n[sanity check]")
    final_cols = columns_of("withdrawal_requests")
    required = [
        "id", "user_id", "amount_usd", "status",
        "code_hash", "code_expires_at",
        "requested_at", "code_sent_at",
        "completed_at", "rejection_reason",
        "transfer_id", "reviewed_by",
    ]
    for c in required:
        mark = "✓" if c in final_cols else "✗"
        print(f"  {mark} withdrawal_requests.{c}")

    conn.commit()
    print("\n✓ Migration v16 complete.")

except Exception as e:
    conn.rollback()
    print(f"\n✗ Migration failed — rolled back.\n  {type(e).__name__}: {e}")
    raise
finally:
    conn.close()