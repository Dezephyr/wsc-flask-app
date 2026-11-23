"""
Crypto staking endpoints — paper staking on top of paper_positions.
"""
import uuid
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import login_required

bp = Blueprint("crypto_stake", __name__, url_prefix="/api/crypto-stake")


STAKING_PLANS = {
    "BTC": {"apy": 3.5, "min_days": 30, "min_amount": 0.001},
    "ETH": {"apy": 4.2, "min_days": 30, "min_amount": 0.01},
    "SOL": {"apy": 6.8, "min_days": 14, "min_amount": 1.0},
    "BNB": {"apy": 5.5, "min_days": 30, "min_amount": 0.1},
    "ADA": {"apy": 4.0, "min_days": 30, "min_amount": 10.0},
    "XRP": {"apy": 2.5, "min_days": 30, "min_amount": 10.0},
}

TERM_DAYS = [14, 30, 60, 90]


@bp.get("/plans")
@login_required
def plans():
    return jsonify({
        "plans": [
            {"coin": c, **cfg, "term_days": TERM_DAYS}
            for c, cfg in STAKING_PLANS.items()
        ]
    })


@bp.get("/stakes")
@login_required
def list_stakes():
    db = get_db()
    rows = db.execute(
        """SELECT id, coin, amount, term_days, apy, status,
                  started_at, unlocks_at, rewards_earned, unstaked_at
           FROM crypto_stakes WHERE user_id = ?
           ORDER BY started_at DESC""",
        (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify({"stakes": [dict(r) for r in rows]})


@bp.post("/stake")
@login_required
def create_stake():
    body = request.get_json(silent=True) or {}
    coin = (body.get("coin") or "").upper()
    try:
        amount = float(body.get("amount") or 0)
        term_days = int(body.get("term_days") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount or term"}), 400

    plan = STAKING_PLANS.get(coin)
    if not plan:
        return jsonify({"error": "Unsupported coin"}), 400
    if amount < plan["min_amount"]:
        return jsonify({"error": f"Minimum stake is {plan['min_amount']} {coin}"}), 400
    if term_days not in TERM_DAYS:
        return jsonify({"error": "Invalid term"}), 400

    db = get_db()
    pos = db.execute(
        """SELECT id, quantity FROM paper_positions
           WHERE user_id = ? AND base_asset = ?""",
        (g.user["id"], coin)
    ).fetchone()
    held = float((pos["quantity"] if pos else 0) or 0)
    if held < amount:
        db.close()
        return jsonify({"error": "insufficient_position", "held": held}), 400

    now = datetime.utcnow()
    unlocks = now + timedelta(days=term_days)
    stake_id = str(uuid.uuid4())

    try:
        db.execute("BEGIN IMMEDIATE")
        new_qty = held - amount
        db.execute(
            """UPDATE paper_positions SET quantity = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (f"{new_qty:.8f}", pos["id"])
        )
        db.execute(
            """INSERT INTO crypto_stakes
               (id, user_id, coin, amount, term_days, apy, status,
                started_at, unlocks_at, rewards_earned)
               VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, '0')""",
            (stake_id, g.user["id"], coin, f"{amount:.8f}", term_days,
             f"{plan['apy']:.2f}",
             now.isoformat(timespec="seconds"),
             unlocks.isoformat(timespec="seconds"))
        )
        db.commit()
    except Exception as err:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({"error": f"Stake failed: {err}"}), 500

    db.close()
    return jsonify({
        "ok": True, "stake_id": stake_id, "coin": coin,
        "amount": amount, "term_days": term_days,
        "apy": plan["apy"],
        "unlocks_at": unlocks.isoformat(timespec="seconds"),
    }), 201


@bp.post("/unstake/<stake_id>")
@login_required
def unstake(stake_id):
    db = get_db()
    row = db.execute(
        """SELECT id, coin, amount, apy, started_at, unlocks_at,
                  status FROM crypto_stakes
           WHERE id = ? AND user_id = ?""",
        (stake_id, g.user["id"])
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Stake not found"}), 404
    if row["status"] != "active":
        db.close()
        return jsonify({"error": "Stake is not active"}), 400

    now = datetime.utcnow()
    try:
        unlocks = datetime.fromisoformat(row["unlocks_at"])
    except Exception:
        unlocks = now

    amount = float(row["amount"] or 0)
    apy = float(row["apy"] or 0)

    if now >= unlocks:
        days = (unlocks - datetime.fromisoformat(row["started_at"])).days
        rewards = amount * (apy / 100) * (days / 365)
        principal = amount
    else:
        rewards = 0.0
        principal = amount

    total_return = principal + rewards

    try:
        db.execute("BEGIN IMMEDIATE")
        pos = db.execute(
            """SELECT id, quantity FROM paper_positions
               WHERE user_id = ? AND base_asset = ?""",
            (g.user["id"], row["coin"])
        ).fetchone()
        if pos:
            new_qty = float(pos["quantity"] or 0) + total_return
            db.execute(
                """UPDATE paper_positions SET quantity = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (f"{new_qty:.8f}", pos["id"])
            )
        else:
            db.execute(
                """INSERT INTO paper_positions
                   (id, user_id, symbol, base_asset, quantity, avg_cost_usd)
                   VALUES (?, ?, ?, ?, ?, '0')""",
                (str(uuid.uuid4()), g.user["id"],
                 row["coin"] + "USDT", row["coin"], f"{total_return:.8f}")
            )
        db.execute(
            """UPDATE crypto_stakes
               SET status = 'unstaked', rewards_earned = ?,
                   unstaked_at = datetime('now')
               WHERE id = ?""",
            (f"{rewards:.8f}", stake_id)
        )
        db.commit()
    except Exception as err:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({"error": f"Unstake failed: {err}"}), 500

    db.close()
    return jsonify({
        "ok": True, "principal": principal,
        "rewards": rewards, "total_returned": total_return,
    })