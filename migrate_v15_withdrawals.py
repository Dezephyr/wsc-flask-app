"""
Fifteenth migration.

Adds the withdrawal_requests table.

Flow:
  1. User requests a withdrawal -> row with status 'pending_admin'.
     A 6-digit code is generated and stored hashed at this moment.
  2. Admin approves -> status becomes 'code_sent', user is notified
     and the plaintext code is shown to them.
  3. User confirms -> status becomes 'completed', funds move.
  4. Admin can reject at any pending stage -> status 'rejected'.

Run: python migrate_v15_withdrawals.py
"""
import sqlite3

DB = "data/wsc.sqlite"
conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys = ON")

conn.execute("""
CREATE TABLE IF NOT EXISTS withdrawal_requests (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  amount_usd TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending_admin'
    CHECK(status IN ('pending_admin','code_sent','completed','rejected','expired')),
  code_hash TEXT,
  code_expires_at TEXT,
  requested_at TEXT NOT NULL DEFAULT (datetime('now')),
  code_sent_at TEXT,
  completed_at TEXT,
  reviewed_by TEXT,
  rejection_reason TEXT,
  transfer_id TEXT
)
""")

conn.execute("CREATE INDEX IF NOT EXISTS idx_wdreq_user   ON withdrawal_requests(user_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_wdreq_status ON withdrawal_requests(status)")

conn.commit()
conn.close()
print("migration v15 complete")