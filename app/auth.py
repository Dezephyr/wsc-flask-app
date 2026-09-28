import os
import functools
import jwt
from flask import request, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash

# werkzeug's hasher (pbkdf2/scrypt) needs no native compilation, unlike
# bcrypt or better-sqlite3 — deliberately chosen to avoid the build-tools
# headaches that come up with native Node/Python addons on Windows.


# ============================================================
# Password hashing
# ============================================================

def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    return check_password_hash(password_hash, password)


# ============================================================
# JWT
# ============================================================

def issue_token(user_row) -> str:
    payload = {
        "id":    user_row["id"],
        "email": user_row["email"],
        "role":  user_row["role"],
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")


def _decode(token: str):
    return jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])


# ============================================================
# Login helpers — email OR username
# ============================================================

def _normalise_identifier(raw) -> str:
    """Trim and lowercase an identifier, returning '' if not a string."""
    if not isinstance(raw, str):
        return ""
    return raw.strip().lower()


def find_user_by_identifier(db, raw_identifier):
    """
    Look up a user by email OR username, case-insensitively.

    `db` is your database handle — adapt the query to match whichever
    library you use (sqlite3, SQLAlchemy, peewee, etc.). Two example
    implementations are given below; keep the one that fits your stack
    and delete the other.
    """
    ident = _normalise_identifier(raw_identifier)
    if not ident:
        return None

    # ------------------------------------------------------------
    # Example A — raw sqlite3 (matches the scaffold style)
    # ------------------------------------------------------------
    cur = db.execute(
        """
        SELECT *
          FROM users
         WHERE LOWER(email) = ?
            OR LOWER(username) = ?
         LIMIT 1
        """,
        (ident, ident),
    )
    row = cur.fetchone()
    return row

    # ------------------------------------------------------------
    # Example B — SQLAlchemy
    # ------------------------------------------------------------
    # from sqlalchemy import or_, func
    # return (
    #     db.session.query(User)
    #     .filter(or_(
    #         func.lower(User.email)    == ident,
    #         func.lower(User.username) == ident,
    #     ))
    #     .first()
    # )


def login(db, payload: dict):
    """
    Core login routine, called from your /api/auth/login route.

    Returns (response_dict, status_code). The route just forwards the
    result — no business logic lives in the view.

    `payload` is the parsed JSON body from the client. It may contain
    any of: identifier / email / username, plus password.
    """
    # Accept whichever key the client sent. `identifier` is preferred,
    # `email` / `username` are kept for backwards compatibility with
    # older clients (mobile app, admin panel, etc.).
    raw = (
        payload.get("identifier")
        or payload.get("email")
        or payload.get("username")
        or ""
    )
    password = payload.get("password") or ""

    if not _normalise_identifier(raw):
        return {"error": "Email or username is required"}, 400
    if not isinstance(password, str) or not password:
        return {"error": "Password is required"}, 400

    user = find_user_by_identifier(db, raw)

    # Always run the password check, even when no user matched, so the
    # response time for "unknown user" and "wrong password" is roughly
    # the same. This closes the timing side-channel that would otherwise
    # let an attacker enumerate valid accounts.
    password_ok = verify_password(
        password,
        user["password_hash"] if user else DUMMY_HASH,
    )

    if not user or not password_ok:
        # Single error for both cases — prevents user enumeration.
        return {"error": "Invalid credentials"}, 401

    token = issue_token(user)
    return {
        "token": token,
        "user":  _public_user(user),
    }, 200


# A pre-computed hash of a random string, used as a decoy when the
# user lookup fails. Its only purpose is to make the "no such user"
# branch take the same time as the "wrong password" branch.
DUMMY_HASH = generate_password_hash("this-password-is-never-used-1234567890")


def _public_user(row) -> dict:
    """Strip secrets from a user row before sending it to the client."""
    return {
        "id":        row["id"],
        "email":     row["email"],
        "username":  row["username"],
        "full_name": row["full_name"],
        "role":      row["role"],
        # add any other non-sensitive fields the dashboard expects
    }


# ============================================================
# Decorators
# ============================================================

def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else None
        if not token:
            return jsonify({"error": "Missing token"}), 401
        try:
            g.user = _decode(token)
        except jwt.PyJWTError:
            return jsonify({"error": "Invalid or expired token"}), 401
        return fn(*args, **kwargs)
    return wrapper


def roles_required(*roles):
    def decorator(fn):
        @functools.wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            if g.user.get("role") not in roles:
                return jsonify({"error": "Forbidden"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator