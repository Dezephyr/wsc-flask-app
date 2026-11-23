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
@bp.post("/public")
def create_public_ticket():
    """
    Unauthenticated contact-form submission from /contact.html.
    Creates a support ticket that shows up in the admin queue.

    Body: { name, email, subject, message }
    """
    body = request.get_json(silent=True) or {}
    name    = (body.get("name") or "").strip()
    email   = (body.get("email") or "").strip().lower()
    subject = (body.get("subject") or "").strip()
    message = (body.get("message") or "").strip()

    if not name or not email or not subject or not message:
        return jsonify({"error": "All fields are required."}), 400
    if "@" not in email:
        return jsonify({"error": "Enter a valid email address."}), 400
    if len(message) > 4000:
        return jsonify({"error": "Message is too long (max 4000 characters)."}), 400

    db = get_db()

    # Look up whether a user with this email exists, so we can attach the
    # ticket to a real account if we can. If not, we fall back to a
    # placeholder so the foreign key still resolves.
    user = db.execute(
        "SELECT id FROM users WHERE email = ?", (email,)
    ).fetchone()

    if user:
        user_id = user["id"]
    else:
        # Guest submissions: create a system user row if it doesn't exist.
        # This keeps the ticket_replies / notifications foreign keys happy.
        guest = db.execute(
            "SELECT id FROM users WHERE email = '__guest__'"
        ).fetchone()
        if guest:
            user_id = guest["id"]
        else:
            user_id = str(uuid.uuid4())
            db.execute(
                """INSERT INTO users
                   (id, email, username, password_hash, full_name, role)
                   VALUES (?, '__guest__', '__guest__', 'disabled', 'Guest', 'user')""",
                (user_id,)
            )

    ticket_id = str(uuid.uuid4())
    # Prefix the subject so admins can spot external tickets at a glance
    full_subject = f"[Contact form] {subject} — from {name} <{email}>"

    db.execute(
        "INSERT INTO support_tickets (id, user_id, subject, message) VALUES (?, ?, ?, ?)",
        (ticket_id, user_id, full_subject, message),
    )

    # Notify every admin/support user
    try:
        staff = db.execute(
            "SELECT id FROM users WHERE role IN ('admin','support')"
        ).fetchall()
        for s in staff:
            db.execute(
                """INSERT INTO notifications (id, user_id, kind, title, body)
                   VALUES (?, ?, 'support', 'New contact-form message', ?)""",
                (
                    str(uuid.uuid4()),
                    s["id"],
                    f"{name} <{email}> — {subject}",
                )
            )
    except Exception:
        pass

    db.commit()
    db.close()

    return jsonify({
        "ok": True,
        "ticket_id": ticket_id[:8],
        "message": "Your message has been received.",
    }), 201

