"""
Second migration: adds tables for notifications, wallets, referral tracking,
loans. Adds preferences column to users.
Run: python migrate_v2.py
"""
import sqlite3

conn = sqlite3.connect("data/wsc.sqlite")
conn.execute("PRAGMA foreign_keys = ON")

# --- users: preferences ---
cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
if "email_notifications" not in cols:
    conn.execute("ALTER TABLE users ADD COLUMN email_notifications INTEGER DEFAULT 1")
    print("Added users.email_notifications")
if "referred_by" not in cols:
    conn.execute("ALTER TABLE users ADD COLUMN referred_by TEXT")
    print("Added users.referred_by")

# --- wallets ---
conn.execute("""
CREATE TABLE IF NOT EXISTS wallets (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  wallet_id TEXT NOT NULL,
  address TEXT NOT NULL,
  chain TEXT,
  linked_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, wallet_id)
)
""")
print("Ensured wallets table")

# --- notifications ---
conn.execute("""
CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT,
  read INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
""")
print("Ensured notifications table")

# --- referrals ---
conn.execute("""
CREATE TABLE IF NOT EXISTS referrals (
  id TEXT PRIMARY KEY,
  referrer_id TEXT NOT NULL REFERENCES users(id),
  referred_user_id TEXT NOT NULL REFERENCES users(id),
  commission_usd TEXT NOT NULL DEFAULT '0',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(referred_user_id)
)
""")
print("Ensured referrals table")

# --- loans: add missing columns if any ---
loan_cols = [r[1] for r in conn.execute("PRAGMA table_info(loans)").fetchall()]
for col, typ in [("notes", "TEXT"), ("admin_notes", "TEXT"), ("reviewed_by", "TEXT"), ("reviewed_at", "TEXT")]:
    if col not in loan_cols:
        conn.execute(f"ALTER TABLE loans ADD COLUMN {col} {typ}")
        print(f"Added loans.{col}")

conn.commit()
conn.close()
print("migration v2 complete")