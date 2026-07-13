
---

## 🧬 Final Code (All Modules – Improved & Fixed)

---

### `main.py` (Entry point – with startup validation and state machine)

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nifty-institutional-bot – hardened production entry point.
"""
import sys
import os
import time
import logging
import threading
import signal
import gc
from datetime import datetime
from queue import Queue

from config import load_config
from utils import (
    setup_logging, check_python_version, check_sqlite_version,
    check_disk_space, check_write_permissions, check_memory,
    check_internet, set_ist_offset, is_market_session
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
    """Central state machine – thread‑safe."""
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
        """Flush active signal and reset counters."""
        with self.lock:
            self.signal_data = None
            self.state = STATE_WAITING
            self.last_reset = datetime.now()
            # Do not reset daily count; we keep it.

def startup_validation() -> bool:
    logging.info("Starting startup validation...")
    checks = [
        ("Python version", check_python_version()),
        ("SQLite version", check_sqlite_version()),
        ("Disk space (>=100MB)", check_disk_space(100)),
        ("Write permissions", check_write_permissions()),
        ("Memory capacity (>=200MB)", check_memory(200)),
        ("Internet connectivity", check_internet()),
    ]
    for name, ok in checks:
        if not ok:
            logging.critical(f"Startup validation failed: {name}")
            return False
        logging.info(f"{name}: OK")
    logging.info("All startup validations passed.")
    return True

def main():
    setup_logging()
    logging.info("=== nifty-institutional-bot (hardened) starting ===")

    if sys.version_info < (3, 12):
        logging.critical("Python 3.12+ required.")
        sys.exit(1)

    config = load_config()
    set_ist_offset()  # ensure IST offset for session checks

    if not startup_validation():
        sys.exit(1)

    # Create queues
    data_queue = Queue(maxsize=100)
    structure_queue = Queue(maxsize=100)
    signal_queue = Queue(maxsize=100)   # not heavily used
    dashboard_queue = Queue(maxsize=100)
    storage_queue = Queue(maxsize=100)

    # Instantiate components
    storage = StorageController(config["DB_PATH"])
    storage.initialize_db()
    data_engine = DataEngine(config, data_queue, storage_queue)
    structure_engine = StructureEngine(config, data_queue, structure_queue, storage_queue)
    signal_engine = SignalEngine(config, structure_queue, signal_queue, storage_queue, dashboard_queue)
    dashboard = Dashboard(config, dashboard_queue)

    app_state = AppState()
    signal_engine.app_state = app_state  # inject state

    # Supervisor manages all threads
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
        sys.exit(1)

    while supervisor.is_running():
        time.sleep(1)

    logging.info("Application terminated.")

if __name__ == "__main__":
    main()
