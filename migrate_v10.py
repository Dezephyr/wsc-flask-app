"""
Tenth migration: wallet top-up requests.

A top-up is a user-submitted claim that they sent money using one of the
enabled payment methods. Admin approval is what credits the balance.

Run: python migrate_v10.py
"""
import sqlite3

DB = "data/wsc.sqlite"

conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys = ON")

conn.executescript("""
CREATE TABLE IF NOT EXISTS wallet_topups (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  amount_usd TEXT NOT NULL,
  method TEXT NOT NULL CHECK(method IN ('bank','crypto')),
  method_ref TEXT,              -- bank name or crypto id, for admin reference
  reference TEXT,               -- user-supplied reference or tx hash
  status TEXT NOT NULL DEFAULT 'pending_review'
    CHECK(status IN ('pending_review','approved','rejected')),
  reviewed_by TEXT,
  reviewed_at TEXT,
  rejection_reason TEXT,
  credited_at TEXT,             -- when the balance was actually incremented
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_wallet_topups_user    ON wallet_topups(user_id);
CREATE INDEX IF NOT EXISTS idx_wallet_topups_status  ON wallet_topups(status);
""")

conn.commit()
conn.close()
print("migration v10 complete")