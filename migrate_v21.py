"""
migrate_v21.py

Adds:
  1. users.require_wallet_to_withdraw  (per-user toggle)
       - 1 → user must have an approved wallet on file before withdrawing
       - 0 → user supplies destination details on each withdrawal request

  2. withdrawal_destinations table
       Stores the per-request destination details captured when the flag
       is 0 (bank / crypto / other), so admins can see where the money
       should go before approving.

Safe to run multiple times.

Usage:
    python migrate_v21.py
"""

import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "data" / "wsc.sqlite"


def column_exists(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def run_migration():
    if not DB_PATH.exists():
        print(f"[migrate_v21] DB not found at: {DB_PATH}")
        sys.exit(1)

    print(f"[migrate_v21] Using database: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()

        # ---- 1. users.require_wallet_to_withdraw ----
        # ALTER TABLE ADD COLUMN is not idempotent in SQLite — guard it.
        if column_exists(cur, "users", "require_wallet_to_withdraw"):
            print("  users.require_wallet_to_withdraw: already exists")
        else:
            cur.execute(
                "ALTER TABLE users "
                "ADD COLUMN require_wallet_to_withdraw INTEGER NOT NULL DEFAULT 0"
            )
            conn.commit()
            print("  users.require_wallet_to_withdraw: added")

        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_require_wallet "
            "ON users(require_wallet_to_withdraw)"
        )
        conn.commit()
        print("  index idx_users_require_wallet  : ready")

        # ---- 2. withdrawal_destinations ----
        cur.execute("""
            CREATE TABLE IF NOT EXISTS withdrawal_destinations (
              id TEXT PRIMARY KEY,
              request_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              method TEXT NOT NULL,
              bank_name TEXT,
              account_name TEXT,
              account_number TEXT,
              routing_number TEXT,
              swift TEXT,
              wallet_address TEXT,
              network TEXT,
              note TEXT,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_wd_dest_request
            ON withdrawal_destinations(request_id)
        """)
        conn.commit()
        print("  withdrawal_destinations table   : ready")

        # ---- Summary ----
        cur.execute(
            "SELECT COUNT(*) FROM users WHERE require_wallet_to_withdraw = 1"
        )
        on_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM users")
        total = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM withdrawal_destinations")
        dest_count = cur.fetchone()[0]

        print()
        print(f"[migrate_v21] Done.")
        print(f"  {on_count}/{total} users currently require a linked wallet")
        print(f"  {dest_count} destination rows on file")

    except sqlite3.Error as e:
        conn.rollback()
        print(f"[migrate_v21] ERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    run_migration()