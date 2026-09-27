from flask import Blueprint, jsonify
from ..services import price_feed
from ..db import get_db
import json


bp = Blueprint("settings_public", __name__, url_prefix="/api/settings")


@bp.get("/public")
def public_settings():
    """
    Returns only what a user needs to know: which payment methods are
    enabled, the addresses/details to send money to, the KYC requirement
    flag, and live USD prices for each enabled crypto.

    This endpoint is intentionally UNAUTHENTICATED. The login and signup
    pages call it before the user has a token, so it must not require
    login. Everything it returns is non-sensitive: bank transfer details,
    crypto deposit addresses, a display-only FX rate, and a platform-wide
    toggle. Nothing here is specific to any user.
    """
    db = get_db()

    # --- Read the KYC requirement flag ---
    # Wrapped in try/except so an older database that hasn't run the
    # kyc_required migration yet still returns a valid response.
    try:
        flag_row = db.execute(
            "SELECT kyc_required FROM platform_flags WHERE id = 1"
        ).fetchone()
        kyc_required = bool(flag_row["kyc_required"]) if flag_row else True
    except Exception:
        kyc_required = True

    # --- Read payment methods and FX rate ---
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

    # --- Bank transfer details ---
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

    # --- Crypto deposit methods ---
    # Only include entries the admin marked enabled with a real address.
    candidates = [
        c for c in crypto_list
        if c.get("enabled") and c.get("address") and c.get("coin")
    ]

    # Batch-fetch live USD prices for every coin in one call.
    symbols = [c["coin"].upper() for c in candidates]
    live_prices = price_feed.get_prices(symbols) if symbols else {}

    enabled_crypto = []
    for c in candidates:
        symbol = c["coin"].upper()

        # Prefer live price; fall back to the admin's manual price.
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
        "kyc_required": kyc_required,
    })