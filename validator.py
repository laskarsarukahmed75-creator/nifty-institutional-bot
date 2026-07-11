import os
import sys
import sqlite3
import requests
import time
from config import DB_PATH, VALIDATOR_INTERVAL
from logger_setup import system_log, error_log

def validate_environment():
    errors = []
    if sys.version_info < (3, 10):
        errors.append("Python 3.10+ required")
    db_dir = os.path.dirname(DB_PATH)
    if not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
        except Exception as e:
            errors.append(f"DB dir: {e}")
    try:
        requests.get("https://query1.finance.yahoo.com", timeout=5)
    except Exception:
        errors.append("No internet")
    for mod in ["yfinance", "flask", "requests", "psutil"]:
        try:
            __import__(mod)
        except ImportError:
            errors.append(f"Missing module: {mod}")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute("SELECT 1")
        conn.close()
    except Exception as e:
        errors.append(f"DB: {e}")
    if errors:
        for err in errors:
            error_log.error(f"Validation: {err}")
        return False
    return True

def continuous_validator():
    while True:
        if not validate_environment():
            error_log.error("Continuous validation failed")
        time.sleep(VALIDATOR_INTERVAL)
