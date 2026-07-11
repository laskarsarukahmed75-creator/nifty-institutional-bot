import threading
import time
from config import HEARTBEAT_INTERVAL
from logger_setup import watchdog_log, error_log

class Watchdog:
    def __init__(self):
        self.threads = {}

    def register(self, name, target, args=(), kwargs=None, daemon=True):
        kwargs = kwargs or {}
        thread = threading.Thread(target=self._wrapped_target, args=(name, target, args, kwargs), daemon=daemon)
        self.threads[name] = {
            "thread": thread,
            "target": target,
            "args": args,
            "kwargs": kwargs,
            "last_heartbeat": time.time(),
            "running": False
        }
        thread.start()
        watchdog_log.info(f"Registered thread '{name}'")

    def _wrapped_target(self, name, target, args, kwargs):
        while True:
            try:
                self.threads[name]["running"] = True
                self.threads[name]["last_heartbeat"] = time.time()
                target(*args, **kwargs)
                watchdog_log.warning(f"Thread '{name}' finished, restarting...")
                self.threads[name]["running"] = False
                time.sleep(1)
            except Exception as e:
                error_log.error(f"Thread '{name}' crashed: {e}. Restarting...")
                self.threads[name]["running"] = False
                time.sleep(2)

    def heartbeat(self, name):
        if name in self.threads:
            self.threads[name]["last_heartbeat"] = time.time()
            self.threads[name]["running"] = True

    def is_alive(self, name):
        if name not in self.threads:
            return False
        return self.threads[name]["running"] and (time.time() - self.threads[name]["last_heartbeat"]) < HEARTBEAT_INTERVAL

    def monitor(self):
        while True:
            for name, info in self.threads.items():
                if not self.is_alive(name):
                    watchdog_log.warning(f"Thread '{name}' is dead. Restarting...")
                    new_thread = threading.Thread(target=self._wrapped_target,
                                                  args=(name, info["target"], info["args"], info["kwargs"]),
                                                  daemon=True)
                    info["thread"] = new_thread
                    new_thread.start()
                    info["last_heartbeat"] = time.time()
                    info["running"] = True
            time.sleep(5)
