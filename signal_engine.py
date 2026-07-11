import logging
from collections import deque
from datetime import datetime
from cache import cache_get, cache_set
from logger_setup import system_log, error_log

class Structure:
    def __init__(self):
        self.origin = None
        self.clone_complete = False
        self.clone_length = 0.0
        self.clone_ratio = 0.0
        self.lock_point = None
        self.accumulation = False
        self.manipulation = False
        self.distribution = False
        self.trend = "NEUTRAL"
        self.confidence = 0.0
        self.swings = []
        self.recent_high = None
        self.recent_low = None
        self.liquidity_sweep = False
        self.cho = False
        self.bos = False

    def to_dict(self):
        return {
            "origin": self.origin,
            "clone_complete": self.clone_complete,
            "clone_length": self.clone_length,
            "clone_ratio": self.clone_ratio,
            "lock_point": self.lock_point,
            "accumulation": self.accumulation,
            "manipulation": self.manipulation,
            "distribution": self.distribution,
            "trend": self.trend,
            "confidence": self.confidence,
            "recent_high": self.recent_high,
            "recent_low": self.recent_low,
            "liquidity_sweep": self.liquidity_sweep,
            "cho": self.cho,
            "bos": self.bos,
        }

class StructureEngine:
    def __init__(self, data_store):
        self.data_store = data_store
        self.structure = Structure()
        self.history = {}

    def _compute_atr(self, highs, lows, closes, period=14):
        if len(closes) < period + 1:
            return 0.0
        tr = [max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
              for i in range(1, len(closes))]
        if len(tr) < period:
            return 0.0
        return sum(tr[-period:]) / period

    def update(self, symbol: str):
        ohlcv = self.data_store.get(symbol)
        if not ohlcv or ohlcv["time"] is None:
            return

        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=200)
        self.history[symbol].append(ohlcv)
        if len(self.history[symbol]) < 20:
            return

        closes = [c["close"] for c in self.history[symbol]]
        highs = [c["high"] for c in self.history[symbol]]
        lows = [c["low"] for c in self.history[symbol]]

        # ATR for noise filter
        atr = self._compute_atr(highs, lows, closes, period=14)
        min_swing_amplitude = atr * 0.5 if atr > 0 else 5.0  # fallback if no ATR

        # Detect swing points with improved logic: look for pivot with 3-bar confirmation
        swing_highs = []
        swing_lows = []
        n = len(highs)
        for i in range(3, n-3):
            # High pivot: high[i] is greater than previous 3 and next 3
            if all(highs[i] > highs[i-j] for j in range(1, 4)) and all(highs[i] > highs[i+j] for j in range(1, 4)):
                # Check amplitude
                if highs[i] - min(highs[i-3:i+4]) >= min_swing_amplitude:
                    swing_highs.append((highs[i], i))
            # Low pivot: low[i] is lower than previous 3 and next 3
            if all(lows[i] < lows[i-j] for j in range(1, 4)) and all(lows[i] < lows[i+j] for j in range(1, 4)):
                if max(lows[i-3:i+4]) - lows[i] >= min_swing_amplitude:
                    swing_lows.append((lows[i], i))

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return

        struct = Structure()
        last_high = swing_highs[-1]
        last_low = swing_lows[-1]
        struct.recent_high = last_high[0]
        struct.recent_low = last_low[0]

        if last_high[1] > last_low[1]:
            struct.trend = "UP"
        else:
            struct.trend = "DOWN"

        if len(swing_highs) >= 3:
            h1 = swing_highs[-2]
            h2 = swing_highs[-1]
            clone_len = abs(h2[0] - h1[0])
            struct.clone_length = clone_len
            if len(swing_highs) >= 4:
                prev_len = abs(swing_highs[-3][0] - swing_highs[-2][0])
                struct.clone_ratio = clone_len / prev_len if prev_len > 0 else 1.0
            else:
                struct.clone_ratio = 1.0
            if struct.trend == "UP":
                target = h1[0] + clone_len
                struct.clone_complete = h2[0] >= target
            else:
                target = h1[0] - clone_len
                struct.clone_complete = h2[0] <= target

        struct.lock_point = last_high[0] if struct.trend == "UP" else last_low[0]

        recent_range = max(highs[-10:]) - min(lows[-10:])
        avg_range = sum(highs[-i] - lows[-i] for i in range(1, 11)) / 10
        if recent_range < avg_range * 0.7:
            if struct.trend == "UP":
                struct.accumulation = True
            else:
                struct.distribution = True

        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            if struct.trend == "UP" and swing_highs[-1][0] > swing_highs[-2][0]:
                if closes[-1] < swing_highs[-1][0]:
                    struct.manipulation = True

        if len(swing_highs) >= 3:
            if struct.trend == "UP":
                if highs[-1] > swing_highs[-2][0] and closes[-1] < swing_highs[-2][0]:
                    struct.liquidity_sweep = True
            else:
                if lows[-1] < swing_lows[-2][0] and closes[-1] > swing_lows[-2][0]:
                    struct.liquidity_sweep = True

        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            if struct.trend == "UP":
                if lows[-1] < swing_lows[-1][0]:
                    struct.cho = True
            else:
                if highs[-1] > swing_highs[-1][0]:
                    struct.cho = True

        if len(swing_highs) >= 3:
            if struct.trend == "UP":
                if highs[-1] > swing_highs[-2][0]:
                    struct.bos = True
            else:
                if lows[-1] < swing_lows[-2][0]:
                    struct.bos = True

        struct.swings = (swing_highs, swing_lows)
        self.structure = struct
        cache_set(f"structure_{symbol}", struct)

    def get_structure(self, symbol: str) -> Structure:
        return self.structure
