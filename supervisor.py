import time
import threading
import logging
import sys
import gc

class Supervisor:
    def __init__(self, data_engine, structure_engine, signal_engine,
                 dashboard, storage, storage_queue, app_state, config):
        self.data_engine = data_engine
        self.structure_engine = structure_engine
        self.signal_engine = signal_engine
        self.dashboard = dashboard
        self.storage = storage
        self.storage_queue = storage_queue
        self.app_state = app_state
        self.config = config

        self.storage.queue = storage_queue
        self.signal_engine.app_state = app_state

        self.threads = {
            "data": data_engine,
            "structure": structure_engine,
            "signal": signal_engine,
            "dashboard": dashboard,
            "storage": storage,
        }
        self.restart_counts = {name: 0 for name in self.threads}
        self.running = False
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True

        self._start_thread("storage")
        time.sleep(0.5)
        for name in ["data", "structure", "signal", "dashboard"]:
            self._start_thread(name)
            time.sleep(0.2)

        logging.info("Supervisor started all threads.")
        while self.running:
            self._check_health()
            if get_memory_usage_mb() > self.config["MEMORY_LIMIT_MB"]:
                logging.warning("Memory limit exceeded, forcing GC.")
                gc.collect()
            time.sleep(5)

    def stop(self):
        with self.lock:
            if not self.running:
                return
            self.running = False
        logging.info("Supervisor stopping threads...")
        for name, thread in self.threads.items():
            try:
                thread.stop()
            except:
                pass
        for name, thread in self.threads.items():
            if thread.is_alive():
                thread.join(timeout=2.0)
        logging.info("All threads stopped.")

    def is_running(self):
        return self.running

    def _start_thread(self, name):
        thread = self.threads.get(name)
        if thread is None:
            logging.error(f"Thread {name} not found.")
            return
        if not thread.is_alive():
            try:
                thread.start()
                logging.info(f"Thread {name} started.")
                self.restart_counts[name] = 0
            except Exception as e:
                logging.error(f"Failed to start {name}: {e}")
                self._handle_failure(name)

    def _check_health(self):
        for name, thread in self.threads.items():
            if not thread.is_alive():
                logging.warning(f"Thread {name} is dead.")
                self._handle_failure(name)

    def _handle_failure(self, name):
        count = self.restart_counts.get(name, 0) + 1
        self.restart_counts[name] = count
        if count > 5:
            logging.critical(f"{name} failed >5 times. Shutting down.")
            self.stop()
            sys.exit(1)
        logging.info(f"Restarting {name} (attempt {count})...")
        old = self.threads[name]
        try:
            old.stop()
        except:
            pass
        del old
        gc.collect()

        new_thread = None
        if name == "data":
            new_thread = self.data_engine.__class__(self.data_engine.config,
                                                    self.data_engine.data_queue,
                                                    self.data_engine.storage_queue)
        elif name == "structure":
            new_thread = self.structure_engine.__class__(self.structure_engine.config,
                                                         self.structure_engine.data_queue,
                                                         self.structure_engine.out_queue,
                                                         self.structure_engine.storage_queue)
        elif name == "signal":
            new_thread = self.signal_engine.__class__(self.signal_engine.config,
                                                      self.signal_engine.in_queue,
                                                      self.signal_engine.out_queue,
                                                      self.signal_engine.storage_queue,
                                                      self.signal_engine.dashboard_queue)
            new_thread.app_state = self.app_state
        elif name == "dashboard":
            new_thread = self.dashboard.__class__(self.dashboard.config,
                                                  self.dashboard.dashboard_queue)
        elif name == "storage":
            new_thread = self.storage.__class__(self.storage.db_path)
            new_thread.queue = self.storage_queue
        else:
            logging.error(f"Unknown thread {name}, cannot restart.")
            return

        self.threads[name] = new_thread
        self._start_thread(name)

def get_memory_usage_mb():
    try:
        import resource
        mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "linux":
            return mem / 1024.0
        else:
            return mem / (1024.0 * 1024.0)
    except:
        try:
            with open("/proc/self/statm", "r") as f:
                pages = int(f.read().split()[0])
                return (pages * 4096) / (1024 * 1024)
        except:
            return 0
