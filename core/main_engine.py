#!/usr/bin/env python3
import logging
import asyncio
import time
from typing import Dict
from config.config import Config

logger = logging.getLogger(__name__)

class MainEngine:
    def __init__(self, telegram=None, broker=None):
        self.telegram = telegram
        self.broker = broker
        self._running = True
        
        from engines.smc_engine import SMCEngine
        self.smc_engine = SMCEngine()

    async def start(self):
        logger.info("[ENGINE] Nifty Institutional Main Engine Core Online.")
        asyncio.create_task(self._signal_loop())

    def _on_tick(self, tick_data: dict):
        try:
            token = tick_data.get('symboltoken')
            ltp = tick_data.get('ltp')
            volume = tick_data.get('volume', 0)
            if not token or ltp is None:
                return
            
            logger.info(f"[TICK DETECTED] Token: {token} | LTP: {ltp}")
            
            # SMC Engine और Candle Engine अपडेट को यहाँ पास करें
            if hasattr(self, 'candle_engine') and self.candle_engine:
                self.candle_engine.update("NIFTY50", float(ltp), int(volume), time.time())
        except Exception as e:
            logger.error(f"[TICK ERROR] Error processing incoming tick: {e}")

    async def _signal_loop(self):
        logger.info("[LOOP] Starting continuous institutional strategy scanner...")
        while self._running:
            try:
                for symbol in Config.SYMBOLS:
                    # लाइव डेटा पाइपलाइन एक्टिव रखने के लिए स्क्रीनर रन करें
                    signal = self.smc_engine.generate_signal(symbol, None)
                    if signal:
                        logger.info(f"[SIGNAL] Trade signal triggered for {symbol}: {signal}")
                        if self.telegram:
                            await self.telegram.send_signal(signal)
            except Exception as e:
                logger.error(f"[LOOP ERROR] Error in signal scanner: {e}")
            await asyncio.sleep(2)
