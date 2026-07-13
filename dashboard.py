import time
import threading
import logging
from queue import Queue, Empty
from typing import Dict

class Dashboard(threading.Thread):
    def __init__(self, config, dashboard_queue: Queue):
        super().__init__(daemon=True)
        self.config = config
        self.dashboard_queue = dashboard_queue
        self.running = False

    def run(self):
        self.running = True
        logging.info("Dashboard started.")
        while self.running:
            try:
                msg = self.dashboard_queue.get(timeout=0.5)
            except Empty:
                continue
            if msg is None:
                continue
            try:
                self._process(msg)
            except Exception as e:
                logging.error(f"Dashboard error (ignored): {e}")
        logging.info("Dashboard stopped.")

    def stop(self):
        self.running = False

    def _process(self, msg: Dict):
        if msg.get("type") == "signal":
            self._display_signal(msg["signal"])
        elif msg.get("type") == "pre_alert":
            print(f"\n{msg['message']}\n")

    def _display_signal(self, signal: Dict):
        asset = signal.get("asset", "UNKNOWN")
        direction = signal.get("direction", "NEUTRAL")
        icon = "📈" if direction == "BUY" else "📉" if direction == "SELL" else "⚪"
        trade_id = signal.get("trade_id", "N/A")
        time_str = signal.get("time", "")
        strength = signal.get("strength", "N/A")
        score = signal.get("score", 0)
        win_prob = signal.get("win_prob", 0)
        rr = signal.get("rr", 0)
        entry = signal.get("entry", 0)
        sl = signal.get("sl", 0)
        tp = signal.get("tp", 0)
        entry_zone = signal.get("entry_zone", "")
        exit_zone = signal.get("exit_zone", "")
        logic = signal.get("confluence_logic", "")
        passed_layers = signal.get("passed_layers", 0)

        chart_lines = self._build_chart(signal)

        output = f"""
❄️ AI SIGNAL: {direction} {icon}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 {asset} | 🆔 #{trade_id}
⏰ {time_str} | ⚡ {strength} ({score:.1f}%)
🎯 Win Prob: {win_prob:.1f}% | R:R {rr:.2f}
💰 Entry: {entry:.2f}  🛑 SL: {sl:.2f}  🎯 TP: {tp:.2f}
📌 Entry Zone: {entry_zone} | Exit Zone: {exit_zone}

📊 CHART:
┌──────────────────────────────────────┐
│           LIVE TOPOLOGY CHART         │
├──────────────────────────────────────┤
{chart_lines}
├──────────────────────────────────────┤
│ S=Support  R=Resistance  ●=Entry    │
│ ▼=SL  ★=Target                      │
└──────────────────────────────────────┘
🧠 Logic: {logic}
📰 News: No news
📊 Layers Passed: {passed_layers}/9
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        print(output, flush=True)

    def _build_chart(self, signal: Dict) -> str:
        entry = signal.get("entry", 0)
        sl = signal.get("sl", 0)
        tp = signal.get("tp", 0)
        supports = signal.get("supports", [])
        resistances = signal.get("resistances", [])
        atr = signal.get("atr", 10)

        min_price = min(sl, tp, entry, min(supports) if supports else entry, min(resistances) if resistances else entry)
        max_price = max(sl, tp, entry, max(supports) if supports else entry, max(resistances) if resistances else entry)
        padding = max(atr * 0.5, 5)
        min_price -= padding
        max_price += padding

        rows = 12
        step = (max_price - min_price) / rows if rows else 1
        lines = []
        for i in range(rows, -1, -1):
            price_level = min_price + i * step
            markers = []
            for s in supports:
                if abs(s - price_level) < step * 0.1:
                    markers.append("S")
            for r in resistances:
                if abs(r - price_level) < step * 0.1:
                    markers.append("R")
            if abs(entry - price_level) < step * 0.1:
                markers.append("●")
            if abs(sl - price_level) < step * 0.1:
                markers.append("▼")
            if abs(tp - price_level) < step * 0.1:
                markers.append("★")
            marker_str = " ".join(markers) if markers else " "
            line = f"│ {price_level:10.2f} {marker_str:<8} │"
            lines.append(line)
        return "\n".join(lines)
