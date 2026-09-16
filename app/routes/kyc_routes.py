import uuid
import requests as http
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import login_required
from ..services import alpaca_broker as alpaca

bp = Blueprint("kyc", __name__, url_prefix="/api/kyc")

REQUIRED_FIELDS = [
    "given_name", "family_name", "date_of_birth", "address_line1",
    "city", "state_region", "postal_code", "country",
]


@bp.get("")
@login_required
def get_kyc():
    db = get_db()
    row = db.execute(
        "SELECT * FROM kyc_submissions WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
        (g.user["id"],),
    ).fetchone()
    db.close()
    return jsonify(dict(row) if row else None)


@bp.post("")
@login_required
def submit_kyc():
    body = request.get_json(silent=True) or {}
    missing = [f for f in REQUIRED_FIELDS if not body.get(f)]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    db = get_db()
    submission_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO kyc_submissions
           (id, user_id, legal_name, date_of_birth, address_line1, address_line2,
            city, state_region, postal_code, country, employment_status,
            is_us_citizen, status, submitted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'submitted', datetime('now'))""",
        (
            submission_id, g.user["id"],
            f"{body['given_name']} {body['family_name']}",
            body["date_of_birth"], body["address_line1"], body.get("address_line2"),
            body["city"], body["state_region"], body["postal_code"], body["country"],
            body.get("employment_status"), 0 if body.get("is_us_citizen") is False else 1,
        ),
    )
    db.commit()

    # Hand the actual identity-verification decision to Alpaca. If Broker API
    # credentials aren't configured yet (e.g. still in the partner-approval
    # process), save the submission as pending_review instead of failing the
    # whole request — an admin can retry the sync once credentials exist.
    try:
        user = db.execute("SELECT email FROM users WHERE id = ?", (g.user["id"],)).fetchone()
        account = alpaca.create_account({**body, "email": user["email"]})
        db.execute(
            "UPDATE kyc_submissions SET alpaca_account_id = ?, alpaca_account_status = ?, status = 'pending_review' WHERE id = ?",
            (account["id"], account["status"], submission_id),
        )
        db.commit()
        db.close()
        return jsonify({"id": submission_id, "status": "pending_review", "alpaca_status": account["status"]}), 201
    except (http.RequestException, KeyError) as err:
        db.execute("UPDATE kyc_submissions SET status = 'pending_review' WHERE id = ?", (submission_id,))
        db.commit()
        db.close()
        return jsonify({
            "id": submission_id,
            "status": "pending_review",
            "note": "Saved locally. Broker API sync failed or is not yet configured — see server logs.",
        }), 202
