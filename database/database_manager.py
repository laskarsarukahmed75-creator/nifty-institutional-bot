# ============================================================================
# START MODULE: DatabaseManager
# Version: 1.0.0
# Dependencies: sqlite3, threading, config
# Public Functions: save_signal, save_position, load_active_positions, record_trade, log_websocket_event, log_health
# Private Functions: _init_db, _get_conn
# Upgrade Notes: Replace with PostgreSQL/Redis by implementing same interface.
# ============================================================================

import sqlite3
import threading
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import contextmanager
from functools import wraps
import time

from ..config.config import Config

def retry_on_lock(max_retries=3, delay=0.1):
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(self, *args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e) and attempt < max_retries-1:
                        time.sleep(delay * (2 ** attempt))
                        continue
                    raise
            return None
        return wrapper
    return decorator

class DatabaseManager:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or Config.DB_FILE
        self._lock = threading.RLock()
        self._init_db()
    
    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT, symbol TEXT, direction TEXT,
                entry_price REAL, exit_price REAL, quantity INTEGER,
                pnl REAL, entry_time TEXT, exit_time TEXT, reason TEXT
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT, direction TEXT, entry REAL,
                stop_loss REAL, take_profit REAL, timestamp TEXT,
                executed INTEGER DEFAULT 0
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS positions (
                order_id TEXT PRIMARY KEY,
                symbol TEXT, direction TEXT, entry_price REAL,
                quantity INTEGER, stop_loss REAL, take_profit REAL,
                trailing_stop REAL, entry_time TEXT, status TEXT,
                sl_order_id TEXT, tp_order_id TEXT
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                symbol TEXT, direction TEXT, order_type TEXT,
                price REAL, quantity INTEGER, status TEXT,
                created_at TEXT, updated_at TEXT
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT, executed_price REAL,
                executed_quantity INTEGER, execution_time TEXT
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS websocket_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT, timestamp TEXT, details TEXT
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS bot_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric TEXT, value TEXT, timestamp TEXT
            )''')
    
    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=20.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    @retry_on_lock()
    def save_signal(self, signal_dict: Dict[str, Any]):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO signals (symbol, direction, entry, stop_loss, take_profit, timestamp) VALUES (?,?,?,?,?,?)",
                (signal_dict['symbol'], signal_dict['direction'], signal_dict['entry'],
                 signal_dict['stop_loss'], signal_dict['take_profit'], signal_dict['timestamp'])
            )
    
    @retry_on_lock()
    def save_position(self, position_dict: Dict[str, Any]):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO positions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (position_dict['order_id'], position_dict['symbol'], position_dict['direction'],
                 position_dict['entry_price'], position_dict['quantity'], position_dict['stop_loss'],
                 position_dict['take_profit'], position_dict['trailing_stop'], position_dict['entry_time'],
                 position_dict['status'], position_dict.get('sl_order_id'), position_dict.get('tp_order_id'))
            )
    
    @retry_on_lock()
    def load_active_positions(self) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall()
            return [dict(row) for row in rows]
    
    @retry_on_lock()
    def update_position_status(self, order_id: str, status: str, sl_oid=None, tp_oid=None):
        with self._get_conn() as conn:
            if sl_oid or tp_oid:
                conn.execute("UPDATE positions SET status=?, sl_order_id=COALESCE(?, sl_order_id), tp_order_id=COALESCE(?, tp_order_id) WHERE order_id=?",
                             (status, sl_oid, tp_oid, order_id))
            else:
                conn.execute("UPDATE positions SET status=? WHERE order_id=?", (status, order_id))
    
    @retry_on_lock()
    def record_trade(self, trade_dict: Dict):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO trades (order_id, symbol, direction, entry_price, exit_price, quantity, pnl, entry_time, exit_time, reason) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (trade_dict['order_id'], trade_dict['symbol'], trade_dict['direction'],
                 trade_dict['entry_price'], trade_dict['exit_price'], trade_dict['quantity'],
                 trade_dict['pnl'], trade_dict['entry_time'], trade_dict['exit_time'], trade_dict['reason'])
            )
    
    def log_websocket_event(self, event_type: str, details: str = ""):
        with self._get_conn() as conn:
            conn.execute("INSERT INTO websocket_events (event_type, timestamp, details) VALUES (?,?,?)",
                         (event_type, datetime.now().isoformat(), details))
    
    def log_health(self, metric: str, value: str):
        with self._get_conn() as conn:
            conn.execute("INSERT INTO bot_health (metric, value, timestamp) VALUES (?,?,?)",
                         (metric, value, datetime.now().isoformat()))

# ============================================================================
# END MODULE: DatabaseManager
# ============================================================================
