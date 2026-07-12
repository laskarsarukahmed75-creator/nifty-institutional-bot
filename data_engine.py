# data_engine.py – FINAL VERSION (Dynamic Import + TOTP + Auto-Fallback)

import time
import threading
import os
from datetime import datetime
import requests
import pyotp

# ---------- SUPERSMART IMPORT (Try both possible names) ----------
SmartConnect = None
try:
    from smartapi import SmartConnect as sc1
    SmartConnect = sc1
    print("✅ Imported SmartConnect from 'smartapi'")
except ImportError:
    try:
        from SmartApi import SmartConnect as sc2
        SmartConnect = sc2
        print("✅ Imported SmartConnect from 'SmartApi'")
    except ImportError:
        # If both fail, raise a clear error
        raise ImportError(
            "❌ Neither 'smartapi' nor 'SmartApi' module found.\n"
            "Please run: pip install smartapi-python --upgrade --no-cache-dir"
        )

# ---------- Config ----------
from config import SMART_API_KEY, SMART_CLIENT_ID, SMART_PASSWORD, DATA_SOURCES
from cache import cache_get, cache_set
from logger_setup import system_log, error_log

# ---------------- DataStore ----------------
class DataStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {symbol: {"time": None, "open": 0.0, "high": 0.0,
                              "low": 0.0, "close": 0.0, "volume": 0}
                     for symbol in DATA_SOURCES}
        self.session = requests.Session()
        self.last_success = {}

    def update(self, symbol, ohlcv):
        with self.lock:
            self.data[symbol] = ohlcv
            self.last_success[symbol] = time.time()

    def get(self, symbol):
        with self.lock:
            return self.data.get(symbol, {})

    def get_all(self):
        with self.lock:
            return self.data.copy()

data_store = DataStore()

# ---------------- SmartAPI Connection ----------------
smart_api = None
smart_api_lock = threading.Lock()

def init_smartapi():
    global smart_api
    with smart_api_lock:
        try:
            # TOTP
            totp_secret = os.getenv("TOTP_SECRET")
            if not totp_secret:
                raise ValueError("TOTP_SECRET not set in environment.")
            current_totp = pyotp.TOTP(totp_secret.strip()).now()
            system_log.info(f"TOTP generated (length: {len(current_totp)})")

            obj = SmartConnect(api_key=SMART_API_KEY)

            # Try client_id first, fallback to clientCode
            try:
                session_data = obj.generate_session(
                    client_id=SMART_CLIENT_ID,
                    password=SMART_PASSWORD,
                    totp=current_totp
                )
                system_log.info("Login with 'client_id' succeeded.")
            except TypeError:
                system_log.warning("'client_id' failed, trying 'clientCode'...")
                session_data = obj.generate_session(
                    clientCode=SMART_CLIENT_ID,
                    password=SMART_PASSWORD,
                    totp=current_totp
                )
                system_log.info("Login with 'clientCode' succeeded.")

            obj.setAccessToken(session_data['access_token'])
            smart_api = obj
            system_log.info("✅ SmartAPI fully initialized.")
            return obj

        except Exception as e:
            error_log.error(f"❌ SmartAPI init error: {e}")
            smart_api = None
            raise

# Try to login at startup
try:
    init_smartapi()
except Exception as e:
    error_log.error(f"Startup error: {e}")
    smart_api = None

# ---------------- Fetch Function ----------------
def _fetch_from_smartapi(symbol):
    global smart_api
    if smart_api is None:
        system_log.warning("SmartAPI not available, re-initializing...")
        init_smartapi()

    try:
        token = DATA_SOURCES.get(symbol)
        if not token:
            raise ValueError(f"No token for {symbol}")

        params = {
            "exchange": "NSE",
            "symboltoken": str(token),
            "interval": "FIVE_MINUTE",
            "fromdate": datetime.now().strftime("%Y-%m-%d 09:15"),
            "todate": datetime.now().strftime("%Y-%m-%d %H:%M")
        }

        response = smart_api.getCandleData(params)
        if response and response.get('status') and response.get('data'):
            latest = response['data'][-1]
            return {
                "time": datetime.strptime(latest[0], "%Y-%m-%dT%H:%M:%S%z"),
                "open": float(latest[1]),
                "high": float(latest[2]),
                "low": float(latest[3]),
                "close": float(latest[4]),
                "volume": int(latest[5])
            }
        else:
            msg = response.get('message', 'No data') if response else 'Empty'
            raise ValueError(f"API error: {msg}")

    except Exception as e:
        error_log.error(f"Fetch failed for {symbol}: {e}")
        cached = cache_get(f"data_{symbol}")
        if cached:
            error_log.info(f"Using cached data for {symbol}")
            return cached
        # Token expiry recovery
        if "Token missing" in str(e) or "AG8003" in str(e):
            system_log.warning("Token expired – re-login...")
            init_smartapi()
            return _fetch_from_smartapi(symbol)  # retry once
        raise

def fetch_live_data():
    for symbol in DATA_SOURCES.keys():
        try:
            ohlcv = _fetch_from_smartapi(symbol)
            data_store.update(symbol, ohlcv)
            cache_set(f"data_{symbol}", ohlcv)
            system_log.info(f"✅ Data updated for {symbol}")
        except Exception as e:
            error_log.error(f"❌ Error for {symbol}: {e}")

def data_task():
    fetch_live_data()
