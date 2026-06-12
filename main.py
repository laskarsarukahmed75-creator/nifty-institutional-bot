#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
INDIAN INDICES SCALPING BOT - YFINANCE FALLBACK (No Angel One Token Required)
"""

import asyncio
import csv
import datetime
import io
import json
import logging
import math
import os
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

import flask
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from gtts import gTTS
from telegram import Bot, Update, InputFile
from telegram.ext import Application, CommandHandler, ContextTypes

# -------------------- Configuration --------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

CAPITAL_BASE = float(os.getenv("CAPITAL_BASE", "50000.0"))
RISK_PERCENT = float(os.getenv("RISK_PERCENT", "2.0"))
ENABLE_AUTO_TRADE = os.getenv("ENABLE_AUTO_TRADE", "False").lower() == "true"
ENABLE_TRAILING_STOP = os.getenv("ENABLE_TRAILING_STOP", "True").lower() == "true"
TRAILING_ACTIVATION_PERCENT = float(os.getenv("TRAILING_ACTIVATION_PERCENT", "0.5"))
TRAILING_STOP_DISTANCE = float(os.getenv("TRAILING_STOP_DISTANCE", "0.3"))

SYMBOLS_YF = [
    {"name": "Nifty 50", "symbol": "^NSEI"},
    {"name": "Bank Nifty", "symbol": "^NSEBANK"},
    {"name": "Sensex", "symbol": "^BSESN"},
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("YFinanceBot")

# -------------------- Thread‑Safe Cache --------------------
GLOBAL_LIVE_FEED_CACHE = {
    "^NSEI": {"ltp": 0.0, "volume": 0, "oi": 0, "timestamp": None, "prev_ltp": 0.0},
    "^NSEBANK": {"ltp": 0.0, "volume": 0, "oi": 0, "timestamp": None, "prev_ltp": 0.0},
    "^BSESN": {"ltp": 0.0, "volume": 0, "oi": 0, "timestamp": None, "prev_ltp": 0.0},
}
CACHE_LOCK = threading.RLock()

# -------------------- Database --------------------
def init_database():
    conn = sqlite3.connect("trades.db", timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, asset_name TEXT, asset_symbol TEXT, action TEXT,
            entry_price REAL, stop_loss REAL, target_price REAL,
            lot_size REAL, risk_amount REAL, smc_score REAL, crt_score REAL,
            status TEXT DEFAULT 'OPEN', trailing_activated INTEGER DEFAULT 0,
            exit_price REAL, pnl REAL
        );
        CREATE TABLE IF NOT EXISTS market_structures (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, timestamp TEXT, structure_type TEXT, price REAL, timeframe TEXT
        );
        CREATE TABLE IF NOT EXISTS order_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, timestamp TEXT, type TEXT, price_high REAL, price_low REAL, mitigated INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS liquidity_pools (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, timestamp TEXT, price_level REAL, volume REAL, is_high INTEGER
        );
        CREATE TABLE IF NOT EXISTS smt_divergences (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol1 TEXT, symbol2 TEXT, timestamp TEXT, divergence_type TEXT, strength REAL
        );
    """)
    conn.commit()
    conn.close()
    if not os.path.exists("backup_nse_ledger.csv"):
        with open("backup_nse_ledger.csv", "w", newline="") as f:
            csv.writer(f).writerow(["timestamp","asset_name","asset_symbol","action",
                                    "entry_price","stop_loss","target_price","lot_size",
                                    "risk_amount","smc_score","crt_score","status"])

