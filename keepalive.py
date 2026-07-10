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

engine = None
data_mgr = None
telegram_ctrl = None

@app.route("/")
def health_check():
    # लाइव स्टेटस चेक करने का पक्का इंतजाम
    status = "running" if engine and getattr(engine, "running", False) else "stopped"
    return jsonify({
        "status": "active" if status == "running" else "inactive",
        "engine_status": status,
        "position_open": engine.position_open if engine else False,
        "pivot": engine.pivot_0_5 if engine else None,
        "data_manager": "active" if data_mgr else "inactive",
        "telegram_control": "active" if telegram_ctrl else "inactive"
    })

def start_engine():
    global engine, data_mgr, telegram_ctrl
    time.sleep(5)  # गनीकॉर्न और फ्लास्क को सेट होने के लिए 5 सेकंड का बाफर
    try:
        engine = NiftyInstitutionalEngine()
        data_mgr = DataManager()
        
        # 4 महीने का डेटा बैकग्राउंड थ्रेड में चुपचाप डाउनलोड होगा
        threading.Thread(target=lambda: data_mgr.fetch_and_store(engine.obj), daemon=True).start()
        
        telegram_ctrl = TelegramControl(engine)
        engine.run()
    except Exception as e:
        logger.error(f"Engine crashed: {e}", exc_info=True)

def self_ping():
    """पुराने बोट की तरह हर 60 सेकंड में सर्वर को जगाए रखने का लूप"""
    port = os.environ.get("PORT", 8080)
    base_url = f"http://0.0.0.0:{port}"
    while True:
        time.sleep(60)
        try:
            requests.get(base_url, timeout=10)
        except Exception:
            pass

if __name__ == "__main__":
    # ⚠️ पुराने अटके हुए डायग्नोस्टिक्स टेस्ट को पूरी तरह हटा दिया गया है
    # अब इंजन सीधे बिना किसी रुकावट के फोर्स-स्टार्ट होगा!
    
    threading.Thread(target=start_engine, daemon=True).start()
    threading.Thread(target=self_ping, daemon=True).start()

    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
