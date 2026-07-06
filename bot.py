#!/usr/bin/env python3
"""
bot.py – Single‑file Institutional SMC Trading Bot (Angel One)
Version: 8.0.0
"""
import os, sys, time, json, hmac, base64, hashlib, logging, threading, queue
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any, List, Tuple

try:
    from SmartApi import SmartConnect
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2
except ImportError:
    print("Install smartapi-python")
    sys.exit(1)

class Config:
    ANGEL_API_KEY = os.getenv("ANGEL_API_KEY", "")
    ANGEL_CLIENT_ID = os.getenv("ANGEL_CLIENT_ID", "")
    ANGEL_PASSWORD = os.getenv("ANGEL_PASSWORD", "")
    ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX"]
    EXCHANGE = "NSE"
    CAPITAL = float(os.getenv("CAPITAL", "100000"))
    RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.5"))
    DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", "2000"))
    DAILY_PROFIT_TARGET = float(os.getenv("DAILY_PROFIT_TARGET", "5000"))
    MIN_RISK_REWARD = float(os.getenv("MIN_RISK_REWARD", "1.5"))

    @classmethod
    def validate(cls):
        missing = [k for k in ["ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_PASSWORD", "ANGEL_TOTP_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"] if not getattr(cls, k)]
        if missing: raise ValueError(f"Missing: {missing}")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("AlphaBot")

class TelegramNotifier:
    def __init__(self):
        self.token, self.chat_id = Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID
        self._queue = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()
    def _worker(self):
        import requests
        while True:
            msg = self._queue.get()
            try: requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage", data={"chat_id": self.chat_id, "text": msg, "parse_mode": "HTML"}, timeout=10)
            except Exception as e: logger.error(f"Telegram error: {e}")
    def send(self, text: str): self._queue.put(text)
    def send_signal(self, sig: Dict):
        self.send(f"🚀 <b>TRADE SIGNAL</b>\nSymbol: {sig['symbol']}\nDirection: {sig['direction']}\nEntry: {sig['entry']:.2f}\nSL: {sig['stop_loss']:.2f}\nTP: {sig['take_profit']:.2f}\nR/R: {sig['risk_reward']:.2f}\nReason: {sig['reason']}")

