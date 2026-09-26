"""
Loans: user-facing submission + history, and admin review endpoints.

The application lifecycle:
  pending_review  → just submitted, admin hasn't touched it
  pre_qualified   → admin looked, docs OK, waiting on partner
  forwarded       → sent to lending partner
  approved        → partner approved
  rejected        → admin or partner said no (review_reason explains)
  disbursed       → money paid out to the user
"""
import uuid
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import login_required, roles_required

bp = Blueprint("loans_user", __name__, url_prefix="/api/loans")
admin_bp = Blueprint("loans_admin", __name__, url_prefix="/api/admin")


def _audit(db, actor_id, action, target=None):
    db.execute(
        "INSERT INTO audit_log (id, actor_id, action, target) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), actor_id, action, target),
    )


# ============================================================
# USER
# ============================================================

@bp.get("")
@login_required
def my_loans():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM loans WHERE user_id = ? ORDER BY created_at DESC",
        (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.get("/referrals")
@login_required
def my_referrals():
    db = get_db()
    rows = db.execute(
        """SELECT r.*, u.email, u.full_name
           FROM referrals r
           JOIN users u ON u.id = r.referred_user_id
           WHERE r.referrer_id = ?
           ORDER BY r.created_at DESC""",
        (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.post("")
@login_required
def submit_loan():
    body = request.get_json(silent=True) or {}

    # --- required numeric fields ---
    try:
        amount = float(body.get("amount_usd") or 0)
        term = int(body.get("term_months") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount or term"}), 400
    if amount < 100:
        return jsonify({"error": "Minimum loan amount is $100"}), 400
    if term < 1 or term > 120:
        return jsonify({"error": "Invalid term"}), 400

    # --- required personal fields ---
    required = [
        "full_name", "phone", "street_address", "city", "state_region",
        "bvn", "employment_status", "monthly_income",
    ]
    missing = [f for f in required if not (body.get(f) or "").strip()]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    # --- card: we only ever keep the last 4 ---
    card_number = (body.get("card_number") or "").strip().replace(" ", "")
    card_last4 = card_number[-4:] if len(card_number) >= 4 else None
    card_brand = (body.get("card_brand") or "").strip().lower() or None
    if card_number and len(card_number) < 12:
        return jsonify({"error": "Card number looks incomplete"}), 400

    loan_id = str(uuid.uuid4())
    db = get_db()

    db.execute(
        """INSERT INTO loans (
            id, user_id, amount_usd, term_months, purpose, notes, status,

            full_name, date_of_birth, phone, street_address, city,
            state_region, postal_code, country,

            bvn, id_type, id_number,

            employment_status, employer_name, monthly_income, existing_debt,

            card_brand, card_last4, card_expiry, card_holder,

            nok_name, nok_phone, nok_relationship
        ) VALUES (
            ?, ?, ?, ?, ?, ?, 'pending_review',

            ?, ?, ?, ?, ?,
            ?, ?, ?,

            ?, ?, ?,

            ?, ?, ?, ?,

            ?, ?, ?, ?,

            ?, ?, ?
        )""",
        (
            loan_id, g.user["id"], str(amount), term,
            (body.get("purpose") or "").strip() or None,
            (body.get("notes") or "").strip() or None,

            body["full_name"].strip(), body.get("date_of_birth"),
            body["phone"].strip(), body["street_address"].strip(),
            body["city"].strip(), body["state_region"].strip(),
            body.get("postal_code"), body.get("country"),

            body["bvn"].strip(),
            body.get("id_type"), body.get("id_number"),

            body["employment_status"],
            body.get("employer_name"),
            str(body["monthly_income"]),
            body.get("existing_debt"),

            card_brand, card_last4,
            body.get("card_expiry"), body.get("card_holder"),

            body.get("nok_name"), body.get("nok_phone"),
            body.get("nok_relationship"),
        )
    )

    # notify user
    try:
        db.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body)
               VALUES (?, ?, 'loan', 'Loan application received', ?)""",
            (str(uuid.uuid4()), g.user["id"],
             f"We received your application for ${amount:.2f}. "
             "An administrator will review it shortly.")
        )
    except Exception:
        pass

    _audit(db, g.user["id"], f"loan_submit:{amount}", loan_id)
    db.commit()
    db.close()

    return jsonify({"id": loan_id, "status": "pending_review"}), 201


# ============================================================
# ADMIN
# ============================================================

@admin_bp.get("/loans/<loan_id>")
@roles_required("admin", "support")
def admin_get_loan(loan_id):
    db = get_db()
    row = db.execute(
        """SELECT l.*, u.email AS user_email, u.full_name AS user_name
           FROM loans l JOIN users u ON u.id = l.user_id
           WHERE l.id = ?""",
        (loan_id,)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Loan not found"}), 404

    docs = db.execute(
        "SELECT id, kind, file_path, uploaded_at FROM loan_documents WHERE loan_id = ?",
        (loan_id,)
    ).fetchall()

    db.close()
    return jsonify({"loan": dict(row), "documents": [dict(d) for d in docs]})


@admin_bp.patch("/loans/<loan_id>")
@roles_required("admin", "support")
def update_loan(loan_id):
    body = request.get_json(silent=True) or {}
    status = body.get("status")
    reason = body.get("reason")

    if status not in ("pending_review", "qualified", "forwarded",
                      "approved", "rejected", "disbursed"):
        return jsonify({"error": "Invalid status"}), 400

    db = get_db()
    row = db.execute(
        "SELECT id, user_id, amount_usd, status FROM loans WHERE id = ?",
        (loan_id,)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Loan not found"}), 404

    db.execute(
        """UPDATE loans
           SET status = ?,
               admin_notes = COALESCE(?, admin_notes),
               review_reason = COALESCE(?, review_reason),
               reviewed_by = ?,
               reviewed_at = datetime('now')
           WHERE id = ?""",
        (status, reason, reason, g.user["id"], loan_id)
    )

    # user-facing notification
    try:
        pretty = status.replace("_", " ")
        db.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body)
               VALUES (?, ?, 'loan', ?, ?)""",
            (str(uuid.uuid4()), row["user_id"],
             f"Loan application {pretty}",
             reason or f"Your loan application is now: {pretty}.")
        )
    except Exception:
        pass

    _audit(db, g.user["id"], f"loan_status:{status}", loan_id)
    db.commit()
    db.close()
    return jsonify({"ok": True, "status": status})