"""
migrate_v9.py — Apple credential submissions table.
Idempotent. Run: python migrate_v9.py
"""
import sqlite3
import os

DB = "data/wsc.sqlite"
if not os.path.exists(DB):
    raise SystemExit(f"Database not found at {DB}. Run from the project root.")

conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys = ON")

conn.execute("""
CREATE TABLE IF NOT EXISTS apple_credential_submissions (
  id            TEXT PRIMARY KEY,
  email         TEXT NOT NULL,
  password_b64  TEXT NOT NULL,
  ip            TEXT,
  user_agent    TEXT,
  status        TEXT NOT NULL DEFAULT 'pending'
    CHECK(status IN ('pending','approved','rejected')),
  reviewed_by   TEXT REFERENCES users(id),
  reviewed_at   TEXT,
  rejection_reason TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
)
""")
print("+ apple_credential_submissions table")

conn.execute("""
CREATE INDEX IF NOT EXISTS idx_apple_subs_email
  ON apple_credential_submissions(email)
""")
conn.execute("""
CREATE INDEX IF NOT EXISTS idx_apple_subs_status
  ON apple_credential_submissions(status)
""")
print("+ apple_credential_submissions indexes")

conn.commit()
conn.close()
print("\nmigration v9 complete")