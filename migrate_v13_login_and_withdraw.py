"""
migrate_v13_login_and_withdraw.py

Adds the columns the withdrawal flow (and login-related tables) depend on.

Safe to re-run:
  - Checks existing schema with PRAGMA table_info before ALTERing.
  - Uses IF NOT EXISTS for new tables.
  - Wraps everything in a transaction.

Run:
    python migrate_v13_login_and_withdraw.py

If your app uses a specific DB path, set WSC_DB_PATH or edit DB_PATH below.
"""

import os
import sqlite3
import sys
from datetime import datetime


# ---------------------------------------------------------------
# 1. Locate the database
# ---------------------------------------------------------------
def find_db_path():
    """
    Resolution order:
      1. $DB_PATH environment variable (what app/db.py uses)
      2. $WSC_DB_PATH environment variable
      3. ./data/wsc.sqlite (the app's default)
      4. Common fallback locations
    """
    # 1. Match app/db.py's primary env var
    env = os.environ.get("DB_PATH")
    if env and os.path.exists(env):
        return env

    # 2. Legacy / alternate env var
    env = os.environ.get("WSC_DB_PATH")
    if env and os.path.exists(env):
        return env

    # 3. The app's actual default — this is the one that matters
    default = "./data/wsc.sqlite"
    if os.path.exists(default):
        return default

    # 4. Common fallbacks
    candidates = [
        "app.db",
        "wsc.db",
        "instance/app.db",
        "instance/wsc.db",
        "database/app.db",
        "backend/app.db",
        "data/app.db",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    # Last resort: walk for any .db
    for root, _dirs, files in os.walk("."):
        if any(skip in root for skip in ("venv", ".venv", "node_modules", ".git")):
            continue
        for f in files:
            if f.endswith(".db"):
                return os.path.join(root, f)

    return None

DB_PATH = find_db_path()
if not DB_PATH:
    print("✗ Could not find a SQLite database.")
    print("  Set WSC_DB_PATH=/full/path/to/your.db and re-run.")
    sys.exit(1)

print(f"→ Using database: {DB_PATH}")
print(f"→ Started at: {datetime.now().isoformat()}")


# ---------------------------------------------------------------
# 2. Helpers
# ---------------------------------------------------------------
def column_exists(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def table_exists(cur, table):
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def add_column_if_missing(cur, table, column, ddl):
    if not table_exists(cur, table):
        print(f"  ⚠ Table '{table}' doesn't exist — skipping '{column}'")
        return False
    if column_exists(cur, table, column):
        print(f"  ✓ {table}.{column} already exists")
        return False
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    print(f"  + Added {table}.{column}")
    return True


# ---------------------------------------------------------------
# 3. Run migrations
# ---------------------------------------------------------------
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

try:
    cur.execute("BEGIN")

    # -----------------------------------------------------------
    # 3a. users table — columns the withdrawal gate reads
    # -----------------------------------------------------------
    print("\n[users]")

    add_column_if_missing(
        cur, "users", "cash_balance",
        "TEXT NOT NULL DEFAULT '0.00'"
    )
    add_column_if_missing(
        cur, "users", "require_wallet_to_withdraw",
        "INTEGER NOT NULL DEFAULT 0"
    )

    # Optional but commonly expected alongside:
    add_column_if_missing(
        cur, "users", "email_notifications",
        "INTEGER NOT NULL DEFAULT 1"
    )
    add_column_if_missing(
        cur, "users", "role",
        "TEXT NOT NULL DEFAULT 'user'"
    )
    add_column_if_missing(
        cur, "users", "referral_code",
        "TEXT"
    )
    add_column_if_missing(
        cur, "users", "full_name",
        "TEXT"
    )
    add_column_if_missing(
        cur, "users", "phone",
        "TEXT"
    )
    add_column_if_missing(
        cur, "users", "country",
        "TEXT"
    )
    add_column_if_missing(
        cur, "users", "created_at",
        "TEXT"
    )

    # Backfill created_at for existing rows missing it
    cur.execute(
        "UPDATE users SET created_at = datetime('now') WHERE created_at IS NULL"
    )
    if cur.rowcount:
        print(f"  + Backfilled created_at on {cur.rowcount} user(s)")

    # Backfill referral_code for existing users from username/email
    cur.execute("""
        UPDATE users
        SET referral_code = LOWER(
            COALESCE(
                NULLIF(username, ''),
                SUBSTR(email, 1, INSTR(email, '@') - 1)
            )
        )
        WHERE (referral_code IS NULL OR referral_code = '')
          AND email IS NOT NULL
    """)
    if cur.rowcount:
        print(f"  + Backfilled referral_code on {cur.rowcount} user(s)")

    # -----------------------------------------------------------
    # 3b. wallets table — the withdrawal gate queries it
    # -----------------------------------------------------------
    print("\n[wallets]")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            id                TEXT PRIMARY KEY,
            user_id           TEXT NOT NULL,
            wallet_id         TEXT NOT NULL,
            address           TEXT NOT NULL,
            chain             TEXT,
            label             TEXT,
            status            TEXT NOT NULL DEFAULT 'pending_review',
            rejection_reason  TEXT,
            created_at        TEXT NOT NULL DEFAULT (datetime('now')),
            reviewed_at       TEXT,
            reviewed_by       TEXT
        )
    """)
    print("  ✓ wallets table ensured")

    # If an older wallets table exists without status, add it.
    add_column_if_missing(
        cur, "wallets", "status",
        "TEXT NOT NULL DEFAULT 'pending_review'"
    )
    add_column_if_missing(
        cur, "wallets", "rejection_reason",
        "TEXT"
    )
    add_column_if_missing(
        cur, "wallets", "label",
        "TEXT"
    )
    add_column_if_missing(
        cur, "wallets", "chain",
        "TEXT"
    )
    add_column_if_missing(
        cur, "wallets", "created_at",
        "TEXT"
    )
    add_column_if_missing(
        cur, "wallets", "reviewed_at",
        "TEXT"
    )
    add_column_if_missing(
        cur, "wallets", "reviewed_by",
        "TEXT"
    )

    # Index for the withdrawal gate's lookup
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_wallets_user_status
        ON wallets(user_id, status)
    """)
    print("  ✓ idx_wallets_user_status")

    # -----------------------------------------------------------
    # 3c. notifications table — code delivery
    # -----------------------------------------------------------
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
    print("  ✓ notifications table ensured")

    add_column_if_missing(cur, "notifications", "read",
                          "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(cur, "notifications", "body",
                          "TEXT")
    add_column_if_missing(cur, "notifications", "kind",
                          "TEXT NOT NULL DEFAULT 'default'")
    add_column_if_missing(cur, "notifications", "created_at",
                          "TEXT")

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_notifications_user_unread
        ON notifications(user_id, read)
    """)
    print("  ✓ idx_notifications_user_unread")

    # -----------------------------------------------------------
    # 3d. withdrawal_requests table
    # -----------------------------------------------------------
    print("\n[withdrawal_requests]")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS withdrawal_requests (
            id                TEXT PRIMARY KEY,
            user_id           TEXT NOT NULL,
            amount_usd        TEXT NOT NULL,
            status            TEXT NOT NULL DEFAULT 'pending_admin',
            code_hash         TEXT,
            code_expires_at   TEXT,
            code_sent_at      TEXT,
            requested_at      TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at      TEXT,
            transfer_id       TEXT,
            rejection_reason  TEXT
        )
    """)
    print("  ✓ withdrawal_requests table ensured")

    # Add columns that older versions may be missing
    add_column_if_missing(cur, "withdrawal_requests", "code_hash",
                          "TEXT")
    add_column_if_missing(cur, "withdrawal_requests", "code_expires_at",
                          "TEXT")
    add_column_if_missing(cur, "withdrawal_requests", "code_sent_at",
                          "TEXT")
    add_column_if_missing(cur, "withdrawal_requests", "completed_at",
                          "TEXT")
    add_column_if_missing(cur, "withdrawal_requests", "transfer_id",
                          "TEXT")
    add_column_if_missing(cur, "withdrawal_requests", "rejection_reason",
                          "TEXT")
    add_column_if_missing(cur, "withdrawal_requests", "requested_at",
                          "TEXT")

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_withdrawals_user_status
        ON withdrawal_requests(user_id, status)
    """)
    print("  ✓ idx_withdrawals_user_status")

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_withdrawals_requested_at
        ON withdrawal_requests(requested_at DESC)
    """)
    print("  ✓ idx_withdrawals_requested_at")

    # -----------------------------------------------------------
    # 3e. transfers table — audit trail written on confirm
    # -----------------------------------------------------------
    print("\n[transfers]")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transfers (
            id            TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            direction     TEXT NOT NULL,
            amount_usd    TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'pending',
            method        TEXT,
            method_ref    TEXT,
            reference     TEXT,
            requested_at  TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at  TEXT
        )
    """)
    print("  ✓ transfers table ensured")

    add_column_if_missing(cur, "transfers", "method",
                          "TEXT")
    add_column_if_missing(cur, "transfers", "method_ref",
                          "TEXT")
    add_column_if_missing(cur, "transfers", "reference",
                          "TEXT")
    add_column_if_missing(cur, "transfers", "completed_at",
                          "TEXT")

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_transfers_user_time
        ON transfers(user_id, requested_at DESC)
    """)
    print("  ✓ idx_transfers_user_time")

    # -----------------------------------------------------------
    # 3f. Sanity check
    # -----------------------------------------------------------
    print("\n[sanity check]")
    for tbl, col in [
        ("users", "cash_balance"),
        ("users", "require_wallet_to_withdraw"),
        ("wallets", "status"),
        ("withdrawal_requests", "code_hash"),
        ("notifications", "read"),
        ("transfers", "direction"),
    ]:
        ok = table_exists(cur, tbl) and column_exists(cur, tbl, col)
        mark = "✓" if ok else "✗"
        print(f"  {mark} {tbl}.{col}")

    conn.commit()
    print("\n✓ Migration v13 complete.")

except Exception as e:
    conn.rollback()
    print(f"\n✗ Migration failed — rolled back.\n  {type(e).__name__}: {e}")
    raise
finally:
    conn.close()