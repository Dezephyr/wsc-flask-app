import uuid
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import roles_required

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _audit(db, actor_id, action, target=None):
    db.execute(
        "INSERT INTO audit_log (id, actor_id, action, target) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), actor_id, action, target),
    )


# ---------- Users & KYC (read-only + status view, never balances) ----------

@bp.get("/users")
@roles_required("admin")
def list_users():
    db = get_db()
    rows = db.execute(
        "SELECT id, email, full_name, role, created_at FROM users ORDER BY created_at DESC"
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


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
    """
    Admins can only reflect Alpaca's decision locally (e.g. after checking
    the Broker dashboard or an Events webhook) — they cannot invent an
    approval.
    """
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


# ---------- Content pages (marketing copy, disclosures) ----------

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


# ---------- Compliance documents (metadata only in this scaffold — wire
# file_path to real object storage such as S3 with server-side encryption) ----------

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


# ---------- Support tickets ----------

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
