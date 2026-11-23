import os
from dotenv import load_dotenv
from flask import send_from_directory

load_dotenv()

from app import create_app, socketio

app = create_app()

# ============================================================
# SERVE UPLOADED FILES (Deposit Proofs, KYC Docs, etc.)
# ============================================================
@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    # Tells Flask to look in "data" -> "uploads" -> "proofs"
    directory = os.path.join(os.getcwd(), 'data', 'uploads', 'proofs')
    return send_from_directory(directory, filename)
if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", 4000))
    # socketio.run handles both regular requests and WebSockets
    socketio.run(app, host="0.0.0.0", port=port, debug=True, allow_unsafe_werkzeug=True)