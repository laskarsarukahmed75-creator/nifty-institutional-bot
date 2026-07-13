import sys
import os
import logging
import sqlite3
import time
import urllib.request
from datetime import datetime, timedelta
import gc

# Global IST offset in seconds (fixed +5:30)
IST_OFFSET = 5 * 3600 + 30 * 60

def set_ist_offset():
    """Set the IST offset globally (used for session checks)."""
    global IST_OFFSET
    # We could attempt to detect from system, but we fix it.

def setup_logging(level="INFO"):
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    try:
        os.makedirs("logs", exist_ok=True)
        fh = logging.FileHandler("logs/bot.log", mode='a')
        fh.setFormatter(logging.Formatter(log_format))
        logging.getLogger().addHandler(fh)
    except Exception:
        pass

def check_python_version():
    return sys.version_info >= (3, 12)

def check_sqlite_version():
    try:
        logging.info(f"SQLite version: {sqlite3.sqlite_version}")
        return True
    except:
        return False

def check_disk_space(min_mb=100):
    try:
        stat = os.statvfs('.')
        free = stat.f_bavail * stat.f_frsize / (1024 * 1024)
        return free >= min_mb
    except:
        return False

def check_write_permissions():
    try:
        test = ".write_test"
        with open(test, 'w') as f:
            f.write("test")
        os.remove(test)
        return True
    except:
        return False

def check_memory(min_mb=200):
    """Check available memory using /proc/meminfo (Linux) or fallback."""
    if sys.platform == "linux":
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        avail_kb = int(line.split()[1])
                        return (avail_kb / 1024) >= min_mb
        except:
            pass
    # Fallback: assume enough
    return True

def check_internet():
    for url in ["https://www.google.com", "https://www.github.com"]:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    return True
        except:
            continue
    return False

def is_market_session():
    """Check if current time (system local) is within NSE session (09:15-15:30 IST)."""
    # Use system time, but we assume system is set to IST or we use UTC+5:30 offset.
    # We'll compute using UTC and add IST offset.
    now_utc = datetime.utcnow()
    now_ist = now_utc + timedelta(seconds=IST_OFFSET)
    hour = now_ist.hour
    minute = now_ist.minute
    current_min = hour * 60 + minute
    start = 9 * 60 + 15
    end = 15 * 60 + 30
    return start <= current_min <= end

def is_weekend():
    now_utc = datetime.utcnow()
    now_ist = now_utc + timedelta(seconds=IST_OFFSET)
    return now_ist.weekday() >= 5  # Sat=5, Sun=6

def safe_divide(a, b, default=0.0):
    try:
        return a / (b + 1e-9) if b != 0 else default
    except ZeroDivisionError:
        return default

def clamp(value, min_val, max_val):
    return max(min_val, min(value, max_val))

def get_memory_usage_mb():
    """Approximate RSS memory usage in MB."""
    try:
        import resource
        # ru_maxrss is in kilobytes on Linux, bytes on macOS; convert.
        mem = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # On Linux, it's in KB; on macOS, bytes. We'll treat as KB for Linux.
        if sys.platform == "linux":
            return mem / 1024.0
        else:
            return mem / (1024.0 * 1024.0)
    except:
        # Fallback: use /proc/self/statm
        try:
            with open("/proc/self/statm", "r") as f:
                parts = f.read().split()
                # first field is size in pages; page size typically 4096
                pages = int(parts[0])
                return (pages * 4096) / (1024 * 1024)
        except:
            return 0
