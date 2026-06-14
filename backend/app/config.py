import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # Exchanges
    BINANCE_WS = "wss://fstream.binance.com/ws"
    
    # Security
    SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey123")
    JWT_ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 60
    AES_KEY = os.getenv("AES_KEY", "32bytessecretkeyforaesencryption")
    
    # Alerts
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    
    # Database
    DATABASE_URL = os.getenv("DATABASE_URL")
    
    # Redis
    REDIS_URL = os.getenv("REDIS_URL")
    
    # Rate limits
    RATE_LIMIT_REQUESTS = 100
    RATE_LIMIT_PERIOD = 60

settings = Settings()




