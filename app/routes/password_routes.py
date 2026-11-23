import uuid
import secrets
from datetime import datetime
from flask import Blueprint, request, jsonify
from ..db import get_db
from ..auth import hash_password
from ..services import mailer

bp = Blueprint("password_reset", __name__, url_prefix="/api/auth")

CODE_TTL_MINUTES = 10
MAX_ATTEMPTS = 5


def _generate_code():
    """6-digit numeric code, no leading zero."""
    return str(secrets.randbelow(900000) + 100000)


def _mask_email(email: str) -> str:
    """j***@e***.com — for display on the code-entry page."""
    if not email or "@" not in email:
        return email or ""
    local, domain = email.split("@", 1)
    masked_local = (local[0] + "***") if local else "***"
    if "." in domain:
        dname, tld = domain.rsplit(".", 1)
        masked_domain = (dname[0] + "***." + tld) if dname else ("***." + tld)
    else:
        masked_domain = domain[0] + "***"
    return f"{masked_local}@{masked_domain}"


# ------------------------------------------------------------
# Step 1 — request a reset code
# ------------------------------------------------------------

@bp.post("/forgot-password")
def forgot_password():
    """
    Body: { "email": "user@example.com" }

    Always returns 200 with a generic message, whether or not the email
    exists, so attackers can't enumerate accounts.
    """
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()

    if not email:
        return jsonify({"error": "Email is required"}), 400

    db = get_db()
    user = db.execute(
        "SELECT id, email, full_name FROM users WHERE email = ?", (email,)
    ).fetchone()

    if user:
        # Invalidate any previous unused codes for this user
        db.execute(
            """UPDATE password_resets
               SET consumed_at = datetime('now')
               WHERE user_id = ? AND consumed_at IS NULL""",
            (user["id"],)
        )

        code = _generate_code()
        reset_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO password_resets
               (id, user_id, email, code_hash, expires_at)
               VALUES (?, ?, ?, ?, datetime('now', ?))""",
            (reset_id, user["id"], user["email"],
             hash_password(code), f"+{CODE_TTL_MINUTES} minutes")
        )
        db.commit()

        # Fire the email (log-only if SMTP not configured)
        try:
            mailer.send_password_reset(
                user["email"], code,
                name=(user["full_name"] or "there").split()[0]
            )
        except Exception as err:
            print(f"[password_reset] email failed: {err}")

    db.close()

    return jsonify({
        "ok": True,
        "message": "If an account exists with that email, a reset code has been sent.",
        "email_masked": _mask_email(email),
        "expires_in_minutes": CODE_TTL_MINUTES,
    })


# ------------------------------------------------------------
# Step 2 — verify the code (no password change yet)
# ------------------------------------------------------------

@bp.post("/verify-reset-code")
def verify_reset_code():
    """
    Body: { "email": "...", "code": "123456" }

    Returns { reset_token: "..." } — a short-lived JWT the client
    passes to /reset-password. This keeps the code out of the final step.
    """
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    code  = (body.get("code") or "").strip()

    if not email or not code:
        return jsonify({"error": "Email and code are required"}), 400
    if not code.isdigit() or len(code) != 6:
        return jsonify({"error": "Code must be 6 digits"}), 400

    db = get_db()
    row = db.execute(
        """SELECT id, user_id, code_hash, expires_at, attempts, consumed_at
           FROM password_resets
           WHERE email = ? AND consumed_at IS NULL
           ORDER BY created_at DESC LIMIT 1""",
        (email,)
    ).fetchone()

    if not row:
        db.close()
        return jsonify({"error": "No active reset request. Start again."}), 400

    if row["attempts"] >= MAX_ATTEMPTS:
        db.close()
        return jsonify({"error": "Too many attempts. Request a new code."}), 429

    expired = db.execute(
        "SELECT 1 FROM password_resets WHERE id = ? AND datetime(expires_at) < datetime('now')",
        (row["id"],)
    ).fetchone()
    if expired:
        db.execute(
            "UPDATE password_resets SET consumed_at = datetime('now') WHERE id = ?",
            (row["id"],)
        )
        db.commit()
        db.close()
        return jsonify({"error": "Code expired. Request a new one."}), 400

    from ..auth import verify_password  # local import avoids circular
    if not verify_password(code, row["code_hash"]):
        db.execute(
            "UPDATE password_resets SET attempts = attempts + 1 WHERE id = ?",
            (row["id"],)
        )
        db.commit()
        db.close()
        return jsonify({"error": "Incorrect code."}), 401

    # Mark this code as consumed so it can't be reused
    db.execute(
        "UPDATE password_resets SET consumed_at = datetime('now') WHERE id = ?",
        (row["id"],)
    )
    db.commit()
    db.close()

    # Issue a short-lived reset token
    import os, jwt, time
    reset_token = jwt.encode(
        {
            "sub": row["user_id"],
            "purpose": "password_reset",
            "exp": int(time.time()) + 600,   # 10 minutes
        },
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )

    return jsonify({"ok": True, "reset_token": reset_token})


# ------------------------------------------------------------
# Step 3 — set the new password
# ------------------------------------------------------------

@bp.post("/reset-password")
def reset_password():
    """
    Body: { "reset_token": "...", "password": "...", "confirm_password": "..." }
    """
    import os, jwt
    body = request.get_json(silent=True) or {}
    token    = (body.get("reset_token") or "").strip()
    password = body.get("password") or ""
    confirm  = body.get("confirm_password") or ""

    if not token or not password or not confirm:
        return jsonify({"error": "All fields are required"}), 400
    if password != confirm:
        return jsonify({"error": "Passwords do not match"}), 400
    if len(password) < 10:
        return jsonify({"error": "Password must be at least 10 characters"}), 400

    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
    except jwt.PyJWTError:
        return jsonify({"error": "Reset link expired or invalid. Start again."}), 401

    if payload.get("purpose") != "password_reset":
        return jsonify({"error": "Invalid reset token"}), 401

    user_id = payload.get("sub")
    db = get_db()
    user = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "Account not found"}), 404

    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(password), user_id)
    )

    try:
        db.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body)
               VALUES (?, ?, 'security', 'Password changed',
                       'Your password was successfully reset. If this wasn''t you, contact support immediately.')""",
            (str(uuid.uuid4()), user_id)
        )
    except Exception:
        pass

    db.commit()
    db.close()

    return jsonify({"ok": True, "message": "Password reset. You can now sign in."})