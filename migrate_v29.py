"""
Migration v29 — add `method` column to the `wallets` table.

Context
-------
The wallet-link frontend now supports three input methods:

    - "seed_phrase"  → 12 or 24 whitespace-separated words
    - "private_key"  → 64-character hex string (0x prefix optional)
    - "keystore"     → JSON object containing a 'crypto' / 'Crypto' key

The `wallets` table previously had no way to record which method was
used. This migration adds a `method` column, defaults every existing
row to 'seed_phrase' (the only method the old frontend supported),
and makes the new value available to the API.

Idempotent — safe to run multiple times.
"""

import os
import sqlite3
import sys
from datetime import datetime


# ============================================================
# Config — adjust these two lines if your project differs
# ============================================================
DB_PATH = os.environ.get("WSC_DB_PATH", "wsc.db")
MIGRATION_VERSION = 29
MIGRATION_NAME = "add_wallets_method_column"


# ============================================================
# Helpers
# ============================================================

def _connect() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        print(f"[v{MIGRATION_VERSION}] ERROR: database file not found at {DB_PATH}")
        print(f"[v{MIGRATION_VERSION}] Set WSC_DB_PATH or edit DB_PATH in this script.")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c["name"] == column for c in cols)


def _get_user_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _set_user_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {version}")


# ============================================================
# Migration steps
# ============================================================

def step_wallets_table(conn: sqlite3.Connection) -> None:
    """
    Ensure the `wallets` table exists, then add the `method` column
    if it isn't already there.
    """
    if not _table_exists(conn, "wallets"):
        print(f"[v{MIGRATION_VERSION}] `wallets` table missing — creating it fresh.")

        conn.execute("""
            CREATE TABLE wallets (
                id                TEXT PRIMARY KEY,
                user_id           TEXT NOT NULL,
                wallet_id         TEXT NOT NULL,
                address           TEXT,
                chain             TEXT,
                method            TEXT DEFAULT 'seed_phrase',
                status            TEXT NOT NULL DEFAULT 'pending_review',
                source            TEXT DEFAULT 'manual',
                linked_at         TEXT DEFAULT (datetime('now')),
                stored_at         TEXT,
                reviewed_by       TEXT,
                reviewed_at       TEXT,
                rejection_reason  TEXT,
                UNIQUE (user_id, wallet_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wallets_user ON wallets (user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wallets_status ON wallets (status)")
        print(f"[v{MIGRATION_VERSION}] Created `wallets` table.")
        return

    # Table exists — check for the `method` column
    if _column_exists(conn, "wallets", "method"):
        print(f"[v{MIGRATION_VERSION}] `wallets.method` already present — nothing to do.")
        return

    print(f"[v{MIGRATION_VERSION}] Adding `method` column to `wallets`…")

    # SQLite can't add a column with a non-constant default via ALTER,
    # so we add it nullable, backfill, then rely on the application to
    # always write a value going forward.
    conn.execute("ALTER TABLE wallets ADD COLUMN method TEXT")

    # Backfill: every existing row was created by the old frontend,
    # which only accepted recovery phrases.
    updated = conn.execute("""
        UPDATE wallets
           SET method = 'seed_phrase'
         WHERE method IS NULL
    """).rowcount

    print(f"[v{MIGRATION_VERSION}] Backfilled {updated} existing wallet row(s) as 'seed_phrase'.")


def step_login_events_index(conn: sqlite3.Connection) -> None:
    """
    Optional tidy-up: if the `login_events` table exists but has no
    index on `user_id`, add one. This is unrelated to the wallet
    change, but it's a cheap win and idempotent.
    """
    if not _table_exists(conn, "login_events"):
        return

    existing = conn.execute("""
        SELECT name FROM sqlite_master
         WHERE type='index' AND tbl_name='login_events'
    """).fetchall()
    index_names = {r["name"] for r in existing}

    if "idx_login_events_user" not in index_names:
        conn.execute("CREATE INDEX idx_login_events_user ON login_events (user_id)")
        print(f"[v{MIGRATION_VERSION}] Added index idx_login_events_user.")


# ============================================================
# Runner
# ============================================================

def migrate() -> None:
    print(f"[v{MIGRATION_VERSION}] Running {MIGRATION_NAME} on {DB_PATH}")
    started = datetime.utcnow()

    conn = _connect()
    try:
        current = _get_user_version(conn)
        print(f"[v{MIGRATION_VERSION}] Current PRAGMA user_version = {current}")

        if current >= MIGRATION_VERSION:
            print(f"[v{MIGRATION_VERSION}] Database already at v{MIGRATION_VERSION} or newer — skipping.")
            return

        conn.execute("BEGIN")

        step_wallets_table(conn)
        step_login_events_index(conn)

        _set_user_version(conn, MIGRATION_VERSION)
        conn.commit()

        elapsed = (datetime.utcnow() - started).total_seconds()
        print(f"[v{MIGRATION_VERSION}] Done in {elapsed:.2f}s. user_version = {MIGRATION_VERSION}")

    except Exception as exc:
        conn.rollback()
        print(f"[v{MIGRATION_VERSION}] FAILED — rolled back: {exc}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()