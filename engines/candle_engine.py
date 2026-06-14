# ============================================================================
# START MODULE: CandleEngine
# Version: 1.0.0
# Dependencies: config, threading, numpy, datetime
# Public Functions: update, get_candles, ema
# Private Functions: _update_candle
# Upgrade Notes: Replace with different timeframe or tick aggregation logic.
# ============================================================================

import threading
from datetime import datetime
from typing import Dict, List
import numpy as np

from config.config import Config

class CandleEngine:
    def __init__(self):
        self.candles: Dict[str, Dict[int, List[Dict]]] = {}
        self._lock = threading.RLock()
        self.timeframes = {Config.TIMEFRAME_1M: '1m', Config.TIMEFRAME_5M: '5m', Config.TIMEFRAME_15M: '15m'}
        for symbol in Config.SYMBOLS:
            self.candles[symbol] = {}
            for tf in self.timeframes.keys():
                self.candles[symbol][tf] = []
    
    def update(self, symbol: str, price: float, volume: int, timestamp: datetime):
        if price <= 0 or np.isnan(price):
            return
        with self._lock:
            for tf in self.timeframes.keys():
                self._update_candle(symbol, price, volume, timestamp, tf)
    
    def _update_candle(self, symbol: str, price: float, volume: int, ts: datetime, tf: int):
        ts_seconds = int(ts.timestamp())
        candle_start_ts = ts_seconds - (ts_seconds % tf)
        start_time = datetime.fromtimestamp(candle_start_ts)
        candles_list = self.candles[symbol][tf]
        if not candles_list or candles_list[-1]['timestamp'] != start_time:
            if candles_list and not candles_list[-1]['complete']:
                candles_list[-1]['complete'] = True
            new_candle = {
                'timestamp': start_time,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': volume,
                'complete': False
            }
            candles_list.append(new_candle)
            if len(candles_list) > 500:
                candles_list.pop(0)
        else:
            candle = candles_list[-1]
            candle['high'] = max(candle['high'], price)
            candle['low'] = min(candle['low'], price)
            candle['close'] = price
            candle['volume'] += volume
    
    def get_candles(self, symbol: str, tf: int, count: int = 100) -> List[Dict]:
        with self._lock:
            return self.candles[symbol][tf][-count:]
    
    def ema(self, series: List[float], period: int) -> List[float]:
        if len(series) < period:
            return []
        multiplier = 2 / (period + 1)
        ema = [series[0]]
        for i in range(1, len(series)):
            if np.isnan(series[i]) or np.isnan(ema[-1]):
                ema.append(series[i])
            else:
                ema.append((series[i] - ema[-1]) * multiplier + ema[-1])
        return ema

# ============================================================================
# END MODULE: CandleEngine
# ============================================================================
