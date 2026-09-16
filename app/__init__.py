import os
from pathlib import Path
from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO
from dotenv import load_dotenv

from .db import init_db
from .routes import auth_routes, kyc_routes, banking_routes, portfolio_routes, admin_routes, support_routes

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

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    init_db()

    # Start the pooled Alpaca market data stream.
    # If ALPACA_DATA_API_KEY/SECRET are missing, this logs a warning and returns.
    from .services import market_stream
    market_stream.init_market_stream(socketio)

    return app