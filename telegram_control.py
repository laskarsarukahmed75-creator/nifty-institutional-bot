#!/usr/bin/env python3
"""
telegram_control.py – NiftyInstitutionalbot Remote Control via Telegram
Supports:
- /stop_trade  → pause trading
- /start_trade → resume trading
- /adjust_sl_tp SYMBOL NEW_SL NEW_TP → adjust SL/TP of an open position (future enhancement)
- /status → returns current bot status
"""

import os
import time
import json
import logging
import threading
import requests
from typing import Optional, Dict

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

logger = logging.getLogger("TelegramControl")

class TelegramControl:
    def __init__(self, engine=None):
        self.engine = engine
        self.offset = 0
        self._stop_flag = False
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info("TelegramControl started.")

    def _send_message(self, text: str):
        try:
            url = BASE_URL + "sendMessage"
            payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Telegram send error: {e}")

    def _listen_loop(self):
        while not self._stop_flag:
            try:
                url = BASE_URL + "getUpdates"
                params = {"offset": self.offset, "timeout": 20}
                resp = requests.get(url, params=params, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get("result", []):
                        self.offset = update["update_id"] + 1
                        msg = update.get("message", {})
                        text = msg.get("text", "").strip()
                        if text:
                            self._handle_command(text)
            except Exception as e:
                logger.error(f"Telegram listen error: {e}")
            time.sleep(2)

    def _handle_command(self, text: str):
        parts = text.lower().split()
        cmd = parts[0] if parts else ""

        if cmd == "/stop_trade":
            with open("stop_signal.txt", "w") as f:
                f.write("STOP")
            self._send_message("🛑 <b>Niftybot Update:</b> Trading paused for today.")
            logger.info("Trading paused via Telegram.")

        elif cmd == "/start_trade":
            if os.path.exists("stop_signal.txt"):
                os.remove("stop_signal.txt")
            self._send_message("🟢 <b>Niftybot Update:</b> Resumed live 0.5 pivot scanning.")
            logger.info("Trading resumed via Telegram.")

        elif cmd == "/status":
            status = self._get_status()
            self._send_message(status)

        elif cmd == "/adjust_sl_tp" and len(parts) >= 4:
            # Format: /adjust_sl_tp NIFTY 22450 22580
            symbol = parts[1].upper()
            try:
                new_sl = float(parts[2])
                new_tp = float(parts[3])
                self._adjust_sl_tp(symbol, new_sl, new_tp)
            except ValueError:
                self._send_message("❌ Invalid SL/TP values. Use numbers.")

        elif cmd == "/help":
            self._send_message("""
<b>Available Commands:</b>
/stop_trade        – Pause trading
/start_trade       – Resume trading
/status            – Show bot status
/adjust_sl_tp SYM SL TP – Adjust SL/TP for open position (future)
/help              – Show this message
            """)

        else:
            self._send_message("Unknown command. Type /help for available commands.")

    def _get_status(self) -> str:
        # Check if engine is running
        engine_status = "🟢 Running" if (self.engine and getattr(self.engine, "running", False)) else "🔴 Stopped"
        pos_open = "Yes" if (self.engine and getattr(self.engine, "position_open", False)) else "No"
        pause = "Yes" if os.path.exists("stop_signal.txt") else "No"
        return (
            f"<b>📊 NiftyInstitutionalbot Status</b>\n"
            f"Engine: {engine_status}\n"
            f"Position Open: {pos_open}\n"
            f"Trading Paused: {pause}\n"
            f"Last Pivot: {getattr(self.engine, 'pivot_0_5', 'N/A')}"
        )

    def _adjust_sl_tp(self, symbol: str, new_sl: float, new_tp: float):
        # This is a placeholder – you would need to implement modification of existing SL/TP orders.
        # Since we don't want to alter app.py logic, we can log and notify.
        # In future, you can extend this to modify orders via Angel One API.
        self._send_message(f"⚠️ SL/TP adjustment for {symbol} not yet implemented. "
                           f"New SL={new_sl}, New TP={new_tp} (simulated)")
        logger.info(f"Telegram SL/TP adjust requested: {symbol} SL={new_sl} TP={new_tp}")

    def stop(self):
        self._stop_flag = True
