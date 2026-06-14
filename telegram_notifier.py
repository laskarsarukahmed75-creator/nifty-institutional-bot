# ============================================================================
# START MODULE: TelegramNotifier
# Version: 2.0.0
# Dependencies: telegram, config, asyncio, queue, threading
# Public Functions: send, send_signal, stop
# Private Functions: _worker, _send
# Upgrade Notes: Replace with any messaging service (Slack, Discord).
# ============================================================================

import asyncio
import threading
import queue
from telegram import Bot
from telegram.error import TelegramError

from ..config.config import Config

class TelegramNotifier:
    def __init__(self):
        self.bot = Bot(token=Config.TELEGRAM_BOT_TOKEN)
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.message_queue = queue.Queue()
        self._stop = False
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        self._loop = None
    
    def _worker(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        while not self._stop:
            try:
                msg = self.message_queue.get(timeout=1)
                self._loop.run_until_complete(self._send(msg))
            except queue.Empty:
                continue
            except Exception:
                pass
    
    async def _send(self, msg: str):
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode='HTML')
        except TelegramError:
            pass
    
    def send(self, msg: str):
        self.message_queue.put(msg)
    
    def send_signal(self, signal: Dict):
        msg = (f"🚀 <b>TRADE SIGNAL</b>\nSymbol: {signal['symbol']}\nDirection: {signal['direction']}\n"
               f"Entry: {signal['entry']:.2f}\nStop Loss: {signal['stop_loss']:.2f}\nTarget: {signal['take_profit']:.2f}\n"
               f"Risk/Reward: {signal['risk_reward']:.2f}\nReason: {signal['reason']}\nTime: {signal['timestamp']}")
        self.send(msg)
    
    def stop(self):
        self._stop = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        if self._loop and not self._loop.is_closed():
            self._loop.close()

# ============================================================================
# END MODULE: TelegramNotifier
# ============================================================================
