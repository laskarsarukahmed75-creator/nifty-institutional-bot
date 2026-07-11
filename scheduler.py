import time
from logger_setup import scheduler_log, error_log

class Scheduler:
    def __init__(self):
        self.tasks = []

    def register(self, interval, function, args=(), kwargs=None):
        kwargs = kwargs or {}
        self.tasks.append({
            "interval": interval,
            "last_run": 0,
            "function": function,
            "args": args,
            "kwargs": kwargs,
        })
        scheduler_log.info(f"Registered task '{function.__name__}' every {interval}s")

    def run(self):
        scheduler_log.info("Scheduler started.")
        while True:
            now = time.time()
            for task in self.tasks:
                if now - task["last_run"] >= task["interval"]:
                    try:
                        task["function"](*task["args"], **task["kwargs"])
                    except Exception as e:
                        error_log.error(f"Scheduler task '{task['function'].__name__}' failed: {e}")
                    task["last_run"] = now
            time.sleep(0.5)
