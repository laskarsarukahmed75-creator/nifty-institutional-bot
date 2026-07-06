import asyncio
import logging
from notifications.telegram_notifier import TelegramNotifier
from core.main_engine import MainEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start_app():
    logger.info("🚀 INITIALIZING UNIVERSAL BULLETPROOF ARCHITECTURE v7.0.0")
    
    # Test Telegram connection on startup
    telegram = TelegramNotifier()
    try:
        await telegram.send_text_alert("🚀 Nifty Bot Startup Test Message: Engine Engaged!")
        logger.info("[TELEGRAM] Startup test message sent successfully.")
    except Exception as e:
        logger.error(f"[TELEGRAM] Startup test message failed: {e}")

    engine = MainEngine(telegram=telegram)
    await engine.start()

if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    loop.run_until_complete(start_app())
