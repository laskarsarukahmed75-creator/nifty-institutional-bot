# keepalive.py
import os
import sys
import threading
import time
import logging
import requests
from flask import Flask, jsonify

# ---------- Validate required environment variables ----------
REQUIRED_ENV_VARS = [
    "ANGEL_API_KEY",
    "ANGEL_CLIENT_ID",
    "ANGEL_PASSWORD",
    "ANGEL_TOTP_SECRET"
]
missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
if missing:
    raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

# ---------- Import engine ----------
try:
    from app import NiftyInstitutionalEngine
except ImportError as e:
    logging.error(f"Failed to import engine: {e}")
    raise

# ---------- Flask app and engine thread ----------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("KeepAlive")

engine = None

@app.route("/")
def health_check():
    status = "running" if engine and engine.running else "stopped"
    return jsonify({
        "status": "active" if status == "running" else "inactive",
        "message": "niftyinstitutionalbot is operational",
        "engine_status": status
    })

@app.route("/stop")
def stop_engine():
    global engine
    if engine:
        engine.stop()
        return jsonify({"status": "stopped"})
    return jsonify({"status": "engine not running"})

def start_engine():
    global engine
    time.sleep(5)  # give Flask a moment to start
    try:
        engine = NiftyInstitutionalEngine()
        engine.run()
    except Exception as e:
        logger.error(f"Engine crashed: {e}", exc_info=True)

def self_ping():
    """Keep Render's health check happy (optional)."""
    base_url = f"http://0.0.0.0:{os.environ.get('PORT', 8080)}"
    while True:
        time.sleep(600)
        try:
            requests.get(base_url, timeout=10)
            logger.info("Self-ping successful")
        except Exception as e:
            logger.error(f"Self-ping failed: {e}")

if __name__ == "__main__":
    engine_thread = threading.Thread(target=start_engine, daemon=True)
    engine_thread.start()
    ping_thread = threading.Thread(target=self_ping, daemon=True)
    ping_thread.start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
