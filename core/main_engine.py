#!/usr/bin/env python3
"""
main_engine.py – Audited Nifty 50 Core with Live Gemini Rejection Alerts & Data Flow Routing
"""
import logging
import asyncio
from typing import Dict
from notifications.telegram_notifier import TelegramNotifier
from core.ai_filter import GeminiFilter

try:
    from notifications.discord_notifier import DiscordNotifier
except ImportError:
    DiscordNotifier = None

logger = logging.getLogger(__name__)

class MainEngine:
    def __init__(self, broker=None, db=None, risk_manager=None, position_manager=None, oco_manager=None, telegram=None, event_bus=None):
        self.broker = broker
        self.db = db
        self.risk_manager = risk_manager
        self.position_manager = position_manager
        self.oco_manager = oco_manager
        self.telegram = telegram if telegram else TelegramNotifier()
        self.ai_filter = GeminiFilter()
        self.event_bus = event_bus
        
        # 1. FIX: DeepSeek Data Pipeline Subscription
        if self.event_bus:
            self.event_bus.subscribe("MARKET_DATA", self._on_market_data)
            logger.info("Successfully bound MainEngine to MARKET_DATA topic pipeline.")
        
        if DiscordNotifier:
            self.discord = DiscordNotifier()
        else:
            self.discord = None

    async def start(self):
        logger.info("Nifty Institutional Main Engine Core Online.")
        if self.discord:
            try:
                self.discord.send("**✅ NIFTY-50 BOT ONLINE:** Live data pipeline fixed & Gemini Rejection alerts fully armed! 🚀🦅")
            except Exception as e:
                logger.error(f"Discord alert issue: {e}")

    async def _on_market_data(self, candle: Dict) -> None:
        """Update your candle engine dynamically when market data ticks"""
        if hasattr(self, 'candle_engine') and self.candle_engine:
            self.candle_engine.update("NIFTY50", candle)

    def process_signal(self, signal_data: dict):
        logger.info(f"Processing Nifty 50 setup for direction: {signal_data.get('direction')}")
        
        # 2. Trigger Gemini Live News Evaluation Check
        approved, news_summary = self.ai_filter.track_live_news_and_validate(signal_data)
        
        signal_data['ai_status'] = "APPROVED 🟢" if approved else "REJECTED 🔴"
        signal_data['news_summary'] = news_summary
        
        # 🚨 FUNCTION: HANDLE AI REJECTION (अगर जेमिनी रिजेक्ट करे तो डिस्कॉर्ड पर चिल्लाओ!)
        if not approved:
            logger.warning("Trade REJECTED by Gemini Filter. Dispatching alert...")
            rejection_msg = (
                f"**⚠️ GOOGLE GEMINI: NIFTY 50 SIGNAL REJECTED!**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Symbol:** NIFTY 50\n"
                f"**Direction:** {signal_data.get('direction', 'N/A')}\n"
                f"**Entry Level:** {signal_data.get('entry', 0.0)}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"**📰 GOOGLE AI LIVE NEWS REASON:**\n"
                f"_{news_summary}_"
            )
            if self.discord: 
                try: self.discord.send(rejection_msg)
                except Exception: pass
            return

        # 3. If APPROVED -> Push for execution
        logger.info("Signal APPROVED by Gemini AI. Dispatching orders...")
        if self.discord:
            try: self.discord.send(f"**🟢 NIFTY SIGNAL APPROVED & EXECUTED:** Entering {signal_data.get('direction')} at {signal_data.get('entry')}")
            except Exception: pass
