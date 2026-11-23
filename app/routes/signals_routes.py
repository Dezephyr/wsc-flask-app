"""
Premium signals: user endpoints + admin CRUD.

Users see:
  GET  /api/signals/me            → their subscription status
  GET  /api/signals               → published signals they're allowed to see
  POST /api/signals/<id>/read     → mark read (optional)

Admin:
  GET    /api/admin/signals
  POST   /api/admin/signals
  PATCH  /api/admin/signals/<id>
  DELETE /api/admin/signals/<id>
  GET    /api/admin/signal-subscriptions
  POST   /api/admin/users/<user_id>/signal-access   (grant/extend/revoke)
"""
import uuid
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import login_required, roles_required

bp = Blueprint("signals", __name__, url_prefix="/api/signals")
admin_bp = Blueprint("signals_admin", __name__, url_prefix="/api/admin")


# ============================================================
# USER ENDPOINTS
# ============================================================

def _active_subscription(db, user_id):
    """Return the user's current active signal subscription row, or None."""
    row = db.execute(
        """SELECT id, tier, status, started_at, expires_at
           FROM user_signal_subscriptions
           WHERE user_id = ? AND status = 'active'
             AND (expires_at IS NULL OR expires_at > datetime('now'))
           ORDER BY started_at DESC LIMIT 1""",
        (user_id,)
    ).fetchone()
    return row


@bp.get("/me")
@login_required
def my_subscription():
    db = get_db()
    sub = _active_subscription(db, g.user["id"])
    db.close()
    if not sub:
        return jsonify({"active": False})
    return jsonify({
        "active": True,
        "tier": sub["tier"],
        "started_at": sub["started_at"],
        "expires_at": sub["expires_at"],
    })


@bp.get("")
@login_required
def list_signals():
    db = get_db()
    sub = _active_subscription(db, g.user["id"])
    if not sub:
        db.close()
        return jsonify({"signals": [], "requires_subscription": True})

    allowed_tiers = ["premium"]
    if sub["tier"] == "vip":
        allowed_tiers.append("vip")

    placeholders = ",".join("?" for _ in allowed_tiers)
    rows = db.execute(
        f"""SELECT id, title, body, symbol, side,
                   entry_price, target_price, stop_price,
                   confidence, tier, created_at
            FROM premium_signals
            WHERE status = 'published' AND tier IN ({placeholders})
            ORDER BY created_at DESC
            LIMIT 100""",
        allowed_tiers
    ).fetchall()
    db.close()
    return jsonify({"signals": [dict(r) for r in rows], "requires_subscription": False})


# ============================================================
# ADMIN ENDPOINTS — signals CRUD
# ============================================================

def _audit(db, actor_id, action, target=None):
    db.execute(
        "INSERT INTO audit_log (id, actor_id, action, target) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), actor_id, action, target),
    )


@admin_bp.get("/signals")
@roles_required("admin", "support")
def admin_list_signals():
    db = get_db()
    rows = db.execute(
        """SELECT * FROM premium_signals ORDER BY created_at DESC"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@admin_bp.post("/signals")
@roles_required("admin")
def admin_create_signal():
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "").strip()
    text  = (body.get("body") or "").strip()
    if not title or not text:
        return jsonify({"error": "title and body are required"}), 400

    sig_id = str(uuid.uuid4())
    db = get_db()
    db.execute(
        """INSERT INTO premium_signals
           (id, title, body, symbol, side, entry_price, target_price,
            stop_price, confidence, tier, status, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sig_id, title, text,
         (body.get("symbol") or "").upper() or None,
         (body.get("side") or "").upper() or None,
         body.get("entry_price"), body.get("target_price"),
         body.get("stop_price"),
         int(body.get("confidence") or 3),
         body.get("tier") or "premium",
         body.get("status") or "published",
         g.user["id"])
    )
    _audit(db, g.user["id"], "signal_create", sig_id)
    db.commit()
    db.close()
    return jsonify({"id": sig_id}), 201


