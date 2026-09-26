"""
migrate_v20.py

Adds:
  1. login_events        — audit trail of successful sign-ins
  2. platform_flags      — singleton row with platform-wide toggles
                           (currently: require_wallet_to_withdraw)

Safe to run multiple times. Uses CREATE TABLE IF NOT EXISTS and
INSERT OR IGNORE, so it never clobbers existing data.

Usage:
    python migrate_v20.py
"""

import sqlite3
import sys
from pathlib import Path


# ------------------------------------------------------------
# Database path — resolved relative to this script's directory,
# so the migration works from any working directory.
# ------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "data" / "wsc.sqlite"


# ------------------------------------------------------------
# Migration statements. Each entry is (description, SQL).
# Running them one at a time lets us commit after each and get
# a clear error message if something fails.
# ------------------------------------------------------------

STATEMENTS = [
    (
        "create login_events table",
        """
        CREATE TABLE IF NOT EXISTS login_events (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          email TEXT,
          ip TEXT,
          user_agent TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
    ),
    (
        "index login_events by created_at",
        """
        CREATE INDEX IF NOT EXISTS idx_login_events_created
          ON login_events(created_at DESC)
        """,
    ),
    (
        "index login_events by user_id",
        """
        CREATE INDEX IF NOT EXISTS idx_login_events_user
          ON login_events(user_id)
        """,
    ),
    (
        "create platform_flags table",
        """
        CREATE TABLE IF NOT EXISTS platform_flags (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          require_wallet_to_withdraw INTEGER NOT NULL DEFAULT 0,
          updated_by TEXT,
          updated_at TEXT
        )
        """,
    ),
    (
        "seed platform_flags singleton row",
        """
        INSERT OR IGNORE INTO platform_flags (id, require_wallet_to_withdraw)
          VALUES (1, 0)
        """,
    ),
]


def run_migration():
    if not DB_PATH.exists():
        print(f"[migrate_v20] Database not found at: {DB_PATH}")
        print("              Update DB_PATH at the top of this script if it moved.")
        sys.exit(1)

    print(f"[migrate_v20] Using database: {DB_PATH}")

    # Record which tables already existed, for the summary printout.
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name IN ('login_events', 'platform_flags')"
        )
        existing = {row["name"] for row in cur.fetchall()}
    finally:
        conn.close()

    had_login_events   = "login_events"   in existing
    had_platform_flags = "platform_flags" in existing

    # Apply each statement in its own transaction so a failure gives
    # a clear "which step failed" message.
    for description, sql in STATEMENTS:
        try:
            c = sqlite3.connect(str(DB_PATH))
            try:
                c.execute(sql)
                c.commit()
            finally:
                c.close()
        except sqlite3.Error as e:
            print(f"[migrate_v20] ERROR while trying to {description}: {e}")
            sys.exit(1)

    # Summary
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) AS n FROM login_events")
        login_count = cur.fetchone()["n"]

        cur.execute(
            "SELECT require_wallet_to_withdraw "
            "FROM platform_flags WHERE id = 1"
        )
        row = cur.fetchone()
        flag_value = bool(row["require_wallet_to_withdraw"]) if row else None

        print()
        print("[migrate_v20] Done.")
        print(f"  login_events table        : "
              f"{'already existed' if had_login_events else 'created'}")
        print(f"  platform_flags table      : "
              f"{'already existed' if had_platform_flags else 'created'}")
        print(f"  login_events row count    : {login_count}")
        if flag_value is None:
            print("  require_wallet_to_withdraw: (row missing — check manually)")
        else:
            print(f"  require_wallet_to_withdraw: {flag_value}")
    finally:
        conn.close()


if __name__ == "__main__":
    run_migration()