import os

SMART_API_KEY = os.getenv('SMART_API_KEY')
SMART_CLIENT_ID = os.getenv('SMART_CLIENT_ID')
SMART_PASSWORD = os.getenv('SMART_PASSWORD')

DATA_SOURCES = {
    "NIFTY": "99926000",      # अपना सही NSE Index Token डालें
    "BANKNIFTY": "99926009"   # अपना सही NSE Index Token डालें
}

# Update intervals (seconds)
DATA_INTERVAL = 5
STRUCTURE_INTERVAL = 10
SIGNAL_INTERVAL = 15
HEALTH_INTERVAL = 300          # 5 minutes
VALIDATOR_INTERVAL = 300
MEMORY_CHECK_INTERVAL = 60

# Risk and SL
MIN_RISK_REWARD = 2.0
MAX_SL_BUFFER = 5.0
SIGNAL_COOLDOWN = 300

# Storage
DB_PATH = os.environ.get("DB_PATH", "data/nifty_bot.db")
WAL_MODE = True
RETENTION_DAYS = 120
RAW_RETENTION_DAYS = 7
MINUTE_RETENTION_DAYS = 30
FIVE_MIN_RETENTION_DAYS = 120

# Cache
CACHE_SIZE = 100

# Rate limiting
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_PERIOD = 10

# Dashboard
DASHBOARD_PORT = int(os.environ.get("PORT", 8080))

# Memory
MAX_MEMORY_MB = 180

# Logging
LOG_LEVEL = "INFO"
LOG_DIR = "logs"

# Heartbeat
HEARTBEAT_INTERVAL = 30

# Retry
RETRY_MAX_ATTEMPTS = 3
RETRY_BACKOFF = 2

# Signal scoring weights (total 100)
SCORE_WEIGHTS = {
    "clone_accuracy": 20,
    "trend_quality": 15,
    "volume_quality": 10,
    "structure_quality": 15,
    "liquidity_quality": 10,
    "market_session": 5,
    "volatility": 10,
    "historical_similarity": 15
}

# Angel One SmartAPI Credentials
SMART_API_KEY = os.getenv('SMART_API_KEY')
SMART_CLIENT_ID = os.getenv('SMART_CLIENT_ID')
SMART_PASSWORD = os.getenv('SMART_PASSWORD')
