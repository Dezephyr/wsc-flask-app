import uuid
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import hash_password, verify_password, issue_token, login_required

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/signup")
def signup():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    full_name = (body.get("full_name") or "").strip()
    country = (body.get("country") or "").strip() or None
    phone = (body.get("phone") or "").strip() or None
    city = (body.get("city") or "").strip() or None
    postal_code = (body.get("postal_code") or "").strip() or None

    if not email or not password or not full_name:
        return jsonify({"error": "email, password, and full_name are required"}), 400
    if len(password) < 10:
        return jsonify({"error": "Password must be at least 10 characters"}), 400

    db = get_db()
    if db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
        db.close()
        return jsonify({"error": "An account with that email already exists"}), 409

    user_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO users
           (id, email, password_hash, full_name, country, phone, city, postal_code, role)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'user')""",
        (user_id, email, hash_password(password), full_name, country, phone, city, postal_code),
    )
    db.commit()
    db.close()

    user_row = {"id": user_id, "email": email, "role": "user"}
    return jsonify({
        "token": issue_token(user_row),
        "user": {
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "country": country,
            "phone": phone,
            "city": city,
            "postal_code": postal_code,
            "role": "user",
        },
    }), 201


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    db = get_db()
    row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    db.close()
    if not row or not verify_password(password, row["password_hash"]):
        return jsonify({"error": "Invalid email or password"}), 401

    return jsonify({
        "token": issue_token(row),
        "user": {"id": row["id"], "email": row["email"], "full_name": row["full_name"], "role": row["role"]},
    })


@bp.get("/me")
@login_required
def me():
    db = get_db()
    row = db.execute(
        "SELECT id, email, full_name, role, created_at FROM users WHERE id = ?", (g.user["id"],)
    ).fetchone()
    db.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dict(row))