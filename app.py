#!/usr/bin/env python3
"""
app.py – Ultimate Institutional Master Orchestrator
Version: 7.1.0 – WebSocket Token Fix
"""
import os
import sys
import time
import json
import logging
import threading
import signal
import traceback
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from config.config import Config
except ImportError:
    from config import Config

try:
    from database.database_manager import DatabaseManager
except ImportError:
    from database_manager import DatabaseManager

try:
    from broker.angel_client import AngelOneClient
except ImportError:
    from angel_client import AngelOneClient

try:
    from risk.risk_manager import RiskManager
except ImportError:
    from risk_manager import RiskManager

try:
    from risk.position_manager import PositionManager
except ImportError:
    from position_manager import PositionManager

try:
    from risk.oco_manager import OCOManager
except ImportError:
    from oco_manager import OCOManager

try:
    from notifications.telegram_notifier import TelegramNotifier
except ImportError:
    from telegram_notifier import TelegramNotifier

try:
    from core.main_engine import MainEngine
except ImportError:
    from main_engine import MainEngine

logger = logging.getLogger("__main__")

class HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "SYSTEM_ONLINE",
            "version": "7.1.0",
            "database_mode": "SQLITE"
        }).encode())

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"Health server started on port {port}")
    server.serve_forever()

def shutdown_handler(signum, frame):
    logger.warning(f"Received signal {signum}. Shutting down...")
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("=" * 70)
    logger.info("🚀 STARTING INSTITUTIONAL ALGO-BOT (v7.1.0)")
    logger.info("=" * 70)

    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    time.sleep(2)

    try:
        db = DatabaseManager()
        telegram = TelegramNotifier()
        broker = AngelOneClient(db)

        if not broker.connect():
            logger.critical("Angel One login failed. Exiting.")
            sys.exit(1)

        logger.info(f"[BOOT] Angel One connected. Auth Token: {broker.auth_token[:10]}...")
        logger.info(f"[BOOT] Feed Token: {broker.feed_token[:10]}...")

        oco_manager = OCOManager()
        position_manager = PositionManager(db=db, broker=broker)

        risk_manager = RiskManager(
            db=db,
            candle_engine=None,
            position_manager=position_manager,
            capital=Config.CAPITAL,
            risk_per_trade_percent=Config.RISK_PER_TRADE_PERCENT,
            daily_loss_limit=Config.DAILY_LOSS_LIMIT,
            daily_profit_target=Config.DAILY_PROFIT_TARGET
        )

        engine = MainEngine(
            broker=broker,
            db=db,
            risk_manager=risk_manager,
            position_manager=position_manager,
            oco_manager=oco_manager,
            telegram=telegram
        )

        if hasattr(engine, 'ws_manager') and engine.ws_manager:
            from broker.websocket_manager import WebSocketManager
            engine.ws_manager = WebSocketManager(
                auth_token=broker.auth_token,
                api_key=Config.ANGEL_API_KEY,
                client_id=Config.ANGEL_CLIENT_ID,
                feed_token=broker.feed_token
            )
            engine.ws_manager.set_callback(engine._on_tick)
            logger.info("[BOOT] WebSocketManager re-initialized with LIVE tokens")

        if hasattr(engine, 'candle_engine'):
            risk_manager.candle_engine = engine.candle_engine

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            asyncio.ensure_future(telegram.send_startup_bump())
        else:
            loop.run_until_complete(telegram.send_startup_bump())

        logger.info("All systems ready. Engaging main engine...")

        if asyncio.iscoroutinefunction(engine.start):
            if loop.is_running():
                asyncio.ensure_future(engine.start())
            else:
                loop.run_until_complete(engine.start())
        else:
            engine.start()

        while True:
            time.sleep(10)

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        traceback.print_exc()
        while True:
            time.sleep(10)
