"""
Bot Trading — user-facing endpoints.

  GET  /api/bots                       -> catalog with filters
  GET  /api/bots/me                    -> my active + past investments
  POST /api/bots/<bot_id>/invest       -> buy into a bot (debits cash_balance)
  POST /api/bots/investments/<id>/cash -> early exit (returns principal)
  GET  /api/bots/investments/<id>      -> single investment detail
"""
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import login_required

bp = Blueprint("bots", __name__, url_prefix="/api/bots")


def _audit(db, actor_id, action, target=None):
    db.execute(
        "INSERT INTO audit_log (id, actor_id, action, target) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), actor_id, action, target),
    )


# ------------------------------------------------------------
# Catalog
# ------------------------------------------------------------

@bp.get("")
@login_required
def list_bots():
    """Catalog with optional ?category= filter."""
    category = (request.args.get("category") or "").strip().lower()

    db = get_db()
    sql = """
        SELECT id, name, category, tagline, description,
               success_rate, daily_profit_min, daily_profit_max,
               duration_days, min_amount, max_amount,
               trading_pairs, total_earned, active_users,
               icon_url, elite, sort_order
        FROM trading_bots
        WHERE active = 1
    """
    args = []
    if category and category != "all":
        sql += " AND category = ?"
        args.append(category)
    sql += " ORDER BY sort_order ASC, created_at ASC"

    rows = db.execute(sql, args).fetchall()

    # Annotate with the caller's current investment status per bot
    mine = {
        r["bot_id"]: r["status"]
        for r in db.execute(
            """SELECT bot_id, status FROM user_bot_investments
               WHERE user_id = ? AND status = 'active'""",
            (g.user["id"],)
        ).fetchall()
    }
    db.close()

    return jsonify([
        {
            "id": r["id"],
            "name": r["name"],
            "category": r["category"],
            "tagline": r["tagline"],
            "description": r["description"],
            "success_rate": r["success_rate"],
            "daily_profit_min": r["daily_profit_min"],
            "daily_profit_max": r["daily_profit_max"],
            "duration_days": r["duration_days"],
            "min_amount": r["min_amount"],
            "max_amount": r["max_amount"],
            "trading_pairs": [p.strip() for p in (r["trading_pairs"] or "").split(",") if p.strip()],
            "total_earned": r["total_earned"],
            "active_users": r["active_users"],
            "icon_url": r["icon_url"],
            "elite": bool(r["elite"]),
            "is_invested": mine.get(r["id"]) == "active",
        }
        for r in rows
    ])


# ------------------------------------------------------------
# My investments
# ------------------------------------------------------------

