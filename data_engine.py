# data_engine.py (पूरा फिक्स्ड + ऑटो-फॉलबैक)

import time
import threading
import os
from datetime import datetime
import requests
import pyotp

from config import SMART_API_KEY, SMART_CLIENT_ID, SMART_PASSWORD, DATA_SOURCES
from smartapi import SmartConnect
from cache import cache_get, cache_set
from logger_setup import system_log, error_log

# ---------------- DataStore Class ----------------
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

# ---------------- SmartAPI Connection (Auto-Detect client_id/clientCode) ----------------
smart_api = None
smart_api_lock = threading.Lock()

def init_smartapi():
    """Initialize SmartAPI with TOTP – auto-fallback for client_id vs clientCode."""
    global smart_api
    with smart_api_lock:
        try:
            # 1. Get TOTP secret
            totp_secret = os.getenv("TOTP_SECRET")
            if not totp_secret:
                raise ValueError("TOTP_SECRET environment variable missing.")
            current_totp = pyotp.TOTP(totp_secret.strip()).now()
            system_log.info(f"TOTP generated (length: {len(current_totp)})")

            # 2. Create SmartConnect object
            obj = SmartConnect(api_key=SMART_API_KEY)

            # 3. Try login with 'client_id' (newer versions)
            try:
                session_data = obj.generate_session(
                    client_id=SMART_CLIENT_ID,
                    password=SMART_PASSWORD,
                    totp=current_totp
                )
                system_log.info("Login successful with 'client_id' parameter.")
            except TypeError as e:
                # If 'client_id' is not accepted, fallback to 'clientCode' (older versions)
                if "client_id" in str(e) or "unexpected keyword" in str(e):
                    system_log.warning("'client_id' not accepted. Falling back to 'clientCode'.")
                    session_data = obj.generate_session(
                        clientCode=SMART_CLIENT_ID,
                        password=SMART_PASSWORD,
                        totp=current_totp
                    )
                    system_log.info("Login successful with 'clientCode' parameter.")
                else:
                    raise  # some other TypeError, re-raise

            # 4. Set access token
            obj.setAccessToken(session_data['access_token'])
            smart_api = obj
            system_log.info("SmartAPI fully initialized and ready.")
            return obj

        except Exception as e:
            error_log.error(f"SmartAPI init failed: {e}")
            smart_api = None
            raise

# Initialize at startup
try:
    init_smartapi()
except Exception as e:
    error_log.error(f"Startup SmartAPI error: {e}")
    smart_api = None

# ---------------- Data Fetching ----------------
def _fetch_from_smartapi(symbol):
    global smart_api
    if smart_api is None:
        system_log.warning("SmartAPI not available. Re-initializing...")
        init_smartapi()

    try:
        token = DATA_SOURCES.get(symbol)
        if not token:
            raise ValueError(f"No token for symbol: {symbol}")

        params = {
            "exchange": "NSE",
            "symboltoken": str(token),
            "interval": "FIVE_MINUTE",   # या 'ONE_MINUTE' as needed
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
            error_msg = response.get('message', 'No data') if response else 'Empty response'
            raise ValueError(f"API Error: {error_msg}")

    except Exception as e:
        error_log.error(f"SmartAPI failed for {symbol}: {e}")

        # Try cache
        cached = cache_get(f"data_{symbol}")
        if cached:
            error_log.info(f"Using cached data for {symbol}")
            return cached

        # If token expired, re-login and retry once
        if "Token missing" in str(e) or "AG8003" in str(e):
            system_log.warning("Token missing or expired. Re-login...")
            init_smartapi()
            return _fetch_from_smartapi(symbol)   # retry once

        raise ValueError(f"SmartAPI failed and no cache available for {symbol}")

def fetch_live_data():
    for symbol in DATA_SOURCES.keys():
        try:
            ohlcv = _fetch_from_smartapi(symbol)
            data_store.update(symbol, ohlcv)
            cache_set(f"data_{symbol}", ohlcv)
            system_log.info(f"Data updated for {symbol}")
        except Exception as e:
            error_log.error(f"Error fetching {symbol}: {e}")

def data_task():
    fetch_live_data()
