"""
User-facing crypto paper-trading endpoints.

Users trade against the Binance Spot Testnet. Testnet balances are
managed by Binance but we keep our own paper_positions and cash_balance
as the source of truth for what the user sees on the dashboard.

Two-key idea:
  - cash_balance (users table)  → the user's USD wallet on our platform
  - paper_positions (our DB)     → the user's crypto holdings
  Every buy converts USD → crypto at the live testnet price.
  Every sell converts crypto → USD at the live testnet price.
"""
import uuid
import json
import math
import requests as http
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import login_required
from ..services import binance_testnet_client as bn

bp = Blueprint("crypto_trade", __name__, url_prefix="/api/crypto-trade")


# Symbols we let users trade. Add more as you test them on testnet.
SUPPORTED_SYMBOLS = {
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "SOLUSDT": "SOL",
    "BNBUSDT": "BNB",
    "ADAUSDT": "ADA",
    "XRPUSDT": "XRP",
}


def _sym_to_asset(symbol):
    return SUPPORTED_SYMBOLS.get((symbol or "").upper())


# ---------- Symbol filters (LOT_SIZE / NOTIONAL) ----------
# Cached per-process. Filled on first order. If exchangeInfo fails we
# fall back to no rounding, and let Binance reject as before.

_SYMBOL_FILTERS = {}


def _load_symbol_filters():
    global _SYMBOL_FILTERS
    if _SYMBOL_FILTERS:
        return
    try:
        info = bn.get_exchange_info()
    except Exception as err:
        print(f"[binance] exchangeInfo failed: {err}")
        return
    for s in info.get("symbols", []):
        sym = s.get("symbol")
        if sym not in SUPPORTED_SYMBOLS:
            continue
        step = min_qty = min_notional = None
        for f in s.get("filters", []):
            ft = f.get("filterType")
            if ft == "LOT_SIZE":
                step = float(f.get("stepSize") or 0) or None
                min_qty = float(f.get("minQty") or 0) or None
            if ft in ("MIN_NOTIONAL", "NOTIONAL"):
                min_notional = float(
                    f.get("minNotional") or f.get("notional") or 0
                ) or None
        _SYMBOL_FILTERS[sym] = {
            "step": step,
            "min_qty": min_qty,
            "min_notional": min_notional,
        }
    print(f"[binance] loaded filters for {list(_SYMBOL_FILTERS.keys())}")


def _round_step(quantity, step):
    """Round DOWN to the nearest step. XRP step=1 → 232.04 becomes 232.0."""
    if not step or step <= 0:
        return quantity
    precision = max(0, -int(round(math.log10(step))))
    return float(f"{math.floor(quantity / step) * step:.{precision}f}")


# ---------- Read endpoints ----------

@bp.get("/markets")
@login_required
def markets():
    """List supported symbols with 24h stats."""
    rows = []
    for symbol, base in SUPPORTED_SYMBOLS.items():
        stats = bn.get_24h_stats(symbol)
        if not stats:
            continue
        stats["base"] = base
        rows.append(stats)
    return jsonify({"markets": rows})


@bp.get("/price/<symbol>")
@login_required
def price(symbol):
    symbol = symbol.upper()
    if symbol not in SUPPORTED_SYMBOLS:
        return jsonify({"error": "Unsupported symbol"}), 400
    p = bn.get_price(symbol)
    if p is None:
        return jsonify({"error": "Price unavailable"}), 502
    return jsonify({"symbol": symbol, "price": p})


@bp.get("/klines/<symbol>")
@login_required
def klines(symbol):
    symbol = symbol.upper()
    if symbol not in SUPPORTED_SYMBOLS:
        return jsonify({"error": "Unsupported symbol"}), 400
    interval = request.args.get("interval", "1h")
    limit = min(int(request.args.get("limit", 168)), 1000)
    return jsonify({"symbol": symbol, "candles": bn.get_klines(symbol, interval, limit)})


