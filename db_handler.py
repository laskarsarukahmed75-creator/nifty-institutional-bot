# db_handler.py
import sqlite3
import json
import datetime
import threading
import time
import logging
from typing import Optional, List, Dict, Any
import os

DB_PATH = os.environ.get("DB_PATH", "/app/data/niftyinstitutionalbot.db")

logger = logging.getLogger("DBHandler")

class DBHandler:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_tables()
        self._start_cleaner()

    def _get_conn(self):
        return sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30
        )

    def _init_tables(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry REAL NOT NULL,
                    sl REAL NOT NULL,
                    tp REAL NOT NULL,
                    status TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS market_vectors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    swing_high REAL NOT NULL,
                    swing_low REAL NOT NULL,
                    length REAL NOT NULL,
                    pivot_0_5 REAL NOT NULL,
                    lock_point REAL,
                    structure_reset INTEGER DEFAULT 0,
                    parent_swing_high REAL,
                    parent_swing_low REAL,
                    parent_length REAL,
                    parent_completed INTEGER,
                    timestamp TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS session_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price REAL,
                    status TEXT,
                    timestamp TEXT
                )
            """)
            conn.commit()
            logger.info("Database tables initialised.")

    def save_vector(self, symbol: str, swing_high: float, swing_low: float,
                    length: float, pivot_0_5: float,
                    lock_point: Optional[float] = None,
                    structure_reset: bool = False,
                    parent_high: Optional[float] = None,
                    parent_low: Optional[float] = None,
                    parent_len: Optional[float] = None,
                    parent_completed: Optional[bool] = None) -> None:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO market_vectors
                (symbol, swing_high, swing_low, length, pivot_0_5,
                 lock_point, structure_reset,
                 parent_swing_high, parent_swing_low, parent_length, parent_completed,
                 timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (symbol, swing_high, swing_low, length, pivot_0_5,
                  lock_point, 1 if structure_reset else 0,
                  parent_high, parent_low, parent_len,
                  1 if parent_completed else 0 if parent_completed is not None else None,
                  datetime.datetime.now(datetime.timezone.utc).isoformat()))
            conn.commit()

    def log_trade(self, symbol: str, side: str, entry: float,
                  sl: float, tp: float, status: str = "OPEN") -> None:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trade_logs
                (symbol, side, entry, sl, tp, status, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (symbol, side, entry, sl, tp, status,
                  datetime.datetime.now(datetime.timezone.utc).isoformat()))
            conn.commit()

    def update_trade_status(self, trade_id: int, status: str) -> None:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE trade_logs SET status = ? WHERE id = ?", (status, trade_id))
            conn.commit()

    def get_state(self, key: str, default: Any = None) -> Any:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM session_state WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return default

    def set_state(self, key: str, value: Any) -> None:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO session_state (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, json.dumps(value), datetime.datetime.now(datetime.timezone.utc).isoformat()))
            conn.commit()

    def _clean_old_data(self):
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=120)).isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM market_vectors WHERE timestamp < ?", (cutoff,))
            cursor.execute("DELETE FROM trade_logs WHERE timestamp < ?", (cutoff,))
            conn.commit()
            logger.info(f"Cleaned data older than 120 days.")

    def _start_cleaner(self):
        def cleaner_loop():
            while True:
                now = datetime.datetime.now(datetime.timezone.utc)
                next_run = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
                sleep_seconds = (next_run - now).total_seconds()
                time.sleep(sleep_seconds)
                self._clean_old_data()
        threading.Thread(target=cleaner_loop, daemon=True).start()
