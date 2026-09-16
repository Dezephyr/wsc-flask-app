import uuid
import requests as http
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import login_required
from ..services import alpaca_broker as alpaca
from ..services import plaid_client as plaid

bp = Blueprint("banking", __name__, url_prefix="/api/banking")


def _latest_kyc(db, user_id):
    return db.execute(
        "SELECT * FROM kyc_submissions WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1", (user_id,)
    ).fetchone()


@bp.post("/plaid/link-token")
@login_required
def plaid_link_token():
    try:
        data = plaid.create_link_token(g.user["id"])
        return jsonify(data)
    except http.RequestException as err:
        return jsonify({"error": "Could not create Plaid link token", "detail": str(err)}), 502


@bp.post("/plaid/exchange")
@login_required
def plaid_exchange():
    """
    After the user finishes Plaid Link in the browser, exchange the public
    token, mint an Alpaca processor token, and create the ACH relationship
    on their brokerage account.
    """
    body = request.get_json(silent=True) or {}
    db = get_db()
    kyc = _latest_kyc(db, g.user["id"])
    if not kyc or not kyc["alpaca_account_id"]:
        db.close()
        return jsonify({"error": "Complete KYC and account approval before linking a bank"}), 400

    try:
        exchange = plaid.exchange_public_token(body.get("public_token"))
        processor = plaid.create_processor_token(exchange["access_token"], body.get("plaid_account_id"))
        relationship = alpaca.create_ach_relationship(kyc["alpaca_account_id"], processor["processor_token"])

        link_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO bank_links (id, user_id, alpaca_ach_relationship_id, bank_name, account_mask, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (link_id, g.user["id"], relationship["id"], body.get("bank_name"), body.get("account_mask"), relationship["status"]),
        )
        db.commit()
        db.close()
        return jsonify({"id": link_id, "status": relationship["status"]}), 201
    except http.RequestException as err:
        db.close()
        return jsonify({"error": "Could not link bank account", "detail": str(err)}), 502


@bp.get("/links")
@login_required
def list_links():
    db = get_db()
    rows = db.execute("SELECT * FROM bank_links WHERE user_id = ?", (g.user["id"],)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.post("/transfer")
@login_required
def request_transfer():
    """
    Deposit or withdrawal. This endpoint only ever calls Alpaca's Transfers
    API — it never writes a balance itself. The transfer's real status lives
    at Alpaca; what we store locally is a display cache.
    """
    body = request.get_json(silent=True) or {}
    amount_usd = body.get("amount_usd")
    direction = body.get("direction")
    bank_link_id = body.get("bank_link_id")

    if not amount_usd or direction not in ("deposit", "withdrawal"):
        return jsonify({"error": "amount_usd and direction ('deposit'|'withdrawal') are required"}), 400

    db = get_db()
    kyc = _latest_kyc(db, g.user["id"])
    link = db.execute(
        "SELECT * FROM bank_links WHERE id = ? AND user_id = ?", (bank_link_id, g.user["id"])
    ).fetchone()
    if not kyc or not kyc["alpaca_account_id"] or not link:
        db.close()
        return jsonify({"error": "Missing an approved account or linked bank"}), 400

    try:
        transfer = alpaca.create_transfer(
            kyc["alpaca_account_id"],
            link["alpaca_ach_relationship_id"],
            str(amount_usd),
            "INCOMING" if direction == "deposit" else "OUTGOING",
        )
        transfer_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO transfers (id, user_id, alpaca_transfer_id, direction, amount_usd, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (transfer_id, g.user["id"], transfer["id"], direction, str(amount_usd), transfer["status"]),
        )
        db.commit()
        db.close()
        return jsonify({"id": transfer_id, "status": transfer["status"]}), 201
    except http.RequestException as err:
        db.close()
        return jsonify({"error": "Transfer request failed", "detail": str(err)}), 502


@bp.get("/transfers")
@login_required
def list_transfers():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM transfers WHERE user_id = ? ORDER BY requested_at DESC", (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])
