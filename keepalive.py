# keepalive.py
import os
import threading
import time
import logging
from flask import Flask, jsonify
import requests
from app import NiftyInstitutionalEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("KeepAlive")

app = Flask(__name__)
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
    time.sleep(5)   # give Flask time to bind port
    try:
        engine = NiftyInstitutionalEngine()
        engine.run()
    except Exception as e:
        logger.error(f"Engine crashed: {e}", exc_info=True)

def self_ping():
    base_url = f"http://0.0.0.0:{os.environ.get('PORT', 8080)}"
    while True:
        time.sleep(600)
        try:
            requests.get(base_url, timeout=10)
            logger.info("Self-ping successful")
        except Exception as e:
            logger.error(f"Self-ping failed: {e}")

if __name__ == "__main__":
    threading.Thread(target=start_engine, daemon=True).start()
    threading.Thread(target=self_ping, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
