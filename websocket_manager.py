"""
Angel One SmartWebSocketManager – Production Grade
Compatible with all smartapi-python versions, Render Free, Python 3.11
"""

import logging
import time
import threading
import inspect
import sys
from typing import Callable, Optional, List, Set, Dict, Any
from functools import wraps

try:
    from importlib.metadata import version as get_version
    _smartapi_version = get_version("smartapi-python")
except Exception:
    _smartapi_version = "unknown"

logger = logging.getLogger(__name__)


class SmartWebSocketManager:
    def __init__(self, auth_token: str, api_key: str, client_id: str, feed_token: str):
        self.auth_token = auth_token
        self.api_key = api_key
        self.client_id = client_id
        self.feed_token = feed_token

        self._ws_class = None
        self._ws_init_params = None
        self._detect_smartapi_version()

        self._connected = False
        self._stop_flag = False
        self._reconnect_attempts = 0
        self._last_data_time = time.time()
        self._lock = threading.RLock()

        self.max_reconnect_attempts = 10
        self.base_delay = 1.0
        self.max_delay = 60.0
        self.heartbeat_timeout = 300   # 5 minutes – avoids false reconnects

        self._subscribed_tokens: Set[str] = set()
        self._subscription_mode = 1
        self._correlation_id = "live_data"

        self._on_data: Optional[Callable] = None
        self._on_open: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        self._on_close: Optional[Callable] = None

        self._ws = None
        self._worker_thread: Optional[threading.Thread] = None

        self._startup_diagnostics()

    # ------------------------------------------------------------------
    # Version detection
    # ------------------------------------------------------------------
    def _detect_smartapi_version(self) -> None:
        try:
            try:
                from SmartApi.smartWebSocketV2 import SmartWebSocketV2
            except ImportError:
                from smartapi_python import SmartWebSocketV2

            self._ws_class = SmartWebSocketV2
            sig = inspect.signature(SmartWebSocketV2.__init__)
            params = list(sig.parameters.keys())
            logger.info(f"SmartWebSocketV2 __init__ params: {params}")

            if 'client_id' in params:
                self._ws_init_params = {
                    'auth_token': self.auth_token,
                    'api_key': self.api_key,
                    'client_id': self.client_id,
                    'feed_token': self.feed_token
                }
            elif 'client_code' in params:
                self._ws_init_params = {
                    'auth_token': self.auth_token,
                    'api_key': self.api_key,
                    'client_code': self.client_id,
                    'feed_token': self.feed_token
                }
            else:
                self._ws_init_params = None
                logger.warning("No named client param – using positional order")
        except Exception as e:
            logger.error(f"Failed to detect SmartAPI: {e}")
            raise RuntimeError("SmartAPI library not properly installed") from e

    def _startup_diagnostics(self) -> None:
        logger.info(f"Python: {sys.version}")
        logger.info(f"smartapi-python: {_smartapi_version}")
        logger.info(f"WebSocket class: {self._ws_class}")
        if self._ws_init_params:
            logger.info(f"Init params keys: {list(self._ws_init_params.keys())}")
        else:
            logger.info("Init params: positional order")
        logger.info(f"Max reconnects: {self.max_reconnect_attempts}")
        logger.info(f"Heartbeat timeout: {self.heartbeat_timeout}s")

    def _create_websocket(self):
        if self._ws_init_params:
            return self._ws_class(**self._ws_init_params)
        else:
            return self._ws_class(
                self.auth_token, self.api_key, self.client_id, self.feed_token
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def connect(self, on_data: Callable,
                on_open: Optional[Callable] = None,
                on_error: Optional[Callable] = None,
                on_close: Optional[Callable] = None,
                timeout: float = 15.0) -> bool:
        with self._lock:
            if self._worker_thread and self._worker_thread.is_alive():
                logger.debug("Worker already running")
                return self._wait_for_connection(timeout)

            self._on_data = on_data
            self._on_open = on_open
            self._on_error = on_error
            self._on_close = on_close
            self._stop_flag = False
            self._reconnect_attempts = 0

            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=False)
            self._worker_thread.start()

        return self._wait_for_connection(timeout)

    def subscribe(self, tokens: List[str], mode: int = 1) -> None:
        if not tokens:
            return
        token_set = set(str(t) for t in tokens)
        with self._lock:
            self._subscribed_tokens = token_set
            self._subscription_mode = mode
        if self._connected and self._ws:
            self._do_subscribe()

    def disconnect(self) -> None:
        with self._lock:
            if self._ws:
                try:
                    self._ws.close()
                except:
                    pass
                self._ws = None
            self._connected = False

    def stop(self) -> None:
        with self._lock:
            self._stop_flag = True
            if self._ws:
                try:
                    self._ws.close()
                except:
                    pass
                self._ws = None
            self._connected = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=65.0)
            if self._worker_thread.is_alive():
                logger.warning("Worker thread did not terminate")
            else:
                self._worker_thread = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Internal worker & reconnection
    # ------------------------------------------------------------------
    def _worker_loop(self) -> None:
        while not self._stop_flag:
            if not self._connected:
                self._attempt_connection()
                if not self._connected:
                    delay = min(self.base_delay * (2 ** self._reconnect_attempts), self.max_delay)
                    logger.info(f"Reconnect attempt {self._reconnect_attempts + 1} in {delay:.1f}s")
                    time.sleep(delay)
                    self._reconnect_attempts += 1
                    if self._reconnect_attempts > self.max_reconnect_attempts:
                        logger.error("Max reconnect attempts reached. Call connect() again.")
                        break
                else:
                    self._reconnect_attempts = 0
            else:
                time.sleep(1)
                if time.time() - self._last_data_time > self.heartbeat_timeout:
                    logger.warning("Heartbeat timeout, forcing reconnect")
                    self._force_reconnect()
        with self._lock:
            self._reconnect_attempts = 0

    def _attempt_connection(self) -> None:
        with self._lock:
            if self._ws:
                try:
                    self._ws.close()
                except:
                    pass
                self._ws = None
            self._connected = False

        try:
            ws = self._create_websocket()
        except Exception as e:
            logger.error(f"Failed to create WebSocket: {e}")
            return

        ws.on_open = self._make_callback(self._on_open_callback)
        ws.on_data = self._make_callback(self._on_data_callback)
        ws.on_error = self._make_callback(self._on_error_callback)
        ws.on_close = self._make_callback(self._on_close_callback)

        with self._lock:
            self._ws = ws
        logger.info("Connecting...")
        try:
            ws.connect()
        except Exception as e:
            logger.error(f"ws.connect() error: {e}")
            with self._lock:
                self._connected = False
                self._ws = None
            return

        start = time.time()
        while not self._connected and (time.time() - start) < 10:
            time.sleep(0.1)

        if self._connected:
            logger.info("Connected")
            if self._subscribed_tokens:
                self._do_subscribe()
        else:
            logger.warning("Connection timeout")
            with self._lock:
                if self._ws:
                    try:
                        self._ws.close()
                    except:
                        pass
                    self._ws = None
                self._connected = False

    def _force_reconnect(self) -> None:
        with self._lock:
            if self._ws:
                try:
                    self._ws.close()
                except:
                    pass
                self._ws = None
            self._connected = False

    # ------------------------------------------------------------------
    # Version-safe subscription
    # ------------------------------------------------------------------
    def _do_subscribe(self) -> None:
        with self._lock:
            if not self._connected or not self._ws:
                logger.warning("Cannot subscribe: not connected")
                return
            tokens_list = list(self._subscribed_tokens)
        if not tokens_list:
            return

        token_list = [{"exchangeType": 1, "tokens": tokens_list}]

        with self._lock:
            if not self._connected or not self._ws:
                return
            ws = self._ws
            try:
                sub_method = ws.subscribe
                sig = inspect.signature(sub_method)
                params = list(sig.parameters.keys())

                if len(params) >= 3 and 'mode' in params:
                    sub_method(self._correlation_id, self._subscription_mode, token_list)
                elif len(params) == 2:
                    sub_method(self._correlation_id, token_list)
                elif len(params) == 1:
                    sub_method(token_list)
                else:
                    sub_method(self._correlation_id, self._subscription_mode, token_list)

                logger.info(f"Subscribed to {len(tokens_list)} tokens")
            except Exception as e:
                logger.error(f"Subscribe failed: {e}")

    # ------------------------------------------------------------------
    # Callbacks (signature‑safe)
    # ------------------------------------------------------------------
    @staticmethod
    def _make_callback(user_func: Optional[Callable]) -> Callable:
        if user_func is None:
            return lambda *args, **kwargs: None
        @wraps(user_func)
        def wrapper(*args, **kwargs):
            try:
                user_func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Callback error: {e}")
        return wrapper

    def _on_open_callback(self, wsapp) -> None:
        with self._lock:
            self._connected = True
            self._last_data_time = time.time()
        logger.info("WebSocket opened")
        if self._on_open:
            self._on_open(wsapp)

    def _on_data_callback(self, wsapp, message, data_type, continue_flag) -> None:
        self._last_data_time = time.time()
        if isinstance(message, dict) and message.get("heartbeat") == "ping":
            return
        if self._on_data:
            self._on_data(wsapp, message)

    def _on_error_callback(self, wsapp, error, extra=None) -> None:
        logger.error(f"WebSocket error: {error}")
        with self._lock:
            self._connected = False
            if self._ws:
                try:
                    self._ws.close()
                except:
                    pass
                self._ws = None
        if self._on_error:
            self._on_error(wsapp, error)

    def _on_close_callback(self, wsapp, close_status_code=1000, close_msg="") -> None:
        logger.warning(f"Closed: {close_status_code} - {close_msg}")
        with self._lock:
            self._connected = False
        if self._on_close:
            self._on_close(wsapp)

    def _wait_for_connection(self, timeout: float) -> bool:
        start = time.time()
        while not self._connected and (time.time() - start) < timeout:
            time.sleep(0.1)
        return self._connected
