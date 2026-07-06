import asyncio
import logging
from notifications.telegram_notifier import TelegramNotifier
from core.main_engine import MainEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start_app():
    logger.info("🚀 INITIALIZING UNIVERSAL BULLETPROOF ARCHITECTURE v7.0.0")
    
    telegram = TelegramNotifier()
    engine = MainEngine(telegram=telegram)
    await engine.start()
    
    # यह जादुई लाइन रेंडर को टाइम आउट भी नहीं होने देगी और प्रोग्राम को बंद (Exited early) भी नहीं होने देगी
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    loop.run_until_complete(start_app())
