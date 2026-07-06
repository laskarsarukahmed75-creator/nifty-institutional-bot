#!/usr/bin/env python3
import logging
import asyncio
from typing import Dict
from config.config import Config

logger = logging.getLogger(__name__)

class MainEngine:
    def __init__(self, telegram=None):
        self.telegram = telegram
        self._running = True
        
        from engines.smc_engine import SMCEngine
        self.smc_engine = SMCEngine()

    async def start(self):
        logger.info("[ENGINE] Nifty Institutional Main Engine Core Online.")
        # प्रोग्राम को हमेशा जिंदा रखने के लिए बैकग्राउंड टास्क की जगह सीधे await करेंगे
        await self._signal_loop()

    def _on_tick(self, tick_data: dict):
        logger.info(f"[TICK] Processing live tick data for symboltoken: {tick_data.get('symboltoken')}")
        if hasattr(self, 'candle_engine') and self.candle_engine:
            self.candle_engine.update("NIFTY50", tick_data)

    async def _signal_loop(self):
        # रेंडर लॉग्स में साफ़ दिखने के लिए एक स्टार्टिंग मैसेज जोड़ दिया है
        logger.info("[LOOP] Starting continuous institutional strategy scanner...")
        while self._running:
            try:
                for symbol in Config.SYMBOLS:
                    signal = self.smc_engine.generate_signal(symbol, None)
                    if signal:
                        logger.info(f"[SIGNAL] Trade signal triggered: {signal}")
                        if self.telegram:
                            await self.telegram.send_signal(signal)
            except Exception as e:
                logger.error(f"[LOOP ERROR] Error in signal scanner: {e}")
            await asyncio.sleep(2)
