#!/usr/bin/env python3
"""
main_engine.py – Institutional Trading Engine Core
"""

import logging
import asyncio
from notifications.telegram_notifier import TelegramNotifier
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
        
        # Connect Discord safely
        if DiscordNotifier:
            self.discord = DiscordNotifier()
            logger.info("Discord Notifier integrated inside MainEngine core.")
        else:
            self.discord = None

    async def start(self):
        logger.info("Main Trading Engine Core Loop Engaged.")
        # Trigger explicit Discord startup confirmation alert
        if self.discord:
            try:
                self.discord.send("**✅ ALGO-BOT SYSTEM ONLINE:** Main engine integrated successfully! Ready for Nifty 50 market sessions. 🚀")
            except Exception as e:
                logger.error(f"Failed to send Discord boot alert: {e}")

    def process_signal(self, signal_data: dict):
        logger.info(f"Processing institutional setup for: {signal_data.get('symbol')}")
        
        # 1. Send to Telegram
        if self.telegram and hasattr(self.telegram, 'send_signal'):
            try: self.telegram.send_signal(signal_data)
            except Exception: pass
            
        # 2. Send to Discord simultaneously
        if self.discord and hasattr(self.discord, 'send_signal'):
            try: self.discord.send_signal(signal_data)
            except Exception: pass
