import time
import threading
import logging
import urllib.request
import urllib.error
import json
import csv
import io
from queue import Queue, Empty
from typing import Dict, Optional
from datetime import datetime
import random

from utils import is_market_session, is_weekend, generate_mock_price, calculate_institutional_options_view

# --- Helper: fetch with headers and retry ---
def fetch_url_with_retry(url, headers=None, timeout=10, retries=3):
    """Fetch URL with retry and custom headers."""
    if headers is None:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/json,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        }
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return resp.read()
                else:
                    logging.debug(f"Attempt {attempt+1}: status {resp.status}")
        except urllib.error.URLError as e:
            logging.debug(f"Attempt {attempt+1} failed: {e}")
            time.sleep(1 * (attempt+1))  # exponential backoff
    return None

class CircuitBreaker:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.last_data_time = time.time()
        self.tripped = False
        self.lock = threading.Lock()

    def record_data(self):
        with self.lock:
            self.last_data_time = time.time()
            if self.tripped:
                self.tripped = False
                logging.info("Circuit breaker reset.")

    def check(self):
        with self.lock:
            if time.time() - self.last_data_time > self.timeout:
                if not self.tripped:
                    self.tripped = True
                    logging.warning("Circuit breaker tripped.")
                return True
            return False

class DataEngine(threading.Thread):
    def __init__(self, config, data_queue: Queue, storage_queue: Queue):
        super().__init__(daemon=True)
        self.config = config
        self.data_queue = data_queue
        self.storage_queue = storage_queue
        self.running = False
        self.paused = False
        self.circuit_breaker = CircuitBreaker(timeout=config["CIRCUIT_BREAKER_TIMEOUT"])
        self.poll_interval = config["POLL_INTERVAL_AGGRESSIVE"]
        self.assets = config["ASSETS"]
        self.yahoo_symbols = config["YAHOO_SYMBOLS"]
        self.stooq_symbols = config["STOOQ_SYMBOLS"]
        self.sources = config["DATA_SOURCES"]  # ["yahoo", "stooq", "cache"]
        self.prev_close = {}
        self.atr_percent = {}
        self.use_mock = False
        self.mock_data = {}
        self.mock_idx = {}

    def run(self):
        self.running = True
        logging.info("DataEngine started.")
        while self.running:
            if not hasattr(self, "_session_log") or time.time() - self._session_log > 60:
                self._session_log = time.time()
                logging.info(f"Session check: market_open={is_market_session()}, weekend={is_weekend()}")

            if not is_market_session() or is_weekend():
                if not self.paused:
                    self.paused = True
                    logging.info("Outside market – entering mock data mode (continuous).")
                for asset in self.assets:
                    if not self.running:
                        break
                    mock = self._get_mock_data(asset)
                    if mock:
                        self.data_queue.put(mock)
                        self.storage_queue.put(("raw_data", mock))
                time.sleep(2)
                continue

            if self.paused:
                self.paused = False
                logging.info("Market active – resuming real data ingestion.")

            for asset in self.assets:
                if not self.running:
                    break
                data = self._fetch_asset_data(asset)
                if data:
                    self.circuit_breaker.record_data()
                    self._update_volatility(asset, data.get("close"))
                    options_view = calculate_institutional_options_view(data["close"])
                    data.update(options_view)
                    self.data_queue.put(data)
                    self.storage_queue.put(("raw_data", data))
                else:
                    # If we still get no data, switch to mock after trying all sources
                    if not self.use_mock:
                        logging.warning(f"No data for {asset} – initializing mock fallback")
                        self.use_mock = True
                    mock = self._get_mock_data(asset)
                    if mock:
                        self.data_queue.put(mock)
                        self.storage_queue.put(("raw_data", mock))
                time.sleep(0.5)  # short delay between assets

            # Adaptive polling: keep at 2 seconds to avoid rate limits
            self.poll_interval = 2
            time.sleep(self.poll_interval)

        logging.info("DataEngine stopped.")

    def stop(self):
        self.running = False

    def _init_mock_data(self, asset):
        if asset not in self.mock_data:
            self.mock_data[asset] = generate_mock_price(base_price=24600 + random.randint(-200, 200), steps=2000)
            self.mock_idx[asset] = 0
            logging.info(f"Mock data feed active for {asset}")

    def _get_mock_data(self, asset):
        if asset not in self.mock_data:
            self._init_mock_data(asset)
        idx = self.mock_idx.get(asset, 0)
        prices = self.mock_data.get(asset, [])
        if not prices or idx >= len(prices):
            self._init_mock_data(asset)
            idx = 0
        price = prices[idx]
        self.mock_idx[asset] = idx + 1
        options_view = calculate_institutional_options_view(price)
        volume_spike = random.choice([1.0, 1.1, 2.1, 3.4]) if (idx % 18 == 0) else 1.0
        base_volume = int(random.randint(600000, 1200000) * volume_spike)
        mock_packet = {
            "asset": asset,
            "open": price,
            "high": price * (1 + random.uniform(0, 0.0025)),
            "low": price * (1 - random.uniform(0, 0.0025)),
            "close": price,
            "volume": base_volume,
            "source": "mock_gift_nifty",
            "timestamp": time.time()
        }
        mock_packet.update(options_view)
        return mock_packet

    def _update_volatility(self, asset, close):
        if close is None:
            return
        prev = self.prev_close.get(asset)
        if prev is not None and prev != 0:
            change = abs(close - prev) / (abs(prev) + 1e-9)
            old = self.atr_percent.get(asset, 0.0)
            self.atr_percent[asset] = 0.9 * old + 0.1 * change
        self.prev_close[asset] = close

    def _fetch_asset_data(self, asset: str) -> Optional[Dict]:
        # Try sources in order; if one returns data, return it.
        for source in self.sources:
            if source == "yahoo":
                data = self._fetch_yahoo(asset)
            elif source == "stooq":
                data = self._fetch_stooq(asset)
            elif source == "cache":
                data = None
            else:
                data = None
            if data:
                data["source"] = source
                data["asset"] = asset
                data["timestamp"] = time.time()
                return data
        return None

    def _fetch_yahoo(self, asset: str) -> Optional[Dict]:
        symbol = self.yahoo_symbols.get(asset)
        if not symbol:
            return None
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
        # Headers to mimic a real browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': 'https://finance.yahoo.com',
            'Referer': 'https://finance.yahoo.com/',
        }
        content = fetch_url_with_retry(url, headers=headers, timeout=10, retries=3)
        if not content:
            return None
        try:
            data = json.loads(content.decode('utf-8'))
            result = data.get("chart", {}).get("result")
            if not result:
                return None
            timestamps = result[0].get("timestamp", [])
            quote = result[0].get("indicators", {}).get("quote", [{}])[0]
            if not timestamps or not quote.get("close"):
                return None
            idx = -1
            return {
                "open": quote["open"][idx],
                "high": quote["high"][idx],
                "low": quote["low"][idx],
                "close": quote["close"][idx],
                "volume": quote["volume"][idx],
                "time": datetime.fromtimestamp(timestamps[idx]).isoformat()
            }
        except Exception as e:
            logging.debug(f"Yahoo parse error for {asset}: {e}")
            return None

    def _fetch_stooq(self, asset: str) -> Optional[Dict]:
        symbol = self.stooq_symbols.get(asset)
        if not symbol:
            return None
        url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        content = fetch_url_with_retry(url, headers=headers, timeout=10, retries=3)
        if not content:
            return None
        try:
            reader = csv.DictReader(io.StringIO(content.decode('utf-8')))
            rows = list(reader)
            if not rows:
                return None
            last = rows[-1]
            return {
                "open": float(last.get("Open", 0)),
                "high": float(last.get("High", 0)),
                "low": float(last.get("Low", 0)),
                "close": float(last.get("Close", 0)),
                "volume": float(last.get("Volume", 0)),
                "time": f"{last['Date']} {last['Time']}"
            }
        except Exception as e:
            logging.debug(f"Stooq parse error for {asset}: {e}")
            return None
