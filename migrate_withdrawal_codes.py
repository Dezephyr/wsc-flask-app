"""
One-time migration: adds the withdrawal_codes side table.

This table holds the plaintext 6-digit code for a withdrawal request
between the moment the user submits it and the moment an admin approves
it. On approval, the plaintext is read, sent to the user, and the row is
deleted. This keeps the plaintext out of `withdrawal_requests` while still
letting the admin see the exact code the user will receive.
"""
import sqlite3
import os
from pathlib import Path

DB = os.environ.get("DB_PATH", "data/wsc.sqlite")
Path(os.path.dirname(DB) or ".").mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys = ON")

# Create the table if it doesn't exist yet
conn.execute("""
CREATE TABLE IF NOT EXISTS withdrawal_codes (
  request_id  TEXT PRIMARY KEY,
  plaintext   TEXT NOT NULL,
  expires_at  TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (request_id) REFERENCES withdrawal_requests(id) ON DELETE CASCADE
);
""")

# Index for cleanup queries
conn.execute("""
CREATE INDEX IF NOT EXISTS idx_withdrawal_codes_expires
  ON withdrawal_codes(expires_at);
""")

conn.commit()

# Report
cols = [r[1] for r in conn.execute("PRAGMA table_info(withdrawal_codes)").fetchall()]
print("withdrawal_codes columns:", cols)
print("migration complete")
conn.close()