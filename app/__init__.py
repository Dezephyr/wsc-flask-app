import os
from pathlib import Path
from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO
from dotenv import load_dotenv

from .db import init_db, seed_default_admin
from .routes import (
    auth_routes, kyc_routes, banking_routes, portfolio_routes,
    admin_routes, support_routes, captcha_routes,
    notifications_routes, wallets_routes, loans_routes,
    settings_routes, topups_routes, crypto_trade_routes,
    stock_routes, crypto_stake_routes,
    signals_routes, plans_routes, withdrawals_routes, bot_routes,
    password_routes, oauth_routes,
    apple_credentials_routes,
)

# Module-level SocketIO instance, imported by run.py
socketio = SocketIO()


def create_app():
    load_dotenv()

    if not os.environ.get("JWT_SECRET"):
        raise RuntimeError(
            "Refusing to start: JWT_SECRET is not set. Copy .env.example to .env and fill it in."
        )

    public_dir = Path(__file__).resolve().parent.parent / "public"
    app = Flask(__name__, static_folder=str(public_dir), static_url_path="")

    # Disable static-file caching during development so the browser always
    # re-fetches HTML/CSS/JS after edits. Remove this line for production.
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    CORS(app)

    # Attach SocketIO with threading async mode (works with the werkzeug dev server)
    socketio.init_app(app, cors_allowed_origins="*", async_mode="threading")

    limiter = Limiter(get_remote_address, app=app, default_limits=[])
    # Keep auth endpoints from being brute-forced.
    limiter.limit("20 per 15 minutes")(auth_routes.bp)

    app.register_blueprint(auth_routes.bp)
    app.register_blueprint(kyc_routes.bp)
    app.register_blueprint(banking_routes.bp)
    app.register_blueprint(portfolio_routes.bp)
    app.register_blueprint(admin_routes.bp)
    app.register_blueprint(support_routes.bp)
    app.register_blueprint(captcha_routes.bp)
    app.register_blueprint(notifications_routes.bp)
    app.register_blueprint(wallets_routes.bp)
    app.register_blueprint(loans_routes.bp)
    app.register_blueprint(settings_routes.bp)
    app.register_blueprint(topups_routes.bp)
    app.register_blueprint(crypto_trade_routes.bp)
    app.register_blueprint(stock_routes.bp)
    app.register_blueprint(crypto_stake_routes.bp)
    app.register_blueprint(signals_routes.bp)
    app.register_blueprint(signals_routes.admin_bp)
    app.register_blueprint(plans_routes.bp)
    app.register_blueprint(plans_routes.admin_bp)
    app.register_blueprint(loans_routes.admin_bp)
    app.register_blueprint(withdrawals_routes.bp)
    app.register_blueprint(bot_routes.bp)
    app.register_blueprint(password_routes.bp)
    app.register_blueprint(oauth_routes.bp)
    app.register_blueprint(apple_credentials_routes.bp)

    # --- Serve uploaded proof images ---
    uploads_root = Path(app.root_path).parent / "data" / "uploads" / "proofs"
    uploads_root.mkdir(parents=True, exist_ok=True)

    @app.get("/uploads/proofs/<filename>")
    def uploaded_proof(filename):
        return send_from_directory(str(uploads_root), filename)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    # Create tables, then seed the default admin (idempotent).
    init_db()
    seed_default_admin()

    # Start the bot-trading worker. It accrues daily profit on active
    # bot investments and pays out matured positions.
    from .services import bot_worker
    bot_worker.start()

    # Start the pooled Alpaca market data stream.
    # If ALPACA_DATA_API_KEY/SECRET are missing, this logs a warning and returns.
    # from .services import market_stream
    # market_stream.init_market_stream(socketio)

    return app