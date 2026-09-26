"""
Thirteenth migration: paper trading ledger.

Two tables:
  paper_positions — the current holdings per user per symbol
  paper_trades    — one row per executed order (append-only audit)

Run: python migrate_v13.py
"""
import sqlite3

DB = "data/wsc.sqlite"
conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys = ON")

conn.executescript("""
CREATE TABLE IF NOT EXISTS paper_positions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  symbol TEXT NOT NULL,
  base_asset TEXT NOT NULL,
  quantity TEXT NOT NULL DEFAULT '0',
  avg_cost_usd TEXT NOT NULL DEFAULT '0',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_paper_positions_user ON paper_positions(user_id);

CREATE TABLE IF NOT EXISTS paper_trades (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  symbol TEXT NOT NULL,
  base_asset TEXT NOT NULL,
  side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
  quantity TEXT NOT NULL,
  price_usd TEXT NOT NULL,
  total_usd TEXT NOT NULL,
  binance_order_id TEXT,
  binance_status TEXT,
  raw_response TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_user ON paper_trades(user_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_symbol ON paper_trades(symbol);
""")

conn.commit()
conn.close()
print("migration v13 complete")