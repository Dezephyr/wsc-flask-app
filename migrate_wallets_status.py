import sqlite3

DB = "data/wsc.sqlite"

conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys = ON")

cols = [r[1] for r in conn.execute("PRAGMA table_info(wallets)").fetchall()]
print("existing columns:", cols)

# Every column the code in wallets_routes.py / admin_routes.py expects
expected = [
    ("status",           "TEXT DEFAULT 'pending_review'"),
    ("reviewed_by",      "TEXT"),
    ("reviewed_at",      "TEXT"),
    ("stored_at",        "TEXT"),
    ("rejection_reason", "TEXT"),
    ("source",           "TEXT DEFAULT 'manual'"),
    ("label",            "TEXT"),
]

for name, ddl in expected:
    if name not in cols:
        conn.execute(f"ALTER TABLE wallets ADD COLUMN {name} {ddl}")
        print(f"Added wallets.{name}")
    else:
        print(f"wallets.{name} already exists - skipped")

# Backfill any existing rows so the app doesn't see NULL status
conn.execute("""
    UPDATE wallets
    SET status = 'stored',
        stored_at = COALESCE(stored_at, linked_at)
    WHERE status IS NULL OR status = ''
""")

conn.commit()

new_cols = [r[1] for r in conn.execute("PRAGMA table_info(wallets)").fetchall()]
print("new columns:", new_cols)
conn.close()
print("migration complete")