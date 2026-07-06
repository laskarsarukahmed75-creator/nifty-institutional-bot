import asyncio
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from notifications.telegram_notifier import TelegramNotifier
from core.main_engine import MainEngine
from broker.websocket_manager import WebSocketManager
from config.config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HealthServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Live and ready!")

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthServer)
    server.serve_forever()

async def start_app():
    logger.info("🚀 INITIALIZING UNIVERSAL BULLETPROOF ARCHITECTURE v7.0.0")
    threading.Thread(target=start_health_server, daemon=True).start()
    
    telegram = TelegramNotifier()
    
    # आपके सिस्टम के मेन इंजन और ब्रोकर को इनिशियलाइज़ करना
    engine = MainEngine(telegram=telegram)
    await engine.start()
    
    # अगर आपके पास कोई ब्रोकर लॉगिन क्लास है, तो उसे यहाँ कनेक्ट करें, 
    # अन्यथा यह सीधे Config फाइल्स से लॉगिन क्रेडेंशियल्स उठाएगा
    try:
        broker_auth = getattr(engine, 'broker', None)
        auth_token = getattr(broker_auth, 'auth_token', Config.ANGEL_AUTH_TOKEN if hasattr(Config, 'ANGEL_AUTH_TOKEN') else "dummy")
        feed_token = getattr(broker_auth, 'feed_token', Config.ANGEL_FEED_TOKEN if hasattr(Config, 'ANGEL_FEED_TOKEN') else "dummy")
        
        ws_manager = WebSocketManager(
            auth_token=auth_token,
            api_key=Config.ANGEL_API_KEY if hasattr(Config, 'ANGEL_API_KEY') else "dummy",
            client_id=Config.ANGEL_CLIENT_ID if hasattr(Config, 'ANGEL_CLIENT_ID') else "dummy",
            feed_token=feed_token
        )
        ws_manager.set_callback(engine._on_tick)
        
        # सिम्बल्स टोकन सब्सक्राइब करें
        tokens = ["99926000", "99926009"]
        ws_manager.subscribe(tokens)
        ws_manager.connect()
        logger.info("[OK] WebSocket Pipeline deployed with live tokens.")
    except Exception as e:
        logger.error(f"WebSocket initiation error: {e}")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(start_app())