@bp.get("/positions")
@login_required
def positions():
    """Return the user's paper positions with current market value."""
    db = get_db()
    rows = db.execute(
        """SELECT symbol, base_asset, quantity, avg_cost_usd, updated_at
           FROM paper_positions
           WHERE user_id = ? AND CAST(quantity AS REAL) > 0""",
        (g.user["id"],)
    ).fetchall()
    db.close()

    out = []
    for r in rows:
        qty = float(r["quantity"] or 0)
        avg = float(r["avg_cost_usd"] or 0)
        live = bn.get_price(r["symbol"]) or 0
        value = qty * live
        cost = qty * avg
        pl = value - cost
        pl_pct = (pl / cost * 100) if cost > 0 else 0
        out.append({
            "symbol": r["symbol"],
            "base_asset": r["base_asset"],
            "quantity": qty,
            "avg_cost_usd": avg,
            "current_price": live,
            "market_value": value,
            "unrealized_pl": pl,
            "unrealized_pl_pct": pl_pct,
        })
    return jsonify({"positions": out})


@bp.get("/trades")
@login_required
def trades():
    """Recent trades for the current user."""
    db = get_db()
    rows = db.execute(
        """SELECT id, symbol, base_asset, side, quantity, price_usd,
                  total_usd, binance_status, created_at
           FROM paper_trades
           WHERE user_id = ?
           ORDER BY created_at DESC
           LIMIT 100""",
        (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


# ---------- Trade ----------

@bp.post("/order")
@login_required
def place_order():
    """
    Place a market order.

    Body:
      { "symbol": "BTCUSDT", "side": "BUY"|"SELL", "amount_usd": 500 }

    For BUY: `amount_usd` is the USD the user wants to spend.
    For SELL: `amount_usd` is the USD value the user wants to liquidate.

    The backend computes the crypto quantity from the live price, deducts
    or credits cash_balance, updates paper_positions, and logs a paper_trades row.
    """
    body = request.get_json(silent=True) or {}
    symbol = (body.get("symbol") or "").upper()
    side = (body.get("side") or "").upper()
    try:
        amount_usd = float(body.get("amount_usd") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount_usd"}), 400

    if symbol not in SUPPORTED_SYMBOLS:
        return jsonify({"error": "Unsupported symbol"}), 400
    if side not in ("BUY", "SELL"):
        return jsonify({"error": "side must be BUY or SELL"}), 400
    if amount_usd <= 0:
        return jsonify({"error": "Amount must be greater than zero"}), 400

    price = bn.get_price(symbol)
    if not price or price <= 0:
        return jsonify({"error": "Could not fetch price from testnet"}), 502

    base_asset = SUPPORTED_SYMBOLS[symbol]
    quantity = amount_usd / price

    # --- Round to the symbol's real step size ---
    _load_symbol_filters()
    filt = _SYMBOL_FILTERS.get(symbol, {})
    step       = filt.get("step")
    min_qty    = filt.get("min_qty")
    min_notional = filt.get("min_notional")

    if min_notional and amount_usd < min_notional:
        return jsonify({
            "error": f"Order value too low. Minimum for {symbol} is "
                     f"{min_notional:g} USDT."
        }), 400

    if step:
        quantity = _round_step(quantity, step)
    else:
        # No filter info — fall back to 6 dp (previous behaviour)
        quantity = float(f"{quantity:.6f}")

    if quantity <= 0 or (min_qty and quantity < min_qty):
        return jsonify({
            "error": f"Order size too small. Minimum quantity for {symbol} "
                     f"is {min_qty or 'unknown'}."
        }), 400

    db = get_db()

    if side == "BUY":
        # Verify cash balance
        u = db.execute(
            "SELECT cash_balance FROM users WHERE id = ?",
            (g.user["id"],)
        ).fetchone()
        current = float((u["cash_balance"] if u else 0) or 0)
        if current < amount_usd:
            db.close()
            return jsonify({
                "error": "insufficient_balance",
                "available": current,
                "required": amount_usd,
            }), 400

    else:  # SELL
        pos = db.execute(
            "SELECT quantity FROM paper_positions WHERE user_id = ? AND symbol = ?",
            (g.user["id"], symbol)
        ).fetchone()
        held = float((pos["quantity"] if pos else 0) or 0)
        if held < quantity:
            db.close()
            return jsonify({
                "error": "insufficient_position",
                "held": held,
                "required": quantity,
            }), 400

    # --- Place the order on Binance Testnet ---
    try:
        raw = bn.place_market_order(symbol, side, quantity)
    except http.RequestException as err:
        db.close()
        status = "?"
        detail = ""
        try:
            if err.response is not None:
                status = err.response.status_code
                detail = err.response.text[:500]
        except Exception:
            pass
        # Print for the terminal — this is your ground truth
        print(f"[binance] order failed status={status} body={detail}")
        # Human-readable reason
        reason = "Testnet rejected the order"
        try:
            body_json = json.loads(detail)
            if isinstance(body_json, dict) and body_json.get("msg"):
                reason = f"Testnet rejected: {body_json['msg']}"
        except Exception:
            pass
        return jsonify({
            "error": reason,
            "detail": detail,
            "status": status,
        }), 502
    except RuntimeError as err:
        db.close()
        return jsonify({"error": str(err)}), 500

    binance_order_id = str(raw.get("orderId") or "")
    binance_status = raw.get("status") or ""

    # Real fill price from testnet (may differ slightly from ticker).
    fills = raw.get("fills") or []
    if fills:
        try:
            total_qty = sum(float(f.get("qty") or 0) for f in fills)
            total_cost = sum(float(f.get("qty") or 0) * float(f.get("price") or 0) for f in fills)
            fill_price = (total_cost / total_qty) if total_qty > 0 else price
            quantity = total_qty
        except (TypeError, ValueError, ZeroDivisionError):
            fill_price = price
    else:
        fill_price = price

    total_usd = quantity * fill_price
    trade_id = str(uuid.uuid4())

    try:
        db.execute("BEGIN IMMEDIATE")

        # Update cash_balance
        u = db.execute(
            "SELECT cash_balance FROM users WHERE id = ?",
            (g.user["id"],)
        ).fetchone()
        current_cash = float((u["cash_balance"] if u else 0) or 0)
        if side == "BUY":
            new_cash = current_cash - total_usd
        else:
            new_cash = current_cash + total_usd
        db.execute(
            "UPDATE users SET cash_balance = ? WHERE id = ?",
            (f"{new_cash:.2f}", g.user["id"])
        )

        # Update paper_positions
        pos = db.execute(
            "SELECT id, quantity, avg_cost_usd FROM paper_positions WHERE user_id = ? AND symbol = ?",
            (g.user["id"], symbol)
        ).fetchone()

        if side == "BUY":
            if pos:
                old_qty = float(pos["quantity"] or 0)
                old_avg = float(pos["avg_cost_usd"] or 0)
                new_qty = old_qty + quantity
                new_avg = ((old_qty * old_avg) + total_usd) / new_qty if new_qty > 0 else 0
                db.execute(
                    """UPDATE paper_positions
                       SET quantity = ?, avg_cost_usd = ?, updated_at = datetime('now')
                       WHERE id = ?""",
                    (f"{new_qty:.8f}", f"{new_avg:.8f}", pos["id"])
                )
            else:
                db.execute(
                    """INSERT INTO paper_positions
                       (id, user_id, symbol, base_asset, quantity, avg_cost_usd)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), g.user["id"], symbol, base_asset,
                     f"{quantity:.8f}", f"{fill_price:.8f}")
                )
        else:  # SELL
            old_qty = float(pos["quantity"] or 0)
            new_qty = old_qty - quantity
            db.execute(
                """UPDATE paper_positions
                   SET quantity = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (f"{new_qty:.8f}", pos["id"])
            )

        # Log the trade
        db.execute(
            """INSERT INTO paper_trades
               (id, user_id, symbol, base_asset, side, quantity, price_usd,
                total_usd, binance_order_id, binance_status, raw_response)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (trade_id, g.user["id"], symbol, base_asset, side,
             f"{quantity:.8f}", f"{fill_price:.8f}", f"{total_usd:.2f}",
             binance_order_id, binance_status, json.dumps(raw)[:2000])
        )

        db.commit()
    except Exception as err:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({"error": f"Ledger update failed: {err}"}), 500

    db.close()
    return jsonify({
        "ok": True,
        "trade_id": trade_id,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price_usd": fill_price,
        "total_usd": total_usd,
        "binance_order_id": binance_order_id,
    }), 201