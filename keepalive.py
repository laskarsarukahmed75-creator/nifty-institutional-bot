# keepalive.py
import os
import sys
import threading
import time
import logging
import requests
from flask import Flask, jsonify

# डेटा मैनेजर, टेलीग्राम कंट्रोल और मुख्य इंजन इम्पोर्ट
from data_manager import DataManager
from telegram_control import TelegramControl

try:
    from app import NiftyInstitutionalEngine
except ImportError as e:
    logging.critical(f"Engine import failed: {e}")
    sys.exit(1)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("KeepAlive")

# इंजन को बूट होते ही सबसे पहले मेन रैम में ऑन कर देते हैं ताकि कोई साइलेंट फ्रीज न हो!
logger.info("🔥 Main Execution: Initializing NiftyInstitutionalEngine...")
try:
    engine = NiftyInstitutionalEngine()
    data_mgr = DataManager()
    telegram_ctrl = TelegramControl(engine)
    
    # 4 महीने का डेटा फेच बैकग्राउंड में फेंकेंगे ताकि रेंडर का पोर्ट जाम न हो
    threading.Thread(target=lambda: data_mgr.fetch_and_store(engine.obj), daemon=True).start()
    
    # मुख्य इंजन का लूप बैकग्राउंड थ्रेड में सुरक्षित ऑन करें
    threading.Thread(target=engine.run, daemon=True).start()
    logger.info("🚀 System Active: Core Engine Loop triggered.")
except Exception as startup_err:
    logger.error(f"❌ DIRECT ENGINE INIT FAILED: {startup_err}")

@app.route("/")
def health_check():
    # अब यह सीधे चेक करेगा, कोई धोखा नहीं
    status = "running" if engine and getattr(engine, "running", False) else "stopped"
    return jsonify({
        "status": "active" if status == "running" else "inactive",
        "engine_status": status,
        "position_open": engine.position_open if engine else False,
        "pivot": engine.pivot_0_5 if engine else None,
        "data_manager": "active" if data_mgr else "inactive",
        "telegram_control": "active" if telegram_ctrl else "inactive"
    })

def self_ping():
    """रेंडर को एक्टिव रखने के लिए हर 60 सेकंड का पिंग लूप"""
    port = os.environ.get("PORT", 8080)
    base_url = f"http://0.0.0.0:{port}"
    while True:
        time.sleep(60)
        try:
            requests.get(base_url, timeout=10)
        except Exception:
            pass

if __name__ == "__main__":
    # पिंगर को एक्टिव करें
    threading.Thread(target=self_ping, daemon=True).start()

    # फ्लास्क सर्वर तुरंत रेंडर के पोर्ट को थाम लेगा
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
