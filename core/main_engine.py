#!/usr/bin/env python3
"""
main_engine.py – Fully Audited & Bug-Free Hybrid Institutional Trading Engine
"""

import logging
import asyncio
from notifications.telegram_notifier import TelegramNotifier
from core.ai_filter import GeminiFilter

try:
    from notifications.discord_notifier import DiscordNotifier
except ImportError:
    DiscordNotifier = None

logger = logging.getLogger(__name__)

class MainEngine:
    def __init__(self, broker=None, db=None, risk_manager=None, position_manager=None, oco_manager=None, telegram=None):
        self.broker = broker
        self.db = db
        self.risk_manager = risk_manager
        self.position_manager = position_manager
        self.oco_manager = oco_manager
        self.telegram = telegram if telegram else TelegramNotifier()
        self.ai_filter = GeminiFilter()
        
        if DiscordNotifier:
            self.discord = DiscordNotifier()
            logger.info("Discord Notifier integrated in MainEngine.")
        else:
            self.discord = None

    async def start(self):
        logger.info("Main Trading Engine Core Loop Engaged. Millisecond price monitoring active.")
        if self.discord:
            try:
                # Discord send is synchronous requests.post, call directly
                self.discord.send("**✅ ALGO-BOT SYSTEM ONLINE:** Fully Audited Hybrid AI & Live News Engine successfully armed! Ready for Nifty 50. 🚀🦅")
            except Exception as e:
                logger.error(f"Discord boot alert failed: {e}")

    async def process_signal(self, signal_data: dict):
        logger.info(f"Technical Setup Detected for {signal_data.get('symbol')}. Triggering Real-time Gemini Live News Check...")
        
        # 1. Run Gemini News Check safely in an executor to prevent blocking the async event loop
        loop = asyncio.get_running_loop()
        approved, news_summary = await loop.run_in_executor(
            None, self.ai_filter.track_live_news_and_validate, signal_data
        )
        
        signal_data['ai_status'] = "APPROVED 🟢" if approved else "REJECTED 🔴"
        signal_data['news_summary'] = news_summary
        
        if not approved:
            logger.warning(f"Signal REJECTED by Gemini Live News Filter. Bypassing trade.")
            reject_msg = f"**⚠️ AI FILTER REJECTED TRADE**\nSymbol: {signal_data.get('symbol')}\nReason/News: {news_summary}"
            if self.discord: 
                self.discord.send(reject_msg)
            return

        logger.info(f"Signal APPROVED by Gemini Live News Filter. Executing institutional routing.")
        
        # 2. Enrich message formatting
        enriched_msg = (
            f"**🚀 NEW INSTITUTIONAL SIGNAL [{signal_data['ai_status']}]**\n"
            f"Symbol: {signal_data.get('symbol', 'N/A')}\n"
            f"Direction: {signal_data.get('direction', 'N/A')}\n"
            f"Entry: {signal_data.get('entry', 0.0)}\n"
            f"SL: {signal_data.get('stop_loss', 0.0)} | TP: {signal_data.get('take_profit', 0.0)}\n"
            f"**📰 LIVE NEWS ANALYSIS:** {news_summary}"
        )

        # 3. Send to Telegram using AWAIT (Fixes silent delivery failure)
        if self.telegram:
            try: 
                await self.telegram.send_text_alert(enriched_msg)
            except Exception as e: 
                logger.error(f"Telegram signal routing failed: {e}")
            
        # 4. Send to Discord
        if self.discord:
            try: 
                self.discord.send(enriched_msg)
            except Exception as e: 
                logger.error(f"Discord signal routing failed: {e}")
