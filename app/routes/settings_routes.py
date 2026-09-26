from flask import Blueprint, jsonify
from ..services import price_feed
from ..db import get_db
from ..auth import login_required
import json


bp = Blueprint("settings_public", __name__, url_prefix="/api/settings")


@bp.get("/public")
@login_required
def public_settings():
    """
    Returns only what a user needs to know: which payment methods are
    enabled, and the addresses/details to send money to. Also includes
    live USD prices for each enabled crypto, sourced from CoinMarketCap
    and cached server-side for 5 minutes. Falls back to the admin's
    manual price_usd if live prices aren't available.
    """
    db = get_db()
    row = db.execute(
        "SELECT value FROM platform_settings WHERE key = 'payment_methods'"
    ).fetchone()
    rate_row = db.execute(
        "SELECT value FROM platform_settings WHERE key = 'ngn_rate'"
    ).fetchone()
    db.close()

    try:
        pm = json.loads(row["value"]) if row else {}
    except Exception:
        pm = {}

    try:
        rate = json.loads(rate_row["value"]) if rate_row else 1650
    except Exception:
        rate = 1650

    bank = pm.get("bank", {}) or {}
    crypto_list = pm.get("crypto", []) or []

    # --- bank (unchanged) ---
    enabled_bank = None
    if bank.get("enabled"):
        enabled_bank = {
            "bank_name": bank.get("bank_name", ""),
            "account_name": bank.get("account_name", ""),
            "account_number": bank.get("account_number", ""),
            "routing_number": bank.get("routing_number", ""),
            "swift": bank.get("swift", ""),
            "reference_hint": bank.get("reference_hint", ""),
        }

    # --- crypto ---
    # First, filter down to the entries we care about.
    candidates = [
        c for c in crypto_list
        if c.get("enabled") and c.get("address") and c.get("coin")
    ]

    # Ask the price feed for live USD prices for all of them in one call.
    symbols = [c["coin"].upper() for c in candidates]
    live_prices = price_feed.get_prices(symbols) if symbols else {}

    enabled_crypto = []
    for c in candidates:
        symbol = c["coin"].upper()

        # Prefer live price; fall back to admin price; else 0.
        price = live_prices.get(symbol)
        if price is None:
            try:
                price = float(c.get("price_usd") or 0)
            except (TypeError, ValueError):
                price = 0
        source = "live" if symbol in live_prices else "manual"

        enabled_crypto.append({
            "id": c.get("id"),
            "coin": c.get("coin"),
            "network": c.get("network"),
            "address": c.get("address"),
            "price_usd": price,
            "price_source": source,
        })

    return jsonify({
        "bank": enabled_bank,
        "crypto": enabled_crypto,
        "ngn_rate": float(rate) if rate else 1650,
    })