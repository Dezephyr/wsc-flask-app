"""
Investment plans: user endpoints + admin CRUD.

Users:
  GET  /api/plans                     → active plans
  GET  /api/plans/me                  → my investments
  POST /api/plans/<plan_id>/invest    → buy into a plan (debits cash_balance)

Admin:
  GET    /api/admin/plans
  POST   /api/admin/plans
  PATCH  /api/admin/plans/<id>
  DELETE /api/admin/plans/<id>
  GET    /api/admin/investments
  POST   /api/admin/investments/<id>/mature   → force maturity, pay out
"""
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import login_required, roles_required

bp = Blueprint("plans", __name__, url_prefix="/api/plans")
admin_bp = Blueprint("plans_admin", __name__, url_prefix="/api/admin")


def _audit(db, actor_id, action, target=None):
    db.execute(
        "INSERT INTO audit_log (id, actor_id, action, target) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), actor_id, action, target),
    )


def _slugify(s):
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in (s or "")).strip("-") or None


# ============================================================
# USER
# ============================================================

@bp.get("")
@login_required
def list_plans():
    db = get_db()
    rows = db.execute(
        """SELECT id, name, slug, description, roi_pct, duration_days,
                  min_amount, max_amount, compounding, payout_mode
           FROM investment_plans WHERE active = 1
           ORDER BY sort_order ASC, created_at ASC"""
    ).fetchall()
    db.close()
    return jsonify({"plans": [dict(r) for r in rows]})


