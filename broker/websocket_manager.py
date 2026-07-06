#!/usr/bin/env python3
import threading
import time
import logging
from typing import Optional, Callable, List
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

logger = logging.getLogger(__name__)

class WebSocketManager:
    def __init__(self, auth_token: str, api_key: str, client_id: str, feed_token: str):
        self.auth_token = auth_token
        self.api_key = api_key
        self.client_id = client_id
        self.feed_token = feed_token
        self.ws = None
        self._connected = False
        self._stop_flag = False
        self._on_tick: Optional[Callable] = None
        self._worker_thread = None

    def set_callback(self, callback: Callable):
        self._on_tick = callback

    def connect(self):
        self._worker_thread = threading.Thread(target=self._ws_loop, daemon=True)
        self._worker_thread.start()

    def subscribe(self, tokens: List[str]):
        self._subscribed_tokens = tokens
        if self._connected and self.ws:
            self._do_subscribe()

    def _ws_loop(self):
        while not self._stop_flag:
            try:
                self.ws = SmartWebSocketV2(self.auth_token, self.api_key, self.client_id, self.feed_token)
                self.ws.on_open = self._on_open
                self.ws.on_data = self._on_data
                self.ws.on_error = self._on_error
                self.ws.on_close = self._on_close
                logger.info("[WS] Connecting to Angel One Live Feed...")
                self.ws.connect()
            except Exception as e:
                logger.error(f"[WS ERROR] Connection failed: {e}")
                time.sleep(5)

    def _on_open(self, *args, **kwargs):
        self._connected = True
        logger.info("[WS] WebSocket connected! Requesting subscription...")
        self._do_subscribe()

    def _on_data(self, *args, **kwargs):
        try:
            # websocket-client वर्ज़न के हिसाब से डेटा निकालना
            message = args[1] if len(args) > 1 else args[0]
            if self._on_tick and isinstance(message, dict):
                tick = {
                    'symboltoken': message.get('symboltoken') or message.get('token'),
                    'ltp': message.get('ltp') or message.get('last_traded_price'),
                    'volume': message.get('volume', 0)
                }
                if tick['symboltoken'] and tick['ltp']:
                    self._on_tick(tick)
        except Exception as e:
            pass

    def _on_error(self, *args, **kwargs):
        logger.error(f"[WS ERROR] Error wrapper triggered: {args}")
        self._connected = False

    def _on_close(self, *args, **kwargs):
        logger.warning("[WS] WebSocket connection closed safely.")
        self._connected = False

    def _do_subscribe(self):
        if self._connected and self.ws and hasattr(self, '_subscribed_tokens'):
            token_list = [{"exchangeType": 1, "tokens": self._subscribed_tokens}]
            self.ws.subscribe("live_data", 1, token_list)
            logger.info(f"[WS] Active subscription on tokens: {self._subscribed_tokens}")

    def stop(self):
        self._stop_flag = True
        if self.ws:
            try: self.ws.close()
            except: pass
