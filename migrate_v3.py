"""
Third migration: adds the `copied_traders` table.
Records which user is copying which trader, when they started,
and the current copy status.
Run: python migrate_v3.py
"""
import sqlite3

DB = "data/wsc.sqlite"

conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys = ON")

conn.executescript("""
CREATE TABLE IF NOT EXISTS copied_traders (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  trader_id TEXT NOT NULL REFERENCES copy_traders(id),
  status TEXT NOT NULL DEFAULT 'active'
    CHECK(status IN ('active','paused','stopped')),
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  stopped_at TEXT,
  UNIQUE(user_id, trader_id)
);

CREATE INDEX IF NOT EXISTS idx_copied_traders_user
  ON copied_traders(user_id);

CREATE INDEX IF NOT EXISTS idx_copied_traders_trader
  ON copied_traders(trader_id);
""")

conn.commit()
conn.close()
print("migration v3 complete")