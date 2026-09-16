import uuid
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import login_required

bp = Blueprint("support", __name__, url_prefix="/api/support-tickets")


@bp.get("")
@login_required
def list_my_tickets():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM support_tickets WHERE user_id = ? ORDER BY updated_at DESC", (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.post("")
@login_required
def create_ticket():
    body = request.get_json(silent=True) or {}
    subject, message = body.get("subject"), body.get("message")
    if not subject or not message:
        return jsonify({"error": "subject and message are required"}), 400

    db = get_db()
    ticket_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO support_tickets (id, user_id, subject, message) VALUES (?, ?, ?, ?)",
        (ticket_id, g.user["id"], subject, message),
    )
    db.commit()
    db.close()
    return jsonify({"id": ticket_id}), 201


@bp.get("/<ticket_id>/replies")
@login_required
def my_ticket_replies(ticket_id):
    db = get_db()
    ticket = db.execute(
        "SELECT * FROM support_tickets WHERE id = ? AND user_id = ?", (ticket_id, g.user["id"])
    ).fetchone()
    if not ticket:
        db.close()
        return jsonify({"error": "Not found"}), 404
    rows = db.execute(
        "SELECT * FROM ticket_replies WHERE ticket_id = ? ORDER BY created_at ASC", (ticket_id,)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])
