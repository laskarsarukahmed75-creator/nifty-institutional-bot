import time
import os
#import psutil
import sqlite3
import requests
from config import HEALTH_INTERVAL, DB_PATH
from logger_setup import system_log, error_log
from cache import cache_set

class HealthMonitor:
    def __init__(self, modules):
        self.modules = modules
        self.status = {}
        self.last_check = {}

    def check_all(self):
        for name, check_func in self.modules.items():
            try:
                ok = check_func()
                self.status[name] = "ok" if ok else "error"
            except Exception as e:
                self.status[name] = f"error: {e}"
            self.last_check[name] = time.time()
        return self.status

    def get_status(self):
        return self.status

def check_internet():
    try:
        requests.get("https://query1.finance.yahoo.com", timeout=5)
        return True
    except:
        return False

def check_database():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute("SELECT 1")
        conn.close()
        return True
    except:
        return False

def continuous_health_monitor(health_monitor):
    while True:
        health_monitor.check_all()
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent()
        disk = psutil.disk_usage('/')
        db_size = 0
        try:
            db_size = os.path.getsize(DB_PATH) / (1024*1024)
        except:
            pass
        for name, status in health_monitor.status.items():
            if status != "ok":
                error_log.error(f"Health: {name} = {status}")
        cache_set("health_status", {
            "modules": health_monitor.status,
            "cpu": cpu,
            "memory": mem.used / (1024*1024),
            "disk": disk.used / (1024*1024*1024),
            "db_size_mb": db_size
        })
        time.sleep(HEALTH_INTERVAL)
