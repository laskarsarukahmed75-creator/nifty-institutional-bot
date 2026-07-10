#!/usr/bin/env python3
"""
keepalive.py – Production KeepAlive Server with Diagnostics, Data Manager, and Telegram Control
"""

import os
import sys
import threading
import time
import logging
import requests
from flask import Flask, jsonify

# Import diagnostic engine (if exists)
try:
    from error_filter import run_diagnostics
except ImportError:
    def run_diagnostics():
        print("⚠️ error_filter.py not found; skipping diagnostics.")
        return None

# Import data manager and telegram control
from data_manager import DataManager
from telegram_control import TelegramControl

# Validate environment
REQUIRED_ENV_VARS = [
    "ANGEL_API_KEY",
    "ANGEL_CLIENT_ID",
    "ANGEL_PASSWORD",
    "ANGEL_TOTP_SECRET"
]
missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
if missing:
    raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

# Run diagnostics (if available)
diag_report = run_diagnostics()
if diag_report is not None and not diag_report:
    sys.exit(1)

# Import engine
try:
    from app import NiftyInstitutionalEngine
except ImportError as e:
    logging.critical(f"Engine import failed: {e}")
    sys.exit(1)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("KeepAlive")

engine = None
data_mgr = None
telegram_ctrl = None

@app.route("/")
def health_check():
    status = "running" if engine and getattr(engine, "running", False) else "stopped"
    return jsonify({
        "status": "active" if status == "running" else "inactive",
        "engine_status": status,
        "position_open": engine.position_open if engine else False,
        "pivot": engine.pivot_0_5 if engine else None,
        "data_manager": "active" if data_mgr else "inactive",
        "telegram_control": "active" if telegram_ctrl else "inactive"
    })

@app.route("/stop")
def stop_engine():
    global engine
    if engine:
        engine.stop()
        return jsonify({"status": "stopped"})
    return jsonify({"status": "engine not running"})

def start_engine():
    global engine, data_mgr, telegram_ctrl
    time.sleep(5)  # give Flask a moment
    try:
        engine = NiftyInstitutionalEngine()
        # Initialize data manager and fetch historical data
        data_mgr = DataManager()
        # Fetch data in background thread to avoid blocking startup
        threading.Thread(target=lambda: data_mgr.fetch_and_store(engine.obj), daemon=True).start()
        # Start Telegram control with engine reference
        telegram_ctrl = TelegramControl(engine)
        # Run engine
        engine.run()
    except Exception as e:
        logger.error(f"Engine crashed: {e}", exc_info=True)

def self_ping():
    """Keep Render's health check happy and prevent spin-down."""
    port = os.environ.get("PORT", 8080)
    base_url = f"http://0.0.0.0:{port}"
    while True:
        time.sleep(60)  # ping every minute
        try:
            resp = requests.get(base_url, timeout=10)
            if resp.status_code == 200:
                logger.info("Self-ping successful")
            else:
                logger.warning(f"Self-ping status: {resp.status_code}")
        except Exception as e:
            logger.error(f"Self-ping failed: {e}")

if __name__ == "__main__":
    engine_thread = threading.Thread(target=start_engine, daemon=True)
    engine_thread.start()
    ping_thread = threading.Thread(target=self_ping, daemon=True)
    ping_thread.start()

    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