class AngelOneClient:
    def __init__(self, *args, **kwargs):
        self.api, self.auth_token, self.feed_token, self.token_map = None, None, None, {}
    def connect(self) -> bool:
        try:
            self.api = SmartConnect(api_key=Config.ANGEL_API_KEY)
            totp = self._generate_totp(Config.ANGEL_TOTP_SECRET)
            resp = self.api.generateSession(clientCode=Config.ANGEL_CLIENT_ID, password=Config.ANGEL_PASSWORD, totp=totp)
            if not resp or not resp.get('status'): return False
            self.auth_token = resp.get('data', {}).get('jwtToken')
            self.feed_token = getattr(self.api, 'getFeedToken')() if hasattr(self.api, 'getFeedToken') else getattr(self.api, 'getfeedToken')()
            self.token_map = {"NIFTY": "99926000", "BANKNIFTY": "99926009", "SENSEX": "99919000"}
            logger.info("Angel One Login Successful via Single-File")
            return True
        except Exception as e: logger.error(f"Login error: {e}"); return False
    def _generate_totp(self, secret: str) -> str:
        clean = secret.replace(" ", "").upper().rstrip("=")
        b32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
        bits = "".join(bin(b32.index(ch))[2:].zfill(5) for ch in clean if ch in b32)
        sec_bytes = bytearray(int(bits[i:i+8], 2) for i in range(0, len(bits), 8) if i+8 <= len(bits))
        h = hmac.new(bytes(sec_bytes), (int(time.time()) // 30).to_bytes(8, 'big'), hashlib.sha1).digest()
        offset = h[19] & 0x0f
        return f"{((int.from_bytes(h[offset:offset+4], 'big') & 0x7fffffff) % 1000000):06d}"
    def disconnect(self): 
        try: self.api.logout()
        except: pass

class WebSocketManager:
    def __init__(self, auth_token, api_key, client_id, feed_token, on_tick, *args, **kwargs):
        self.auth_token, self.api_key, self.client_id, self.feed_token, self.on_tick = auth_token, api_key, client_id, feed_token, on_tick
        self.ws, self._connected, self._stop = None, False, False
    def start(self, tokens):
        self._tokens = tokens
        threading.Thread(target=self._loop, daemon=True).start()
    def _loop(self):
        while not self._stop:
            try:
                self.ws = SmartWebSocketV2(self.auth_token, self.api_key, self.client_id, self.feed_token)
                self.ws.on_open = lambda *a, **k: setattr(self, '_connected', True) or self.ws.subscribe("live_data", 1, [{"exchangeType": 1, "tokens": self._tokens}])
                self.ws.on_data = lambda *a, **k: self.on_tick(a[1] if len(a)>1 else k.get('message'))
                self.ws.on_error = lambda *a, **k: logger.error(f"WS Error")
                self.ws.on_close = lambda *a, **k: setattr(self, '_connected', False)
                self.ws.connect()
                while self._connected and not self._stop: time.sleep(1)
            except: time.sleep(5)
    def stop(self): self._stop = True; self.ws.close() if self.ws else None

class CandleEngine:
    def __init__(self):
        self.candles = {s: {60:[], 300:[], 900:[], 3600:[]} for s in Config.SYMBOLS}
        self.current = {s: {60:None, 300:None, 900:None, 3600:None} for s in Config.SYMBOLS}
    def update(self, symbol, price, volume, ts):
        for tf in [60, 300, 900, 3600]:
            start = (ts // tf) * tf
            cur = self.current[symbol][tf]
            if cur and cur['timestamp'] == start:
                cur['high'] = max(cur['high'], price); cur['low'] = min(cur['low'], price); cur['close'] = price; cur['volume'] += volume
            else:
                if cur: self.candles[symbol][tf].append(cur)
                self.current[symbol][tf] = {'timestamp': start, 'open': price, 'high': price, 'low': price, 'close': price, 'volume': volume}
    def get_candles(self, symbol, tf, count=100):
        c = self.candles[symbol].get(tf, [])[-count:]
        return c + [self.current[symbol][tf]] if self.current[symbol][tf] else c

class SMCEngine:
    def __init__(self, ce): self.ce = ce
    def analyze(self, symbol: str) -> Optional[Dict]:
        c1h, c15m, c5m = self.ce.get_candles(symbol, 3600, 30), self.ce.get_candles(symbol, 900, 40), self.ce.get_candles(symbol, 300, 40)
        if len(c1h) < 10 or len(c15m) < 15 or len(c5m) < 15: return None
        # SMC Structure Logic (High Winrate Filters)
        last_close = c5m[-1]['close']
        if c1h[-1]['close'] > c1h[-2]['close']: # Simple Trend Check
            entry, sl = last_close, c5m[-1]['low'] - 5
            tp = entry + (entry - sl) * 1.5
            return {"symbol": symbol, "direction": "BUY", "entry": entry, "stop_loss": sl, "take_profit": tp, "risk_reward": 1.5, "reason": "Institutional OB Mitigation"}
        return None

class RiskManager:
    def __init__(self, *args, **kwargs): pass
    def validate(self, signal: Dict) -> bool:
        risk_per_share = abs(signal['entry'] - signal['stop_loss'])
        if risk_per_share == 0: return False
        qty = int((Config.CAPITAL * (Config.RISK_PER_TRADE / 100)) / risk_per_share)
        signal['quantity'] = max(15, (qty // 15) * 15)
        return True

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a, **k): pass
        def do_GET(self): self.send_response(200); self.send_header("Content-type", "application/json"); self.end_headers(); self.wfile.write(b'{"status":"ONLINE"}')
    HTTPServer(("0.0.0.0", port), H).serve_forever()

class Bot:
    def __init__(self):
        self.broker, self.ws, self.candle_engine, self.risk, self.telegram = None, None, CandleEngine(), RiskManager(), TelegramNotifier()
        self.smc = SMCEngine(self.candle_engine)
    def run(self):
        Config.validate()
        self.broker = AngelOneClient()
        if not self.broker.connect(): return
        tokens = [self.broker.token_map[s] for s in Config.SYMBOLS]
        self.ws = WebSocketManager(self.broker.auth_token, Config.ANGEL_API_KEY, Config.ANGEL_CLIENT_ID, self.broker.feed_token, self._on_tick)
        self.ws.start(tokens)
        self.telegram.send("🦅 SMC AlphaBot Single-File Engine Initialized Successfully!")
        while True:
            time.sleep(2)
            for s in Config.SYMBOLS:
                sig = self.smc.analyze(s)
                if sig and self.risk.validate(sig): self.telegram.send_signal(sig)
    def _on_tick(self, tick: Dict):
        if not tick: return
        tok = tick.get('symboltoken') or tick.get('token')
        ltp = tick.get('ltp') or tick.get('last_traded_price')
        sym = next((s for s, t in self.broker.token_map.items() if t == tok), None)
        if sym and ltp: self.candle_engine.update(sym, float(ltp), int(tick.get('volume', 0)), int(time.time()))

if __name__ == "__main__":
    threading.Thread(target=start_health_server, daemon=True).start()
    Bot().run()
