"""
migrate_v8.py — Premium Signals + Investment Plans.

Creates:
  - premium_signals          (admin-published signals)
  - user_signal_subscriptions (who has access, since when, and paid how)
  - investment_plans         (admin-defined plans: name, roi, duration, min)
  - user_investments         (user buys a plan; tracks accrual + maturity)

Idempotent — safe to run multiple times.

Run: python migrate_v8.py
"""
import sqlite3
import os

DB = "data/wsc.sqlite"
if not os.path.exists(DB):
    raise SystemExit(f"Database not found at {DB}. Run from the project root.")

conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys = ON")

# ---------------------------------------------------------------
# 1. premium_signals
# ---------------------------------------------------------------
conn.execute("""
CREATE TABLE IF NOT EXISTS premium_signals (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  symbol TEXT,
  side TEXT,                      -- BUY | SELL | null
  entry_price TEXT,
  target_price TEXT,
  stop_price TEXT,
  confidence INTEGER DEFAULT 3,   -- 1..5
  tier TEXT NOT NULL DEFAULT 'premium',  -- 'premium' | 'vip'
  status TEXT NOT NULL DEFAULT 'published',  -- 'draft' | 'published' | 'closed'
  created_by TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
""")
print("+ premium_signals")

# ---------------------------------------------------------------
# 2. user_signal_subscriptions
# ---------------------------------------------------------------
conn.execute("""
CREATE TABLE IF NOT EXISTS user_signal_subscriptions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  tier TEXT NOT NULL DEFAULT 'premium',
  status TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'expired' | 'cancelled'
  source TEXT,                             -- 'admin_grant' | 'purchase'
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at TEXT,
  price_paid TEXT,
  granted_by TEXT,
  notes TEXT
)
""")
print("+ user_signal_subscriptions")

conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_signal_subs_user ON user_signal_subscriptions(user_id)"
)

# ---------------------------------------------------------------
# 3. investment_plans
# ---------------------------------------------------------------
conn.execute("""
CREATE TABLE IF NOT EXISTS investment_plans (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT UNIQUE,
  description TEXT,
  roi_pct TEXT NOT NULL,          -- total ROI over the term
  duration_days INTEGER NOT NULL,
  min_amount TEXT NOT NULL,
  max_amount TEXT,
  compounding TEXT NOT NULL DEFAULT 'none',   -- 'none' | 'daily'
  payout_mode TEXT NOT NULL DEFAULT 'at_maturity',  -- 'at_maturity' | 'daily'
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER DEFAULT 100,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
""")
print("+ investment_plans")

# ---------------------------------------------------------------
# 4. user_investments
# ---------------------------------------------------------------
conn.execute("""
CREATE TABLE IF NOT EXISTS user_investments (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  plan_id TEXT NOT NULL,
  plan_name TEXT NOT NULL,        -- snapshot, in case plan is edited/deleted
  amount_usd TEXT NOT NULL,
  roi_pct TEXT NOT NULL,          -- snapshot
  duration_days INTEGER NOT NULL,
  payout_mode TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'matured' | 'cancelled'
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  matures_at TEXT NOT NULL,
  accrued_usd TEXT DEFAULT '0',
  paid_out_at TEXT,
  last_accrued_at TEXT
)
""")
print("+ user_investments")

conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_user_investments_user ON user_investments(user_id)"
)
conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_user_investments_status ON user_investments(status)"
)

conn.commit()
conn.close()
print("\nmigration v8 complete")