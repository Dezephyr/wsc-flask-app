"""
Fifth migration: record the payment lifecycle for each copy-trade request.
Copy subscriptions now go through admin review before funds move.

Run: python migrate_v5.py
"""
import sqlite3

DB = "data/wsc.sqlite"

conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys = ON")

# --- copied_traders: add payment columns (if missing) ---
cols = [r[1] for r in conn.execute("PRAGMA table_info(copied_traders)").fetchall()]

new_cols = [
    ("amount_usd",      "TEXT DEFAULT '0'"),
    ("source",          "TEXT DEFAULT 'bank'"),
    ("wallet_id",       "TEXT"),
    ("wallet_address",  "TEXT"),
    ("tx_hash",         "TEXT"),
    ("funded_at",       "TEXT"),
    ("payment_status",  "TEXT DEFAULT 'pending_review'"),
    ("reviewed_by",     "TEXT"),
    ("reviewed_at",     "TEXT"),
    ("rejection_reason","TEXT"),
]

for name, ddl in new_cols:
    if name not in cols:
        conn.execute(f"ALTER TABLE copied_traders ADD COLUMN {name} {ddl}")
        print(f"Added copied_traders.{name}")
    else:
        print(f"copied_traders.{name} already exists - skipped")

# --- widen the status CHECK by rebuilding the table ---
schema_sql = conn.execute(
    "SELECT sql FROM sqlite_master WHERE type='table' AND name='copied_traders'"
).fetchone()[0]

if "pending_payment" not in (schema_sql or ""):
    print("Recreating copied_traders with widened status CHECK...")

    # Snapshot old rows into Python so we can re-insert safely
    old_rows = conn.execute("SELECT * FROM copied_traders").fetchall()
    old_cols = [r[1] for r in conn.execute("PRAGMA table_info(copied_traders)").fetchall()]

    conn.executescript("""
        PRAGMA foreign_keys = OFF;
        DROP TABLE IF EXISTS copied_traders_new;
        CREATE TABLE copied_traders_new (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL REFERENCES users(id),
          trader_id TEXT NOT NULL REFERENCES copy_traders(id),
          status TEXT NOT NULL DEFAULT 'pending_payment'
            CHECK(status IN ('pending_payment','active','paused','stopped','rejected')),
          started_at TEXT NOT NULL DEFAULT (datetime('now')),
          stopped_at TEXT,
          amount_usd TEXT DEFAULT '0',
          source TEXT DEFAULT 'bank',
          wallet_id TEXT,
          wallet_address TEXT,
          tx_hash TEXT,
          funded_at TEXT,
          payment_status TEXT DEFAULT 'pending_review',
          reviewed_by TEXT,
          reviewed_at TEXT,
          rejection_reason TEXT,
          UNIQUE(user_id, trader_id)
        );
    """)

    # Re-insert old data, filling any missing columns with None
    for row in old_rows:
        d = dict(zip(old_cols, row))
        conn.execute(
            """INSERT INTO copied_traders_new
               (id, user_id, trader_id, status, started_at, stopped_at,
                amount_usd, source, wallet_id, wallet_address, tx_hash,
                funded_at, payment_status, reviewed_by, reviewed_at, rejection_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                d.get("id"), d.get("user_id"), d.get("trader_id"),
                d.get("status", "pending_payment"),
                d.get("started_at"), d.get("stopped_at"),
                d.get("amount_usd", "0"),
                d.get("source", "bank"),
                d.get("wallet_id"), d.get("wallet_address"), d.get("tx_hash"),
                d.get("funded_at"),
                d.get("payment_status", "pending_review"),
                d.get("reviewed_by"), d.get("reviewed_at"),
                d.get("rejection_reason"),
            )
        )

    conn.executescript("""
        DROP TABLE copied_traders;
        ALTER TABLE copied_traders_new RENAME TO copied_traders;
        CREATE INDEX IF NOT EXISTS idx_copied_traders_user
          ON copied_traders(user_id);
        CREATE INDEX IF NOT EXISTS idx_copied_traders_trader
          ON copied_traders(trader_id);
        CREATE INDEX IF NOT EXISTS idx_copied_traders_pending
          ON copied_traders(payment_status);
        PRAGMA foreign_keys = ON;
    """)
    print("copied_traders recreated with new CHECK.")
else:
    print("copied_traders already has 'pending_payment' - no rebuild needed.")

# --- users: local cash ledger (fallback until Alpaca journal is wired) ---
ucols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
if "cash_balance" not in ucols:
    conn.execute("ALTER TABLE users ADD COLUMN cash_balance TEXT DEFAULT '0'")
    print("Added users.cash_balance")
else:
    print("users.cash_balance already exists - skipped")

conn.commit()
conn.close()
print("migration v5 complete")