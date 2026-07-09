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
        """Create all required tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # trade_logs table
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
            # market_vectors table – now includes parent vector info
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
                    parent_completed INTEGER,   -- 1 if completed, 0 otherwise
                    timestamp TEXT NOT NULL
                )
            """)
            # session_state table (key-value store)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS session_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    # ---------- Vectors ----------
    def save_vector(self, symbol: str, swing_high: float, swing_low: float,
                    length: float, pivot_0_5: float,
                    parent_swing_high: Optional[float] = None,
                    parent_swing_low: Optional[float] = None,
                    parent_length: Optional[float] = None,
                    parent_completed: Optional[bool] = None) -> None:
        """Save a detected swing vector and its parent vector info."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO market_vectors
                (symbol, swing_high, swing_low, length, pivot_0_5,
                 parent_swing_high, parent_swing_low, parent_length,
                 parent_completed, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (symbol, swing_high, swing_low, length, pivot_0_5,
                  parent_swing_high, parent_swing_low, parent_length,
                  1 if parent_completed else 0 if parent_completed is not None else None,
                  datetime.datetime.utcnow().isoformat()))
            conn.commit()

    def fetch_historical_vectors(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve the most recent vectors for a symbol."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, symbol, swing_high, swing_low, length, pivot_0_5,
                       parent_swing_high, parent_swing_low, parent_length,
                       parent_completed, timestamp
                FROM market_vectors
                WHERE symbol = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (symbol, limit))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    # ---------- Trade Logs ----------
    def log_trade(self, symbol: str, side: str, entry: float,
                  sl: float, tp: float, status: str = "OPEN") -> None:
        """Log a trade execution."""
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
        """Update the status of an existing trade."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE trade_logs
                SET status = ?
                WHERE id = ?
            """, (status, trade_id))
            conn.commit()

    # ---------- Session State ----------
    def get_state(self, key: str, default: Any = None) -> Any:
        """Retrieve a state value (JSON stored)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM session_state WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return default

    def set_state(self, key: str, value: Any) -> None:
        """Store a state value (JSON serialised)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO session_state (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, json.dumps(value), datetime.datetime.utcnow().isoformat()))
            conn.commit()
