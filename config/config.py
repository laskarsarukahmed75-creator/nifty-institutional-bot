# ============================================================================
# START MODULE: Config
# Version: 2.0.0
# Dependencies: os, dotenv
# Public Functions: get_env(), validate()
# Private Functions: _load_env()
# Upgrade Notes: Add new environment variables here. Maintain backward compatibility.
# ============================================================================

import os
from dotenv import load_dotenv
from typing import Set, Dict, Any

load_dotenv()

class Config:
    """Central configuration – replace entire class for new settings."""
    
    # Angel One
    ANGEL_API_KEY = os.getenv("ANGEL_API_KEY", "")
    ANGEL_CLIENT_ID = os.getenv("ANGEL_CLIENT_ID", "")
    ANGEL_PASSWORD = os.getenv("ANGEL_PASSWORD", "")
    ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")
    
    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # Trading Symbols
    SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"]
    EXCHANGE = "NSE"
    PRODUCT_TYPE = "INTRADAY"
    
    # Risk & Capital
    CAPITAL = float(os.getenv("CAPITAL", "100000"))
    RISK_PER_TRADE_PERCENT = float(os.getenv("RISK_PER_TRADE_PERCENT", "0.5"))
    MAX_TRADES_PER_DAY = int(os.getenv("MAX_TRADES_PER_DAY", "10"))
    DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", "5000"))
    TRAILING_STOP_PERCENT = float(os.getenv("TRAILING_STOP_PERCENT", "0.3"))
    COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "60"))
    MIN_RISK_REWARD = float(os.getenv("MIN_RISK_REWARD", "1.5"))
    SL_PERCENT = float(os.getenv("SL_PERCENT", "0.2"))
    TP_PERCENT = float(os.getenv("TP_PERCENT", "0.6"))
    MAX_LEVERAGE = float(os.getenv("MAX_LEVERAGE", "5"))
    
    # Market Hours
    MARKET_OPEN = os.getenv("MARKET_OPEN", "09:15")
    MARKET_CLOSE = os.getenv("MARKET_CLOSE", "15:30")
    
    # Timeframes (seconds)
    TIMEFRAME_1M = int(os.getenv("TIMEFRAME_1M", "60"))
    TIMEFRAME_5M = int(os.getenv("TIMEFRAME_5M", "300"))
    TIMEFRAME_15M = int(os.getenv("TIMEFRAME_15M", "900"))
    
    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "trading_bot.log")
    LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", "10485760"))
    LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))
    
    # Database
    DB_FILE = os.getenv("DB_FILE", "trades.db")
    
    # Broker limits
    MAX_CONSECUTIVE_ORDER_FAILURES = int(os.getenv("MAX_CONSECUTIVE_ORDER_FAILURES", "3"))
    MAX_WEBSOCKET_RECONNECT_ATTEMPTS = int(os.getenv("MAX_WEBSOCKET_RECONNECT_ATTEMPTS", "10"))
    
    # Instrument lot sizes (override via env JSON)
    LOT_SIZES = {"NIFTY": 15, "BANKNIFTY": 15, "SENSEX": 15}
    
    @classmethod
    def validate(cls) -> None:
        """Check all required environment variables are set."""
        required = [
            "ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_PASSWORD", "ANGEL_TOTP_SECRET",
            "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"
        ]
        missing = [r for r in required if not getattr(cls, r)]
        if missing:
            raise ValueError(f"Missing environment variables: {missing}")
    
    @classmethod
    def get_lot_size(cls, symbol: str) -> int:
        return cls.LOT_SIZES.get(symbol, 1)

# ============================================================================
# END MODULE: Config
# ============================================================================
