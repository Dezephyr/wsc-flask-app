import requests as http
from flask import Blueprint, jsonify, g
from ..db import get_db
from ..auth import login_required
from ..services import alpaca_broker as alpaca

bp = Blueprint("portfolio", __name__, url_prefix="/api/portfolio")


@bp.get("")
@login_required
def get_portfolio():
    db = get_db()
    kyc = db.execute(
        "SELECT * FROM kyc_submissions WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1", (g.user["id"],)
    ).fetchone()
    db.close()

    if not kyc or not kyc["alpaca_account_id"]:
        return jsonify({"status": "no_account", "account": None, "positions": []})

    try:
        account = alpaca.get_trade_account(kyc["alpaca_account_id"])
        positions = alpaca.get_positions(kyc["alpaca_account_id"])
        return jsonify({"status": "ok", "account": account, "positions": positions})
    except http.RequestException as err:
        return jsonify({"error": "Could not reach Alpaca", "detail": str(err)}), 502
