import time
import threading
import logging
from queue import Queue, Empty
from typing import Dict
from datetime import datetime

from utils import clamp

class SignalEngine(threading.Thread):
    def __init__(self, config, in_queue: Queue, out_queue: Queue, storage_queue: Queue, dashboard_queue: Queue):
        super().__init__(daemon=True)
        self.config = config
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.storage_queue = storage_queue
        self.dashboard_queue = dashboard_queue
        self.running = False
        self.app_state = None
        self.last_pre_alert = {}
        self.processed_candles = set()

    def run(self):
        self.running = True
        logging.info("SignalEngine started.")
        while self.running:
            try:
                item = self.in_queue.get(timeout=0.5)
            except Empty:
                continue
            if item is None:
                continue
            self._process_structure(item)
        logging.info("SignalEngine stopped.")

    def stop(self):
        self.running = False

    def _process_structure(self, struct_data: Dict):
        asset = struct_data.get("asset")
        candle = struct_data.get("candle")
        structure = struct_data.get("structure")
        if not asset or not candle or not structure:
            return

        today = datetime.now().date()
        if self.app_state:
            if self.app_state.last_signal_date != today:
                self.app_state.signal_count_today = 0
                self.app_state.last_signal_date = today
            if self.app_state.signal_count_today >= self.config["MAX_SIGNALS_PER_DAY"]:
                logging.debug(f"Daily max reached for {asset}")
                return

        # Pre-alert
        now = time.time()
        close_time = candle["start_time"] + 15 * 60
        time_to_close = close_time - now
        if 300 <= time_to_close <= 360:
            score = structure.get("score", 0)
            if score >= 70:
                msg = f"🚨 PRE-SIGNAL ALERT: Potential High-Probability Setup forming on {asset} within 5 minutes."
                logging.info(msg)
                self.dashboard_queue.put({"type": "pre_alert", "asset": asset, "message": msg, "score": score})
                self.storage_queue.put(("pre_alert", {"asset": asset, "time": now, "score": score}))

        key = f"{asset}_{candle['start_time']}"
        if key in self.processed_candles:
            return
        self.processed_candles.add(key)

        # Use the new `ready` flag from structure
        if not structure.get("ready", False):
            return

        clone_complete = structure.get("clone_complete", False)
        accumulation = structure.get("accumulation_confirm", False)
        distribution = structure.get("distribution_confirm", False)
        origin_shift = structure.get("origin_shift", False)
        origin_confirm = structure.get("origin_confirm", False)
        structure_confirm = structure.get("structure_confirm", False)

        direction = None
        if clone_complete and accumulation and origin_shift:
            direction = "BUY"
        elif clone_complete and distribution and origin_confirm and structure_confirm:
            direction = "SELL"

        if direction:
            signal = {
                "trade_id": f"{asset[:3]}{int(time.time()) % 1000000}",
                "asset": asset,
                "direction": direction,
                "entry": structure.get("entry", 0),
                "sl": structure.get("sl", 0),
                "tp": structure.get("tp", 0),
                "rr": structure.get("risk_reward", 0),
                "win_prob": clamp(60 + (structure.get("score", 0) - 70) * 0.5, 50, 95),
                "score": structure.get("score", 0),
                "strength": "High" if structure.get("score", 0) >= 85 else "Medium" if structure.get("score", 0) >= 70 else "Low",
                "time": datetime.now().isoformat(),
                "confluence_logic": f"{direction} confirmed: Clone={clone_complete}, Accum={accumulation}",
                "passed_layers": 9,
                "entry_zone": structure.get("entry_zone", ""),
                "exit_zone": structure.get("exit_zone", ""),
                "supports": structure.get("supports", []),
                "resistances": structure.get("resistances", []),
                "atr": structure.get("atr", 0),
            }
            self.dashboard_queue.put({"type": "signal", "signal": signal})
            self.storage_queue.put(("signal", signal))
            if self.app_state:
                self.app_state.signal_data = signal
                self.app_state.transition("ACTIVE_SIGNAL")
                self.app_state.signal_count_today += 1
            logging.info(f"Signal {direction} for {asset} ID {signal['trade_id']}")
