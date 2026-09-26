"""
Twelfth migration: add proof_path to wallet_topups.

Run: python migrate_v12.py
"""
import sqlite3

DB = "data/wsc.sqlite"
conn = sqlite3.connect(DB)

cols = [r[1] for r in conn.execute("PRAGMA table_info(wallet_topups)").fetchall()]
if "proof_path" not in cols:
    conn.execute("ALTER TABLE wallet_topups ADD COLUMN proof_path TEXT")
    print("Added wallet_topups.proof_path")
else:
    print("wallet_topups.proof_path already exists")

conn.commit()
conn.close()
print("migration v12 complete")