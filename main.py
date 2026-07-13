#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nifty-institutional-bot – entry point with full error logging.
"""
import sys
import os
import time
import logging
import threading
import signal
import gc
import traceback
from datetime import datetime
from queue import Queue

from config import load_config
from utils import (
    setup_logging, check_python_version, check_sqlite_version,
    check_disk_space, check_write_permissions, check_memory,
    check_internet, set_ist_offset
)
from supervisor import Supervisor
from data_engine import DataEngine
from structure_engine import StructureEngine
from signal_engine import SignalEngine
from dashboard import Dashboard
from storage import StorageController

# State machine constants
STATE_WAITING = "WAITING"
STATE_COLLECTING = "COLLECTING"
STATE_BUILDING_STRUCTURE = "BUILDING_STRUCTURE"
STATE_STRUCTURE_CONFIRMED = "STRUCTURE_CONFIRMED"
STATE_SIGNAL_READY = "SIGNAL_READY"
STATE_ACTIVE_SIGNAL = "ACTIVE_SIGNAL"
STATE_TP_OR_SL = "TP_OR_SL"
STATE_RESET = "RESET"

class AppState:
    def __init__(self):
        self.state = STATE_WAITING
        self.lock = threading.Lock()
        self.signal_data = None
        self.last_reset = datetime.now()
        self.signal_count_today = 0
        self.last_signal_date = None

    def transition(self, new_state: str):
        with self.lock:
            old = self.state
            self.state = new_state
            logging.info(f"State transition: {old} -> {new_state}")
            if new_state == STATE_RESET:
                self.signal_data = None
                self.last_reset = datetime.now()

    def get_state(self) -> str:
        with self.lock:
            return self.state

    def reset_state(self):
        with self.lock:
            self.signal_data = None
            self.state = STATE_WAITING
            self.last_reset = datetime.now()

def startup_validation() -> bool:
    logging.info("Starting startup validation...")
    # All checks are now non‑fatal; we log errors but continue.
    checks = [
        ("Python version", check_python_version()),
        ("SQLite version", check_sqlite_version()),
        ("Disk space", check_disk_space(100)),
        ("Write permissions", check_write_permissions()),
        ("Memory capacity", check_memory(200)),
        ("Internet connectivity", check_internet()),
    ]
    all_ok = True
    for name, ok in checks:
        if not ok:
            logging.warning(f"Startup check failed: {name} – continuing anyway.")
            all_ok = False
        else:
            logging.info(f"{name}: OK")
    # We continue even if some checks fail, because Render environments may have limitations.
    return True  # always proceed

def main():
    setup_logging()
    logging.info("=== nifty-institutional-bot (hardened) starting ===")

    if sys.version_info < (3, 12):
        logging.critical("Python 3.12+ required.")
        sys.exit(1)

    config = load_config()
    set_ist_offset()

    startup_validation()  # no longer blocks

    # Create queues
    data_queue = Queue(maxsize=100)
    structure_queue = Queue(maxsize=100)
    signal_queue = Queue(maxsize=100)
    dashboard_queue = Queue(maxsize=100)
    storage_queue = Queue(maxsize=100)

    storage = StorageController(config["DB_PATH"])
    storage.initialize_db()
    data_engine = DataEngine(config, data_queue, storage_queue)
    structure_engine = StructureEngine(config, data_queue, structure_queue, storage_queue)
    signal_engine = SignalEngine(config, structure_queue, signal_queue, storage_queue, dashboard_queue)
    dashboard = Dashboard(config, dashboard_queue)

    app_state = AppState()
    signal_engine.app_state = app_state

    supervisor = Supervisor(
        data_engine=data_engine,
        structure_engine=structure_engine,
        signal_engine=signal_engine,
        dashboard=dashboard,
        storage=storage,
        storage_queue=storage_queue,
        app_state=app_state,
        config=config
    )

    def shutdown_handler(sig, frame):
        logging.info("Shutdown signal received.")
        supervisor.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        supervisor.start()
    except Exception as e:
        logging.critical(f"Supervisor failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    while supervisor.is_running():
        time.sleep(1)

    logging.info("Application terminated.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("FATAL UNHANDLED EXCEPTION:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
