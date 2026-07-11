import sys
import time
import threading
from config import DASHBOARD_PORT
from data_engine import data_store, data_task
from structure_engine import StructureEngine
from signal_engine import SignalEngine
from dashboard import attach_engines, run_dashboard
from storage import Storage
from health import HealthMonitor, continuous_health_monitor, check_internet, check_database
from watchdog import Watchdog
from scheduler import Scheduler
from validator import validate_environment, continuous_validator
from memory_manager import memory_task
from logger_setup import system_log, error_log

def main():
    if not validate_environment():
        system_log.error("Startup validation failed. Exiting.")
        sys.exit(1)

    storage = Storage()

    struct_engine = StructureEngine(data_store)
    signal_engine = SignalEngine(struct_engine)

    attach_engines(signal_engine, struct_engine, data_store)

    health_modules = {
        "data_engine": lambda: data_store.get("NIFTY") is not None,
        "structure_engine": lambda: True,
        "signal_engine": lambda: True,
        "storage": lambda: True,
        "internet": check_internet,
        "database": check_database,
    }
    health_monitor = HealthMonitor(health_modules)

    watchdog = Watchdog()

    scheduler = Scheduler()
    scheduler.register(5, data_task)
    scheduler.register(10, struct_engine.update, args=("NIFTY",))
    scheduler.register(15, signal_engine.generate_signal, args=("NIFTY",))
    scheduler.register(60, memory_task)
    scheduler.register(3600, storage._cleanup_task)

    # watchdog.register starts the thread immediately
    watchdog.register("scheduler", scheduler.run)
    watchdog.register("health", continuous_health_monitor, args=(health_monitor,))
    watchdog.register("validator", continuous_validator)

    # Start watchdog monitor (infinite loop that checks threads)
    watchdog_thread = threading.Thread(target=watchdog.monitor, daemon=True)
    watchdog_thread.start()

    dash_thread = threading.Thread(target=run_dashboard, daemon=True)
    dash_thread.start()

    system_log.info("All systems started. Nifty Institutional Bot running.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        system_log.info("Shutting down.")
        sys.exit(0)

if __name__ == "__main__":
    main()
