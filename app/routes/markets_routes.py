from flask import Blueprint, jsonify, request
from ..auth import login_required
from ..services import coinbase_client

bp = Blueprint("markets", __name__, url_prefix="/api/markets")


# The six products we want to show on the Crypto Trading page.
# product_id format on Advanced Trade: BASE-QUOTE (e.g. BTC-USD).
DEFAULT_PRODUCTS = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "USDT-USD",
    "USDC-USD",
    "ADA-USD",
]


@bp.get("/crypto")
@login_required
def crypto_markets():
    """
    Return a curated list of crypto markets with their live spot prices.
    Public data (no user-specific info), cached 10 seconds.
    """
    products = coinbase_client.get_products()
    by_id = {p.get("product_id"): p for p in products if p.get("product_id")}

    rows = []
    for pid in DEFAULT_PRODUCTS:
        p = by_id.get(pid)
        if not p:
            continue
        try:
            price = float(p.get("price") or 0)
        except (TypeError, ValueError):
            price = 0

        rows.append({
            "product_id": p.get("product_id"),
            "base": p.get("base_currency_id"),
            "quote": p.get("quote_currency_id"),
            "price": price,
            "price_percentage_change_24h": float(p.get("price_percentage_change_24h") or 0),
            "volume_24h": float(p.get("volume_24h") or 0),
            "status": p.get("status"),
            "trading_disabled": bool(p.get("trading_disabled")),
        })

    return jsonify({"products": rows})


@bp.get("/crypto/<path:product_id>")
@login_required
def crypto_detail(product_id):
    """
    Single product detail — used by the trade modal.
    """
    price = coinbase_client.get_spot_price(product_id)
    if price is None:
        return jsonify({"error": "Product not found or price unavailable"}), 404
    return jsonify({"product_id": product_id, "price": price})