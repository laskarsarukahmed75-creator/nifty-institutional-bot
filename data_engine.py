import time
import threading
import os
from datetime import datetime
from config import SMART_API_KEY, SMART_CLIENT_ID, SMART_PASSWORD
from smartapi import SmartConnect
import yfinance as yf
import requests
from config import DATA_SOURCES, DATA_INTERVAL
from cache import cache_get, cache_set
from retry import retry
from logger_setup import system_log, error_log

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
# Initialize SmartAPI Connection
try:
    smart_api = SmartConnect(api_key=SMART_API_KEY)
    session_data = smart_api.generate_session(client_id=SMART_CLIENT_ID, password=SMART_PASSWORD)
except Exception as e:
    error_log.error(f"Angel One Login Failed: {e}")

def _fetch_yahoo(symbol):
def _fetch_from_smartapi(symbol):
    try:
        # Angel One SmartAPI से 1 मिनट का लाइव डेटा लेना
        response = smart_api.getCandleData(
            exchange="NSE",
            symboltoken="YOUR_TOKEN_HERE",
            interval="ONE_MINUTE",
            fromdate=datetime.now().strftime("%Y-%m-%d 09:15"),
            todate=datetime.now().strftime("%Y-%m-%d %H:%M")
        )
        if response['status'] and response['data']:
            latest = response['data'][-1]  # सबसे आखिरी कैंडल निकालना
            return {
                "time": datetime.strptime(latest[0], "%Y-%m-%dT%H:%M:%S%z"),
                "open": float(latest[1]),
                "high": float(latest[2]),
                "low": float(latest[3]),
                "close": float(latest[4]),
                "volume": int(latest[5])
            }
        else:
            raise ValueError(response.get('message', 'No data returned'))
    except Exception as e:
        error_log.error(f"SmartAPI failed for {symbol}: {e}")
        cached = cache_get(f"data_{symbol}")
        if cached:
            error_log.info(f"Using cached data for {symbol}")
            return cached
        raise ValueError(f"SmartAPI failed and no cache available for {symbol}")

def fetch_live_data():
    for symbol in DATA_SOURCES.keys():
        try:
            ohlcv = _fetch_from_smartapi(symbol)
            data_store.update(symbol, ohlcv)
            cache_set(f"data_{symbol}", ohlcv)
        except Exception as e:
            error_log.error(f"Error fetching {symbol}: {e}")

def data_task():
    fetch_live_data()
