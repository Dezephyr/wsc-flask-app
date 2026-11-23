"""
Bot Trading background worker.

Runs a single daemon thread that ticks every N seconds. On every tick it:
  1. Accrues daily profit on every active user_bot_investment.
  2. Matures any investment whose matures_at has passed.
  3. Updates trading_bots.total_earned.
"""
import random
import threading
import time
import uuid
from datetime import datetime
from decimal import Decimal

from ..db import get_db

TICK_SECONDS = 60
_lock = threading.Lock()
_started = False


def _now():
    return datetime.utcnow()


def _accrue_one_tick(db):
    now = _now()
    rows = db.execute(
        """SELECT id, user_id, bot_id, amount_usd,
                  daily_profit_min, daily_profit_max,
                  accrued_usd, last_accrued_at
           FROM user_bot_investments
           WHERE status = 'active'"""
    ).fetchall()

    for r in rows:
        try:
            last = datetime.fromisoformat(r["last_accrued_at"]) if r["last_accrued_at"] else now
        except Exception:
            last = now

        seconds = max((now - last).total_seconds(), 0)
        if seconds <= 0:
            continue

        days = seconds / 86400.0
        rate_pct = (float(r["daily_profit_min"] or 0) + float(r["daily_profit_max"] or 0)) / 2.0
        principal = float(r["amount_usd"] or 0)
        delta = principal * (rate_pct / 100.0) * days
        delta *= random.uniform(0.85, 1.15)

        new_accrued = float(r["accrued_usd"] or 0) + delta

        db.execute(
            """UPDATE user_bot_investments
               SET accrued_usd = ?, last_accrued_at = ?
               WHERE id = ?""",
            (f"{new_accrued:.4f}", now.isoformat(timespec="seconds"), r["id"])
        )
        db.execute(
            "UPDATE trading_bots SET total_earned = total_earned + ? WHERE id = ?",
            (delta, r["bot_id"])
        )


def _mature_due(db):
    now = _now().isoformat(timespec="seconds")
    rows = db.execute(
        """SELECT id, user_id, bot_id, amount_usd, accrued_usd
           FROM user_bot_investments
           WHERE status = 'active' AND matures_at <= ?""",
        (now,)
    ).fetchall()

    for r in rows:
        principal = Decimal(str(r["amount_usd"] or "0"))
        accrued   = Decimal(str(r["accrued_usd"] or "0"))
        payout    = principal + accrued

        u = db.execute(
            "SELECT cash_balance FROM users WHERE id = ?",
            (r["user_id"],)
        ).fetchone()
        current = Decimal(str((u and u["cash_balance"]) or "0"))
        new_balance = current + payout

        db.execute(
            "UPDATE users SET cash_balance = ? WHERE id = ?",
            (f"{new_balance:.2f}", r["user_id"])
        )
        db.execute(
            """UPDATE user_bot_investments
               SET status = 'matured',
                   matured_at = datetime('now'),
                   paid_out_at = datetime('now')
               WHERE id = ?""",
            (r["id"],)
        )
        db.execute(
            "UPDATE trading_bots SET active_users = MAX(active_users - 1, 0) WHERE id = ?",
            (r["bot_id"],)
        )

        try:
            db.execute(
                """INSERT INTO notifications (id, user_id, kind, title, body)
                   VALUES (?, ?, 'bot', 'Bot investment matured', ?)""",
                (str(uuid.uuid4()), r["user_id"],
                 f"Your bot investment has matured. Principal ${principal:.2f} "
                 f"+ profit ${accrued:.2f} = ${payout:.2f} credited to your balance.")
            )
        except Exception:
            pass


def _loop():
    while True:
        try:
            with _lock:
                db = get_db()
                try:
                    db.execute("BEGIN IMMEDIATE")
                    _accrue_one_tick(db)
                    _mature_due(db)
                    db.commit()
                except Exception:
                    try: db.execute("ROLLBACK")
                    except Exception: pass
                finally:
                    db.close()
        except Exception as e:
            print(f"[bot_worker] tick error: {e}")

        time.sleep(TICK_SECONDS)


def start():
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_loop, name="bot-worker", daemon=True)
    t.start()
    print("[bot_worker] started (tick every", TICK_SECONDS, "s)")