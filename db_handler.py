# db_handler.py
import sqlite3
import json
import datetime
from typing import Optional, List, Dict, Any

DB_PATH = "niftyinstitutionalbot.db"

class DBHandler:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self):
        with sqlite3.connect(self.db_path) as conn:
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
            conn.commit()

    def save_vector(self, symbol: str, swing_high: float, swing_low: float,
                    length: float, pivot_0_5: float,
                    parent_swing_high: Optional[float] = None,
                    parent_swing_low: Optional[float] = None,
                    parent_length: Optional[float] = None,
                    parent_completed: Optional[bool] = None) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO market_vectors
                (symbol, swing_high, swing_low, length, pivot_0_5,
                 parent_swing_high, parent_swing_low, parent_length, parent_completed, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (symbol, swing_high, swing_low, length, pivot_0_5,
                  parent_swing_high, parent_swing_low, parent_length,
                  1 if parent_completed else 0 if parent_completed is not None else None,
                  datetime.datetime.utcnow().isoformat()))
            conn.commit()

    def log_trade(self, symbol: str, side: str, entry: float,
                  sl: float, tp: float, status: str = "OPEN") -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trade_logs
                (symbol, side, entry, sl, tp, status, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (symbol, side, entry, sl, tp, status,
                  datetime.datetime.utcnow().isoformat()))
            conn.commit()

    def update_trade_status(self, trade_id: int, status: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE trade_logs SET status = ? WHERE id = ?", (status, trade_id))
            conn.commit()

    def get_state(self, key: str, default: Any = None) -> Any:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM session_state WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return default

    def set_state(self, key: str, value: Any) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO session_state (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, json.dumps(value), datetime.datetime.utcnow().isoformat()))
            conn.commit()
