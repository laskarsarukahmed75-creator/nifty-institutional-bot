#!/usr/bin/env python3
"""
discord_notifier.py – Fixed Discord Webhook Alerting Layer
"""

import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

class DiscordNotifier:
    def __init__(self):
        # Directly fetch from Render Environment Variable or fallback to config
        self.webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')
        if not self.webhook_url:
            try:
                from config.config import Config
                self.webhook_url = getattr(Config, 'DISCORD_WEBHOOK_URL', '')
            except Exception:
                pass

    def send(self, message: str) -> bool:
        if not self.webhook_url:
            logger.error("Discord Webhook URL is completely missing from Env!")
            return False
        try:
            data = {"content": message}
            response = requests.post(self.webhook_url, json=data, headers={"Content-Type": "application/json"})
            if response.status_code != 204:
                logger.error(f"Discord API returned status code: {response.status_code}")
            return response.status_code == 204
        except Exception as e:
            logger.error(f"Discord notification HTTP failed: {e}")
            return False

    def send_signal(self, signal: dict):
        msg = (
            f"**🚀 NEW TRADE SIGNAL GENERATED**\n"
            f"Symbol: {signal.get('symbol', 'N/A')}\n"
            f"Direction: {signal.get('direction', 'N/A')}\n"
            f"Entry: {signal.get('entry', 0.0)}\n"
            f"Stop Loss: {signal.get('stop_loss', 0.0)}\n"
            f"Take Profit: {signal.get('take_profit', 0.0)}"
        )
        self.send(msg)
