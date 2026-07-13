import sqlite3
import threading
import logging
import time
import os
import json
from queue import Queue, Empty
from typing import Dict

class StorageController(threading.Thread):
    def __init__(self, db_path: str):
        super().__init__(daemon=True)
        self.db_path = db_path
        self.running = False
        self.queue = Queue(maxsize=100)
        self.last_prune = time.time()
        self.last_vacuum = time.time()
        self.prune_interval = 86400
        self.vacuum_interval = 604800
        self.prune_days = 120
        self.conn = None
        self.lock = threading.Lock()

    def initialize_db(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS candles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT, start_time INTEGER, open REAL, high REAL,
                low REAL, close REAL, volume REAL, timestamp REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS structures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT, candle_id INTEGER, score REAL,
                structure_json TEXT, timestamp REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT UNIQUE, asset TEXT, direction TEXT,
                entry REAL, sl REAL, tp REAL, rr REAL, win_prob REAL,
                score REAL, timestamp REAL, signal_json TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT, data_json TEXT, timestamp REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pre_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT, timestamp REAL, score REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT, message TEXT, timestamp REAL
            )
        """)
        conn.commit()
        conn.close()
        logging.info("Database initialised.")

    def run(self):
        self.running = True
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        logging.info("Storage thread started.")
        while self.running:
            try:
                item = self.queue.get(timeout=0.5)
            except Empty:
                self._maybe_prune()
                continue
            if item is None:
                continue
            self._process(item)
        self.conn.close()
        logging.info("Storage stopped.")

    def stop(self):
        self.running = False

    def _process(self, item):
        typ, data = item
        try:
            if typ == "candle":
                self._insert_candle(data)
            elif typ == "structure":
                self._insert_structure(data)
            elif typ == "signal":
                self._insert_signal(data)
            elif typ == "raw_data":
                self._insert_raw(data)
            elif typ == "pre_alert":
                self._insert_pre_alert(data)
            else:
                logging.warning(f"Unknown storage type: {typ}")
        except Exception as e:
            logging.error(f"Storage insert error: {e}")

    def _insert_candle(self, candle):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """INSERT INTO candles
                   (asset, start_time, open, high, low, close, volume, timestamp)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (candle["asset"], candle["start_time"], candle["open"], candle["high"],
                 candle["low"], candle["close"], candle["volume"], candle.get("timestamp", time.time()))
            )
            self.conn.commit()

    def _insert_structure(self, structure):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO structures (asset, candle_id, score, structure_json, timestamp) VALUES (?,?,?,?,?)",
                (structure.get("asset"), structure.get("candle_id", 0), structure.get("score", 0),
                 json.dumps(structure), time.time())
            )
            self.conn.commit()

    def _insert_signal(self, signal):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO signals
                   (trade_id, asset, direction, entry, sl, tp, rr, win_prob, score, timestamp, signal_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (signal["trade_id"], signal["asset"], signal["direction"], signal["entry"],
                 signal["sl"], signal["tp"], signal["rr"], signal["win_prob"], signal["score"],
                 time.time(), json.dumps(signal))
            )
            self.conn.commit()

    def _insert_raw(self, data):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO raw_data (asset, data_json, timestamp) VALUES (?,?,?)",
                (data.get("asset"), json.dumps(data), time.time())
            )
            self.conn.commit()

    def _insert_pre_alert(self, alert):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO pre_alerts (asset, timestamp, score) VALUES (?,?,?)",
                (alert["asset"], alert["time"], alert["score"])
            )
            self.conn.commit()

    def _maybe_prune(self):
        now = time.time()
        if now - self.last_prune >= self.prune_interval:
            self._prune_old()
            self.last_prune = now
        if now - self.last_vacuum >= self.vacuum_interval:
            self._vacuum()
            self.last_vacuum = now

    def _prune_old(self):
        cutoff = time.time() - (self.prune_days * 86400)
        logging.info(f"Pruning data older than {self.prune_days} days")
        tables = ["candles", "structures", "raw_data", "pre_alerts", "logs"]
        with self.lock:
            cur = self.conn.cursor()
            for table in tables:
                deleted = 1
                while deleted > 0:
                    cur.execute(f"DELETE FROM {table} WHERE timestamp < ? LIMIT 5000", (cutoff,))
                    deleted = cur.rowcount
                    self.conn.commit()
                    if deleted:
                        logging.debug(f"Pruned {deleted} rows from {table}")
            self.conn.commit()

    def _vacuum(self):
        logging.info("Running VACUUM...")
        with self.lock:
            self.conn.execute("VACUUM")
            self.conn.commit()