@bp.get("/me")
@login_required
def my_investments():
    db = get_db()
    rows = db.execute(
        """SELECT id, plan_id, plan_name, amount_usd, roi_pct, duration_days,
                  payout_mode, status, started_at, matures_at, accrued_usd
           FROM user_investments
           WHERE user_id = ?
           ORDER BY started_at DESC""",
        (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify({"investments": [dict(r) for r in rows]})


@bp.post("/<plan_id>/invest")
@login_required
def invest(plan_id):
    body = request.get_json(silent=True) or {}
    try:
        amount = Decimal(str(body.get("amount") or "0"))
    except Exception:
        return jsonify({"error": "Invalid amount"}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than zero"}), 400

    db = get_db()
    plan = db.execute(
        """SELECT id, name, roi_pct, duration_days, min_amount, max_amount,
                  payout_mode, active
           FROM investment_plans WHERE id = ?""",
        (plan_id,)
    ).fetchone()
    if not plan or not plan["active"]:
        db.close()
        return jsonify({"error": "Plan not found or inactive"}), 404

    min_amt = Decimal(str(plan["min_amount"] or "0"))
    max_amt = Decimal(str(plan["max_amount"] or "0")) if plan["max_amount"] else None
    if amount < min_amt:
        db.close()
        return jsonify({"error": f"Minimum is ${min_amt}"}), 400
    if max_amt and amount > max_amt:
        db.close()
        return jsonify({"error": f"Maximum is ${max_amt}"}), 400

    u = db.execute(
        "SELECT cash_balance FROM users WHERE id = ?", (g.user["id"],)
    ).fetchone()
    current = Decimal(str((u and u["cash_balance"]) or "0"))
    if current < amount:
        db.close()
        return jsonify({"error": "insufficient_balance", "available": str(current)}), 400

    now = datetime.utcnow()
    matures = now + timedelta(days=plan["duration_days"])
    inv_id = str(uuid.uuid4())

    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "UPDATE users SET cash_balance = ? WHERE id = ?",
            (f"{current - amount:.2f}", g.user["id"])
        )
        db.execute(
            """INSERT INTO user_investments
               (id, user_id, plan_id, plan_name, amount_usd, roi_pct,
                duration_days, payout_mode, status, started_at, matures_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (inv_id, g.user["id"], plan["id"], plan["name"],
             f"{amount:.2f}", plan["roi_pct"], plan["duration_days"],
             plan["payout_mode"],
             now.isoformat(timespec="seconds"),
             matures.isoformat(timespec="seconds"))
        )
        _audit(db, g.user["id"], f"invest:{plan['name']}:{amount}", inv_id)
        db.commit()
    except Exception as e:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({"error": f"Investment failed: {e}"}), 500

    db.close()
    return jsonify({
        "ok": True, "investment_id": inv_id,
        "amount": f"{amount:.2f}",
        "matures_at": matures.isoformat(timespec="seconds"),
    }), 201


# ============================================================
# ADMIN — plans CRUD
# ============================================================

@admin_bp.get("/plans")
@roles_required("admin", "support")
def admin_list_plans():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM investment_plans ORDER BY sort_order, created_at"
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@admin_bp.post("/plans")
@roles_required("admin")
def admin_create_plan():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    try:
        roi = float(body.get("roi_pct") or 0)
        dur = int(body.get("duration_days") or 0)
        min_amt = float(body.get("min_amount") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid numeric fields"}), 400

    if roi <= 0 or dur <= 0 or min_amt <= 0:
        return jsonify({"error": "roi, duration, and min must be > 0"}), 400

    plan_id = str(uuid.uuid4())
    db = get_db()
    db.execute(
        """INSERT INTO investment_plans
           (id, name, slug, description, roi_pct, duration_days, min_amount,
            max_amount, compounding, payout_mode, active, sort_order)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (plan_id, name, _slugify(name), body.get("description"),
         f"{roi:.2f}", dur, f"{min_amt:.2f}",
         f"{float(body['max_amount']):.2f}" if body.get("max_amount") else None,
         body.get("compounding") or "none",
         body.get("payout_mode") or "at_maturity",
         1 if body.get("active", True) else 0,
         int(body.get("sort_order") or 100))
    )
    _audit(db, g.user["id"], "plan_create", plan_id)
    db.commit()
    db.close()
    return jsonify({"id": plan_id}), 201


@admin_bp.patch("/plans/<plan_id>")
@roles_required("admin")
def admin_update_plan(plan_id):
    body = request.get_json(silent=True) or {}
    allowed = ["name", "slug", "description", "roi_pct", "duration_days",
               "min_amount", "max_amount", "compounding", "payout_mode",
               "active", "sort_order"]
    updates = {k: body[k] for k in allowed if k in body}
    if not updates:
        return jsonify({"error": "no fields to update"}), 400

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [plan_id]

    db = get_db()
    db.execute(
        f"UPDATE investment_plans SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
        values
    )
    _audit(db, g.user["id"], "plan_update", plan_id)
    db.commit()
    db.close()
    return jsonify({"ok": True})


@admin_bp.delete("/plans/<plan_id>")
@roles_required("admin")
def admin_delete_plan(plan_id):
    db = get_db()
    db.execute("DELETE FROM investment_plans WHERE id = ?", (plan_id,))
    _audit(db, g.user["id"], "plan_delete", plan_id)
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ============================================================
# ADMIN — investments
# ============================================================

@admin_bp.get("/investments")
@roles_required("admin", "support")
def admin_list_investments():
    db = get_db()
    rows = db.execute(
        """SELECT i.*, u.email AS user_email, u.full_name AS user_name
           FROM user_investments i
           JOIN users u ON u.id = i.user_id
           ORDER BY i.started_at DESC"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@admin_bp.post("/investments/<inv_id>/mature")
@roles_required("admin")
def admin_mature_investment(inv_id):
    """Force-mature an investment and credit principal + ROI to the user."""
    db = get_db()
    row = db.execute(
        """SELECT id, user_id, amount_usd, roi_pct, status
           FROM user_investments WHERE id = ?""",
        (inv_id,)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Investment not found"}), 404
    if row["status"] != "active":
        db.close()
        return jsonify({"error": "Already matured or cancelled"}), 409

    principal = Decimal(str(row["amount_usd"] or "0"))
    roi_pct   = Decimal(str(row["roi_pct"] or "0"))
    payout    = principal + principal * roi_pct / Decimal("100")

    try:
        db.execute("BEGIN IMMEDIATE")
        u = db.execute("SELECT cash_balance FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        current = Decimal(str((u and u["cash_balance"]) or "0"))
        new_bal = current + payout
        db.execute("UPDATE users SET cash_balance = ? WHERE id = ?",
                   (f"{new_bal:.2f}", row["user_id"]))
        db.execute(
            """UPDATE user_investments
               SET status = 'matured', accrued_usd = ?, paid_out_at = datetime('now')
               WHERE id = ?""",
            (f"{payout - principal:.2f}", inv_id)
        )
        _audit(db, g.user["id"], "investment_mature", inv_id)
        db.commit()
    except Exception as e:
        try: db.execute("ROLLBACK")
        except Exception: pass
        db.close()
        return jsonify({"error": f"Maturity failed: {e}"}), 500

    db.close()
    return jsonify({"ok": True, "payout": f"{payout:.2f}"})