@bp.get("/me")
@login_required
def my_investments():
    db = get_db()
    rows = db.execute(
        """SELECT id, bot_id, bot_name, category, amount_usd,
                  daily_profit_min, daily_profit_max, duration_days,
                  accrued_usd, status, started_at, matures_at,
                  last_accrued_at, matured_at, paid_out_at
           FROM user_bot_investments
           WHERE user_id = ?
           ORDER BY started_at DESC""",
        (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.get("/investments/<inv_id>")
@login_required
def investment_detail(inv_id):
    db = get_db()
    row = db.execute(
        """SELECT * FROM user_bot_investments
           WHERE id = ? AND user_id = ?""",
        (inv_id, g.user["id"])
    ).fetchone()
    db.close()
    if not row:
        return jsonify({"error": "Investment not found"}), 404
    return jsonify(dict(row))


# ------------------------------------------------------------
# Invest
# ------------------------------------------------------------

@bp.post("/<bot_id>/invest")
@login_required
def invest(bot_id):
    body = request.get_json(silent=True) or {}
    try:
        amount = Decimal(str(body.get("amount") or "0"))
    except Exception:
        return jsonify({"error": "Invalid amount"}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than zero"}), 400

    db = get_db()

    bot = db.execute(
        """SELECT id, name, category, min_amount, max_amount,
                  daily_profit_min, daily_profit_max, duration_days, active
           FROM trading_bots WHERE id = ?""",
        (bot_id,)
    ).fetchone()
    if not bot or not bot["active"]:
        db.close()
        return jsonify({"error": "Bot not found or inactive"}), 404

    min_amt = Decimal(str(bot["min_amount"] or "0"))
    max_amt = Decimal(str(bot["max_amount"] or "0")) if bot["max_amount"] else None
    if amount < min_amt:
        db.close()
        return jsonify({"error": f"Minimum investment is ${min_amt:.2f}"}), 400
    if max_amt and amount > max_amt:
        db.close()
        return jsonify({"error": f"Maximum investment is ${max_amt:.2f}"}), 400

    existing = db.execute(
        """SELECT id FROM user_bot_investments
           WHERE user_id = ? AND bot_id = ? AND status = 'active'""",
        (g.user["id"], bot_id)
    ).fetchone()
    if existing:
        db.close()
        return jsonify({
            "error": "You already have an active investment in this bot",
            "investment_id": existing["id"],
        }), 409

    u = db.execute(
        "SELECT cash_balance FROM users WHERE id = ?",
        (g.user["id"],)
    ).fetchone()
    current = Decimal(str((u and u["cash_balance"]) or "0"))
    if current < amount:
        db.close()
        return jsonify({
            "error": "insufficient_balance",
            "available": f"{current:.2f}",
            "required":  f"{amount:.2f}",
        }), 400

    now = datetime.utcnow()
    matures = now + timedelta(days=int(bot["duration_days"]))
    inv_id = str(uuid.uuid4())

    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "UPDATE users SET cash_balance = ? WHERE id = ?",
            (f"{current - amount:.2f}", g.user["id"])
        )
        db.execute(
            """INSERT INTO user_bot_investments
               (id, user_id, bot_id, bot_name, category, amount_usd,
                daily_profit_min, daily_profit_max, duration_days,
                accrued_usd, status, started_at, matures_at, last_accrued_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '0', 'active', ?, ?, ?)""",
            (
                inv_id, g.user["id"], bot["id"], bot["name"], bot["category"],
                f"{amount:.2f}",
                bot["daily_profit_min"], bot["daily_profit_max"],
                int(bot["duration_days"]),
                now.isoformat(timespec="seconds"),
                matures.isoformat(timespec="seconds"),
                now.isoformat(timespec="seconds"),
            )
        )
        db.execute(
            "UPDATE trading_bots SET active_users = active_users + 1 WHERE id = ?",
            (bot["id"],)
        )

        try:
            db.execute(
                """INSERT INTO notifications (id, user_id, kind, title, body)
                   VALUES (?, ?, 'bot', 'Bot investment started', ?)""",
                (str(uuid.uuid4()), g.user["id"],
                 f"Your ${amount:.2f} investment in {bot['name']} is now active. "
                 f"It matures on {matures.date().isoformat()}.")
            )
        except Exception:
            pass

        _audit(db, g.user["id"], f"bot_invest:{bot['name']}:{amount}", inv_id)
        db.commit()
    except Exception as e:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({"error": f"Investment failed: {e}"}), 500

    db.close()
    return jsonify({
        "ok": True,
        "investment_id": inv_id,
        "amount_usd": f"{amount:.2f}",
        "matures_at": matures.isoformat(timespec="seconds"),
    }), 201


# ------------------------------------------------------------
# Early exit (cash out)
# ------------------------------------------------------------

@bp.post("/investments/<inv_id>/cash")
@login_required
def cash_out(inv_id):
    db = get_db()
    row = db.execute(
        """SELECT id, user_id, bot_id, amount_usd, accrued_usd, status, matures_at
           FROM user_bot_investments
           WHERE id = ? AND user_id = ?""",
        (inv_id, g.user["id"])
    ).fetchone()

    if not row:
        db.close()
        return jsonify({"error": "Investment not found"}), 404
    if row["status"] != "active":
        db.close()
        return jsonify({"error": "This investment is not active"}), 400

    principal = Decimal(str(row["amount_usd"] or "0"))
    accrued   = Decimal(str(row["accrued_usd"] or "0"))
    payout = principal  # early exit forfeits accrued profit

    try:
        db.execute("BEGIN IMMEDIATE")
        u = db.execute(
            "SELECT cash_balance FROM users WHERE id = ?",
            (row["user_id"],)
        ).fetchone()
        current = Decimal(str((u and u["cash_balance"]) or "0"))
        new_balance = current + payout

        db.execute(
            "UPDATE users SET cash_balance = ? WHERE id = ?",
            (f"{new_balance:.2f}", row["user_id"])
        )
        db.execute(
            """UPDATE user_bot_investments
               SET status = 'cancelled', matured_at = datetime('now')
               WHERE id = ?""",
            (inv_id,)
        )
        db.execute(
            "UPDATE trading_bots SET active_users = MAX(active_users - 1, 0) WHERE id = ?",
            (row["bot_id"],)
        )

        try:
            db.execute(
                """INSERT INTO notifications (id, user_id, kind, title, body)
                   VALUES (?, ?, 'bot', 'Bot investment closed early', ?)""",
                (str(uuid.uuid4()), row["user_id"],
                 f"Your bot investment has been closed. ${payout:.2f} (principal) "
                 f"returned. Accrued profit of ${accrued:.2f} was forfeited.")
            )
        except Exception:
            pass

        _audit(db, g.user["id"], "bot_cashout", inv_id)
        db.commit()
    except Exception as e:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({"error": f"Cash-out failed: {e}"}), 500

    db.close()
    return jsonify({
        "ok": True,
        "returned": f"{payout:.2f}",
        "new_balance": f"{new_balance:.2f}",
    })