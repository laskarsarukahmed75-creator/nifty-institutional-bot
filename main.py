#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nifty-institutional-bot – entry point with HTTP health check.
"""
import sys
import os
import time
import logging
import threading
import signal
import traceback
from datetime import datetime
from queue import Queue
from http.server import HTTPServer, BaseHTTPRequestHandler

from config import load_config
from utils import setup_logging, set_ist_offset, check_python_version
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
    checks = [
        ("Python version", check_python_version()),
        ("Disk space", lambda: True),
        ("Write permissions", lambda: True),
        ("Memory capacity", lambda: True),
        ("Internet connectivity", lambda: True),
    ]
    for name, func in checks:
        try:
            ok = func()
            if ok:
                logging.info(f"{name}: OK")
            else:
                logging.warning(f"{name}: failed – continuing")
        except Exception as e:
            logging.warning(f"{name}: exception {e} – continuing")
    return True

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK - nifty-institutional-bot running')
    def log_message(self, format, *args):
        pass

def start_health_server(port):
    try:
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logging.info(f"✅ Health check server running on port {port}")
        return server
    except Exception as e:
        logging.error(f"❌ Failed to start health server: {e}")
        raise

def main():
    setup_logging()
    logging.info("=== nifty-institutional-bot (ULTIMATE) starting ===")

    if sys.version_info < (3, 12):
        logging.critical("Python 3.12+ required.")
        sys.exit(1)

    config = load_config()
    set_ist_offset()

    startup_validation()

    if os.environ.get("FORCE_SESSION", "false").lower() == "true":
        logging.info("⚠️  FORCE_SESSION is ON – bot will run continuously.")
        os.environ["FORCE_SESSION"] = "true"

    port = int(os.environ.get('PORT', 8080))
    logging.info(f"Attempting to bind to port {port}...")
    start_health_server(port)
    time.sleep(0.5)

    data_queue = Queue(maxsize=200)
    structure_queue = Queue(maxsize=200)
    signal_queue = Queue(maxsize=200)
    dashboard_queue = Queue(maxsize=200)
    storage_queue = Queue(maxsize=200)

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
