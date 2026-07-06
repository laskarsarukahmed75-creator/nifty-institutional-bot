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
        self._subscribed_tokens: List[str] = []
        self._on_tick: Optional[Callable] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10

        logger.info(f"[WS] Initialized with feed_token: {feed_token[:10]}...")

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
                self._connect_websocket()
                self._run_websocket()
                self._reconnect_attempts = 0
            except Exception as e:
                logger.error(f"[WS] WebSocket error: {e}")
                self._reconnect_attempts += 1
                delay = min(2 ** self._reconnect_attempts, 30)
                if self._reconnect_attempts > self._max_reconnect_attempts:
                    logger.error("[WS] Max reconnect attempts reached. Giving up.")
                    break
                logger.info(f"[WS] Reconnecting in {delay}s")
                time.sleep(delay)

    def _connect_websocket(self):
        logger.info("[WS] Connecting with fresh live session tokens...")
        self.ws = SmartWebSocketV2(self.auth_token, self.api_key, self.client_id, self.feed_token)

        self.ws.on_open = self._make_callback(self._on_open)
        self.ws.on_data = self._make_callback(self._on_data)
        self.ws.on_error = self._make_callback(self._on_error)
        self.ws.on_close = self._make_callback(self._on_close)
        self.ws.connect()

    def _make_callback(self, target_method):
        def wrapper(*args, **kwargs):
            try:
                target_method(*args, **kwargs)
            except Exception as e:
                logger.error(f"[WS] Callback error in {target_method.__name__}: {e}")
        return wrapper

    def _run_websocket(self):
        if self.ws:
            while self._connected and not self._stop_flag:
                time.sleep(1)

    def _on_open(self, *args, **kwargs):
        self._connected = True
        logger.info("[WS] WebSocket opened successfully.")
        if self._subscribed_tokens:
            self._do_subscribe()

    def _on_data(self, *args, **kwargs):
        message = args[1] if len(args) >= 2 else kwargs.get('message')
        if self._on_tick and message:
            try:
                if isinstance(message, dict):
                    tick = {
                        'symboltoken': message.get('symboltoken') or message.get('token'),
                        'ltp': message.get('ltp') or message.get('last_traded_price'),
                        'volume': message.get('volume', 0)
                    }
                    if tick['symboltoken'] and tick['ltp']:
                        self._on_tick(tick)
            except Exception as e:
                logger.error(f"[WS] Tick parsing error: {e}")

    def _on_error(self, *args, **kwargs):
        error_msg = args[1] if len(args) > 1 else kwargs.get('error', 'unknown')
        logger.error(f"[WS] WebSocket error observed: {error_msg}")
        self._connected = False

    def _on_close(self, *args, **kwargs):
        code = args[1] if len(args) > 1 else kwargs.get('close_status_code', 1000)
        logger.warning(f"[WS] WebSocket safely closed. Code: {code}")
        self._connected = False

    def _do_subscribe(self):
        if not self._connected or not self.ws or not self._subscribed_tokens:
            return
        token_list = [{"exchangeType": 1, "tokens": self._subscribed_tokens}]
        try:
            self.ws.subscribe("live_data", 1, token_list)
            logger.info(f"[WS] Subscribed successfully to tokens: {self._subscribed_tokens}")
        except Exception as e:
            logger.error(f"[WS] Subscribe failed: {e}")

    def stop(self):
        self._stop_flag = True
        if self.ws:
            try: self.ws.close()
            except Exception: pass
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=3)
