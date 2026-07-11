import gc
import psutil
import os
from config import MAX_MEMORY_MB
from logger_setup import system_log, error_log
from cache import cache_clear

def trim_memory():
    process = psutil.Process(os.getpid())
    mem_mb = process.memory_info().rss / (1024 * 1024)
    if mem_mb > MAX_MEMORY_MB:
        system_log.warning(f"Memory {mem_mb:.1f} MB > {MAX_MEMORY_MB} MB. Trimming...")
        cache_clear()
        gc.collect()
        return True
    return False

def memory_task():
    trim_memory()
