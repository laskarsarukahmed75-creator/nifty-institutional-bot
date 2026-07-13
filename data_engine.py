import time
import threading
import logging
import urllib.request
import json
import csv
import io
from queue import Queue, Empty
from typing import Dict, Optional

from config import load_config
from utils import is_market_session, is_weekend, safe_divide

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
        self.poll_interval = config["POLL_INTERVAL_NORMAL"]
        self.assets = config["ASSETS"]
        self.yahoo_symbols = config["YAHOO_SYMBOLS"]
        self.stooq_symbols = config["STOOQ_SYMBOLS"]
        self.sources = config["DATA_SOURCES"]
        # Volatility tracker (simple: price change %)
        self.prev_close = {}  # asset -> last close
        self.atr_percent = {}  # asset -> recent ATR percentage

    def run(self):
        self.running = True
        logging.info("DataEngine started.")
        while self.running:
            if not is_market_session() or is_weekend():
                if not self.paused:
                    self.paused = True
                    logging.info("Outside market – sleep mode.")
                time.sleep(60)
                continue
            if self.paused:
                self.paused = False
                logging.info("Market active – resuming.")

            # Fetch data for all assets
            for asset in self.assets:
                if not self.running:
                    break
                data = self._fetch_asset_data(asset)
                if data:
                    self.circuit_breaker.record_data()
                    # Update volatility tracker
                    self._update_volatility(asset, data.get("close"))
                    self.data_queue.put(data)
                    self.storage_queue.put(("raw_data", data))
                else:
                    logging.debug(f"No data for {asset}")

                time.sleep(0.5)  # small delay between assets

            # Adjust polling interval based on average ATR% across assets
            avg_atr = 0.0
            count = 0
            for v in self.atr_percent.values():
                avg_atr += v
                count += 1
            if count:
                avg_atr /= count
                if avg_atr > self.config["ATR_HIGH"]:
                    self.poll_interval = self.config["POLL_INTERVAL_AGGRESSIVE"]
                elif avg_atr < self.config["ATR_LOW"]:
                    self.poll_interval = self.config["POLL_INTERVAL_LATENT"]
                else:
                    self.poll_interval = self.config["POLL_INTERVAL_NORMAL"]

            time.sleep(self.poll_interval)

        logging.info("DataEngine stopped.")

    def stop(self):
        self.running = False

    def _update_volatility(self, asset, close):
        if close is None:
            return
        prev = self.prev_close.get(asset)
        if prev is not None and prev != 0:
            change = abs(close - prev) / (prev + 1e-9)
            # Simple exponential smoothing for ATR% (simplified)
            old = self.atr_percent.get(asset, 0.0)
            self.atr_percent[asset] = 0.9 * old + 0.1 * change
        self.prev_close[asset] = close

    def _fetch_asset_data(self, asset: str) -> Optional[Dict]:
        for source in self.sources:
            if source == "yahoo":
                data = self._fetch_yahoo(asset)
            elif source == "stooq":
                data = self._fetch_stooq(asset)
            elif source == "cache":
                data = None  # not implemented
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
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read().decode('utf-8'))
                result = data.get("chart", {}).get("result")
                if not result:
                    return None
                meta = result[0].get("meta", {})
                timestamps = result[0].get("timestamp", [])
                quote = result[0].get("indicators", {}).get("quote", [{}])[0]
                if not timestamps or not quote.get("close"):
                    return None
                idx = -1
                return {
                    "open": quote["open"][idx] if quote["open"] else None,
                    "high": quote["high"][idx] if quote["high"] else None,
                    "low": quote["low"][idx] if quote["low"] else None,
                    "close": quote["close"][idx] if quote["close"] else None,
                    "volume": quote["volume"][idx] if quote["volume"] else None,
                    "time": datetime.fromtimestamp(timestamps[idx]).isoformat()
                }
        except Exception as e:
            logging.debug(f"Yahoo error for {asset}: {e}")
            return None

    def _fetch_stooq(self, asset: str) -> Optional[Dict]:
        symbol = self.stooq_symbols.get(asset)
        if not symbol:
            return None
        url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                if resp.status != 200:
                    return None
                content = resp.read().decode('utf-8')
                reader = csv.DictReader(io.StringIO(content))
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
            logging.debug(f"Stooq error for {asset}: {e}")
            return None
