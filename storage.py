import sqlite3
import json
import threading
import time
import os
from datetime import datetime, timedelta
from config import DB_PATH, WAL_MODE, RAW_RETENTION_DAYS, MINUTE_RETENTION_DAYS, FIVE_MIN_RETENTION_DAYS
from logger_setup import database_log, error_log

class Storage:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self.db_path = DB_PATH
        self._ensure_dir()
        self._init_db()
        self._start_cleaner()
        self._initialized = True

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        if WAL_MODE:
            conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            c = conn.cursor()
            # raw_data
            c.execute("""
                CREATE TABLE IF NOT EXISTS raw_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL, high REAL, low REAL, close REAL, volume INTEGER
                )
            """)
            # minute_data with unique constraint
            c.execute("""
                CREATE TABLE IF NOT EXISTS minute_data (
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL, high REAL, low REAL, close REAL, volume INTEGER,
                    PRIMARY KEY (symbol, timestamp)
                )
            """)
            # five_minute_data with unique constraint
            c.execute("""
                CREATE TABLE IF NOT EXISTS five_minute_data (
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL, high REAL, low REAL, close REAL, volume INTEGER,
                    PRIMARY KEY (symbol, timestamp)
                )
            """)
            # signals
            c.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry REAL, sl REAL, tp REAL, rr REAL,
                    confidence REAL,
                    reason TEXT,
                    layers TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
            # structures
            c.execute("""
                CREATE TABLE IF NOT EXISTS structures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    json TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            # Indexes
            for table in ["raw_data", "minute_data", "five_minute_data"]:
                c.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_symbol ON {table}(symbol)")
                c.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_time ON {table}(timestamp)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_signals_time ON signals(timestamp)")
            conn.commit()

    def save_raw(self, symbol, ohlcv):
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO raw_data (symbol, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (symbol, ohlcv["time"].isoformat(), ohlcv["open"], ohlcv["high"],
                  ohlcv["low"], ohlcv["close"], ohlcv["volume"]))
            conn.commit()

    def save_signal(self, symbol, signal):
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO signals (symbol, direction, entry, sl, tp, rr, confidence, reason, layers, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (symbol, signal.direction, signal.entry, signal.sl, signal.tp,
                  signal.rr, signal.confidence, signal.reason, json.dumps(signal.layers),
                  signal.timestamp.isoformat()))
            conn.commit()

    def save_structure(self, symbol, structure):
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO structures (symbol, json, timestamp)
                VALUES (?, ?, ?)
            """, (symbol, json.dumps(structure.to_dict()), datetime.now().isoformat()))
            conn.commit()

    def _aggregate_minutes(self):
        cutoff = (datetime.now() - timedelta(days=RAW_RETENTION_DAYS)).isoformat()
        with self._get_conn() as conn:
            c = conn.cursor()
            # Use CTE to compute aggregates with proper open/close
            c.execute("""
                WITH grouped AS (
                    SELECT
                        symbol,
                        strftime('%Y-%m-%dT%H:%M:00', timestamp) AS ts,
                        FIRST_VALUE(open) OVER (PARTITION BY symbol, strftime('%Y-%m-%dT%H:%M:00', timestamp) ORDER BY timestamp) AS open,
                        MAX(high) OVER (PARTITION BY symbol, strftime('%Y-%m-%dT%H:%M:00', timestamp)) AS high,
                        MIN(low) OVER (PARTITION BY symbol, strftime('%Y-%m-%dT%H:%M:00', timestamp)) AS low,
                        FIRST_VALUE(close) OVER (PARTITION BY symbol, strftime('%Y-%m-%dT%H:%M:00', timestamp) ORDER BY timestamp DESC) AS close,
                        SUM(volume) OVER (PARTITION BY symbol, strftime('%Y-%m-%dT%H:%M:00', timestamp)) AS volume
                    FROM raw_data
                    WHERE timestamp < ?
                )
                INSERT OR REPLACE INTO minute_data (symbol, timestamp, open, high, low, close, volume)
                SELECT DISTINCT symbol, ts, open, high, low, close, volume
                FROM grouped
                WHERE ts IS NOT NULL
            """, (cutoff,))
            conn.commit()
            c.execute("DELETE FROM raw_data WHERE timestamp < ?", (cutoff,))
            conn.commit()

    def _aggregate_five_minutes(self):
        cutoff = (datetime.now() - timedelta(days=MINUTE_RETENTION_DAYS)).isoformat()
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                WITH grouped AS (
                    SELECT
                        symbol,
                        strftime('%Y-%m-%dT%H:%M:00', timestamp) AS ts,
                        FIRST_VALUE(open) OVER (PARTITION BY symbol, strftime('%Y-%m-%dT%H:%M:00', timestamp) ORDER BY timestamp) AS open,
                        MAX(high) OVER (PARTITION BY symbol, strftime('%Y-%m-%dT%H:%M:00', timestamp)) AS high,
                        MIN(low) OVER (PARTITION BY symbol, strftime('%Y-%m-%dT%H:%M:00', timestamp)) AS low,
                        FIRST_VALUE(close) OVER (PARTITION BY symbol, strftime('%Y-%m-%dT%H:%M:00', timestamp) ORDER BY timestamp DESC) AS close,
                        SUM(volume) OVER (PARTITION BY symbol, strftime('%Y-%m-%dT%H:%M:00', timestamp)) AS volume
                    FROM minute_data
                    WHERE timestamp < ?
                )
                INSERT OR REPLACE INTO five_minute_data (symbol, timestamp, open, high, low, close, volume)
                SELECT DISTINCT symbol, ts, open, high, low, close, volume
                FROM grouped
                WHERE ts IS NOT NULL
            """, (cutoff,))
            conn.commit()
            c.execute("DELETE FROM minute_data WHERE timestamp < ?", (cutoff,))
            conn.commit()

    def _clean_old_data(self):
        cutoff = (datetime.now() - timedelta(days=FIVE_MIN_RETENTION_DAYS)).isoformat()
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM five_minute_data WHERE timestamp < ?", (cutoff,))
            c.execute("DELETE FROM signals WHERE timestamp < ?", (cutoff,))
            c.execute("DELETE FROM structures WHERE timestamp < ?", (cutoff,))
            conn.commit()

    def _cleanup_task(self):
        self._aggregate_minutes()
        self._aggregate_five_minutes()
        self._clean_old_data()

    def _start_cleaner(self):
        def cleaner_loop():
            while True:
                now = datetime.now()
                next_run = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                sleep_seconds = (next_run - now).total_seconds()
                time.sleep(sleep_seconds)
                self._cleanup_task()
        threading.Thread(target=cleaner_loop, daemon=True).start()
