import uuid
import re
import secrets
import string
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import hash_password, verify_password, issue_token, login_required
from .captcha_routes import verify_captcha

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,24}$")


def generate_referral_code():
    """Return an 8-character code, avoiding ambiguous characters."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _record_login_event(db, user_id, email):
    """
    Insert a successful login into login_events.

    Does NOT commit — the caller is responsible for committing, so this
    write is part of the same transaction as the rest of the login flow.

    Never raises — logging must not break the login flow.
    """
    try:
        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
        ua = (request.headers.get("User-Agent") or "")[:500]
        db.execute(
            """INSERT INTO login_events (id, user_id, email, ip, user_agent)
               VALUES (?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), user_id, email, ip, ua),
        )
    except Exception:
        # Swallow — logging failures should not block a valid login.
        pass


@bp.post("/signup")
def signup():
    body = request.get_json(silent=True) or {}

    full_name = (body.get("full_name") or "").strip()
    username = (body.get("username") or "").strip().lower()
    email = (body.get("email") or "").strip().lower()
    phone = (body.get("phone") or "").strip()
    country = (body.get("country") or "").strip()
    referred_by_code = (body.get("referral_code") or "").strip() or None
    password = body.get("password") or ""
    confirm = body.get("confirm_password") or ""
    captcha_token = body.get("captcha_token") or ""
    captcha_answer = body.get("captcha_answer") or ""

    # --- validation ---
    if not full_name or not username or not email or not password:
        return jsonify({"error": "Name, username, email, and password are required"}), 400

    if not USERNAME_RE.match(username):
        return jsonify({"error": "Username must be 3-24 characters: letters, numbers, underscore"}), 400

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({"error": "Please enter a valid email address"}), 400

    if not phone:
        return jsonify({"error": "Phone number is required"}), 400

    if not country:
        return jsonify({"error": "Please select a country"}), 400

    if len(password) < 10:
        return jsonify({"error": "Password must be at least 10 characters"}), 400

    if password != confirm:
        return jsonify({"error": "Passwords do not match"}), 400

    # --- captcha ---
    if not verify_captcha(captcha_token, captcha_answer):
        return jsonify({"error": "Captcha is incorrect or has expired. Please try again."}), 400

    db = get_db()
    if db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
        db.close()
        return jsonify({"error": "An account with that email already exists"}), 409

    if db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
        db.close()
        return jsonify({"error": "That username is already taken"}), 409

    # Generate a unique referral code for this new user
    while True:
        own_referral_code = generate_referral_code()
        clash = db.execute(
            "SELECT 1 FROM users WHERE referral_code = ?", (own_referral_code,)
        ).fetchone()
        if not clash:
            break

    user_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO users
           (id, email, username, password_hash, full_name, country, phone,
            referral_code, referred_by, role)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'user')""",
        (user_id, email, username, hash_password(password), full_name,
         country, phone, own_referral_code, referred_by_code),
    )

    # If they used a referral code, record the referral + notify the referrer
    if referred_by_code:
        referrer = db.execute(
            "SELECT id FROM users WHERE referral_code = ?",
            (referred_by_code,)
        ).fetchone()
        if referrer:
            db.execute(
                """INSERT INTO referrals
                   (id, referrer_id, referred_user_id, status)
                   VALUES (?, ?, ?, 'pending')""",
                (str(uuid.uuid4()), referrer["id"], user_id)
            )
            db.execute(
                """INSERT INTO notifications
                   (id, user_id, kind, title, body)
                   VALUES (?, ?, 'referral', 'New referral',
                           'Someone signed up using your referral link.')""",
                (str(uuid.uuid4()), referrer["id"])
            )

    # Welcome notification for the new user
    db.execute(
        """INSERT INTO notifications (id, user_id, kind, title, body)
           VALUES (?, ?, 'welcome', 'Welcome to Wall Street Capital!',
                   'Your account is ready. Complete identity verification to unlock deposits, withdrawals, and trading.')""",
        (str(uuid.uuid4()), user_id)
    )
    db.commit()
    db.close()

    # ---- Welcome email (best-effort — never blocks signup) ----
    # Sent only on signup, never on login. Failures are logged but never
    # prevent the account from being created.
    try:
        from ..services import mailer
        mailer.send_welcome(email, name=full_name)
    except Exception as e:
        print(f"[signup] welcome email failed for {email}: {e}")

    user_row = {"id": user_id, "email": email, "role": "user"}
    return jsonify({
        "token": issue_token(user_row),
        "user": {
            "id": user_id,
            "email": email,
            "username": username,
            "full_name": full_name,
            "country": country,
            "phone": phone,
            "referral_code": own_referral_code,
            "referred_by_code": referred_by_code,
            "role": "user",
        },
    }), 201


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}

    # Accept either "identifier" (new) or "email" (old) from the client.
    # The value can be an email address OR a username.
    identifier = (
        body.get("identifier")
        or body.get("email")
        or ""
    ).strip()

    password = body.get("password") or ""

    if not identifier or not password:
        return jsonify({"error": "Email/username and password are required"}), 400

    identifier_lower = identifier.lower()

    db = get_db()

    # Match on email (case-insensitive) OR username (case-insensitive).
    # COALESCE guards against NULL usernames on legacy rows.
    row = db.execute(
        """SELECT * FROM users
           WHERE LOWER(email) = ?
              OR LOWER(COALESCE(username, '')) = ?
           LIMIT 1""",
        (identifier_lower, identifier_lower)
    ).fetchone()

    if not row or not verify_password(password, row["password_hash"]):
        db.close()
        return jsonify({"error": "Invalid email/username or password"}), 401

    # Successful login — record the event, then commit once.
    # No welcome email here — that only fires on signup.
    _record_login_event(db, row["id"], row["email"])
    db.commit()
    db.close()

    return jsonify({
        "token": issue_token(row),
        "user": {
            "id": row["id"],
            "email": row["email"],
            "username": row["username"] if "username" in row.keys() else None,
            "full_name": row["full_name"],
            "role": row["role"],
        },
    })


@bp.get("/me")
@login_required
def me():
    db = get_db()

    # Defensive: only include require_wallet_to_withdraw if the column
    # actually exists on this DB. That way an older database that hasn't
    # been migrated yet won't blow up the whole /me endpoint.
    existing_cols = {
        r["name"] for r in db.execute("PRAGMA table_info(users)").fetchall()
    }

    base_cols = [
        "id", "email", "username", "full_name", "role", "created_at",
        "referral_code", "phone", "country", "email_notifications",
    ]
    if "require_wallet_to_withdraw" in existing_cols:
        base_cols.append("require_wallet_to_withdraw")

    select_sql = "SELECT " + ", ".join(base_cols) + " FROM users WHERE id = ?"
    row = db.execute(select_sql, (g.user["id"],)).fetchone()
    db.close()

    if not row:
        return jsonify({"error": "Not found"}), 404

    out = dict(row)

    # Guarantee the key is always present in the JSON, even on an
    # un-migrated DB. The frontend reads it directly.
    out.setdefault("require_wallet_to_withdraw", 0)

    return jsonify(out)


@bp.post("/change-password")
@login_required
def change_password():
    body = request.get_json(silent=True) or {}
    current = body.get("current_password") or ""
    new = body.get("new_password") or ""
    confirm = body.get("confirm_password") or ""

    if not current or not new or not confirm:
        return jsonify({"error": "All fields are required"}), 400
    if new != confirm:
        return jsonify({"error": "New passwords do not match"}), 400
    if len(new) < 10:
        return jsonify({"error": "New password must be at least 10 characters"}), 400

    db = get_db()
    row = db.execute("SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)).fetchone()
    if not row or not verify_password(current, row["password_hash"]):
        db.close()
        return jsonify({"error": "Current password is incorrect"}), 401

    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(new), g.user["id"])
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@bp.patch("/preferences")
@login_required
def update_preferences():
    body = request.get_json(silent=True) or {}
    email_notifications = body.get("email_notifications")

    db = get_db()
    if email_notifications is not None:
        db.execute(
            "UPDATE users SET email_notifications = ? WHERE id = ?",
            (1 if email_notifications else 0, g.user["id"])
        )
        db.commit()
    db.close()
    return jsonify({"ok": True})


@bp.post("/bootstrap-admin")
def bootstrap_admin():
    """
    TEMPORARY: promote a user to admin.
    Only works if the bootstrap token matches. Delete this route after use.
    """
    import os
    expected = os.environ.get("BOOTSTRAP_TOKEN")
    if not expected:
        return jsonify({"error": "BOOTSTRAP_TOKEN not set"}), 403

    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()
    email = (body.get("email") or "").strip().lower()

    if token != expected:
        return jsonify({"error": "Forbidden"}), 403
    if not email:
        return jsonify({"error": "email is required"}), 400

    db = get_db()
    row = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "User not found"}), 404

    db.execute("UPDATE users SET role = 'admin' WHERE id = ?", (row["id"],))
    db.commit()
    db.close()
    return jsonify({"ok": True, "email": email, "role": "admin"})