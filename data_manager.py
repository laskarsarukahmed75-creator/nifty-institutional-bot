#!/usr/bin/env python3
"""
data_manager.py – NiftyInstitutionalbot Data Bank
Stores 4 months of Nifty 50 historical candles, auto-deletes old data,
and provides a lightweight cache for the engine.
"""

import os
import sqlite3
import datetime
import logging
import threading
import time
from typing import List, Dict, Any, Optional

DB_NAME = "nifty_institutional_data.db"
logger = logging.getLogger("DataManager")

class DataManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._init_db()
        # Run auto-cleaner every 24 hours in background
        self._cleaner_thread = threading.Thread(target=self._auto_clean_loop, daemon=True)
        self._cleaner_thread.start()
        logger.info("DataManager initialized with auto-cleaner.")

    def _init_db(self):
        """Create table if not exists."""
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS nifty_candles (
                    timestamp TEXT PRIMARY KEY,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume INTEGER
                )
            ''')
            conn.commit()

    def fetch_and_store(self, smart_api_obj, token="99926000", interval="FIVE_MINUTE", days=120):
        """
        Fetch historical candles from Angel One and store in DB.
        """
        if not smart_api_obj:
            logger.error("SmartAPI object is None, cannot fetch data.")
            return

        to_date = datetime.datetime.now()
        from_date = to_date - datetime.timedelta(days=days)

        logger.info(f"Fetching candles from {from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')}")

        try:
            params = {
                "exchange": "NSE",
                "symboltoken": token,
                "interval": interval,
                "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
                "todate": to_date.strftime("%Y-%m-%d %H:%M")
            }
            resp = smart_api_obj.getCandleData(params)
            if resp.get("status") and resp.get("data"):
                candles = resp["data"]
                with sqlite3.connect(DB_NAME) as conn:
                    cursor = conn.cursor()
                    for row in candles:
                        cursor.execute('''
                            INSERT OR REPLACE INTO nifty_candles
                            (timestamp, open, high, low, close, volume)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (row[0], row[1], row[2], row[3], row[4], row[5]))
                    conn.commit()
                logger.info(f"Stored {len(candles)} candles.")
            else:
                logger.warning(f"No data received or API error: {resp}")
        except Exception as e:
            logger.error(f"Failed to fetch/store candles: {e}")

    def _auto_clean_loop(self):
        """Background loop: delete candles older than 4 months every 24 hours."""
        while True:
            time.sleep(86400)  # 24 hours
            self._delete_old_candles()

    def _delete_old_candles(self, days=120):
        """Delete candles older than 'days'."""
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM nifty_candles WHERE timestamp < ?", (cutoff,))
            deleted = cursor.rowcount
            conn.commit()
            if deleted:
                logger.info(f"Auto-cleaner removed {deleted} old candles.")
        return deleted

    def get_candles(self, limit=500) -> List[Dict]:
        """Retrieve last N candles for analysis (optional)."""
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM nifty_candles ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
