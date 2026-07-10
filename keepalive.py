# keepalive.py
import os
import threading
import time
import logging
import datetime
from flask import Flask, jsonify
import requests
from app import NiftyInstitutionalEngine

# ---------- Logging Setup ----------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("KeepAliveServer")

app = Flask(__name__)
engine = None

@app.route("/")
def health_check():
    """Render Web Service handles health check and returns engine status."""
    status = "running" if engine and engine.running else "stopped"
    is_paused = "paused" if engine and engine.paused else "active"
    
    return jsonify({
        "status": "operational" if status == "running" else "inactive",
        "message": "niftyinstitutionalbot Institutional Engine (15m Structure) is live",
        "engine_status": status,
        "operation_mode": is_paused,
        "current_time_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()
    })

@app.route("/stop")
def stop_engine():
    """Emergency route to manually stop the bot via browser/HTTP request."""
    global engine
    if engine:
        engine.stop()
        return jsonify({"status": "stopped", "message": "Engine shut down successfully."})
    return jsonify({"status": "error", "message": "Engine was not running."})

def start_engine_thread():
    """Target function to boot the algorithmic engine in a separate daemon thread."""
    global engine
    logger.info("Waiting 5 seconds for system warm-up before initializing engine...")
    time.sleep(5)
    try:
        engine = NiftyInstitutionalEngine()
        engine.run()
    except Exception as e:
        logger.error(f"Algorithmic Core crashed unexpectedly: {e}", exc_info=True)

def self_ping_loop():
    """Anti-Sleep Loop: Keeps Render's free/hobby tier instances from sleeping."""
    port = os.environ.get('PORT', '8080')
    base_url = f"http://127.0.0.1:{port}"
    
    # Wait for Flask to boot completely
    time.sleep(15)
    logger.info(f"Self-ping cycle initiated against local fallback target: {base_url}")
    
    while True:
        try:
            # Pings every 10 minutes (600 seconds)
            response = requests.get(base_url, timeout=10)
            if response.status_code == 200:
                logger.info("Anti-sleep self-ping: SUCCESS (Instance is awake)")
            else:
                logger.warning(f"Anti-sleep self-ping returned unexpected status: {response.status_code}")
        except Exception as e:
            logger.error(f"Self-ping execution bottleneck encountered: {e}")
        
        time.sleep(600)

if __name__ == "__main__":
    # 1. Start the main algorithmic trading engine in background
    trading_thread = threading.Thread(target=start_engine_thread, daemon=True)
    trading_thread.start()
    
    # 2. Start the anti-sleep manager to monitor local loopback
    ping_thread = threading.Thread(target=self_ping_loop, daemon=True)
    ping_thread.start()
    
    # 3. Initialize Gunicorn-compatible Flask web portal
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Launching production Flask listener on port {port}...")
    
    # Running inside production container context
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
