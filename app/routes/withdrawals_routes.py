"""
Withdrawal flow — user side.

  POST /api/banking/withdraw/request   -> creates a request + hashed code
  GET  /api/banking/withdraw/my-requests
  POST /api/banking/withdraw/confirm   -> code + move funds
  POST /api/banking/withdraw/<id>/resend

Money movement is a local ledger op. When Alpaca Transfers is live, swap
the debit block for a call to alpaca.create_transfer(...).

Code lifecycle:
  - Request time:  generate plaintext, store its hash, do not show anyone.
  - Approval time: admin endpoint generates a NEW plaintext, hashes it,
                   overwrites the old hash, and sends the plaintext to the
                   user via the notifications table.
  - Confirm time:  the stored hash is verified against the code the user
                   typed. Single-use: the row is flipped to 'completed'.

Withdrawal policy (per-user):
  users.require_wallet_to_withdraw
    1 → user must have an approved wallet on file (wallets.status='stored')
    0 → user must supply destination details on each request; those are
        stored in withdrawal_destinations for the admin to review.
"""
import uuid
import secrets
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import login_required, hash_password, verify_password

bp = Blueprint("withdrawals", __name__, url_prefix="/api/banking/withdraw")

CODE_TTL_MINUTES = 10
STALE_PENDING_HOURS = 24


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _generate_code():
    """6-digit numeric code, no leading zero."""
    return str(secrets.randbelow(900000) + 100000)


def _parse_amount(raw):
    try:
        amount = Decimal(str(raw or "0"))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if amount <= 0:
        return None
    return amount


def _notify_admins(db, title, body, kind="withdrawals"):
    try:
        admins = db.execute(
            "SELECT id FROM users WHERE role IN ('admin', 'support')"
        ).fetchall()
        for a in admins:
            db.execute(
                """INSERT INTO notifications (id, user_id, kind, title, body)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), a["id"], kind, title, body),
            )
    except Exception:
        pass


def _expire_stale_pending(db, user_id):
    try:
        db.execute(
            """UPDATE withdrawal_requests
               SET status = 'expired'
               WHERE user_id = ?
                 AND status IN ('pending_admin', 'code_sent')
                 AND requested_at < datetime('now', ?)""",
            (user_id, f"-{STALE_PENDING_HOURS} hours"),
        )
    except Exception:
        pass


def _user_has_stored_wallet(db, user_id):
    try:
        row = db.execute(
            """SELECT id FROM wallets
               WHERE user_id = ? AND status = 'stored'
               LIMIT 1""",
            (user_id,)
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _validate_destination(destination):
    """
    Returns (cleaned_dict, error_message).
    cleaned_dict is only returned when error_message is None.
    """
    if not isinstance(destination, dict):
        return None, "Provide destination details."

    method = (destination.get("method") or "").strip().lower()
    if method not in ("bank", "crypto", "other"):
        return None, "Destination method must be 'bank', 'crypto', or 'other'."

    cleaned = {"method": method}

    if method == "bank":
        required = ["bank_name", "account_name", "account_number"]
        for f in required:
            v = (destination.get(f) or "").strip()
            if not v:
                return None, f"Missing destination field: {f}"
            cleaned[f] = v
        cleaned["routing_number"] = (destination.get("routing_number") or "").strip() or None
        cleaned["swift"] = (destination.get("swift") or "").strip() or None

    elif method == "crypto":
        for f in ("wallet_address", "network"):
            v = (destination.get(f) or "").strip()
            if not v:
                return None, f"Missing destination field: {f}"
            cleaned[f] = v

    else:  # other
        note = (destination.get("note") or "").strip()
        if not note:
            return None, "Provide a note describing where to send the funds."
        cleaned["note"] = note

    return cleaned, None


# ------------------------------------------------------------
# USER: request a withdrawal
# ------------------------------------------------------------

@bp.post("/request")
@login_required
def request_withdrawal():
    body = request.get_json(silent=True) or {}

    amount = _parse_amount(body.get("amount_usd"))
    if amount is None:
        return jsonify({"error": "Enter a valid amount greater than zero."}), 400

    db = get_db()

    # ---- 1. Load the user --------------------------------------------------
    user = db.execute(
        """SELECT id, cash_balance, require_wallet_to_withdraw
           FROM users WHERE id = ?""",
        (g.user["id"],)
    ).fetchone()

    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    # ---- 2. Wallet policy (per-user) --------------------------------------
    needs_wallet = bool(user["require_wallet_to_withdraw"])
    destination = None

    if needs_wallet:
        if not _user_has_stored_wallet(db, g.user["id"]):
            db.close()
            return jsonify({
                "error": "wallet_required",
                "message": "Your account requires a linked wallet before "
                           "withdrawal. Go to Link Wallet to add one."
            }), 400
    else:
        # User must supply destination details on this request.
        destination, err = _validate_destination(body.get("destination"))
        if err:
            db.close()
            return jsonify({
                "error": "destination_required",
                "message": err,
            }), 400

    # ---- 3. Auto-expire stale pending requests ----------------------------
    _expire_stale_pending(db, g.user["id"])

    # ---- 4. Reject if a fresh pending request exists ----------------------
    pending = db.execute(
        """SELECT id, status FROM withdrawal_requests
           WHERE user_id = ? AND status IN ('pending_admin', 'code_sent')
           ORDER BY requested_at DESC LIMIT 1""",
        (g.user["id"],)
    ).fetchone()
    if pending:
        db.close()
        return jsonify({
            "error": "You already have a withdrawal request in progress.",
            "pending_id": pending["id"],
            "pending_status": pending["status"],
        }), 409

    # ---- 5. Balance check -------------------------------------------------
    current = Decimal(str(user["cash_balance"] or "0"))
    if current < amount:
        db.close()
        return jsonify({
            "error": "Insufficient balance",
            "available": f"{current:.2f}",
            "required":  f"{amount:.2f}",
        }), 400

    # ---- 6. Create the request + code -------------------------------------
    code = _generate_code()
    req_id = str(uuid.uuid4())

    try:
        db.execute("BEGIN IMMEDIATE")

        db.execute(
            """INSERT INTO withdrawal_requests
               (id, user_id, amount_usd, status, code_hash, code_expires_at)
               VALUES (?, ?, ?, 'pending_admin', ?, datetime('now', ?))""",
            (
                req_id, g.user["id"], f"{amount:.2f}",
                hash_password(code),
                f"+{CODE_TTL_MINUTES} minutes",
            )
        )

        # Persist the destination details, if any.
        if destination:
            db.execute(
                """INSERT INTO withdrawal_destinations
                   (id, request_id, user_id, method,
                    bank_name, account_name, account_number,
                    routing_number, swift,
                    wallet_address, network, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), req_id, g.user["id"],
                    destination["method"],
                    destination.get("bank_name"),
                    destination.get("account_name"),
                    destination.get("account_number"),
                    destination.get("routing_number"),
                    destination.get("swift"),
                    destination.get("wallet_address"),
                    destination.get("network"),
                    destination.get("note"),
                )
            )

        _notify_admins(
            db,
            "New withdrawal request",
            f"A user requested a withdrawal of ${amount:.2f}. "
            f"Review it in the Withdrawals queue.",
            kind="withdrawals",
        )

        db.commit()
    except Exception as e:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({
            "error": "Could not create withdrawal request",
            "detail": str(e),
        }), 500

    db.close()
    return jsonify({
        "ok": True,
        "request_id": req_id,
        "status": "pending_admin",
        "amount_usd": f"{amount:.2f}",
        "expires_in_minutes": CODE_TTL_MINUTES,
    }), 201


