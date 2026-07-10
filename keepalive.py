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
    status = "running" if engine and getattr(engine, "running", False) else "stopped"
    return jsonify({
        "status": "active" if status == "running" else "inactive",
        "engine_status": status,
        "position_open": engine.position_open if engine else False,
        "pivot": engine.pivot_0_5 if engine else None,
        "data_manager": "active" if data_mgr else "inactive",
        "telegram_control": "active" if telegram_ctrl else "inactive"
    })

def start_engine_safely():
    global engine, data_mgr, telegram_ctrl
    # 📢 रेंडर को शांत करने के लिए 25 सेकंड का लंबा डिले, ताकि पहले Flask पोर्ट बाइंड हो जाए!
    time.sleep(25)  
    try:
        logger.info("⚡ Background Thread: Launching NiftyInstitutionalEngine Core...")
        engine = NiftyInstitutionalEngine()
        data_mgr = DataManager()
        
        # 4 महीने का हिस्टोरिकल डेटा बिना वेब सर्वर को रोके बैकग्राउंड में डाउनलोड होगा
        threading.Thread(target=lambda: data_mgr.fetch_and_store(engine.obj), daemon=True).start()
        
        telegram_ctrl = TelegramControl(engine)
        engine.run()
    except Exception as e:
        logger.error(f"Engine background crash: {e}", exc_info=True)

def self_ping():
    """रेंडर को एक्टिव रखने के लिए हर 60 सेकंड का पिंग"""
    port = os.environ.get("PORT", 8080)
    base_url = f"http://0.0.0.0:{port}"
    while True:
        time.sleep(60)
        try:
            requests.get(base_url, timeout=10)
        except Exception:
            pass

if __name__ == "__main__":
    # 🔥 मास्टर स्ट्रोक: भारी ट्रेडिंग लोड को तुरंत अलग थ्रेड में फेंक दिया
    engine_thread = threading.Thread(target=start_engine_safely, daemon=True)
    engine_thread.start()
    
    ping_thread = threading.Thread(target=self_ping, daemon=True)
    ping_thread.start()

    # फ्लास्क सर्वर रेंडर के पोर्ट को तुरंत (0.1 सेकंड में) पकड़ लेगा
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
