import os
from typing import Dict, Any

def load_config() -> Dict[str, Any]:
    return {
        "DB_PATH": os.getenv("DB_PATH", "data/nifty_bot.db"),
        "DATA_SOURCES": ["yahoo", "stooq", "cache"],
        "POLL_INTERVAL_AGGRESSIVE": 1,
        "POLL_INTERVAL_NORMAL": 5,
        "POLL_INTERVAL_LATENT": 10,
        "CIRCUIT_BREAKER_TIMEOUT": 30,
        "SESSION_START": "09:15",
        "SESSION_END": "15:30",
        "TIMEZONE": "Asia/Kolkata",
        "ASSETS": ["NIFTY 50", "NIFTY BANK", "SENSEX", "INDIA VIX"],
        "YAHOO_SYMBOLS": {
            "NIFTY 50": "^NSEI",
            "NIFTY BANK": "^NSEBANK",
            "SENSEX": "^BSESN",
            "INDIA VIX": "^INDIAVIX"
        },
        "STOOQ_SYMBOLS": {
            "NIFTY 50": "nifty",
            "NIFTY BANK": "banknifty",
            "SENSEX": "sensex",
            "INDIA VIX": "india_vix"
        },
        # Weighted decision matrix (sum = 100)
        "WEIGHT_CLONE_COMPLETION": 25,
        "WEIGHT_ORIGIN_MAPPING": 20,
        "WEIGHT_LIQUIDITY_SWEEPS": 20,
        "WEIGHT_STRUCTURE_ALIGNMENT": 15,
        "WEIGHT_TRAP_FILTER": 10,
        "WEIGHT_PREMIUM_DISCOUNT": 10,
        "MIN_RISK_REWARD": 2.0,
        "MAX_SIGNALS_PER_DAY": 2,
        "PRUNE_DAYS": 120,
        "PRUNE_INTERVAL": 86400,
        "VACUUM_INTERVAL": 604800,
        "MEMORY_LIMIT_MB": 200,
        "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
        # ATR volatility thresholds for polling
        "ATR_LOW": 0.5,      # if ATR% < 0.5% -> latent
        "ATR_HIGH": 1.5,     # if ATR% > 1.5% -> aggressive
    }
