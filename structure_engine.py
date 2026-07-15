import time
import threading
import logging
from queue import Queue, Empty
from typing import Dict, List
from collections import deque
import math

from utils import safe_divide, clamp

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
        self.asset_candles = {}
        self.atr_period = 14
        self.atr_values = {}
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

        options_keys = [
            "total_call_oi", "total_put_oi", "pcr",
            "highest_call_oi_strike", "highest_put_oi_strike",
            "call_oi_skew", "put_oi_skew"
        ]

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
            for k in options_keys:
                if k in data:
                    self.current_candle[k] = data[k]
        else:
            c = self.current_candle
            c["high"] = max(c["high"], price)
            c["low"] = min(c["low"], price)
            c["close"] = price
            c["volume"] += data.get("volume", 0)
            c["trades"] += 1
            for k in options_keys:
                if k in data:
                    c[k] = data[k]

    def _close_candle(self, candle: Dict):
        asset = candle["asset"]
        if asset not in self.asset_candles:
            self.asset_candles[asset] = []
        self.asset_candles[asset].append(candle)
        if len(self.asset_candles[asset]) > 500:
            self.asset_candles[asset] = self.asset_candles[asset][-500:]

        self._update_atr(asset, candle)
        structure = self._compute_structure(asset, candle)
        if structure and structure.get("score", 0) > 0:
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

        recent = history[-20:]
        highs = [c["high"] for c in recent]
        lows = [c["low"] for c in recent]
        recent_high = max(highs)
        recent_low = min(lows)
        avg_volume = sum(c["volume"] for c in recent) / len(recent) + 1e-9
        close = candle["close"]
        volume = candle["volume"]

        range_pct = (recent_high - recent_low) / recent_low * 100
        accumulation = range_pct < 1.0 and volume > 1.2 * avg_volume
        distribution = range_pct > 2.0 and volume > 1.5 * avg_volume

        # ---- ATR‑WEIGHTED ADAPTIVE VOLUME RATIO ----
        atr_pct = safe_divide(atr, close) * 100.0
        adaptive_multiplier = clamp(1.2 + (atr_pct * 0.5), 1.3, 2.2)
        volume_breakout_confirmed = volume >= (avg_volume * adaptive_multiplier)

        origin_shift = (close > recent_high or close < recent_low) and volume_breakout_confirmed
        origin_confirm = close > recent_high and volume_breakout_confirmed

        clone_length = recent_high - recent_low
        clone_complete = False
        if volume_breakout_confirmed:
            if close > recent_high + clone_length * 0.5:
                clone_complete = True
            elif close < recent_low - clone_length * 0.5:
                clone_complete = True

        structure_confirm = True
        manipulation_phase = False
        structure_mismatch = False
        clone_ratio_variance = False

        # ---- INSTITUTIONAL OI SKEW METRICS ----
        pcr = candle.get("pcr", 1.0)
        resistance = candle.get("highest_call_oi_strike", close + 100)
        support = candle.get("highest_put_oi_strike", close - 100)
        call_skew = candle.get("call_oi_skew", 0.5)
        put_skew = candle.get("put_oi_skew", 0.5)

        # ---- MULTI‑ZONE ANTI‑TRAP FILTER ----
        oi_sentiment_conflict = False
        skew_imbalance = False
        if close > recent_high:
            if close >= (resistance - 10) and pcr < 0.95:
                oi_sentiment_conflict = True
            if call_skew > 0.58:
                skew_imbalance = True
        if close < recent_low:
            if close <= (support + 10) and pcr > 1.05:
                oi_sentiment_conflict = True
            if put_skew > 0.58:
                skew_imbalance = True

        entry = close
        if close > recent_low:
            sl = recent_low
            tp = recent_high + clone_length
        else:
            sl = recent_high
            tp = recent_low - clone_length

        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr = safe_divide(reward, risk, default=0.0)
        rr_ok = rr >= self.config["MIN_RISK_REWARD"]

        score = 0.0
        if clone_complete:
            score += self.w["clone"] * 100
        if origin_shift:
            score += self.w["origin"] * 100
        if accumulation or distribution:
            score += self.w["liquidity"] * 100
        if structure_confirm:
            score += self.w["structure"] * 100
        if not manipulation_phase:
            score += self.w["trap"] * 100
        if not structure_mismatch and not clone_ratio_variance:
            score += self.w["premium"] * 100

        if oi_sentiment_conflict:
            score -= 45
        if skew_imbalance:
            score -= 15
        score = clamp(score, 0, 100)

        logging.info(f"⚡ [METRICS] Spot: {close:.2f} | DynVolRatio: {volume/avg_volume:.2f}x (Req: {adaptive_multiplier:.2f}x) | PCR: {pcr} | Skews(C/P): {call_skew}/{put_skew} | Score: {score:.1f}")

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
            "entry_zone": f"{recent_low:.2f}-{recent_high:.2f}",
            "exit_zone": f"{entry + clone_length:.2f}-{entry + 2*clone_length:.2f}",
            "supports": [recent_low, support],
            "resistances": [recent_high, resistance],
            "atr": atr,
            "ready": score >= 75 and rr_ok and not oi_sentiment_conflict and not skew_imbalance
        }
