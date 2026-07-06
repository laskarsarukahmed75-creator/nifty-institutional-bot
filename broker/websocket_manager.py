#!/usr/bin/env python3
import threading
import time
import logging
from typing import Optional, Dict, Callable, List
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
from config.config import Config

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
                logger.info("[WS] Angel One WebSocket connecting...")
                self.ws.connect()
            except Exception as e:
                logger.error(f"[WS ERROR] WebSocket loop error: {e}")
                time.sleep(5)

    def _on_open(self, wsapp):
        self._connected = True
        logger.info("[WS] WebSocket opened successfully. Subscribing to tokens...")
        self._do_subscribe()

    def _on_data(self, wsapp, message, data_type, continue_flag):
        try:
            if self._on_tick and isinstance(message, dict):
                tick = {
                    'symboltoken': message.get('symboltoken') or message.get('token'),
                    'ltp': message.get('ltp') or message.get('last_traded_price'),
                    'volume': message.get('volume', 0)
                }
                if tick['symboltoken'] and tick['ltp']:
                    self._on_tick(tick)
        except Exception as e:
            logger.error(f"[WS ERROR] Tick parsing error: {e}")

    def _on_error(self, wsapp, error, extra=None):
        logger.error(f"[WS ERROR] WebSocket error observed: {error}")
        self._connected = False

    def _on_close(self, wsapp, close_status_code=1000, close_msg=""):
        logger.warning(f"[WS] WebSocket closed: {close_status_code}")
        self._connected = False

    def _do_subscribe(self):
        if self._connected and self.ws and hasattr(self, '_subscribed_tokens'):
            token_list = [{"exchangeType": 1, "tokens": self._subscribed_tokens}]
            self.ws.subscribe("live_data", 1, token_list)
            logger.info(f"[WS] Subscribed to tokens: {self._subscribed_tokens}")
