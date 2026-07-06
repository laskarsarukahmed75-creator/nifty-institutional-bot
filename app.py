import asyncio
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from notifications.telegram_notifier import TelegramNotifier
from core.main_engine import MainEngine
from broker.websocket_manager import WebSocketManager
from config.config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# रेंडर को शांत रखने के लिए एक छोटा डमी वेब सर्वर ताकि "In Progress" हटकर सीधे Live हो जाए
class HealthServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is alive and screening market data!")

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthServer)
    logger.info(f"Health server active on port {port}")
    server.serve_forever()

async def start_app():
    logger.info("🚀 INITIALIZING UNIVERSAL BULLETPROOF ARCHITECTURE v7.0.0")
    
    # 1. डमी वेब सर्वर चालू करें ताकि रेंडर तुरंत 'Live' स्टेटस दे
    threading.Thread(target=start_health_server, daemon=True).start()
    
    # 2. टेलीग्राम अलर्ट शुरू करें
    telegram = TelegramNotifier()
    telegram.send("🚀 Nifty Bot Startup Test Message: Engine Engaged with Live Health Check!")
    
    # Mock या असली broker ऑब्जेक्ट से टोकन डिटेल्स निकालें (जैसा आपके सिस्टम में कॉन्फिगर है)
    engine = MainEngine(telegram=telegram)
    await engine.start()
    
    # 3. एंजल वन वेबसोकेट चालू करें (डमी टोकन्स उदाहरण के लिए, ये आपके config/broker से ऑटो-मैप होंगे)
    try:
        ws_manager = WebSocketManager(
            auth_token=os.environ.get("ANGEL_AUTH_TOKEN", "dummy"),
            api_key=Config.ANGEL_API_KEY if hasattr(Config, 'ANGEL_API_KEY') else "dummy",
            client_id=os.environ.get("ANGEL_CLIENT_ID", "dummy"),
            feed_token=os.environ.get("ANGEL_FEED_TOKEN", "dummy")
        )
        ws_manager.set_callback(engine._on_tick)
        
        # सिम्बल्स के टोकन सब्सक्राइब करें (जैसे Nifty=99926000)
        tokens = ["99926000", "99926009"] 
        ws_manager.subscribe(tokens)
        ws_manager.connect()
        logger.info("[WS START] Angel One WebSocket loop initialized.")
    except Exception as e:
        logger.error(f"Failed to boot WebSocket Manager: {e}")

    # परमानेंट नॉन-ब्लॉकिंग कीप-अलाइव लूप
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    loop.run_until_complete(start_app())
