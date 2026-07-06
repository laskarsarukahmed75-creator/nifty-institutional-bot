import asyncio
import logging
from notifications.telegram_notifier import TelegramNotifier
from core.main_engine import MainEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start_app():
    logger.info("🚀 INITIALIZING UNIVERSAL BULLETPROOF ARCHITECTURE v7.0.0")
    
    # Initialize Telegram
    telegram = TelegramNotifier()
    try:
        # यहाँ हमने 'send_text_alert' को बदलकर सही नाम 'send' कर दिया है!
        telegram.send("🚀 Nifty Bot Startup Test Message: Engine Engaged via Correct Pipeline!")
        logger.info("[TELEGRAM] Startup test message queued successfully.")
    except Exception as e:
        logger.error(f"[TELEGRAM] Startup test message failed: {e}")

    # Start the core engine
    engine = MainEngine(telegram=telegram)
    await engine.start()

if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    loop.run_until_complete(start_app())
