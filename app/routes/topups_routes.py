import uuid
import os
from werkzeug.utils import secure_filename
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import login_required

bp = Blueprint("topups", __name__, url_prefix="/api/topups")
UPLOAD_DIR = os.path.join("data", "uploads", "proofs")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_PROOF_EXT = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_PROOF_BYTES = 5 * 1024 * 1024   # 5 MB


def _save_proof(file_storage):
    """
    Save an uploaded image and return its relative path.
    Returns None if the file is missing or invalid.
    """
    if not file_storage or not file_storage.filename:
        return None
    name = secure_filename(file_storage.filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_PROOF_EXT:
        return None

    # Read into memory to enforce a size limit before writing
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_PROOF_BYTES:
        return None

    new_name = f"{uuid.uuid4().hex}.{ext}"
    full_path = os.path.join(UPLOAD_DIR, new_name)
    file_storage.save(full_path)
    return new_name

@bp.get("")
@login_required
def my_topups():
    """User's own top-up history."""
    db = get_db()
    rows = db.execute(
        """SELECT id, amount_usd, method, method_ref, reference,
                  status, rejection_reason, created_at, credited_at
           FROM wallet_topups
           WHERE user_id = ?
           ORDER BY created_at DESC""",
        (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.post("")
@login_required
def submit_topup():
    """
    User claims they sent money using an enabled payment method.
    Now multipart/form-data so the proof can be an image.
    """
    # Accept both form fields and JSON, in case any old client still posts JSON.
    if request.content_type and request.content_type.startswith("multipart/"):
        data = request.form
    else:
        data = request.get_json(silent=True) or {}

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than zero"}), 400

    method = (data.get("method") or "").strip()
    if method not in ("bank", "crypto"):
        return jsonify({"error": "method must be 'bank' or 'crypto'"}), 400

    method_ref = (data.get("method_ref") or "").strip() or None
    reference  = (data.get("reference") or "").strip() or None

    if method == "crypto" and not method_ref:
        return jsonify({"error": "method_ref (crypto id) is required for crypto"}), 400

    # Proof of payment — file upload (preferred) or text (legacy)
    proof_path = None
    if request.files:
        proof_path = _save_proof(request.files.get("proof"))
        if proof_path is None and request.files.get("proof"):
            return jsonify({"error": "Proof image is invalid or too large (max 5 MB, PNG/JPG/WEBP/GIF)."}), 400

    if method == "crypto" and not proof_path and not reference:
        return jsonify({"error": "Proof of payment (image or transaction hash) is required."}), 400

    db = get_db()

    pending = db.execute(
        "SELECT COUNT(*) AS n FROM wallet_topups WHERE user_id = ? AND status = 'pending_review'",
        (g.user["id"],)
    ).fetchone()
    if pending and pending["n"] >= 5:
        db.close()
        return jsonify({
            "error": "You already have 5 top-ups pending review. Wait for those to be processed before submitting more."
        }), 429

    topup_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO wallet_topups
           (id, user_id, amount_usd, method, method_ref, reference, proof_path, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_review')""",
        (topup_id, g.user["id"], f"{amount:.2f}", method, method_ref, reference, proof_path)
    )

    try:
        db.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body)
               VALUES (?, ?, 'transfer', 'Top-up request received', ?)""",
            (str(uuid.uuid4()), g.user["id"],
             f"Your top-up request for ${amount:.2f} is awaiting confirmation.")
        )
    except Exception:
        pass

    db.commit()
    db.close()
    return jsonify({
        "id": topup_id,
        "status": "pending_review",
        "message": "Top-up request received. An administrator will confirm it shortly.",
    }), 202