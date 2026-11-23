"""
One-time migration: adds `loans` and `copy_traders` tables.
Run: python migrate_add_tables.py
"""
import sqlite3

conn = sqlite3.connect("data/wsc.sqlite")

conn.executescript("""
CREATE TABLE IF NOT EXISTS loans (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  amount_usd TEXT NOT NULL,
  term_months INTEGER NOT NULL,
  purpose TEXT,
  notes TEXT,
  status TEXT NOT NULL DEFAULT 'pending_review'
    CHECK(status IN ('pending_review','pre_qualified','forwarded','approved','rejected')),
  admin_notes TEXT,
  reviewed_by TEXT,
  reviewed_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS copy_traders (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  bio TEXT,
  avatar_url TEXT,
  external_id TEXT,
  provider TEXT,
  roi REAL,
  win_rate REAL,
  total_trades INTEGER DEFAULT 0,
  max_followers INTEGER,
  risk_level TEXT DEFAULT 'low',
  elite INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
""")

conn.commit()
conn.close()
print("migration done")