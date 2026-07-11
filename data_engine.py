import time
import threading
import os
from datetime import datetime
import requests
import pyotp

from config import SMART_API_KEY, SMART_CLIENT_ID, SMART_PASSWORD, DATA_SOURCES
from SmartApi import SmartConnect  # ✅ कैपिटल S और A के साथ फिक्स किया गया
import yfinance as yf
from cache import cache_get, cache_set
from retry import retry
from logger_setup import system_log, error_log

class DataStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {symbol: {"time": None, "open": 0.0, "high": 0.0,
                              "low": 0.0, "close": 0.0, "volume": 0}
                     for symbol in DATA_SOURCES}
        self.session = requests.Session()
        self.last_success = {}

    def update(self, symbol, ohlcv):
        with self.lock:
            self.data[symbol] = ohlcv
            self.last_success[symbol] = time.time()

    def get(self, symbol):
        with self.lock:
            return self.data.get(symbol, {})

    def get_all(self):
        with self.lock:
            return self.data.copy()

data_store = DataStore()

# --- SmartAPI Global Object ---
smart_api = None
smart_api_lock = threading.Lock()

def init_smartapi():
    """SmartAPI को Initialize करें और Access Token सेट करें"""
    global smart_api
    with smart_api_lock:
        try:
            system_log.info("Initializing SmartAPI connection...")
            
            # 1. API Key से Connect करें
            obj = SmartConnect(api_key=SMART_API_KEY)
            
            # 2. TOTP handle करें (अगर सेट है तो, वरना खाली)
            totp_secret = os.getenv('SMART_TOTP_KEY')
            totp_val = pyotp.TOTP(totp_secret).now() if totp_secret else ""
            
            # 3. Session Generate करें
            session_data = obj.generateSession(
                clientCode=SMART_CLIENT_ID, 
                password=SMART_PASSWORD, 
                totp=totp_val
            )
            
            # 4. Access Token सेट करें (Token Missing एरर फिक्स)
            obj.setAccessToken(session_data['access_token'])
            
            system_log.info("SmartAPI Login Successful. Token Set.")
            smart_api = obj
            return obj
            
        except Exception as e:
            error_log.error(f"SmartAPI Init Failed: {e}")
            smart_api = None
            raise

# सर्वर शुरू होते ही पहला लॉगिन प्रयास
try:
    init_smartapi()
except Exception as e:
    error_log.error(f"Startup SmartAPI error: {e}")
    smart_api = None

def _fetch_from_smartapi(symbol):
    global smart_api
    
    # अगर API उपलब्ध नहीं है, तो दोबारा री-लॉगिन करें
    if smart_api is None:
        system_log.warning("SmartAPI not available. Re-initializing...")
        init_smartapi()

    try:
        token = DATA_SOURCES.get(symbol)
        if not token:
            raise ValueError(f"No token for symbol: {symbol}")

        params = {
            "exchange": "NSE",
            "symboltoken": str(token),
            "interval": "FIVE_MINUTE",
            "fromdate": datetime.now().strftime("%Y-%m-%d 09:15"),
            "todate": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        
        response = smart_api.getCandleData(params)
        
        if response and response.get('status') and response.get('data'):
            latest = response['data'][-1]
            return {
                "time": datetime.strptime(latest[0], "%Y-%m-%dT%H:%M:%S%z"),
                "open": float(latest[1]),
                "high": float(latest[2]),
                "low": float(latest[3]),
                "close": float(latest[4]),
                "volume": int(latest[5])
            }
        else:
            error_msg = response.get('message', 'No data') if response else 'Empty response'
            raise ValueError(f"API Error: {error_msg}")
            
    except Exception as e:
        error_log.error(f"SmartAPI failed for {symbol}: {e}")
        
        # पुराना कैश डेटा चेक करें
        cached = cache_get(f"data_{symbol}")
        if cached:
            error_log.info(f"Using cached data for {symbol}")
            return cached
            
        # अगर टोकन एक्सपायर या मिसिंग हो, तो दोबारा री-लॉगिन करके प्रयास करें
        if "Token missing" in str(e) or "AG8003" in str(e):
            system_log.warning("Token expired or missing. Re-login attempt...")
            init_smartapi()
            return _fetch_from_smartapi(symbol) 
        
        raise ValueError(f"SmartAPI failed and no cache available for {symbol}")

def fetch_live_data():
    for symbol in DATA_SOURCES.keys():
        try:
            ohlcv = _fetch_from_smartapi(symbol)
            data_store.update(symbol, ohlcv)
            cache_set(f"data_{symbol}", ohlcv)
            system_log.info(f"Data updated for {symbol}")
        except Exception as e:
            error_log.error(f"Error fetching {symbol}: {e}")

def data_task():
    fetch_live_data()
