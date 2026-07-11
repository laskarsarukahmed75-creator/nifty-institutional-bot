import time
from config import RETRY_MAX_ATTEMPTS, RETRY_BACKOFF
from logger_setup import error_log

def retry(max_attempts=RETRY_MAX_ATTEMPTS, backoff=RETRY_BACKOFF):
    def decorator(func):
        def wrapper(*args, **kwargs):
            attempts = 0
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    wait = backoff ** attempts
                    error_log.warning(f"Retry {attempts}/{max_attempts} for {func.__name__} after {wait}s due to {e}")
                    time.sleep(wait)
            raise Exception(f"{func.__name__} failed after {max_attempts} attempts")
        return wrapper
    return decorator
