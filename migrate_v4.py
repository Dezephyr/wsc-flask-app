"""
Fourth migration: adds display fields to copy_traders so the user-facing
Copy Trading cards can show a tier, star rating, review count, equity,
and minimum investment — all set by the admin.

Run: python migrate_v4.py
"""
import sqlite3

DB = "data/wsc.sqlite"

conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys = ON")

existing = [r[1] for r in conn.execute("PRAGMA table_info(copy_traders)").fetchall()]

new_columns = [
    ("tier",                "TEXT DEFAULT 'PRO'"),       # "PRO", "ELITE", "STARTER"
    ("rating",              "REAL DEFAULT 5.0"),         # 0.0 – 5.0
    ("reviews",             "INTEGER DEFAULT 0"),        # number of ratings
    ("equity",              "REAL DEFAULT 0"),           # equity %, display only
    ("minimum_investment",  "REAL DEFAULT 0"),           # USD
]

for name, definition in new_columns:
    if name not in existing:
        conn.execute(f"ALTER TABLE copy_traders ADD COLUMN {name} {definition}")
        print(f"Added copy_traders.{name}")
    else:
        print(f"copy_traders.{name} already exists — skipped")

# Give sensible starting values to any existing rows that were created
# before these columns existed, so the cards don't render as 0/blank.
conn.execute("UPDATE copy_traders SET tier = 'PRO' WHERE tier IS NULL")
conn.execute("UPDATE copy_traders SET rating = 5.0 WHERE rating IS NULL OR rating = 0")
conn.execute("UPDATE copy_traders SET reviews = 5 WHERE reviews IS NULL OR reviews = 0")
conn.execute("UPDATE copy_traders SET minimum_investment = 1000 WHERE minimum_investment IS NULL OR minimum_investment = 0")
conn.execute("UPDATE copy_traders SET equity = win_rate WHERE (equity IS NULL OR equity = 0) AND win_rate IS NOT NULL")

conn.commit()
conn.close()
print("migration v4 complete")