"""
Migration: add require_wallet_to_withdraw column to users.

Run this once from the project root (same folder as run.py):

    python -m app.migrations.add_require_wallet_to_withdraw

The migration is idempotent — running it again is safe and does nothing.
"""
from app.db import get_db


def column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return any(r["name"] == column for r in rows)


def table_exists(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?;",
        (table,),
    ).fetchone()
    return row is not None


def run():
    conn = get_db()

    # ---- 1. users.require_wallet_to_withdraw ----
    if not column_exists(conn, "users", "require_wallet_to_withdraw"):
        print("[migration] adding users.require_wallet_to_withdraw")
        conn.execute(
            "ALTER TABLE users ADD COLUMN "
            "require_wallet_to_withdraw INTEGER NOT NULL DEFAULT 0;"
        )
    else:
        print("[migration] users.require_wallet_to_withdraw already exists")

    # ---- 2. platform_flags (older deployments had this table; leave it alone) ----
    if not table_exists(conn, "platform_flags"):
        print("[migration] creating platform_flags (unused but kept for compat)")
        conn.execute(
            """
            CREATE TABLE platform_flags (
              id INTEGER PRIMARY KEY CHECK(id = 1),
              require_wallet_to_withdraw INTEGER NOT NULL DEFAULT 0,
              updated_by TEXT,
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO platform_flags (id, require_wallet_to_withdraw) "
            "VALUES (1, 0);"
        )

    conn.commit()
    conn.close()
    print("[migration] done")


if __name__ == "__main__":
    run()