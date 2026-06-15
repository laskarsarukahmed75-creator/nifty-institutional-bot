from typing import Dict, List, Optional, Any, Tuple, Set
import logging
# ============================================================================
# START MODULE: WebSocketManager
# Version: 2.0.0
# Dependencies: SmartApi.smartWebSocketV2, threading, random, config, database_manager
# Public Functions: set_callback, connect, subscribe, stop, is_connected
# Private Functions: _worker_loop, _attempt_connection, _on_open_internal, _on_data_internal, _on_error_internal, _on_close_internal, _do_subscribe, _force_reconnect
# Upgrade Notes: Replace with any WebSocket library. Must implement same callbacks.
# ============================================================================

import threading
import time
import random
import inspect
from typing import List, Set, Callable, Optional

from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from config.config import Config
from database.database_manager import DatabaseManager

class WebSocketManager:
    def __init__(self, auth_token: str, api_key: str, client_id: str, feed_token: str, db: DatabaseManager = None):
        self.auth_token = auth_token
        self.api_key = api_key
        self.client_id = client_id
        self.feed_token = feed_token
        self.ws = None
        self._connected = False
        self._stop_flag = False
        self._reconnect_attempts = 0
        self._last_data_time = time.time()
        self._lock = threading.RLock()
        self._subscribed_tokens: Set[str] = set()
        self._subscription_mode = 1
        self._correlation_id = "live_data"
        self._on_tick: Optional[Callable] = None
        self._worker_thread: Optional[threading.Thread] = None
        self.db = db or DatabaseManager()
    
    def set_callback(self, callback: Callable):
        self._on_tick = callback
    
    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected
    
    def connect(self):
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=False)
        self._worker_thread.start()
    
    def subscribe(self, tokens: List[str]):
        with self._lock:
            self._subscribed_tokens = set(tokens)
        if self.is_connected and self.ws:
            self._do_subscribe()
    
    def _worker_loop(self):
        while not self._stop_flag:
            if not self.is_connected:
                self._attempt_connection()
                if not self.is_connected:
                    delay = min(1.0 * (2 ** self._reconnect_attempts), 60.0)
                    delay += random.uniform(0, 1)
                    time.sleep(delay)
                    self._reconnect_attempts += 1
                    if self._reconnect_attempts > Config.MAX_WEBSOCKET_RECONNECT_ATTEMPTS:
                        self.db.log_websocket_event("MAX_RECONNECT_FAILED")
                        break
                else:
                    self._reconnect_attempts = 0
                    self.db.log_websocket_event("CONNECTED")
            else:
                time.sleep(1)
                if time.time() - self._last_data_time > 45:
                    self.db.log_websocket_event("HEARTBEAT_TIMEOUT")
                    self._force_reconnect()
        self.db.log_websocket_event("WORKER_STOPPED")
    
    def _make_callback(self, target_method):
        def wrapper(*args, **kwargs):
            try:
                target_method(*args, **kwargs)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"WebSocket callback error: {e}")
        return wrapper
    
    def _attempt_connection(self):
        try:
            sig = inspect.signature(SmartWebSocketV2.__init__)
            params = list(sig.parameters.keys())
            if 'client_id' in params:
                ws = SmartWebSocketV2(auth_token=self.auth_token, api_key=self.api_key,
                                      client_id=self.client_id, feed_token=self.feed_token)
            elif 'client_code' in params:
                ws = SmartWebSocketV2(auth_token=self.auth_token, api_key=self.api_key,
                                      client_code=self.client_id, feed_token=self.feed_token)
            else:
                ws = SmartWebSocketV2(self.auth_token, self.api_key, self.client_id, self.feed_token)
        except Exception:
            return
        
        ws.on_open = self._make_callback(self._on_open_internal)
        ws.on_data = self._make_callback(self._on_data_internal)
        ws.on_error = self._make_callback(self._on_error_internal)
        ws.on_close = self._make_callback(self._on_close_internal)
        
        with self._lock:
            self.ws = ws
        try:
            threading.Thread(target=ws.connect, daemon=True).start()
        except Exception:
            with self._lock:
                self._connected = False
            return
        
        start = time.time()
        while not self.is_connected and (time.time() - start) < 10:
            time.sleep(0.1)
        if self.is_connected:
            self._do_subscribe()
    
    def _on_open_internal(self, *args, **kwargs):
        with self._lock:
            self._connected = True
            self._last_data_time = time.time()
        self.db.log_websocket_event("OPEN")
    
    def _on_data_internal(self, *args, **kwargs):
        self._last_data_time = time.time()
        raw = None
        if len(args) >= 2:
            raw = args[1]
        elif 'message' in kwargs:
            raw = kwargs['message']
        if self._on_tick is None or raw is None:
            return
        normalized = None
        if isinstance(raw, dict):
            ltp = raw.get('ltp') or raw.get('last_traded_price') or raw.get('lastPrice')
            if ltp is None:
                return
            token = raw.get('symboltoken') or raw.get('token')
            volume = raw.get('volume', 0)
            try:
                normalized = {
                    'ltp': float(ltp),
                    'symboltoken': str(token) if token else '',
                    'volume': int(volume)
                }
            except (ValueError, TypeError):
                return
        else:
            return
        try:
            self._on_tick(normalized)
        except Exception:
            pass
    
    def _on_error_internal(self, *args, **kwargs):
        error_msg = str(args[1]) if len(args) > 1 else str(kwargs.get('error', 'unknown'))
        with self._lock:
            self._connected = False
            if self.ws:
                try:
                    self.ws.close()
                except:
                    pass
                self.ws = None
        self.db.log_websocket_event("ERROR", error_msg)
    
    def _on_close_internal(self, *args, **kwargs):
        code = args[1] if len(args) > 1 else kwargs.get('close_status_code', 1000)
        msg = args[2] if len(args) > 2 else kwargs.get('close_msg', '')
        with self._lock:
            self._connected = False
        self.db.log_websocket_event("CLOSE", f"code={code} msg={msg}")
    
    def _do_subscribe(self):
        with self._lock:
            if not self._connected or not self.ws:
                return
            tokens = list(self._subscribed_tokens)
        if not tokens:
            return
        token_list = [{"exchangeType": 1, "tokens": tokens}]
        try:
            self.ws.subscribe(self._correlation_id, self._subscription_mode, token_list)
        except Exception:
            pass
    
    def _force_reconnect(self):
        with self._lock:
            if self.ws:
                try:
                    self.ws.close()
                except:
                    pass
                self.ws = None
            self._connected = False
    
    def stop(self):
        self._stop_flag = True
        with self._lock:
            if self.ws:
                try:
                    self.ws.close()
                except:
                    pass
                self.ws = None
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5.0)

# ============================================================================
# END MODULE: WebSocketManager
# ============================================================================
