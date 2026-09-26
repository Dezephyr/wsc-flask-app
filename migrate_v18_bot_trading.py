"""
Bot Trading — creates trading_bots and user_bot_investments tables,
plus indexes. Safe to re-run.

Run:
    python migrate_v18_bot_trading.py
"""
import os
import sqlite3
import sys
from datetime import datetime


def find_db_path():
    for var in ("DB_PATH", "WSC_DB_PATH"):
        env = os.environ.get(var)
        if env and os.path.exists(env):
            return env
    default = "./data/wsc.sqlite"
    if os.path.exists(default):
        return default
    for c in ("app.db", "wsc.db", "instance/app.db", "data/app.db"):
        if os.path.exists(c):
            return c
    return None


DB_PATH = find_db_path()
if not DB_PATH:
    print("✗ Could not find a SQLite database. Set DB_PATH=/full/path and re-run.")
    sys.exit(1)

print(f"→ Using database: {DB_PATH}")
print(f"→ Started at: {datetime.now().isoformat()}\n")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

try:
    cur.execute("BEGIN")

    # ------------------------------------------------------------
    # trading_bots  — the marketplace catalog (admin-managed)
    # ------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trading_bots (
            id                TEXT PRIMARY KEY,
            name              TEXT NOT NULL,
            category          TEXT NOT NULL
                                CHECK(category IN ('forex','crypto','stocks','commodities')),
            tagline           TEXT,
            description       TEXT,
            success_rate      INTEGER NOT NULL DEFAULT 0,
            daily_profit_min  REAL NOT NULL DEFAULT 0,
            daily_profit_max  REAL NOT NULL DEFAULT 0,
            duration_days     INTEGER NOT NULL DEFAULT 30,
            min_amount        REAL NOT NULL DEFAULT 100,
            max_amount        REAL NOT NULL DEFAULT 10000,
            trading_pairs     TEXT,
            total_earned      REAL NOT NULL DEFAULT 0,
            active_users      INTEGER NOT NULL DEFAULT 0,
            icon_url          TEXT,
            elite             INTEGER NOT NULL DEFAULT 0,
            active            INTEGER NOT NULL DEFAULT 1,
            sort_order        INTEGER NOT NULL DEFAULT 100,
            created_at        TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    print("  ✓ trading_bots table ensured")

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_trading_bots_category
        ON trading_bots(category, active)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_trading_bots_sort
        ON trading_bots(sort_order, created_at)
    """)
    print("  ✓ indexes on trading_bots")

    # ------------------------------------------------------------
    # user_bot_investments — who invested in what
    # ------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_bot_investments (
            id                TEXT PRIMARY KEY,
            user_id           TEXT NOT NULL REFERENCES users(id),
            bot_id            TEXT NOT NULL REFERENCES trading_bots(id),
            bot_name          TEXT NOT NULL,
            category          TEXT NOT NULL,
            amount_usd        TEXT NOT NULL,
            daily_profit_min  REAL NOT NULL DEFAULT 0,
            daily_profit_max  REAL NOT NULL DEFAULT 0,
            duration_days     INTEGER NOT NULL,
            accrued_usd       REAL NOT NULL DEFAULT 0,
            status            TEXT NOT NULL DEFAULT 'active'
                                CHECK(status IN ('active','matured','cancelled')),
            started_at        TEXT NOT NULL DEFAULT (datetime('now')),
            matures_at        TEXT NOT NULL,
            last_accrued_at   TEXT,
            matured_at        TEXT,
            paid_out_at       TEXT
        )
    """)
    print("  ✓ user_bot_investments table ensured")

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_bot_inv_user
        ON user_bot_investments(user_id, status)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_bot_inv_bot
        ON user_bot_investments(bot_id, status)
    """)
    print("  ✓ indexes on user_bot_investments")

    # ------------------------------------------------------------
    # Seed a few example bots so the page isn't empty
    # ------------------------------------------------------------
    count = cur.execute("SELECT COUNT(*) FROM trading_bots").fetchone()[0]
    if count == 0:
        import uuid as _uuid
        seeds = [
            {
                "name": "ForexMaster Pro",
                "category": "forex",
                "tagline": "Forex Trading",
                "description": "Advanced forex trading bot specializing in major currency "
                               "pairs. Uses sophisticated algorithms to analyze market "
                               "trends and execute high-probability trades.",
                "success_rate": 87,
                "daily_profit_min": 0.80,
                "daily_profit_max": 2.50,
                "duration_days": 30,
                "min_amount": 100,
                "max_amount": 10000,
                "trading_pairs": "EUR/USD, GBP/USD, USD/JPY, AUD/USD",
            },
            {
                "name": "GoldRush Bot",
                "category": "commodities",
                "tagline": "Commodities Trading",
                "description": "Specialized commodities trading bot with expertise in "
                               "precious metals and energy markets. Ideal for portfolio "
                               "diversification.",
                "success_rate": 84,
                "daily_profit_min": 0.70,
                "daily_profit_max": 2.80,
                "duration_days": 90,
                "min_amount": 200,
                "max_amount": 15000,
                "trading_pairs": "GOLD, SILVER, OIL, COPPER",
            },
        ]
        for s in seeds:
            cur.execute("""
                INSERT INTO trading_bots
                (id, name, category, tagline, description, success_rate,
                 daily_profit_min, daily_profit_max, duration_days,
                 min_amount, max_amount, trading_pairs)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(_uuid.uuid4()), s["name"], s["category"], s["tagline"],
                s["description"], s["success_rate"],
                s["daily_profit_min"], s["daily_profit_max"],
                s["duration_days"], s["min_amount"], s["max_amount"],
                s["trading_pairs"],
            ))
        print(f"  ✓ seeded {len(seeds)} example bots")

    conn.commit()
    print("\n✓ Migration v18 complete.")

except Exception as e:
    conn.rollback()
    print(f"\n✗ Migration failed — rolled back.\n  {type(e).__name__}: {e}")
    raise
finally:
    conn.close()