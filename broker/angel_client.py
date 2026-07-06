#!/usr/bin/env python3
"""
angel_client.py – Angel One SmartAPI Client with Robust Login & TOTP
Version: 3.2.1
"""
import time
import hmac
import hashlib
import base64
import logging
import threading
import traceback
from typing import Optional, Dict, List, Any

from SmartApi import SmartConnect
from config.config import Config
from database.database_manager import DatabaseManager

logger = logging.getLogger(__name__)


class AngelOneClient:
    def __init__(self, db: DatabaseManager = None):
        self.api: Optional[SmartConnect] = None
        self.auth_token: Optional[str] = None
        self.feed_token: Optional[str] = None
        self.client_id = Config.ANGEL_CLIENT_ID
        self.token_map: Dict[str, str] = {}
        self.instrument_map: Dict[str, Dict] = {}
        self._lock = threading.RLock()
        self._connected = False
        self.db = db or DatabaseManager()

    def connect(self) -> bool:
        with self._lock:
            try:
                logger.info("[ANGEL] Initializing SmartConnect API...")
                self.api = SmartConnect(api_key=Config.ANGEL_API_KEY)

                totp_secret = Config.ANGEL_TOTP_SECRET
                logger.info(f"[ANGEL] TOTP secret (masked): {totp_secret[:4]}...{totp_secret[-4:] if len(totp_secret)>8 else ''}")
                
                totp = self._generate_totp(totp_secret)
                logger.info(f"[ANGEL] Generated TOTP: {totp}")

                logger.info(f"[ANGEL] Attempting login with Client ID: {self.client_id}")
                login_resp = self.api.generateSession(
                    clientCode=self.client_id,
                    password=Config.ANGEL_PASSWORD,
                    totp=totp
                )
                logger.info(f"[ANGEL] Login response: {login_resp}")

                if not login_resp:
                    logger.error("[ANGEL] Login response is empty or None")
                    return False

                if not login_resp.get('status'):
                    error_msg = login_resp.get('message', 'Unknown error')
                    logger.error(f"[ANGEL] Login failed: {error_msg}")
                    return False

                data = login_resp.get('data', {})
                self.auth_token = data.get('jwtToken')
                if not self.auth_token:
                    logger.error("[ANGEL] JWT token missing in response")
                    return False

                self.feed_token = self._get_feed_token()
                if not self.feed_token:
                    logger.error("[ANGEL] Feed token acquisition failed")
                    return False

                self._load_instrument_master()
                self._connected = True
                logger.info("[ANGEL] ✅ Login successful.")
                return True

            except Exception as e:
                logger.error(f"[ANGEL] Connection error: {e}")
                traceback.print_exc()
                return False

    def _get_feed_token(self) -> Optional[str]:
        methods = [
            ('getFeedToken', lambda: self.api.getFeedToken()),
            ('getfeedToken', lambda: self.api.getfeedToken()),
            ('get_feed_token', lambda: self.api.get_feed_token()),
        ]
        for name, method in methods:
            if hasattr(self.api, name):
                try:
                    token = method()
                    if token and isinstance(token, str) and len(token) > 5:
                        logger.info(f"[ANGEL] Feed token acquired via {name}")
                        return token
                except Exception:
                    continue
        if hasattr(self.api, 'feed_token'):
            return self.api.feed_token
        if hasattr(self.api, 'feedToken'):
            return self.api.feedToken
        return None

    def _generate_totp(self, secret: str) -> str:
        try:
            import pyotp
            totp = pyotp.TOTP(secret)
            code = totp.now()
            logger.debug("[TOTP] Generated using pyotp")
            return code
        except ImportError:
            logger.debug("[TOTP] pyotp not installed, using custom decoder")
        except Exception as e:
            logger.warning(f"[TOTP] pyotp error: {e}, falling back to custom")

        try:
            clean = secret.replace(" ", "").upper().rstrip("=")
            b32_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
            for ch in clean:
                if ch not in b32_chars:
                    raise ValueError(f"Invalid Base32 character: {ch}")

            bits = ""
            for ch in clean:
                bits += bin(b32_chars.index(ch))[2:].zfill(5)
            if len(bits) % 8 != 0:
                bits += "0" * (8 - (len(bits) % 8))
            secret_bytes = bytearray()
            for i in range(0, len(bits), 8):
                if i+8 <= len(bits):
                    secret_bytes.append(int(bits[i:i+8], 2))

            timestep = int(time.time()) // 30
            msg = timestep.to_bytes(8, 'big')
            h = hmac.new(bytes(secret_bytes), msg, hashlib.sha1).digest()
            offset = h[19] & 0x0f
            code = (int.from_bytes(h[offset:offset+4], 'big') & 0x7fffffff) % 1000000
            return f"{code:06d}"
        except Exception as e:
            logger.error(f"[TOTP] Custom TOTP generation failed: {e}")
            return "000000"

    def _load_instrument_master(self):
        self.token_map = {
            "NIFTY": "99926000",
            "BANKNIFTY": "99926009",
            "SENSEX": "99919000"
        }
        try:
            for symbol in ["NIFTY", "BANKNIFTY", "SENSEX"]:
                resp = self.api.searchScrip(exchange="NSE", searchtext=symbol)
                if resp and resp.get('status') and resp.get('data'):
                    for item in resp['data']:
                        if item.get('symbolname') == symbol:
                            self.token_map[symbol] = str(item.get('symboltoken'))
                            break
        except Exception as e:
            logger.warning(f"[ANGEL] Dynamic instrument load failed: {e}. Using fallback tokens.")
        logger.info(f"[ANGEL] Token map: {self.token_map}")

    def get_trading_symbol(self, symbol: str) -> str: return symbol
    def get_token(self, symbol: str) -> str:
        with self._lock: return self.token_map.get(symbol, "")

    def place_order(self, symbol: str, direction: str, quantity: int, price: float, stop_loss: float, take_profit: float) -> Optional[Dict]: pass
    def cancel_order(self, order_id: str) -> bool: pass
    def exit_position(self, symbol: str, direction: str, quantity: int) -> Optional[str]: pass
    def get_order_status(self, order_id: str) -> Optional[Dict]: pass
    def get_order_book(self) -> List[Dict]: pass
    def get_trade_book(self) -> List[Dict]: pass
    def get_margin(self) -> Dict: pass
    def get_positions(self) -> List[Dict]: pass
    def reconcile_positions(self, local_positions: List[Dict]) -> Dict: pass
    def disconnect(self):
        with self._lock:
            if self.api:
                try: self.api.logout()
                except: pass
            self._connected = False
            logger.info("[ANGEL] Disconnected")
    @property
    def is_connected(self): return self._connected