# ------------------------------------------------------------
# USER: view their own requests
# ------------------------------------------------------------

@bp.get("/my-requests")
@login_required
def my_requests():
    db = get_db()
    rows = db.execute(
        """SELECT id, amount_usd, status,
                  requested_at, code_sent_at, code_expires_at,
                  completed_at, rejection_reason
           FROM withdrawal_requests
           WHERE user_id = ?
           ORDER BY requested_at DESC
           LIMIT 20""",
        (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


# ------------------------------------------------------------
# USER: confirm with the code
# ------------------------------------------------------------

@bp.post("/confirm")
@login_required
def confirm_withdrawal():
    body = request.get_json(silent=True) or {}
    req_id = (body.get("request_id") or "").strip()
    code   = (body.get("code") or "").strip()

    if not req_id or not code:
        return jsonify({"error": "request_id and code are required"}), 400
    if not code.isdigit() or len(code) != 6:
        return jsonify({"error": "Code must be exactly 6 digits"}), 400

    db = get_db()
    row = db.execute(
        """SELECT id, user_id, amount_usd, status, code_hash, code_expires_at
           FROM withdrawal_requests
           WHERE id = ?""",
        (req_id,)
    ).fetchone()

    if not row:
        db.close()
        return jsonify({"error": "Request not found"}), 404
    if row["user_id"] != g.user["id"]:
        db.close()
        return jsonify({"error": "Forbidden"}), 403

    if row["status"] == "completed":
        db.close()
        return jsonify({
            "ok": True,
            "status": "completed",
            "amount_usd": row["amount_usd"],
            "note": "Already confirmed previously.",
        }), 200
    if row["status"] == "rejected":
        db.close()
        return jsonify({"error": "This request was rejected"}), 409
    if row["status"] == "expired":
        db.close()
        return jsonify({"error": "This request has expired. Please start a new withdrawal."}), 409
    if row["status"] != "code_sent":
        db.close()
        return jsonify({"error": "The admin has not approved this request yet"}), 409

    expired = db.execute(
        """SELECT 1 FROM withdrawal_requests
           WHERE id = ? AND datetime(code_expires_at) < datetime('now')""",
        (req_id,)
    ).fetchone()
    if expired:
        db.execute(
            "UPDATE withdrawal_requests SET status = 'expired' WHERE id = ?",
            (req_id,)
        )
        db.commit()
        db.close()
        return jsonify({"error": "This code has expired. Please request a new withdrawal."}), 409

    if not verify_password(code, row["code_hash"]):
        db.close()
        return jsonify({"error": "Incorrect code. Check your notifications and try again."}), 401

    amount = Decimal(str(row["amount_usd"] or "0"))
    transfer_id = None
    new_balance = None

    try:
        db.execute("BEGIN IMMEDIATE")

        u = db.execute(
            "SELECT cash_balance FROM users WHERE id = ?",
            (row["user_id"],)
        ).fetchone()
        current = Decimal(str((u["cash_balance"] if u else "0") or "0"))

        if current < amount:
            db.execute("ROLLBACK")
            db.close()
            return jsonify({
                "error": "Insufficient balance. Your balance changed since the request.",
                "available": f"{current:.2f}",
                "required":  f"{amount:.2f}",
            }), 400

        new_balance = current - amount
        db.execute(
            "UPDATE users SET cash_balance = ? WHERE id = ?",
            (f"{new_balance:.2f}", row["user_id"])
        )

        transfer_id = str(uuid.uuid4())
        try:
            db.execute(
                """INSERT INTO transfers
                   (id, user_id, direction, amount_usd, status, requested_at)
                   VALUES (?, ?, 'withdrawal', ?, 'completed', datetime('now'))""",
                (transfer_id, row["user_id"], f"{amount:.2f}")
            )
        except Exception:
            transfer_id = None

        db.execute(
            """UPDATE withdrawal_requests
               SET status = 'completed',
                   completed_at = datetime('now'),
                   transfer_id = ?
               WHERE id = ?""",
            (transfer_id, req_id)
        )

        try:
            db.execute(
                """INSERT INTO notifications (id, user_id, kind, title, body)
                   VALUES (?, ?, 'withdrawal', 'Withdrawal completed', ?)""",
                (str(uuid.uuid4()), row["user_id"],
                 f"Your withdrawal of ${amount:.2f} has been processed.")
            )
        except Exception:
            pass

        db.commit()
    except Exception as e:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({"error": f"Confirmation failed: {e}"}), 500

    db.close()
    return jsonify({
        "ok": True,
        "status": "completed",
        "amount_usd": f"{amount:.2f}",
        "new_balance": f"{new_balance:.2f}" if new_balance is not None else None,
    })


# ------------------------------------------------------------
# USER: resend code
# ------------------------------------------------------------

@bp.post("/<request_id>/resend")
@login_required
def resend_withdrawal_code(request_id):
    db = get_db()
    row = db.execute(
        """SELECT id, user_id, amount_usd, status
           FROM withdrawal_requests WHERE id = ?""",
        (request_id,)
    ).fetchone()

    if not row:
        db.close()
        return jsonify({"error": "Request not found"}), 404
    if row["user_id"] != g.user["id"]:
        db.close()
        return jsonify({"error": "Forbidden"}), 403
    if row["status"] != "code_sent":
        db.close()
        return jsonify({
            "error": f"Cannot resend code for a request in status '{row['status']}'.",
            "hint": "Only approved requests awaiting confirmation can be resent."
        }), 409

    new_code = _generate_code()

    try:
        db.execute(
            """UPDATE withdrawal_requests
               SET code_hash = ?,
                   code_expires_at = datetime('now', ?)
               WHERE id = ?""",
            (hash_password(new_code), f"+{CODE_TTL_MINUTES} minutes", request_id)
        )
        try:
            db.execute(
                """INSERT INTO notifications (id, user_id, kind, title, body)
                   VALUES (?, ?, 'withdrawal', 'New withdrawal code', ?)""",
                (str(uuid.uuid4()), row["user_id"],
                 f"Your new confirmation code is: {new_code}\n\n"
                 f"Enter it on the Withdraw page within {CODE_TTL_MINUTES} minutes. "
                 f"This code is single-use.")
            )
        except Exception:
            pass
        db.commit()
    except Exception as e:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({"error": f"Could not resend: {e}"}), 500

    db.close()
    return jsonify({
        "ok": True,
        "message": "A new code was sent to your notifications.",
        "expires_in_minutes": CODE_TTL_MINUTES,
    })