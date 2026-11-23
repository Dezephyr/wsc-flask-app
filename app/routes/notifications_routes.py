import uuid
from flask import Blueprint, jsonify, g
from ..db import get_db
from ..auth import login_required

bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")


@bp.get("")
@login_required
def list_notifications():
    db = get_db()
    rows = db.execute(
        """SELECT * FROM notifications
           WHERE user_id = ?
           ORDER BY created_at DESC
           LIMIT 50""",
        (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.get("/unread-count")
@login_required
def unread_count():
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read = 0",
        (g.user["id"],)
    ).fetchone()
    db.close()
    return jsonify({"count": row["n"] if row else 0})


@bp.post("/<notification_id>/read")
@login_required
def mark_read(notification_id):
    db = get_db()
    db.execute(
        "UPDATE notifications SET read = 1 WHERE id = ? AND user_id = ?",
        (notification_id, g.user["id"])
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@bp.post("/read-all")
@login_required
def mark_all_read():
    db = get_db()
    db.execute(
        "UPDATE notifications SET read = 1 WHERE user_id = ?",
        (g.user["id"],)
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ---------- helper for other routes to create a notification ----------
def notify(user_id, kind, title, body=None):
    import uuid as _uuid
    db = get_db()
    db.execute(
        "INSERT INTO notifications (id, user_id, kind, title, body) VALUES (?, ?, ?, ?, ?)",
        (str(_uuid.uuid4()), user_id, kind, title, body)
    )
    db.commit()
    db.close()