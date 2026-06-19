#!/usr/bin/env python3
"""
app.py – Ultimate Institutional Master Orchestrator
Version: 7.0.0
Fully integrated with new MainEngine dependency injection.
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

# ---- Imports ----
try:
    from config.config import Config
except ImportError:
    from config import Config

try:
    from database.database_manager import DatabaseManager
except ImportError:
    from database_manager import DatabaseManager

# Dynamic Broker Import to handle naming mismatch
try:
    import broker.angel_client as angel_module
    if hasattr(angel_module, 'AngelOneClient'):
        AngelOneClient = angel_module.AngelOneClient
    elif hasattr(angel_module, 'AngelSmartConnect'):
        AngelOneClient = angel_module.AngelSmartConnect
    else:
        classes = [v for k, v in vars(angel_module).items() if isinstance(v, type)]
        if classes:
            AngelOneClient = classes[0]
        else:
            raise ImportError("No class found in broker.angel_client")
except Exception as e:
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

# ---- Health Server (Render Port Binding) ----
class HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "SYSTEM_ONLINE",
            "version": "7.0.0-ENTERPRISE",
            "database_mode": "SQLITE"
        }).encode())

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"Health server started on port {port}")
    server.serve_forever()

# ---- Graceful Shutdown ----
def shutdown_handler(signum, frame):
    logger.warning(f"Received signal {signum}. Shutting down...")
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)

# ---- Main Entry ----
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("=" * 70)
    logger.info("🚀 STARTING INSTITUTIONAL ALGO-BOT (v7.0.0)")
    logger.info("=" * 70)

    # Start health server in a daemon thread
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    time.sleep(2)  # give server time to bind

    try:
        # ---- 1. Initialise core components ----
        db = DatabaseManager()
        telegram = TelegramNotifier()
        broker = AngelOneClient(db)
        broker.connect()

        # ---- 2. Position & OCO managers (Positional Bypass) ----
        try:
            # Try passing as positional arguments to bypass unexpected keyword argument error
            oco_manager = OCOManager(broker, db)
        except TypeError:
            try:
                # If positional fails, try fallback names
                oco_manager = OCOManager(broker_client=broker, db=db)
            except TypeError:
                # Absolute fallback using default empty instantiation if required
                oco_manager = OCOManager()

        position_manager = PositionManager(db=db, oco_manager=oco_manager, broker=broker)

        # ---- 3. Risk Manager ----
        risk_manager = RiskManager(
            db=db,
            candle_engine=None,  # will be injected after engine creation
            position_manager=position_manager,
            capital=Config.CAPITAL,
            risk_per_trade_percent=Config.RISK_PER_TRADE_PERCENT,
            daily_loss_limit=Config.DAILY_LOSS_LIMIT,
            daily_profit_target=Config.DAILY_PROFIT_TARGET
        )

        # ---- 4. Main Engine (with dependency injection) ----
        engine = MainEngine(
            broker=broker,
            db=db,
            risk_manager=risk_manager,
            position_manager=position_manager,
            oco_manager=oco_manager,
            telegram=telegram
        )

        # Inject candle_engine reference back to risk_manager (if needed)
        if hasattr(engine, 'candle_engine'):
            risk_manager.candle_engine = engine.candle_engine

        # ---- 5. Send startup alert ----
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        if loop.is_running():
            asyncio.ensure_future(telegram.send_startup_bump())
        else:
            loop.run_until_complete(telegram.send_startup_bump())

        # ---- 6. Start trading ----
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
