"""
Server-generated captcha for the signup form.
Generates a random 5-character code, draws it to an image, returns a token + image.
The expected answer is stored in-memory, keyed by token, expiring after 5 minutes.
"""
import os
import io
import time
import uuid
import base64
import random
import threading
from flask import Blueprint, jsonify, request

from PIL import Image, ImageDraw, ImageFont, ImageFilter

bp = Blueprint("captcha", __name__, url_prefix="/api/captcha")

# In-memory store: token -> { answer, expires_at }
_store = {}
_lock = threading.Lock()
TTL_SECONDS = 300   # 5 minutes


def _cleanup_expired():
    now = time.time()
    with _lock:
        expired = [k for k, v in _store.items() if v["expires_at"] < now]
        for k in expired:
            _store.pop(k, None)


def _random_code(length=5):
    # Exclude ambiguous characters (0/O, 1/I/l) for readability
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(alphabet) for _ in range(length))


def _render_image(code: str) -> bytes:
    width, height = 180, 60
    img = Image.new("RGB", (width, height), (10, 20, 40))
    draw = ImageDraw.Draw(img)

    # Try several fonts; fall back to PIL's built-in if none are available
    font = None
    for name in ("arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(name, 36)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    # Draw each character with slight random offset and rotation
    x = 20
    for ch in code:
        ch_img = Image.new("RGBA", (40, 50), (0, 0, 0, 0))
        ch_draw = ImageDraw.Draw(ch_img)
        ch_draw.text((0, 0), ch, font=font, fill=(96, 165, 250))
        ch_img = ch_img.rotate(random.randint(-18, 18), expand=1, resample=Image.BICUBIC)
        y_offset = random.randint(-4, 4)
        img.paste(ch_img, (x, 8 + y_offset), ch_img)
        x += 30 + random.randint(0, 4)

    # Noise: random dots
    for _ in range(220):
        draw.point(
            (random.randint(0, width), random.randint(0, height)),
            fill=(random.randint(40, 120), random.randint(60, 140), random.randint(140, 220)),
        )

    # Noise: a few lines
    for _ in range(3):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        draw.line((x1, y1, x2, y2), fill=(59, 130, 246), width=1)

    img = img.filter(ImageFilter.SMOOTH)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@bp.get("/new")
def new_captcha():
    _cleanup_expired()
    code = _random_code()
    token = str(uuid.uuid4())
    with _lock:
        _store[token] = {"answer": code, "expires_at": time.time() + TTL_SECONDS}

    img_bytes = _render_image(code)
    b64 = base64.b64encode(img_bytes).decode("ascii")

    return jsonify({
        "token": token,
        "image": f"data:image/png;base64,{b64}",
        "expires_in": TTL_SECONDS,
    })


def verify_captcha(token: str, user_answer: str) -> bool:
    """Used by auth_routes.signup(). Returns True if the answer is correct."""
    if not token or not user_answer:
        return False

    with _lock:
        entry = _store.pop(token, None)   # one-shot: consume on verify

    if not entry:
        return False
    if entry["expires_at"] < time.time():
        return False
    return entry["answer"].upper() == user_answer.strip().upper()


@bp.post("/verify")
def verify_captcha_endpoint():
    body = request.get_json(silent=True) or {}
    ok = verify_captcha(body.get("token"), body.get("answer"))
    return jsonify({"ok": ok})