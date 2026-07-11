import logging
import logging.handlers
import os
from config import LOG_DIR, LOG_LEVEL

_logger_cache = {}

def setup_logger(name, log_file, level=LOG_LEVEL):
    if name in _logger_cache:
        return _logger_cache[name]
    os.makedirs(LOG_DIR, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, log_file),
        maxBytes=10*1024*1024,
        backupCount=5
    )
    handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    # Avoid duplicate handlers
    if not logger.handlers:
        logger.addHandler(handler)
        logger.addHandler(console)
    _logger_cache[name] = logger
    return logger

system_log = setup_logger("System", "system.log")
signal_log = setup_logger("Signal", "signal.log")
error_log = setup_logger("Error", "error.log")
scheduler_log = setup_logger("Scheduler", "scheduler.log")
watchdog_log = setup_logger("Watchdog", "watchdog.log")
database_log = setup_logger("Database", "database.log")
