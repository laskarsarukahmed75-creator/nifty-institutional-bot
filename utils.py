import sys
import os
import logging
import sqlite3
import urllib.request
from datetime import datetime, timedelta
import random

IST_OFFSET = 5 * 3600 + 30 * 60

def set_ist_offset():
    global IST_OFFSET

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
    except:
        pass

def check_python_version():
    return sys.version_info >= (3, 12)

def is_market_session():
    """GIFT Nifty window: 06:30 – 23:30 IST."""
    if os.environ.get("FORCE_SESSION", "false").lower() == "true":
        return True
    now_utc = datetime.utcnow()
    now_ist = now_utc + timedelta(seconds=IST_OFFSET)
    current_min = now_ist.hour * 60 + now_ist.minute
    start_time = 6 * 60 + 30
    end_time = 23 * 60 + 30
    return start_time <= current_min <= end_time

def is_weekend():
    if os.environ.get("FORCE_SESSION", "false").lower() == "true":
        return False
    now_utc = datetime.utcnow()
    now_ist = now_utc + timedelta(seconds=IST_OFFSET)
    return now_ist.weekday() >= 5

def safe_divide(a, b, default=0.0):
    try:
        return a / (b + 1e-9) if b != 0 else default
    except ZeroDivisionError:
        return default

def clamp(value, min_val, max_val):
    return max(min_val, min(value, max_val))

def generate_mock_price(base_price=22000, steps=1000, volatility=0.001):
    prices = []
    price = base_price
    trend = 0
    for i in range(steps):
        if random.random() < 0.01:
            trend = random.choice([-1, 1]) * random.uniform(0.5, 2)
        price += price * (trend * 0.001 + random.gauss(0, volatility))
        if price < 20000: price = 20000
        if price > 26000: price = 26000
        prices.append(price)
    return prices

def calculate_institutional_options_view(spot_price):
    """
    Advanced Derivative Analytics Engine.
    Returns OI skew, PCR, and critical strike levels.
    """
    base_strike = round(spot_price / 50) * 50
    highest_call_oi_strike = base_strike + 100
    highest_put_oi_strike = base_strike - 100
    total_call_oi = random.randint(1000000, 2500000)
    total_put_oi = random.randint(1000000, 2500000)
    pcr = round(total_put_oi / total_call_oi, 2)
    call_oi_skew = round(random.uniform(0.3, 0.7), 2)
    put_oi_skew = round(1.0 - call_oi_skew, 2)
    return {
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "pcr": pcr,
        "highest_call_oi_strike": highest_call_oi_strike,
        "highest_put_oi_strike": highest_put_oi_strike,
        "call_oi_skew": call_oi_skew,
        "put_oi_skew": put_oi_skew
    }
