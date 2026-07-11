# keepalive.py
import os
import subprocess
import threading
import time
import logging
import datetime
from flask import Flask, jsonify

# ---------- Logging Setup ----------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("KeepAliveServer")

app = Flask(__name__)

# 🚀 मास्टर स्ट्रोक: Gunicorn जैसे ही इस फाइल को पढ़ेगा, यह तुरंत 
# आपके मुख्य बोट (app.py) को बैकग्राउंड में लॉन्च कर देगा।
# इससे रेंडर का पोर्ट टाइमआउट एरर हमेशा के लिए खत्म हो जाएगा!
try:
    logger.info("Latching and spawning main trading engine (app.py) in isolated background process...")
    subprocess.Popen(["python", "app.py"])
except Exception as e:
    logger.error(f"Failed to auto-spawn main bot engine: {e}")

@app.route("/")
def health_check():
    """Render Web Service handles health check and returns portal status."""
    return jsonify({
        "status": "operational",
        "message": "Nifty Institutional Bot Layer is live and bridging requests.",
        "current_time_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()
    })

def self_ping_loop():
    """Anti-Sleep Loop: Keeps Render's free tier instances from sleeping."""
    import requests
    port = os.environ.get('PORT', '8080')
    base_url = f"http://127.0.0.1:{port}"
    
    # Flask को बूट होने का समय दें
    time.sleep(20)
    logger.info(f"Self-ping cycle initiated against local target: {base_url}")
    
    while True:
        try:
            response = requests.get(base_url, timeout=10)
            if response.status_code == 200:
                logger.info("Anti-sleep self-ping: SUCCESS (Instance is awake)")
            else:
                logger.warning(f"Anti-sleep self-ping returned status: {response.status_code}")
        except Exception as e:
            logger.error(f"Self-ping heartbeat check failed: {e}")
        
        # हर 10 मिनट में पिंग करेगा
        time.sleep(600)

# बैकग्राउंड पिंग थ्रेड को तुरंत चालू करें
ping_thread = threading.Thread(target=self_ping_loop, daemon=True)
ping_thread.start()

if __name__ == "__main__":
    # लोकल टेस्टिंग के लिए फॉलबैक रनर
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Launching Flask fallback listener on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
