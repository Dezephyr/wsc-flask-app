import uuid
import requests as http
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import login_required
from ..services import alpaca_broker as alpaca

bp = Blueprint("portfolio", __name__, url_prefix="/api/portfolio")


@bp.get("")
@login_required
def get_portfolio():
    db = get_db()
    kyc = db.execute(
        "SELECT * FROM kyc_submissions WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
        (g.user["id"],)
    ).fetchone()

    local_row = db.execute(
        "SELECT cash_balance FROM users WHERE id = ?",
        (g.user["id"],)
    ).fetchone()
    local_balance = float((local_row["cash_balance"] if local_row else 0) or 0)

    db.close()

    if not kyc or not kyc["alpaca_account_id"]:
        return jsonify({
            "status": "no_account",
            "account": {
                "cash_balance": f"{local_balance:.2f}",
                "portfolio_value": "0.00",
            },
            "positions": [],
        })

    try:
        account = alpaca.get_trade_account(kyc["alpaca_account_id"])
        positions = alpaca.get_positions(kyc["alpaca_account_id"])

        if isinstance(account, dict):
            account.setdefault(
                "cash_balance",
                account.get("cash") or f"{local_balance:.2f}"
            )

        return jsonify({"status": "ok", "account": account, "positions": positions})
    except http.RequestException as err:
        return jsonify({"error": "Could not reach Alpaca", "detail": str(err)}), 502


# ============================================================
# COPY TRADING (user-facing)
# ============================================================

@bp.get("/copy-traders")
@login_required
def list_copy_traders():
    """
    Discover tab - all active traders the admin has published.
    Each entry is annotated with whether THIS user is already copying
    them, or has a request pending admin approval.
    """
    db = get_db()

    traders = db.execute(
        """SELECT id, display_name, bio, avatar_url, roi, win_rate,
                  total_trades, max_followers, risk_level, elite,
                  tier, rating, reviews, equity, minimum_investment
           FROM copy_traders
           WHERE active = 1
           ORDER BY display_name ASC"""
    ).fetchall()

    # Map trader_id -> copy status for this user
    status_map = {
        row["trader_id"]: row["status"]
        for row in db.execute(
            """SELECT trader_id, status FROM copied_traders
               WHERE user_id = ? AND status IN ('active', 'pending_payment')""",
            (g.user["id"],)
        ).fetchall()
    }

    db.close()

    return jsonify([
        {
            "id": t["id"],
            "display_name": t["display_name"],
            "bio": t["bio"],
            "avatar_url": t["avatar_url"],
            "roi": t["roi"],
            "win_rate": t["win_rate"],
            "total_trades": t["total_trades"],
            "max_followers": t["max_followers"],
            "risk_level": t["risk_level"],
            "elite": bool(t["elite"]),
            "tier": t["tier"] or "PRO",
            "rating": t["rating"] if t["rating"] is not None else 5.0,
            "reviews": t["reviews"] or 0,
            "equity": t["equity"] if t["equity"] is not None else 0,
            "minimum_investment": t["minimum_investment"] if t["minimum_investment"] is not None else 0,
            "is_copying": status_map.get(t["id"]) == "active",
            "copy_status": status_map.get(t["id"]),
        }
        for t in traders
    ])


@bp.get("/my-copies")
@login_required
def list_my_copies():
    """
    My Copies tab - traders this user has requested or is actively copying.
    Includes payment lifecycle fields for the UI.
    """
    db = get_db()
    rows = db.execute(
        """SELECT c.id AS copy_id,
                  c.status AS copy_status,
                  c.started_at,
                  c.stopped_at,
                  c.amount_usd,
                  c.source,
                  c.payment_status,
                  c.rejection_reason,
                  t.id AS trader_id,
                  t.display_name,
                  t.bio,
                  t.avatar_url,
                  t.roi,
                  t.win_rate,
                  t.total_trades,
                  t.risk_level,
                  t.elite,
                  t.tier,
                  t.rating,
                  t.reviews,
                  t.equity,
                  t.minimum_investment,
                  t.max_followers
           FROM copied_traders c
           JOIN copy_traders t ON t.id = c.trader_id
           WHERE c.user_id = ?
             AND c.status IN ('active', 'pending_payment')
           ORDER BY c.started_at DESC""",
        (g.user["id"],)
    ).fetchall()
    db.close()

    return jsonify([
        {
            "copy_id": r["copy_id"],
            "status": r["copy_status"],
            "payment_status": r["payment_status"],
            "amount_usd": r["amount_usd"],
            "source": r["source"],
            "rejection_reason": r["rejection_reason"],
            "started_at": r["started_at"],
            "trader": {
                "id": r["trader_id"],
                "display_name": r["display_name"],
                "bio": r["bio"],
                "avatar_url": r["avatar_url"],
                "roi": r["roi"],
                "win_rate": r["win_rate"],
                "total_trades": r["total_trades"],
                "max_followers": r["max_followers"],
                "risk_level": r["risk_level"],
                "elite": bool(r["elite"]),
                "tier": r["tier"] or "PRO",
                "rating": r["rating"] if r["rating"] is not None else 5.0,
                "reviews": r["reviews"] or 0,
                "equity": r["equity"] if r["equity"] is not None else 0,
                "minimum_investment": r["minimum_investment"] if r["minimum_investment"] is not None else 0,
            },
        }
        for r in rows
    ])


