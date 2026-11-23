"""
migrate_v18_kyc_toggle.py — Add kyc_required to platform_flags.

Enables the admin-controlled toggle that decides whether new signups
are redirected to the KYC form or straight to their dashboard.

Idempotent — safe to run multiple times.

Run: python migrate_v18_kyc_toggle.py
"""
import sqlite3
import os

DB = "data/wsc.sqlite"

if not os.path.exists(DB):
    raise SystemExit(f"Database not found at {DB}. Run from the project root.")

conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys = ON")

# ---------------------------------------------------------------
# Ensure the platform_flags table exists
# ---------------------------------------------------------------
conn.execute("""
CREATE TABLE IF NOT EXISTS platform_flags (
  id INTEGER PRIMARY KEY CHECK(id = 1),
  require_wallet_to_withdraw INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
""")

# Make sure the single row exists
conn.execute("INSERT OR IGNORE INTO platform_flags (id) VALUES (1)")

# ---------------------------------------------------------------
# Add kyc_required if missing
# ---------------------------------------------------------------
cols = [r[1] for r in conn.execute("PRAGMA table_info(platform_flags)").fetchall()]

if "kyc_required" not in cols:
    conn.execute(
        "ALTER TABLE platform_flags ADD COLUMN kyc_required INTEGER NOT NULL DEFAULT 1"
    )
    print("+ platform_flags.kyc_required")
else:
    print("= platform_flags.kyc_required (already present)")

# ---------------------------------------------------------------
# Sanity check: confirm the row exists and has the default value
# ---------------------------------------------------------------
row = conn.execute(
    "SELECT id, kyc_required FROM platform_flags WHERE id = 1"
).fetchone()
print(f"= platform_flags row: id={row[0]}, kyc_required={row[1]}")

conn.commit()
conn.close()
print("\nmigration v18 complete")