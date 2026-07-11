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

def _fetch_yahoo(symbol):
    ticker = yf.Ticker(symbol, session=data_store.session)
    hist = ticker.history(period="1d", interval="1m")
    if hist.empty:
        raise ValueError("Empty data")
    latest = hist.iloc[-1]
    return {
        "time": latest.name.to_pydatetime(),
        "open": float(latest["Open"]),
        "high": float(latest["High"]),
        "low": float(latest["Low"]),
        "close": float(latest["Close"]),
        "volume": int(latest["Volume"])
    }

def _fetch_stooq(symbol):
    url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
    resp = data_store.session.get(url, timeout=5)
    if resp.status_code != 200:
        raise ValueError("Stooq error")
    lines = resp.text.strip().split('\n')
    if len(lines) < 2:
        raise ValueError("No data from Stooq")
    last = lines[-1].split(',')
    if len(last) < 7:
        raise ValueError("Invalid CSV format")
    dt_str = last[0] + ' ' + last[1]
    dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
    return {
        "time": dt,
        "open": float(last[2]),
        "high": float(last[3]),
        "low": float(last[4]),
        "close": float(last[5]),
        "volume": int(float(last[6]))
    }

def _fetch_twelve(symbol):
    apikey = os.environ.get("TWELVE_API_KEY", "")
    if not apikey:
        raise ValueError("No API key for TwelveData")
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=1min&outputsize=1&apikey={apikey}"
    resp = data_store.session.get(url, timeout=5)
    if resp.status_code != 200:
        raise ValueError("TwelveData error")
    data = resp.json()
    if "values" not in data or not data["values"]:
        raise ValueError("No data from TwelveData")
    last = data["values"][0]
    dt = datetime.fromisoformat(last["datetime"])
    return {
        "time": dt,
        "open": float(last["open"]),
        "high": float(last["high"]),
        "low": float(last["low"]),
        "close": float(last["close"]),
        "volume": int(last["volume"])
    }

@retry(max_attempts=3, backoff=2)
def _fetch_data(symbol, yf_symbol, stooq_symbol, twelve_symbol):
    try:
        return _fetch_yahoo(yf_symbol)
    except Exception as e:
        error_log.warning(f"Yahoo failed for {symbol}: {e}")
        try:
            return _fetch_stooq(stooq_symbol)
        except Exception as e2:
            error_log.warning(f"Stooq failed for {symbol}: {e2}")
            try:
                return _fetch_twelve(twelve_symbol)
            except Exception as e3:
                error_log.warning(f"TwelveData failed for {symbol}: {e3}")
                cached = cache_get(f"data_{symbol}")
                if cached:
                    error_log.info(f"Using cached data for {symbol}")
                    return cached
                raise ValueError(f"All data sources failed for {symbol}")

def fetch_live_data():
    for symbol, info in DATA_SOURCES.items():
        try:
            ohlcv = _fetch_data(symbol, info["yfinance"], info["stooq"], info["twelve"])
            data_store.update(symbol, ohlcv)
            cache_set(f"data_{symbol}", ohlcv)
        except Exception as e:
            error_log.error(f"Error fetching {symbol}: {e}")

def data_task():
    fetch_live_data()
