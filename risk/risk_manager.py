from typing import Dict, List, Optional, Any, Tuple, Set
import logging
# ============================================================================
# START MODULE: RiskManager
# Version: 2.0.0
# Dependencies: config, database_manager, position_manager, oco_manager
# Public Functions: can_trade, open_position, update_trailing_stop, check_exit, close_position, record_order_failure
# Private Functions: _reset_daily, _total_exposure
# Upgrade Notes: Replace with different risk rules (e.g., Kelly, fixed fractional).
# ============================================================================

import threading
from datetime import datetime
from typing import Dict, Optional
import numpy as np

from config.config import Config
from database.database_manager import DatabaseManager
from .position_manager import PositionManager
from .oco_manager import OCOManager

class RiskManager:
    def __init__(self, db: DatabaseManager = None, pos_mgr: PositionManager = None, oco_mgr: OCOManager = None):
        self.daily_loss = 0.0
        self.trades_today = 0
        self.last_reset = datetime.now().date()
        self._lock = threading.RLock()
        self.db = db or DatabaseManager()
        self.position_manager = pos_mgr or PositionManager(self.db)
        self.oco_manager = oco_mgr or OCOManager()
        self.consecutive_order_failures = 0
        self.circuit_breaker_open = False
    
    def _reset_daily(self):
        today = datetime.now().date()
        if today != self.last_reset:
            self.daily_loss = 0.0
            self.trades_today = 0
            self.last_reset = today
            self.consecutive_order_failures = 0
            self.circuit_breaker_open = False
    
    def _total_exposure(self) -> float:
        total = 0.0
        for pos in self.position_manager.get_all_positions().values():
            total += pos['entry_price'] * pos['quantity']
        return total
    
    def can_trade(self, signal: Dict) -> bool:
        self._reset_daily()
        if self.circuit_breaker_open:
            return False
        if self.trades_today >= Config.MAX_TRADES_PER_DAY:
            return False
        if self.daily_loss >= Config.DAILY_LOSS_LIMIT:
            self.circuit_breaker_open = True
            return False
        for pos in self.position_manager.get_all_positions().values():
            if pos['symbol'] == signal['symbol']:
                return False
        new_notional = signal['entry'] * (Config.CAPITAL * Config.RISK_PER_TRADE_PERCENT / 100 / abs(signal['entry'] - signal['stop_loss']) if abs(signal['entry'] - signal['stop_loss']) > 0 else 0)
        total_exposure = self._total_exposure() + new_notional
        if total_exposure > Config.CAPITAL * Config.MAX_LEVERAGE:
            return False
        risk_per_share = abs(signal['entry'] - signal['stop_loss'])
        if risk_per_share <= 0 or np.isnan(risk_per_share):
            return False
        max_risk_amount = Config.CAPITAL * Config.RISK_PER_TRADE_PERCENT / 100
        quantity = int(max_risk_amount / risk_per_share)
        lot_size = Config.get_lot_size(signal['symbol'])
        quantity = max(lot_size, (quantity // lot_size) * lot_size)
        if quantity <= 0 or quantity > 100000:
            return False
        signal['quantity'] = quantity
        return True
    
    def open_position(self, order_ids: Dict, signal: Dict):
        with self._lock:
            self.position_manager.add_position(order_ids, signal)
            self.trades_today += 1
            self.consecutive_order_failures = 0
    
    def record_order_failure(self):
        self.consecutive_order_failures += 1
        if self.consecutive_order_failures >= Config.MAX_CONSECUTIVE_ORDER_FAILURES:
            self.circuit_breaker_open = True
    
    def update_trailing_stop(self, order_id: str, current_price: float):
        self.position_manager.update_trailing_stop(order_id, current_price)
    
    def check_exit(self, order_id: str, current_price: float) -> bool:
        return self.position_manager.check_exit(order_id, current_price)
    
    def close_position(self, order_id: str, exit_price: float, broker) -> float:
        return self.position_manager.close_position(order_id, exit_price, broker, self)

# ============================================================================
# END MODULE: RiskManager
# ============================================================================
