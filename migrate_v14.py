"""
Adds the crypto_stakes table for paper crypto staking.
Run: python migrate_v14.py
"""
import sqlite3

DB = "data/wsc.sqlite"
conn = sqlite3.connect(DB)

conn.execute("""
CREATE TABLE IF NOT EXISTS crypto_stakes (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  coin TEXT NOT NULL,
  amount TEXT NOT NULL,
  term_days INTEGER NOT NULL,
  apy TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  started_at TEXT NOT NULL,
  unlocks_at TEXT,
  rewards_earned TEXT DEFAULT '0',
  unstaked_at TEXT
)
""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_stakes_user ON crypto_stakes(user_id)")
conn.commit()
conn.close()
print("migration v14 complete")