@bp.post("/copy-traders/<trader_id>")
@login_required
def request_copy_trader(trader_id):
    """
    User submits a copy-trade REQUEST. Money does not move here.
    The row sits in the admin queue with status='pending_payment' and
    payment_status='pending_review'.

    Admin approval (in admin_routes.approve_copy_payment) is what:
      - debits cash_balance (source='balance'), or
      - records wallet confirmation (source='wallet')
      - flips status to 'active'
    """
    body = request.get_json(silent=True) or {}

    try:
        amount = float(body.get("amount") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than zero"}), 400

    source = body.get("source") or "balance"
    if source not in ("balance", "wallet"):
        return jsonify({"error": "source must be 'balance' or 'wallet'"}), 400

    wallet_id = body.get("wallet_id")
    wallet_address = body.get("wallet_address")
    tx_hash = body.get("tx_hash")

    if source == "wallet" and not wallet_address:
        return jsonify({"error": "wallet_address is required for wallet payments"}), 400

    db = get_db()
    trader = db.execute(
        "SELECT id, display_name, minimum_investment FROM copy_traders WHERE id = ? AND active = 1",
        (trader_id,)
    ).fetchone()
    if not trader:
        db.close()
        return jsonify({"error": "Trader not found or not active"}), 404

    min_inv = float(trader["minimum_investment"] or 0)
    if amount < min_inv:
        db.close()
        return jsonify({
            "error": f"Minimum investment for this trader is ${min_inv:.2f}"
        }), 400

    existing = db.execute(
        "SELECT id, status FROM copied_traders WHERE user_id = ? AND trader_id = ?",
        (g.user["id"], trader_id)
    ).fetchone()

    if existing and existing["status"] in ("active", "pending_payment"):
        db.close()
        return jsonify({
            "error": "You already have an active or pending copy for this trader",
            "status": existing["status"],
        }), 409

    if existing:
        copy_id = existing["id"]
        db.execute(
            """UPDATE copied_traders
               SET status = 'pending_payment',
                   stopped_at = NULL,
                   started_at = datetime('now'),
                   amount_usd = ?, source = ?, wallet_id = ?,
                   wallet_address = ?, tx_hash = ?,
                   payment_status = 'pending_review',
                   funded_at = NULL,
                   reviewed_by = NULL, reviewed_at = NULL,
                   rejection_reason = NULL
               WHERE id = ?""",
            (f"{amount:.2f}", source, wallet_id, wallet_address, tx_hash, copy_id)
        )
    else:
        copy_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO copied_traders
               (id, user_id, trader_id, status,
                amount_usd, source, wallet_id, wallet_address, tx_hash,
                payment_status)
               VALUES (?, ?, ?, 'pending_payment', ?, ?, ?, ?, ?,
                       'pending_review')""",
            (copy_id, g.user["id"], trader_id,
             f"{amount:.2f}", source, wallet_id, wallet_address, tx_hash)
        )

    try:
        db.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body)
               VALUES (?, ?, 'copy_trading', 'Copy request received', ?)""",
            (str(uuid.uuid4()), g.user["id"],
             f"Your request to copy {trader['display_name']} for ${amount:.2f} "
             "is awaiting approval. You'll be notified once it's reviewed.")
        )
    except Exception:
        pass

    db.commit()
    db.close()
    return jsonify({
        "ok": True,
        "copy_id": copy_id,
        "status": "pending_payment",
        "payment_status": "pending_review",
        "message": "Your request is pending admin approval.",
    }), 202


@bp.delete("/copy-traders/<trader_id>")
@login_required
def stop_copying(trader_id):
    """
    User stops copying a trader. If the copy is still pending_payment,
    this simply cancels the request. If it's active, the copy is stopped.

    Note: no automatic refund here. If you want refunds on stop, add the
    refund block inside this function (a commented example is included).
    """
    db = get_db()
    row = db.execute(
        """SELECT id, amount_usd, source, status
           FROM copied_traders
           WHERE user_id = ? AND trader_id = ?
             AND status IN ('active', 'pending_payment')""",
        (g.user["id"], trader_id)
    ).fetchone()

    if not row:
        db.close()
        return jsonify({"error": "Not currently copying this trader"}), 404

    # --- OPTIONAL REFUND on stop. Uncomment if you want it. ---
    # if row["status"] == "active" and row["source"] == "balance":
    #     amount = float(row["amount_usd"] or 0)
    #     if amount > 0:
    #         u = db.execute(
    #             "SELECT cash_balance FROM users WHERE id = ?",
    #             (g.user["id"],)
    #         ).fetchone()
    #         current = float((u["cash_balance"] if u else 0) or 0)
    #         db.execute(
    #             "UPDATE users SET cash_balance = ? WHERE id = ?",
    #             (f"{current + amount:.2f}", g.user["id"])
    #         )

    db.execute(
        """UPDATE copied_traders
           SET status = 'stopped', stopped_at = datetime('now')
           WHERE id = ?""",
        (row["id"],)
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})