@admin_bp.patch("/signals/<signal_id>")
@roles_required("admin")
def admin_update_signal(signal_id):
    body = request.get_json(silent=True) or {}
    allowed = ["title", "body", "symbol", "side", "entry_price",
               "target_price", "stop_price", "confidence", "tier", "status"]
    updates = {k: body[k] for k in allowed if k in body}
    if not updates:
        return jsonify({"error": "no fields to update"}), 400

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [signal_id]

    db = get_db()
    db.execute(
        f"UPDATE premium_signals SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
        values
    )
    _audit(db, g.user["id"], "signal_update", signal_id)
    db.commit()
    db.close()
    return jsonify({"ok": True})


@admin_bp.delete("/signals/<signal_id>")
@roles_required("admin")
def admin_delete_signal(signal_id):
    db = get_db()
    db.execute("DELETE FROM premium_signals WHERE id = ?", (signal_id,))
    _audit(db, g.user["id"], "signal_delete", signal_id)
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ============================================================
# ADMIN ENDPOINTS — subscriptions
# ============================================================

@admin_bp.get("/signal-subscriptions")
@roles_required("admin", "support")
def admin_list_subs():
    db = get_db()
    rows = db.execute(
        """SELECT s.*, u.email AS user_email, u.full_name AS user_name
           FROM user_signal_subscriptions s
           JOIN users u ON u.id = s.user_id
           ORDER BY s.started_at DESC"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@admin_bp.post("/users/<user_id>/signal-access")
@roles_required("admin")
def admin_grant_signal(user_id):
    """
    Grant, extend, or revoke signal access.

    Body:
      { action: "grant" | "revoke",
        tier: "premium" | "vip",
        days: 30,          # for grant
        price_paid: "50"   # optional
      }
    """
    body = request.get_json(silent=True) or {}
    action = body.get("action")

    db = get_db()
    user = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    if action == "revoke":
        db.execute(
            """UPDATE user_signal_subscriptions
               SET status = 'cancelled'
               WHERE user_id = ? AND status = 'active'""",
            (user_id,)
        )
        _audit(db, g.user["id"], "signal_revoke", user_id)
        db.commit()
        db.close()
        return jsonify({"ok": True, "status": "cancelled"})

    if action != "grant":
        db.close()
        return jsonify({"error": "action must be 'grant' or 'revoke'"}), 400

    tier = body.get("tier") or "premium"
    if tier not in ("premium", "vip"):
        db.close()
        return jsonify({"error": "tier must be 'premium' or 'vip'"}), 400

    try:
        days = int(body.get("days") or 30)
        if days <= 0 or days > 3650:
            raise ValueError
    except (TypeError, ValueError):
        db.close()
        return jsonify({"error": "days must be a positive integer"}), 400

    # extend existing active sub if present
    existing = db.execute(
        """SELECT id, expires_at FROM user_signal_subscriptions
           WHERE user_id = ? AND status = 'active'
           ORDER BY started_at DESC LIMIT 1""",
        (user_id,)
    ).fetchone()

    if existing and existing["expires_at"]:
        try:
            base = datetime.fromisoformat(existing["expires_at"])
        except Exception:
            base = datetime.utcnow()
    else:
        base = datetime.utcnow()

    new_expires = (base + timedelta(days=days)).isoformat(timespec="seconds")

    if existing:
        db.execute(
            """UPDATE user_signal_subscriptions
               SET tier = ?, expires_at = ?, price_paid = COALESCE(?, price_paid)
               WHERE id = ?""",
            (tier, new_expires, body.get("price_paid"), existing["id"])
        )
    else:
        db.execute(
            """INSERT INTO user_signal_subscriptions
               (id, user_id, tier, status, source, started_at, expires_at,
                price_paid, granted_by)
               VALUES (?, ?, ?, 'active', 'admin_grant', datetime('now'), ?, ?, ?)""",
            (str(uuid.uuid4()), user_id, tier, new_expires,
             body.get("price_paid"), g.user["id"])
        )

    _audit(db, g.user["id"], f"signal_grant:{tier}:{days}d", user_id)
    db.commit()
    db.close()
    return jsonify({"ok": True, "expires_at": new_expires, "tier": tier})