"""
Google + Apple sign-in.

Flow:
  Browser obtains an ID token from the provider SDK.
  POSTs it to /api/auth/oauth/google or /api/auth/oauth/apple.
  Server verifies the token, finds or creates a local user, returns a WSC JWT.
"""
import os
import uuid
import requests as http
from flask import Blueprint, request, jsonify
from ..db import get_db
from ..auth import issue_token, hash_password

bp = Blueprint("oauth", __name__, url_prefix="/api/auth/oauth")


def _find_or_create_user(db, provider, provider_uid, email, full_name):
    """
    Return a user row for this OAuth identity, creating one if needed.
    If a local user already exists with the same email, link the identity
    to that user instead of creating a duplicate.
    """
    # 1. Already-linked identity?
    row = db.execute(
        """SELECT u.* FROM oauth_identities oi
           JOIN users u ON u.id = oi.user_id
           WHERE oi.provider = ? AND oi.provider_uid = ?""",
        (provider, provider_uid)
    ).fetchone()
    if row:
        return row, False

    # 2. Existing user by email?
    existing = db.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()

    if existing:
        user_id = existing["id"]
        created = False
    else:
        # Create a new user — random unusable password (OAuth-only)
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
            (user_id, email, username,
             hash_password(uuid.uuid4().hex + uuid.uuid4().hex),  # unusable pw
             full_name or email.split("@")[0],
             None, None)
        )
        db.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body)
               VALUES (?, ?, 'welcome', 'Welcome to Wall Street Capital!',
                       'Your account is ready. Complete identity verification to unlock trading.')""",
            (str(uuid.uuid4()), user_id)
        )
        created = True

    # 3. Record the identity link
    db.execute(
        """INSERT INTO oauth_identities (id, user_id, provider, provider_uid, email)
           VALUES (?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), user_id, provider, provider_uid, email)
    )

    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return row, created


# ------------------------------------------------------------
# GOOGLE
# ------------------------------------------------------------

@bp.post("/google")
def google_signin():
    """
    Body: { "id_token": "..." }

    The browser uses Google Identity Services (GSI) to obtain the ID token.
    We verify it against Google's tokeninfo endpoint. For production
    you may want google-auth's verify_oauth2_token instead — it validates
    the signature offline.
    """
    body = request.get_json(silent=True) or {}
    id_token = (body.get("id_token") or "").strip()
    if not id_token:
        return jsonify({"error": "id_token is required"}), 400

    try:
        resp = http.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": id_token},
            timeout=10,
        )
        resp.raise_for_status()
        info = resp.json()
    except http.RequestException as err:
        return jsonify({"error": f"Google verification failed: {err}"}), 401

    expected_client = os.environ.get("GOOGLE_CLIENT_ID")
    if expected_client and info.get("aud") != expected_client:
        return jsonify({"error": "Token audience mismatch"}), 401

    if info.get("email_verified") not in (True, "true"):
        return jsonify({"error": "Google email is not verified"}), 401

    email = (info.get("email") or "").lower()
    uid = info.get("sub")
    full_name = info.get("name") or email.split("@")[0]

    if not email or not uid:
        return jsonify({"error": "Google response missing email or sub"}), 401

    db = get_db()
    user, created = _find_or_create_user(db, "google", uid, email, full_name)
    db.commit()
    db.close()

    return jsonify({
        "token": issue_token(user),
        "user": {
            "id": user["id"],
            "email": user["email"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
        },
        "created": created,
    })


# ------------------------------------------------------------
# APPLE
# ------------------------------------------------------------

def _apple_public_keys():
    resp = http.get("https://appleid.apple.com/auth/keys", timeout=10)
    resp.raise_for_status()
    return resp.json().get("keys", [])


@bp.post("/apple")
def apple_signin():
    """
    Body: { "id_token": "...", "full_name": "Optional Name" }

    Apple returns the user's name only on the FIRST sign-in, so the
    browser must forward it. Subsequent sign-ins carry no name.
    """
    import jwt
    from jwt import PyJWKClient

    body = request.get_json(silent=True) or {}
    id_token = (body.get("id_token") or "").strip()
    full_name_override = (body.get("full_name") or "").strip() or None

    if not id_token:
        return jsonify({"error": "id_token is required"}), 400

    try:
        jwks_client = PyJWKClient("https://appleid.apple.com/auth/keys")
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=os.environ.get("APPLE_CLIENT_ID"),
            issuer="https://appleid.apple.com",
        )
    except Exception as err:
        return jsonify({"error": f"Apple verification failed: {err}"}), 401

    email = (claims.get("email") or "").lower()
    uid = claims.get("sub")

    if not email or not uid:
        return jsonify({"error": "Apple response missing email or sub"}), 401

    full_name = full_name_override or email.split("@")[0]

    db = get_db()
    user, created = _find_or_create_user(db, "apple", uid, email, full_name)
    db.commit()
    db.close()

    return jsonify({
        "token": issue_token(user),
        "user": {
            "id": user["id"],
            "email": user["email"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
        },
        "created": created,
    })