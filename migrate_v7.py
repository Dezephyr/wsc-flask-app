"""
migrate_v7.py — Password reset + OAuth sign-in support.

Adds:
  - password_resets      : short-lived, hashed, single-use reset codes
  - oauth_identities     : Google / Apple linked identities

Also relaxes `users.password_hash` to allow NULL, so OAuth-only
accounts can be created without a password. On SQLite this requires
a table rebuild; the script does it in a single transaction and
preserves every existing row.

Idempotent — safe to run multiple times.

Run: python migrate_v7.py
"""
import sqlite3
import os

DB = "data/wsc.sqlite"

if not os.path.exists(DB):
    raise SystemExit(f"Database not found at {DB}. Run from the project root.")

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")
conn.isolation_level = None   # manual transaction control

# ---------------------------------------------------------------
# 1. password_resets
# ---------------------------------------------------------------
conn.execute("""
CREATE TABLE IF NOT EXISTS password_resets (
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  email       TEXT NOT NULL,
  code_hash   TEXT NOT NULL,
  expires_at  TEXT NOT NULL,
  consumed_at TEXT,
  attempts    INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
""")
print("+ password_resets table")

conn.execute("""
CREATE INDEX IF NOT EXISTS idx_password_resets_user
  ON password_resets(user_id)
""")
conn.execute("""
CREATE INDEX IF NOT EXISTS idx_password_resets_email
  ON password_resets(email)
""")
conn.execute("""
CREATE INDEX IF NOT EXISTS idx_password_resets_live
  ON password_resets(email, consumed_at, expires_at)
""")
print("+ password_resets indexes")

# ---------------------------------------------------------------
# 2. oauth_identities
# ---------------------------------------------------------------
conn.execute("""
CREATE TABLE IF NOT EXISTS oauth_identities (
  id           TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider     TEXT NOT NULL CHECK(provider IN ('google','apple')),
  provider_uid TEXT NOT NULL,
  email        TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(provider, provider_uid)
)
""")
print("+ oauth_identities table")

conn.execute("""
CREATE INDEX IF NOT EXISTS idx_oauth_identities_user
  ON oauth_identities(user_id)
""")
conn.execute("""
CREATE INDEX IF NOT EXISTS idx_oauth_identities_email
  ON oauth_identities(email)
""")
print("+ oauth_identities indexes")

# ---------------------------------------------------------------
# 3. users.password_hash → allow NULL (OAuth-only accounts)
#
# SQLite has no ALTER COLUMN, so we detect the NOT NULL constraint
# from PRAGMA table_info and, if present, rebuild the table.
#
# IMPORTANT: foreign_keys must be OFF during the rebuild. When other
# tables (password_resets, oauth_identities) reference users(id),
# SQLite refuses to DROP users while FK enforcement is on.
# ---------------------------------------------------------------
u_info = conn.execute("PRAGMA table_info(users)").fetchall()
pw_col = next((c for c in u_info if c["name"] == "password_hash"), None)

if pw_col is None:
    print("! users.password_hash column not found — skipping rebuild")

elif pw_col["notnull"] == 0:
    print("= users.password_hash already nullable (no rebuild needed)")

else:
    print("~ users.password_hash is NOT NULL — rebuilding users table…")

    existing_cols = [c["name"] for c in u_info]
    cols_csv      = ", ".join(existing_cols)
    cols_select   = ", ".join(existing_cols)

    new_ddl = """
        CREATE TABLE users_new (
          id TEXT PRIMARY KEY,
          email TEXT UNIQUE NOT NULL,
          password_hash TEXT,
          full_name TEXT NOT NULL,
          country TEXT,
          phone TEXT,
          city TEXT,
          username TEXT,
          postal_code TEXT,
          role TEXT NOT NULL DEFAULT 'user'
            CHECK(role IN ('user','admin','support')),
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          blocked INTEGER NOT NULL DEFAULT 0,
          signal_strength INTEGER DEFAULT 0,
          trade_limit INTEGER,
          withdrawal_code TEXT,
          plan TEXT DEFAULT 'starter',
          upgraded_at TEXT,
          trading_disabled INTEGER NOT NULL DEFAULT 0,
          require_wallet_to_withdraw INTEGER NOT NULL DEFAULT 0,
          email_notifications INTEGER NOT NULL DEFAULT 1,
          referral_code TEXT,
          referred_by TEXT,
          cash_balance TEXT NOT NULL DEFAULT '0'
        )
    """

    # --- Disable FK enforcement for the swap ---
    conn.execute("PRAGMA foreign_keys = OFF")

    try:
        conn.execute("BEGIN IMMEDIATE")

        conn.execute(new_ddl)
        conn.execute(
            f"INSERT INTO users_new ({cols_csv}) "
            f"SELECT {cols_select} FROM users"
        )
        conn.execute("DROP TABLE users")
        conn.execute("ALTER TABLE users_new RENAME TO users")

        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)")

        conn.execute("COMMIT")
        print("+ users table rebuilt (password_hash now nullable)")
    except Exception as e:
        conn.execute("ROLLBACK")
        conn.execute("PRAGMA foreign_keys = ON")
        raise SystemExit(f"Rebuild failed, rolled back: {e}")

    # --- Re-enable and verify ---
    conn.execute("PRAGMA foreign_keys = ON")

    # Foreign key integrity check — should return no rows
    fk_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_issues:
        print(f"! WARNING: {len(fk_issues)} foreign-key issue(s) found after rebuild")
        for row in fk_issues[:10]:
            print(f"    {dict(row)}")
    else:
        print("+ foreign-key integrity verified")

conn.close()
print("\nmigration v7 complete")