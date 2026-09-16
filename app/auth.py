import os
import functools
import jwt
from flask import request, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash

# werkzeug's hasher (pbkdf2/scrypt) needs no native compilation, unlike
# bcrypt or better-sqlite3 — deliberately chosen to avoid the build-tools
# headaches that come up with native Node/Python addons on Windows.


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def issue_token(user_row) -> str:
    payload = {"id": user_row["id"], "email": user_row["email"], "role": user_row["role"]}
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")


def _decode(token: str):
    return jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])


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