def log_trade_to_db(trade: Dict) -> int:
    conn = sqlite3.connect("trades.db")
    cur = conn.cursor()
    cur.execute("""INSERT INTO trades (timestamp, asset_name, asset_symbol, action,
        entry_price, stop_loss, target_price, lot_size, risk_amount, smc_score, crt_score, status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (trade["timestamp"], trade["asset_name"], trade["asset_symbol"], trade["action"],
         trade["entry_price"], trade["stop_loss"], trade["target_price"],
         trade["lot_size"], trade["risk_amount"], trade.get("smc_score",0),
         trade.get("crt_score",0), trade.get("status","OPEN")))
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    with open("backup_nse_ledger.csv", "a", newline="") as f:
        csv.DictWriter(f, fieldnames=trade.keys()).writerow(trade)
    return tid

def update_trade_exit(tid, exit_price, pnl):
    conn = sqlite3.connect("trades.db")
    conn.execute("UPDATE trades SET status='CLOSED', exit_price=?, pnl=? WHERE id=?", (exit_price, pnl, tid))
    conn.commit()
    conn.close()

# -------------------- Footprint (dummy for compatibility) --------------------
@dataclass
class Tick:
    timestamp: datetime.datetime
    price: float
    volume: int
    side: str

class FootprintAnalyzer:
    def __init__(self, window_sec=60):
        self.queue = deque()
        self.delta = 0.0
    def add_tick(self, tick: Tick):
        self.delta += tick.volume if tick.side == "BUY" else -tick.volume
    def get_delta(self): return self.delta

footprint = FootprintAnalyzer()

# -------------------- Live Data Fetch Thread (yfinance) --------------------
def yfinance_live_feed():
    """Background thread to fetch latest LTP every second."""
    last_data = {}
    while True:
        try:
            for sym_info in SYMBOLS_YF:
                symbol = sym_info["symbol"]
                ticker = yf.Ticker(symbol)
                # Get 1m data to extract latest
                hist = ticker.history(period="1d", interval="1m")
                if not hist.empty:
                    ltp = hist["Close"].iloc[-1]
                    volume = hist["Volume"].iloc[-1] if not pd.isna(hist["Volume"].iloc[-1]) else 0
                    with CACHE_LOCK:
                        prev = GLOBAL_LIVE_FEED_CACHE[symbol].get("ltp", ltp)
                        GLOBAL_LIVE_FEED_CACHE[symbol].update({
                            "ltp": ltp,
                            "prev_ltp": prev,
                            "volume": volume,
                            "oi": 0,
                            "timestamp": datetime.datetime.now()
                        })
                    # Determine tick side
                    side = "BUY" if ltp > prev else "SELL" if ltp < prev else "NEUTRAL"
                    if side != "NEUTRAL":
                        footprint.add_tick(Tick(datetime.datetime.now(), ltp, max(1, volume), side))
        except Exception as e:
            logger.error(f"YFinance fetch error: {e}")
        time.sleep(1)

# ==================== INDICATORS & PATTERNS (SAME AS BEFORE) ====================
historical_dfs = {"1m": {}, "5m": {}, "15m": {}, "1h": {}}
HIST_LOCK = threading.RLock()

def calculate_ema(data, period):
    if len(data) < period: return np.full_like(data, np.nan)
    alpha = 2/(period+1)
    ema = np.full_like(data, np.nan)
    ema[period-1] = np.mean(data[:period])
    for i in range(period, len(data)):
        ema[i] = (data[i]-ema[i-1])*alpha + ema[i-1]
    return ema

def calculate_rsi(data, period=14):
    if len(data) < period+1: return 50.0
    deltas = np.diff(data)
    seed = deltas[:period]
    up = seed[seed>=0].sum()/period
    down = -seed[seed<0].sum()/period
    if down == 0: return 100.0
    rs = up/down
    rsi = 100 - 100/(1+rs)
    for i in range(period, len(deltas)):
        delta = deltas[i]
        upval = delta if delta>0 else 0
        downval = -delta if delta<0 else 0
        up = (up*(period-1)+upval)/period
        down = (down*(period-1)+downval)/period
        rs = up/down if down!=0 else float('inf')
        rsi = 100 - 100/(1+rs)
    return rsi

def calculate_atr(high, low, close, period=14):
    if len(high) < period+1: return 0.0
    tr = np.maximum(high[1:]-low[1:], np.abs(high[1:]-close[:-1]), np.abs(low[1:]-close[:-1]))
    return np.mean(tr[:period])

def calculate_vwap(df):
    if df["volume"].sum() == 0: return df["close"].iloc[-1]
    tp = (df["high"]+df["low"]+df["close"])/3.0
    return (tp*df["volume"]).sum()/df["volume"].sum()

def detect_order_blocks(df):
    if len(df)<5: return []
    blocks = []
    for i in range(2, len(df)-1):
        if df["close"].iloc[i] > df["open"].iloc[i] and (df["close"].iloc[i]-df["low"].iloc[i]) > (df["high"].iloc[i]-df["low"].iloc[i])*0.6:
            if df["low"].iloc[i+1] > df["low"].iloc[i] and df["low"].iloc[i+2] > df["low"].iloc[i]:
                blocks.append({"type":"BULLISH","high":df["high"].iloc[i],"low":df["low"].iloc[i]})
        elif df["close"].iloc[i] < df["open"].iloc[i] and (df["high"].iloc[i]-df["close"].iloc[i]) > (df["high"].iloc[i]-df["low"].iloc[i])*0.6:
            if df["high"].iloc[i+1] < df["high"].iloc[i] and df["high"].iloc[i+2] < df["high"].iloc[i]:
                blocks.append({"type":"BEARISH","high":df["high"].iloc[i],"low":df["low"].iloc[i]})
    return blocks

def detect_bos_choch(df, lookback=20):
    if len(df)<lookback: return (None,0.0)
    highs, lows, closes = df["high"].values, df["low"].values, df["close"].values
    swings_high, swings_low = [], []
    for i in range(2,len(df)-2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            swings_high.append((i, highs[i]))
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            swings_low.append((i, lows[i]))
    if len(swings_high)<2 or len(swings_low)<2: return (None,0.0)
    ph, pl = swings_high[-2][1], swings_low[-2][1]
    ch, cl = swings_high[-1][1], swings_low[-1][1]
    price = closes[-1]
    if price > ph and ph > ch: return ("BOS_UP", price)
    if price < pl and pl < cl: return ("BOS_DOWN", price)
    if len(swings_high)>=3 and len(swings_low)>=3:
        if swings_high[-1][1] > swings_high[-2][1] and swings_low[-1][1] < swings_low[-2][1]:
            return ("CHOCH_DOWN", price)
        if swings_low[-1][1] < swings_low[-2][1] and swings_high[-1][1] > swings_high[-2][1]:
            return ("CHOCH_UP", price)
    return (None,0.0)

def detect_liquidity_pools(df, lookback=100):
    levels = {}
    for val in df["high"].tail(lookback):
        levels[round(val,2)] = levels.get(round(val,2),0)+1
    for val in df["low"].tail(lookback):
        levels[round(val,2)] = levels.get(round(val,2),0)+1
    return [lev for lev, cnt in levels.items() if cnt>=3]

def calculate_premium_discount(df, lookback=100):
    if len(df)<lookback: return (0,0,0)
    h, l = df["high"].tail(lookback).max(), df["low"].tail(lookback).min()
    r = h-l
    fib618 = h - r*0.618
    fib382 = h - r*0.382
    cur = df["close"].iloc[-1]
    if cur < fib382: return (h, fib382, fib618)
    else: return (fib382, l, fib618)

def detect_market_structure_shift(df):
    if len(df)<50: return (False,"")
    closes = df["close"].values
    ema20 = calculate_ema(closes,20)[-1]
    ema50 = calculate_ema(closes,50)[-1]
    cur, prev = closes[-1], closes[-2]
    if ema20>ema50 and cur<prev and cur<ema20: return (True,"MSS_DOWN")
    if ema20<ema50 and cur>prev and cur>ema20: return (True,"MSS_UP")
    return (False,"")

def detect_smt_divergence(df_nifty, df_bank):
    if len(df_nifty)<20 or len(df_bank)<20: return (False,"",0.0)
    nh, nl = df_nifty["high"].tail(10).values, df_nifty["low"].tail(10).values
    bh, bl = df_bank["high"].tail(10).values, df_bank["low"].tail(10).values
    if nl[-1] < nl[-2] and bl[-1] > bl[-2]:
        return (True,"BULLISH", abs(nl[-1]-nl[-2])/nl[-2]*100)
    if nh[-1] > nh[-2] and bh[-1] < bh[-2]:
        return (True,"BEARISH", abs(nh[-1]-nh[-2])/nh[-2]*100)
    return (False,"",0.0)

def detect_fair_value_gap(df, idx):
    if idx<2 or idx>=len(df): return None
    c0h, c0l = df["high"].iloc[idx-2], df["low"].iloc[idx-2]
    c1h, c1l = df["high"].iloc[idx-1], df["low"].iloc[idx-1]
    if c0l > c1h: return (c1h, c0l)
    if c1l > c0h: return (c0h, c1l)
    return None

def detect_crt_setup(df):
    if len(df)<10: return (0,0.0,0.0,0.0,0.0)
    recent = df.tail(10)
    c1 = -3; c2 = -2; c3 = -1
    c1_bull = recent["close"].iloc[c1] > recent["open"].iloc[c1] and (recent["high"].iloc[c1]-recent["low"].iloc[c1]) > (recent["high"].iloc[-5:].mean()-recent["low"].iloc[-5:].mean())*0.8
    c1_bear = recent["close"].iloc[c1] < recent["open"].iloc[c1] and (recent["high"].iloc[c1]-recent["low"].iloc[c1]) > (recent["high"].iloc[-5:].mean()-recent["low"].iloc[-5:].mean())*0.8
    htf_high = recent["high"].iloc[-10:-2].max()
    htf_low = recent["low"].iloc[-10:-2].min()
    c2_bull = recent["low"].iloc[c2] <= htf_low and recent["close"].iloc[c2] > recent["open"].iloc[c2]
    c2_bear = recent["high"].iloc[c2] >= htf_high and recent["close"].iloc[c2] < recent["open"].iloc[c2]
    c3_bull = recent["close"].iloc[c3] > max(recent["high"].iloc[c1], recent["high"].iloc[c2]) and recent["close"].iloc[c3] > recent["open"].iloc[c3]
    c3_bear = recent["close"].iloc[c3] < min(recent["low"].iloc[c1], recent["low"].iloc[c2]) and recent["close"].iloc[c3] < recent["open"].iloc[c3]
    is_buy = c1_bull and c2_bull and c3_bull
    is_sell = c1_bear and c2_bear and c3_bear
    if not (is_buy or is_sell): return (0,0,0,0,0)
    if is_buy:
        entry = (max(recent["high"].iloc[c1], recent["high"].iloc[c2]) + min(recent["low"].iloc[c1], recent["low"].iloc[c2]))/2
        sl = recent["low"].iloc[c2] - (recent["high"].iloc[c1]-recent["low"].iloc[c1])*0.5
        target = recent["close"].iloc[-1] + (recent["high"].iloc[c1]-recent["low"].iloc[c1])*1.5
        conf = abs(recent["high"].iloc[c1]-recent["low"].iloc[c1])/(recent["close"].iloc[-1]+1e-6)*100
        return (1, entry, sl, target, conf)
    else:
        entry = (max(recent["high"].iloc[c1], recent["high"].iloc[c2]) + min(recent["low"].iloc[c1], recent["low"].iloc[c2]))/2
        sl = recent["high"].iloc[c2] + (recent["high"].iloc[c1]-recent["low"].iloc[c1])*0.5
        target = recent["close"].iloc[-1] - (recent["high"].iloc[c1]-recent["low"].iloc[c1])*1.5
        conf = abs(recent["high"].iloc[c1]-recent["low"].iloc[c1])/(recent["close"].iloc[-1]+1e-6)*100
        return (-1, entry, sl, target, conf)

def detect_ifvg(df):
    if len(df)<5: return (0,0,0)
    fvg = detect_fair_value_gap(df, -1)
    if not fvg: return (0,0,0)
    upper, lower = fvg
    cur = df["close"].iloc[-1]
    if cur < lower: return (-1, lower, upper)
    if cur > upper: return (1, lower, upper)
    return (0,0,0)

def get_hour_open(symbol):
    with CACHE_LOCK:
        return GLOBAL_LIVE_FEED_CACHE.get(symbol, {}).get("ltp", 0.0)

def hourly_discount_filter(sym, price, side):
    hour_open = get_hour_open(sym)
    if hour_open == 0: return True
    if side == "BUY": return price < hour_open
    else: return price > hour_open

def position_size(capital, risk_pct, entry, sl):
    risk_amt = capital * (risk_pct/100.0)
    price_risk = abs(entry - sl)
    if price_risk <= 1e-6: return (0,0)
    lot = risk_amt / price_risk
    return (lot, risk_amt)

# -------------------- Historical Data Refresher (yfinance) --------------------
def historical_refresher():
    """Fetch 1m/5m/15m/1h data every 5 minutes from yfinance."""
    while True:
        try:
            for interval in ["1m", "5m", "15m", "1h"]:
                for sym_info in SYMBOLS_YF:
                    sym = sym_info["symbol"]
                    try:
                        ticker = yf.Ticker(sym)
                        end = datetime.datetime.now()
                        start = end - datetime.timedelta(days=7)
                        df = ticker.history(start=start, end=end, interval=interval)
                        if not df.empty:
                            df.columns = [c.lower() for c in df.columns]
                            with HIST_LOCK:
                                historical_dfs[interval][sym] = df
                    except Exception as e:
                        logger.error(f"Historical fetch error {sym} {interval}: {e}")
                    time.sleep(1)  # avoid rate limits
            logger.info("Historical data refreshed")
        except Exception as e:
            logger.error(f"Historical refresher error: {e}")
        time.sleep(300)

price_history = {"^NSEI": deque(maxlen=100), "^NSEBANK": deque(maxlen=100), "^BSESN": deque(maxlen=100)}

def fetch_options_chain(symbol):
    return {"pcr": 1.0, "max_oi_call": 0, "max_oi_put": 0, "total_oi": 0}

def process_symbol(sym_info):
    sym = sym_info["symbol"]
    name = sym_info["name"]
    with CACHE_LOCK:
        ltp = GLOBAL_LIVE_FEED_CACHE.get(sym, {}).get("ltp", 0)
    if ltp == 0: return None
    price_history[sym].append(ltp)
    if len(price_history[sym]) < 20: return None

    hist = list(price_history[sym])
    indices = pd.date_range(end=datetime.datetime.now(), periods=len(hist), freq='S')
    df = pd.DataFrame({
        "open": hist, "high": hist, "low": hist, "close": hist, "volume": 1
    }, index=indices)
    df["high"] = df["high"] * 1.0001
    df["low"] = df["low"] * 0.9999

    closes = df["close"].values
    high = df["high"].values
    low = df["low"].values
    current = ltp

    ema20 = calculate_ema(closes,20)[-1] if len(closes)>=20 else current
    ema50 = calculate_ema(closes,50)[-1] if len(closes)>=50 else current
    rsi = calculate_rsi(closes,14)
    atr = calculate_atr(high, low, closes, 14)
    vwap = calculate_vwap(df)

    bos, _ = detect_bos_choch(df)
    mss, mss_type = detect_market_structure_shift(df)
    crt_sig, _, sl, target, conf = detect_crt_setup(df)
    ifvg_sig, _, _ = detect_ifvg(df)

    final_signal = 0
    score = 0
    if crt_sig != 0:
        score += 2
        final_signal = crt_sig
    if ifvg_sig != 0 and ifvg_sig == final_signal:
        score += 2
    if mss and ((mss_type == "MSS_UP" and final_signal==1) or (mss_type=="MSS_DOWN" and final_signal==-1)):
        score += 1
    if bos and ((bos=="BOS_UP" and final_signal==1) or (bos=="BOS_DOWN" and final_signal==-1)):
        score += 1
    if score < 4: return None

    action = "BUY" if final_signal == 1 else "SELL"
    entry_price = current
    stop_loss = sl if sl != 0 else (current - atr*1.5 if final_signal==1 else current + atr*1.5)
    target_price = target if target != 0 else (current + atr*2.0 if final_signal==1 else current - atr*2.0)

    if not hourly_discount_filter(sym, current, action):
        return None
    lot, risk = position_size(CAPITAL_BASE, RISK_PERCENT, entry_price, stop_loss)
    if lot <= 0: return None

    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "asset_name": name, "asset_symbol": sym, "action": action,
        "entry_price": entry_price, "stop_loss": stop_loss, "target_price": target_price,
        "lot_size": lot, "risk_amount": risk, "smc_score": score, "crt_score": conf,
        "status": "OPEN"
    }

# -------------------- Trade Manager --------------------
class TradeManager:
    def __init__(self):
        self.active = {}
    def open(self, trade: dict) -> int:
        tid = log_trade_to_db(trade)
        trade["id"] = tid
        trade["peak"] = trade["entry_price"]
        trade["trail_activated"] = False
        self.active[tid] = trade
        return tid
    def update_price(self, tid: int, price: float):
        trade = self.active.get(tid)
        if not trade: return
        action = trade["action"]
        entry = trade["entry_price"]
        sl = trade["stop_loss"]
        target = trade["target_price"]
        if action == "BUY":
            if price >= target:
                self.close(tid, price, "TARGET")
                return
            if price <= sl:
                self.close(tid, price, "STOP_LOSS")
                return
            if ENABLE_TRAILING_STOP:
                if price > trade["peak"]:
                    trade["peak"] = price
                if not trade["trail_activated"] and (price - entry)/entry*100 >= TRAILING_ACTIVATION_PERCENT:
                    trade["trail_activated"] = True
                if trade["trail_activated"]:
                    new_sl = trade["peak"] * (1 - TRAILING_STOP_DISTANCE/100)
                    if new_sl > sl:
                        trade["stop_loss"] = new_sl
                        conn = sqlite3.connect("trades.db")
                        conn.execute("UPDATE trades SET stop_loss=? WHERE id=?", (new_sl, tid))
                        conn.commit()
                        conn.close()
        else:
            if price <= target:
                self.close(tid, price, "TARGET")
                return
            if price >= sl:
                self.close(tid, price, "STOP_LOSS")
                return
            if ENABLE_TRAILING_STOP:
                if price < trade["peak"]:
                    trade["peak"] = price
                if not trade["trail_activated"] and (entry - price)/entry*100 >= TRAILING_ACTIVATION_PERCENT:
                    trade["trail_activated"] = True
                if trade["trail_activated"]:
                    new_sl = trade["peak"] * (1 + TRAILING_STOP_DISTANCE/100)
                    if new_sl < sl:
                        trade["stop_loss"] = new_sl
                        conn = sqlite3.connect("trades.db")
                        conn.execute("UPDATE trades SET stop_loss=? WHERE id=?", (new_sl, tid))
                        conn.commit()
                        conn.close()
    def close(self, tid, exit_price, reason):
        trade = self.active.pop(tid, None)
        if trade:
            pnl = (exit_price - trade["entry_price"]) * trade["lot_size"] if trade["action"]=="BUY" else (trade["entry_price"] - exit_price) * trade["lot_size"]
            update_trade_exit(tid, exit_price, pnl)
            logger.info(f"Trade {tid} closed: {reason} PnL={pnl:.2f}")
            asyncio.create_task(send_telegram(f"🔒 Trade closed: {trade['asset_name']} {trade['action']} at {exit_price:.2f}, PnL ₹{pnl:.2f} ({reason})"))

trade_mgr = TradeManager()

# -------------------- Telegram --------------------
telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)

async def send_telegram(text):
    try:
        await telegram_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

async def send_photo(buf, caption=""):
    try:
        buf.seek(0)
        await telegram_bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=InputFile(buf, "chart.png"), caption=caption)
    except Exception as e:
        logger.error(f"Photo send error: {e}")

async def send_voice(text, lang="hi"):
    try:
        tts = gTTS(text=text, lang=lang, slow=False)
        audio = io.BytesIO()
        tts.write_to_fp(audio)
        audio.seek(0)
        await telegram_bot.send_voice(chat_id=TELEGRAM_CHAT_ID, voice=InputFile(audio, "voice.mp3"))
    except Exception as e:
        logger.error(f"Voice error: {e}")

def gemini_report(trade):
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = f"Generate a short trade report in HINDI without asterisks. Trade: {trade['asset_name']} {trade['action']} Entry {trade['entry_price']} SL {trade['stop_loss']} Target {trade['target_price']} Risk ₹{trade['risk_amount']}."
        resp = model.generate_content(prompt)
        return resp.text.strip()
    except:
        return f"व्यापार {trade['action']} {trade['asset_name']} में प्रवेश किया गया।"

# -------------------- Chart --------------------
def generate_chart(df, sym, action, entry, sl, target):
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(12,6))
    if "timestamp" in df.columns:
        dates = df["timestamp"].tail(50)
    else:
        dates = df.index[-50:]
    closes = df["close"].tail(50)
    ax.plot(dates, closes, color="cyan", lw=1.5)
    ax.axhline(y=entry, color="green", ls="--", label=f"Entry {entry:.2f}")
    ax.axhline(y=sl, color="red", ls="--", label=f"SL {sl:.2f}")
    ax.axhline(y=target, color="blue", ls="--", label=f"Target {target:.2f}")
    ax.set_title(f"{sym} - {action} Signal")
    ax.legend()
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf

# -------------------- Scanner --------------------
async def run_scanner():
    logger.info("Scanner started with yfinance")
    last_trade_time = {}
    while True:
        for sym_info in SYMBOLS_YF:
            if sym_info["name"] != "Nifty 50":
                continue
            trade = process_symbol(sym_info)
            if trade and ENABLE_AUTO_TRADE:
                now = time.time()
                sym = trade["asset_symbol"]
                if sym in last_trade_time and now - last_trade_time[sym] < 300:
                    continue
                last_trade_time[sym] = now
                tid = trade_mgr.open(trade)
                await send_telegram(
                    f"🚨 AUTO TRADE\n{trade['asset_name']} {trade['action']}\n"
                    f"Entry {trade['entry_price']:.2f} SL {trade['stop_loss']:.2f} Target {trade['target_price']:.2f}\n"
                    f"Lot {trade['lot_size']:.4f} Risk ₹{trade['risk_amount']:.2f} Score {trade['smc_score']}"
                )
                if sym in price_history and len(price_history[sym]) > 10:
                    hist = list(price_history[sym])
                    indices = pd.date_range(end=datetime.datetime.now(), periods=len(hist), freq='S')
                    df_chart = pd.DataFrame({"close": hist}, index=indices)
                    df_chart["timestamp"] = indices
                    loop = asyncio.get_running_loop()
                    buf = await loop.run_in_executor(None, generate_chart, df_chart,
                                                     trade["asset_name"], trade["action"],
                                                     trade["entry_price"], trade["stop_loss"],
                                                     trade["target_price"])
                    await send_photo(buf, caption=f"{trade['asset_name']} {trade['action']} signal")
                await send_voice(f"{trade['asset_name']} पर {trade['action']} का ऑटो ट्रेड लिया गया। प्रवेश {trade['entry_price']:.2f}")
                report = gemini_report(trade)
                await send_telegram(report)
            elif trade and not ENABLE_AUTO_TRADE:
                await send_telegram(
                    f"📈 SIGNAL (Manual)\n{trade['asset_name']} {trade['action']}\n"
                    f"Entry {trade['entry_price']:.2f} SL {trade['stop_loss']:.2f} Target {trade['target_price']:.2f}"
                )
        await asyncio.sleep(1)

async def trade_management_loop():
    while True:
        for tid, trade in list(trade_mgr.active.items()):
            with CACHE_LOCK:
                price = GLOBAL_LIVE_FEED_CACHE.get(trade["asset_symbol"], {}).get("ltp", 0)
            if price > 0:
                trade_mgr.update_price(tid, price)
        await asyncio.sleep(0.5)

# -------------------- Telegram Bot --------------------
async def start_cmd(update, ctx):
    await update.message.reply_text("Bot active (yfinance mode). Commands: /status, /ledger, /positions, /close <id>")
async def status_cmd(update, ctx):
    await update.message.reply_text(f"✅ Running. Auto trade: {ENABLE_AUTO_TRADE}, Active trades: {len(trade_mgr.active)}")
async def ledger_cmd(update, ctx):
    conn = sqlite3.connect("trades.db")
    cur = conn.cursor()
    cur.execute("SELECT timestamp, asset_name, action, entry_price, status, pnl FROM trades ORDER BY timestamp DESC LIMIT 10")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("No trades")
        return
    msg = "📜 Recent trades:\n"
    for r in rows:
        msg += f"{r[0][:16]} | {r[1]} | {r[2]} | {r[3]:.2f} | {r[4]} | PnL {r[5] if r[5] else 0}\n"
    await update.message.reply_text(msg)
async def positions_cmd(update, ctx):
    if not trade_mgr.active:
        await update.message.reply_text("No open positions")
        return
    msg = "📊 Open positions:\n"
    for tid, t in trade_mgr.active.items():
        msg += f"ID {tid}: {t['asset_name']} {t['action']} Entry {t['entry_price']:.2f} SL {t['stop_loss']:.2f}\n"
    await update.message.reply_text(msg)
async def close_cmd(update, ctx):
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: /close <trade_id>")
        return
    try:
        tid = int(args[0])
        if tid in trade_mgr.active:
            sym = trade_mgr.active[tid]["asset_symbol"]
            with CACHE_LOCK:
                price = GLOBAL_LIVE_FEED_CACHE.get(sym, {}).get("ltp", 0)
            if price > 0:
                trade_mgr.close(tid, price, "MANUAL")
                await update.message.reply_text(f"Trade {tid} closed at {price:.2f}")
            else:
                await update.message.reply_text("Cannot get price")
        else:
            await update.message.reply_text("Trade ID not found")
    except:
        await update.message.reply_text("Invalid ID")

def run_telegram_bot():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("ledger", ledger_cmd))
    app.add_handler(CommandHandler("positions", positions_cmd))
    app.add_handler(CommandHandler("close", close_cmd))
    app.run_polling(signal_handlers=False)

# -------------------- Flask --------------------
flask_app = flask.Flask(__name__)

@flask_app.route("/")
def index():
    return "Indian Indices Scalping Bot - Running (yfinance mode)"

@flask_app.route("/test_telegram")
def test_telegram():
    asyncio.run(send_telegram("✅ Bot connectivity test from Flask"))
    return "Test message sent"

@flask_app.route("/status")
def status():
    return f"Auto trade: {ENABLE_AUTO_TRADE}, Active trades: {len(trade_mgr.active)}"

def run_flask():
    port = int(os.getenv("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False)

# -------------------- Main --------------------
def main():
    init_database()
    # Rebuild DB from CSV if needed
    conn = sqlite3.connect("trades.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM trades")
    if cur.fetchone()[0] == 0 and os.path.exists("backup_nse_ledger.csv"):
        with open("backup_nse_ledger.csv", "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cur.execute("""INSERT INTO trades (timestamp, asset_name, asset_symbol, action,
                    entry_price, stop_loss, target_price, lot_size, risk_amount, smc_score, crt_score, status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (row["timestamp"], row["asset_name"], row["asset_symbol"], row["action"],
                     float(row["entry_price"]), float(row["stop_loss"]), float(row["target_price"]),
                     float(row["lot_size"]), float(row["risk_amount"]), float(row["smc_score"]),
                     float(row["crt_score"]), row["status"]))
        conn.commit()
        logger.info("Database restored from CSV backup")
    conn.close()

    # Start threads
    threading.Thread(target=yfinance_live_feed, daemon=True).start()
    threading.Thread(target=historical_refresher, daemon=True).start()
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=run_telegram_bot, daemon=True).start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(run_scanner())
    loop.create_task(trade_management_loop())
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        loop.close()

if __name__ == "__main__":
    main()
