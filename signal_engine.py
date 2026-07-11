from datetime import datetime, timedelta
from typing import Optional
from config import MIN_RISK_REWARD, MAX_SL_BUFFER, SIGNAL_COOLDOWN, SCORE_WEIGHTS
from logger_setup import signal_log, error_log
import hashlib
import json

class Signal:
    def __init__(self, direction, entry, sl, tp, rr, confidence, reason=""):
        self.direction = direction
        self.entry = entry
        self.sl = sl
        self.tp = tp
        self.rr = rr
        self.confidence = confidence
        self.reason = reason
        self.timestamp = datetime.now()
        self.layers = []

    def to_dict(self):
        return {
            "direction": self.direction,
            "entry": self.entry,
            "sl": self.sl,
            "tp": self.tp,
            "rr": self.rr,
            "confidence": self.confidence,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
            "layers": self.layers
        }

class SignalEngine:
    def __init__(self, structure_engine):
        self.structure_engine = structure_engine
        self.last_signal = None
        self.last_signal_time = None
        self._duplicate_cache = {}   # hash_key -> timestamp

    def _clean_duplicate_cache(self):
        now = datetime.now()
        expired = [k for k, ts in self._duplicate_cache.items() if (now - ts).total_seconds() > 600]  # 10 min TTL
        for k in expired:
            del self._duplicate_cache[k]

    def _compute_signal_hash(self, symbol, direction, entry, struct):
        # Create a unique fingerprint of the signal context
        data = {
            "symbol": symbol,
            "direction": direction,
            "entry": round(entry, 2),
            "trend": struct.trend,
            "bos": struct.bos,
            "cho": struct.cho,
            "clone_ratio": round(struct.clone_ratio, 3),
            "lock_point": round(struct.lock_point, 2) if struct.lock_point else None,
        }
        json_str = json.dumps(data, sort_keys=True)
        return hashlib.md5(json_str.encode()).hexdigest()

    def _score_confidence(self, struct, ohlcv):
        score = 0
        if struct.clone_complete:
            score += SCORE_WEIGHTS["clone_accuracy"]
        elif struct.clone_ratio > 0.8:
            score += SCORE_WEIGHTS["clone_accuracy"] * 0.5
        if struct.trend != "NEUTRAL":
            score += SCORE_WEIGHTS["trend_quality"]
        if ohlcv and ohlcv.get("volume", 0) > 100000:
            score += SCORE_WEIGHTS["volume_quality"]
        if not struct.manipulation:
            score += SCORE_WEIGHTS["structure_quality"] * 0.7
        if struct.accumulation or struct.distribution:
            score += SCORE_WEIGHTS["structure_quality"] * 0.3
        if struct.liquidity_sweep:
            score += SCORE_WEIGHTS["liquidity_quality"]
        score += SCORE_WEIGHTS["market_session"]
        if 0.9 <= struct.clone_ratio <= 1.1:
            score += SCORE_WEIGHTS["historical_similarity"]
        return min(100, score)

    def generate_signal(self, symbol: str) -> Optional[Signal]:
        self._clean_duplicate_cache()

        struct = self.structure_engine.get_structure(symbol)
        ohlcv = self.structure_engine.data_store.get(symbol)

        if self.last_signal_time:
            elapsed = (datetime.now() - self.last_signal_time).total_seconds()
            if elapsed < SIGNAL_COOLDOWN:
                return None

        if struct.trend == "NEUTRAL":
            return None
        if not (struct.accumulation or struct.distribution):
            return None
        if not struct.clone_complete:
            return None
        if not struct.liquidity_sweep:
            return None
        if not struct.cho:
            return None
        if not struct.bos:
            return None
        if not ohlcv or ohlcv.get("volume", 0) < 100000:
            return None

        direction = "BUY" if struct.trend == "UP" else "SELL"
        entry = ohlcv["close"]
        if direction == "BUY":
            sl = struct.recent_low - MAX_SL_BUFFER
            tp = entry + struct.clone_length * struct.clone_ratio
        else:
            sl = struct.recent_high + MAX_SL_BUFFER
            tp = entry - struct.clone_length * struct.clone_ratio

        risk = abs(entry - sl)
        reward = abs(tp - entry)
        if risk == 0:
            return None
        rr = reward / risk
        if rr < MIN_RISK_REWARD:
            return None

        confidence = self._score_confidence(struct, ohlcv)
        if confidence < 70:
            return None

        # Enhanced duplicate check using hash
        sig_hash = self._compute_signal_hash(symbol, direction, entry, struct)
        if sig_hash in self._duplicate_cache:
            return None
        self._duplicate_cache[sig_hash] = datetime.now()
        if len(self._duplicate_cache) > 1000:
            oldest = min(self._duplicate_cache, key=self._duplicate_cache.get)
            del self._duplicate_cache[oldest]

        sig = Signal(direction, entry, sl, tp, rr, confidence)
        sig.reason = f"Clone Complete, {struct.trend} trend, RR {rr:.2f}"
        sig.layers = ["Trend", "Structure", "Clone", "Liquidity", "CHOCH", "BOS", "Volume", "RR", "Confidence", "Final"]
        self.last_signal = sig
        self.last_signal_time = sig.timestamp
        signal_log.info(f"SIGNAL: {sig.direction} at {sig.entry}, SL={sig.sl}, TP={sig.tp}, RR={sig.rr:.2f}, Conf={confidence}")
        return sig

    def get_last_signal(self):
        return self.last_signal
