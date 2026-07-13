import time
import threading
import logging
import math
from queue import Queue, Empty
from typing import Dict, List, Optional
from collections import deque

from utils import safe_divide

class StructureEngine(threading.Thread):
    def __init__(self, config, data_queue: Queue, out_queue: Queue, storage_queue: Queue):
        super().__init__(daemon=True)
        self.config = config
        self.data_queue = data_queue
        self.out_queue = out_queue
        self.storage_queue = storage_queue
        self.running = False
        self.candle_window = 15 * 60
        self.current_candle = None
        self.asset_candles = {}       # asset -> list of completed candles
        self.atr_period = 14
        self.atr_values = {}          # asset -> deque of true ranges
        self.structure_cache = {}

        # Weights (from config)
        self.w = {
            "clone": config["WEIGHT_CLONE_COMPLETION"] / 100.0,
            "origin": config["WEIGHT_ORIGIN_MAPPING"] / 100.0,
            "liquidity": config["WEIGHT_LIQUIDITY_SWEEPS"] / 100.0,
            "structure": config["WEIGHT_STRUCTURE_ALIGNMENT"] / 100.0,
            "trap": config["WEIGHT_TRAP_FILTER"] / 100.0,
            "premium": config["WEIGHT_PREMIUM_DISCOUNT"] / 100.0,
        }

    def run(self):
        self.running = True
        logging.info("StructureEngine started.")
        while self.running:
            try:
                item = self.data_queue.get(timeout=0.5)
            except Empty:
                continue
            if item is None:
                continue
            self._process_raw(item)
        logging.info("StructureEngine stopped.")

    def stop(self):
        self.running = False

    def _process_raw(self, data: Dict):
        asset = data.get("asset")
        price = data.get("close")
        if asset is None or price is None:
            return
        ts = data.get("timestamp", time.time())
        boundary = int(ts // self.candle_window) * self.candle_window

        if self.current_candle is None or self.current_candle["asset"] != asset or self.current_candle["start_time"] != boundary:
            if self.current_candle is not None:
                self._close_candle(self.current_candle)
            self.current_candle = {
                "asset": asset,
                "start_time": boundary,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": data.get("volume", 0),
                "trades": 1
            }
        else:
            c = self.current_candle
            c["high"] = max(c["high"], price)
            c["low"] = min(c["low"], price)
            c["close"] = price
            c["volume"] += data.get("volume", 0)
            c["trades"] += 1

    def _close_candle(self, candle: Dict):
        asset = candle["asset"]
        if asset not in self.asset_candles:
            self.asset_candles[asset] = []
        self.asset_candles[asset].append(candle)
        if len(self.asset_candles[asset]) > 500:
            self.asset_candles[asset] = self.asset_candles[asset][-500:]

        self._update_atr(asset, candle)
        structure = self._compute_structure(asset, candle)
        if structure:
            self.out_queue.put({
                "asset": asset,
                "candle": candle,
                "structure": structure,
                "score": structure.get("score", 0),
                "timestamp": time.time()
            })
            self.storage_queue.put(("candle", candle))
            self.storage_queue.put(("structure", structure))

    def _update_atr(self, asset: str, candle: Dict):
        if asset not in self.atr_values:
            self.atr_values[asset] = deque(maxlen=self.atr_period)
        history = self.asset_candles[asset]
        if len(history) >= 2:
            prev = history[-2]
            tr = max(candle["high"] - candle["low"],
                     abs(candle["high"] - prev["close"]),
                     abs(candle["low"] - prev["close"]))
        else:
            tr = candle["high"] - candle["low"]
        self.atr_values[asset].append(tr)

    def get_atr(self, asset: str) -> float:
        vals = self.atr_values.get(asset)
        if not vals:
            return 0.0
        return sum(vals) / len(vals)

    def _compute_structure(self, asset: str, candle: Dict) -> Dict:
        atr = self.get_atr(asset)
        history = self.asset_candles.get(asset, [])
        if len(history) < 20:
            return {"score": 0, "ready": False}

        # Simple support/resistance from recent pivots (simplified)
        recent = history[-20:]
        highs = [c["high"] for c in recent]
        lows = [c["low"] for c in recent]
        closes = [c["close"] for c in recent]
        recent_high = max(highs)
        recent_low = min(lows)
        avg_volume = sum(c["volume"] for c in recent) / len(recent) + 1e-9
        close = candle["close"]
        volume = candle["volume"]

        # Pattern detection (simplified but deterministic)
        range_mid = (recent_high + recent_low) / 2
        accumulation = close < range_mid and volume > 1.2 * avg_volume
        distribution = close > range_mid and volume > 1.2 * avg_volume
        origin_shift = close > recent_high or close < recent_low
        origin_confirm = close > recent_high   # for buy
        clone_complete = True  # placeholder
        structure_confirm = True
        manipulation_phase = False
        structure_mismatch = False
        clone_ratio_variance = False

        # Risk reward
        entry = close
        sl = recent_low if close > recent_low else recent_high
        tp = recent_high if close > recent_low else recent_low
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr = safe_divide(reward, risk, default=0.0)
        rr_ok = rr >= self.config["MIN_RISK_REWARD"]

        # Weighted scoring (each component contributes up to its weight * 100)
        score = 0.0
        score += self.w["clone"] * 100 if clone_complete else 0
        score += self.w["origin"] * 100 if origin_shift else 0
        score += self.w["liquidity"] * 100 if (accumulation or distribution) else 0
        score += self.w["structure"] * 100 if structure_confirm else 0
        score += self.w["trap"] * 100 if not manipulation_phase else 0
        score += self.w["premium"] * 100 if (not structure_mismatch and not clone_ratio_variance) else 0
        score = clamp(score, 0, 100)

        return {
            "score": score,
            "clone_complete": clone_complete,
            "origin_shift": origin_shift,
            "accumulation_confirm": accumulation,
            "distribution_confirm": distribution,
            "origin_confirm": origin_confirm,
            "structure_confirm": structure_confirm,
            "manipulation_phase": manipulation_phase,
            "structure_mismatch": structure_mismatch,
            "clone_ratio_variance": clone_ratio_variance,
            "risk_reward": rr,
            "risk_reward_ok": rr_ok,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "entry_zone": f"{recent_low:.2f}-{range_mid:.2f}",
            "exit_zone": f"{range_mid:.2f}-{recent_high:.2f}",
            "supports": [recent_low],
            "resistances": [recent_high],
            "atr": atr,
            "ready": score >= 70
        }

    @staticmethod
    def clamp(val, minv, maxv):
        return max(minv, min(val, maxv))
