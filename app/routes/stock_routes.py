"""
Stock market endpoints.

- Trading / portfolio actions proxy Alpaca (existing flow).
- Symbol search + chart data proxy Yahoo Finance so the browser never
  talks to Yahoo directly (avoids CORS and rate-limit issues).
"""
import time
import requests
from threading import Lock

from flask import Blueprint, request, jsonify, g, Response

from ..db import get_db
from ..auth import login_required
from ..services import alpaca_broker as alpaca


bp = Blueprint("stock", __name__, url_prefix="/api/stock")


# A small curated list used as a fallback for the search tab.
POPULAR = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "SPY", "QQQ", "VTI", "AMD", "NFLX"
]


# ---------------------------------------------------------------------
# Tiny in-memory TTL cache for upstream Yahoo calls.
# Thread-safe enough for a single-process Flask app. If you run gunicorn
# with multiple workers, each worker keeps its own cache — still fine,
# you just get up to N upstream calls per TTL window instead of 1.
# ---------------------------------------------------------------------
_CACHE = {}
_CACHE_LOCK = Lock()


def _cached_get(url, headers, ttl=30):
    """GET with a per-URL TTL cache. Returns the requests.Response."""
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(url)
        if hit and now - hit["ts"] < ttl:
            return hit["resp"]

    resp = requests.get(url, headers=headers, timeout=15)

    with _CACHE_LOCK:
        _CACHE[url] = {"ts": now, "resp": resp}
    return resp


YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _alpaca_account_id():
    db = get_db()
    row = db.execute(
        "SELECT alpaca_account_id FROM kyc_submissions "
        "WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
        (g.user["id"],)
    ).fetchone()
    db.close()
    return row["alpaca_account_id"] if row else None


# ---------------------------------------------------------------------
# Search — now backed by Yahoo Finance
# ---------------------------------------------------------------------
@bp.get("/search")
@login_required
def search():
    q = (request.args.get("q") or "").strip()

    # Empty query → return the curated popular list, same shape as before.
    if not q:
        return jsonify({
            "results": [{"symbol": s, "name": s} for s in POPULAR]
        })

    url = (
        "https://query1.finance.yahoo.com/v1/finance/search"
        f"?q={requests.utils.quote(q)}&quotesCount=20&newsCount=0"
    )

    try:
        upstream = _cached_get(url, YAHOO_HEADERS, ttl=300)
    except requests.RequestException as err:
        return jsonify({"error": f"Search failed: {err}"}), 502

    if upstream.status_code != 200:
        return jsonify({"error": f"Upstream {upstream.status_code}"}), 502

    try:
        data = upstream.json()
    except ValueError:
        return jsonify({"error": "Upstream returned non-JSON"}), 502

    quotes = data.get("quotes", []) or []
    results = [
        {
            "symbol":   qq.get("symbol"),
            "name":     qq.get("shortname") or qq.get("longname") or qq.get("symbol"),
            "exchange": qq.get("exchange") or qq.get("exchDisp") or "",
            "type":     qq.get("quoteType") or "",
        }
        for qq in quotes
        if qq.get("symbol")
        and qq.get("quoteType") in ("EQUITY", "ETF", "INDEX")
    ]

    return jsonify({"results": results})


# ---------------------------------------------------------------------
# Chart proxy for the dashboard's canvas renderer
# GET /api/stock/chart/AAPL?range=3mo&interval=1d
# ---------------------------------------------------------------------
@bp.get("/chart/<path:symbol>")
@login_required
def chart(symbol):
    symbol   = symbol.upper()
    range_   = request.args.get("range", "3mo")
    interval = request.args.get("interval", "1d")

    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{symbol}?range={range_}&interval={interval}"
    )

    try:
        upstream = _cached_get(url, YAHOO_HEADERS, ttl=30)
    except requests.RequestException as err:
        return jsonify({"error": f"Chart failed: {err}"}), 502

    return Response(
        upstream.content,
        status=upstream.status_code,
        content_type=upstream.headers.get("Content-Type", "application/json"),
    )


# ---------------------------------------------------------------------
# Alpaca-backed endpoints (unchanged behaviour)
# ---------------------------------------------------------------------
@bp.get("/quote/<symbol>")
@login_required
def quote(symbol):
    symbol = symbol.upper()
    try:
        data = alpaca.get_quote(symbol)
        return jsonify(data)
    except Exception as err:
        return jsonify({"error": f"Quote failed: {err}"}), 502


@bp.get("/bars/<symbol>")
@login_required
def bars(symbol):
    symbol = symbol.upper()
    timeframe = request.args.get("timeframe", "1Day")
    limit = min(int(request.args.get("limit", 100)), 500)
    try:
        data = alpaca.get_bars(symbol, timeframe=timeframe, limit=limit)
        return jsonify({"symbol": symbol, "bars": data})
    except Exception as err:
        return jsonify({"error": f"Bars failed: {err}"}), 502


@bp.get("/positions")
@login_required
def positions():
    acct = _alpaca_account_id()
    if not acct:
        return jsonify({"positions": [], "status": "no_account"})
    try:
        return jsonify({"positions": alpaca.get_positions(acct)})
    except Exception as err:
        return jsonify({"error": str(err)}), 502


@bp.get("/orders")
@login_required
def orders():
    acct = _alpaca_account_id()
    if not acct:
        return jsonify({"orders": []})
    try:
        return jsonify({"orders": alpaca.get_orders(acct)})
    except Exception as err:
        return jsonify({"error": str(err)}), 502


@bp.post("/order")
@login_required
def place_order():
    body = request.get_json(silent=True) or {}
    symbol = (body.get("symbol") or "").upper()
    side   = (body.get("side") or "").upper()
    qty    = body.get("qty")
    try:
        qty = float(qty)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid qty"}), 400

    if not symbol or side not in ("BUY", "SELL") or qty <= 0:
        return jsonify({"error": "symbol, side, qty required"}), 400

    acct = _alpaca_account_id()
    if not acct:
        return jsonify({"error": "No brokerage account. Complete KYC first."}), 400

    try:
        result = alpaca.place_order(acct, symbol, qty, side)
        return jsonify({"ok": True, "order": result}), 201
    except Exception as err:
        return jsonify({"error": f"Order failed: {err}"}), 502