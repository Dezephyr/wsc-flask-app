"""
One-time migration: adds referral_code to users and backfills it for existing users.
Run: python migrate_referral.py
"""
import sqlite3
import uuid
import secrets
import string

DB = "data/wsc.sqlite"

def make_code():
    # 8-char code, uppercase letters + digits, no ambiguous chars
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))

conn = sqlite3.connect(DB)
cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]

if "referral_code" not in cols:
    conn.execute("ALTER TABLE users ADD COLUMN referral_code TEXT")
    print("Column referral_code added.")
else:
    print("Column referral_code already exists.")

# Backfill any user without a code
rows = conn.execute("SELECT id, referral_code FROM users").fetchall()
backfilled = 0
for row in rows:
    uid, existing = row
    if not existing:
        # generate a unique one
        while True:
            code = make_code()
            clash = conn.execute(
                "SELECT 1 FROM users WHERE referral_code = ?", (code,)
            ).fetchone()
            if not clash:
                break
        conn.execute("UPDATE users SET referral_code = ? WHERE id = ?", (code, uid))
        backfilled += 1

conn.commit()
conn.close()
print(f"Backfilled {backfilled} user(s) with a referral code.")
print("migration done")