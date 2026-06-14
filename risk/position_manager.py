# ============================================================================
# START MODULE: PositionManager
# Version: 1.0.0
# Dependencies: database_manager, config
# Public Functions: add_position, get_all_positions, update_trailing_stop, check_exit, close_position
# Private Functions: none
# Upgrade Notes: Replace with different position tracking.
# ============================================================================

import threading
from datetime import datetime
from typing import Dict, Optional

from config.config import Config
from database.database_manager import DatabaseManager

class PositionManager:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.active_positions: Dict[str, Dict] = {}
        self._lock = threading.RLock()
        for pos in self.db.load_active_positions():
            self.active_positions[pos['order_id']] = pos
    
    def add_position(self, order_ids: Dict, signal: Dict):
        with self._lock:
            pos = {
                'order_id': order_ids['order_id'],
                'symbol': signal['symbol'],
                'direction': signal['direction'],
                'entry_price': signal['entry'],
                'quantity': signal['quantity'],
                'stop_loss': signal['stop_loss'],
                'take_profit': signal['take_profit'],
                'entry_time': datetime.now().isoformat(),
                'trailing_stop': signal['stop_loss'],
                'status': 'OPEN',
                'sl_order_id': order_ids.get('sl_order_id'),
                'tp_order_id': order_ids.get('tp_order_id')
            }
            self.active_positions[order_ids['order_id']] = pos
            self.db.save_position(pos)
    
    def get_all_positions(self) -> Dict[str, Dict]:
        with self._lock:
            return self.active_positions.copy()
    
    def update_trailing_stop(self, order_id: str, current_price: float):
        pos = self.active_positions.get(order_id)
        if not pos:
            return
        if pos['direction'] == 'BUY':
            new_stop = current_price * (1 - Config.TRAILING_STOP_PERCENT / 100)
            if new_stop > pos['trailing_stop']:
                pos['trailing_stop'] = new_stop
        else:
            new_stop = current_price * (1 + Config.TRAILING_STOP_PERCENT / 100)
            if new_stop < pos['trailing_stop']:
                pos['trailing_stop'] = new_stop
        self.db.save_position(pos)
    
    def check_exit(self, order_id: str, current_price: float) -> bool:
        pos = self.active_positions.get(order_id)
        if not pos:
            return False
        if pos['direction'] == 'BUY':
            return current_price <= pos['trailing_stop'] or current_price >= pos['take_profit']
        else:
            return current_price >= pos['trailing_stop'] or current_price <= pos['take_profit']
    
    def close_position(self, order_id: str, exit_price: float, broker, risk_mgr) -> float:
        pos = self.active_positions.pop(order_id, None)
        if not pos:
            return 0.0
        exit_order_id = broker.exit_position(pos['symbol'], pos['direction'], pos['quantity'])
        if not exit_order_id:
            return 0.0
        if pos.get('sl_order_id'):
            broker.cancel_order(pos['sl_order_id'])
        if pos.get('tp_order_id'):
            broker.cancel_order(pos['tp_order_id'])
        if pos['direction'] == 'BUY':
            pnl = (exit_price - pos['entry_price']) * pos['quantity']
        else:
            pnl = (pos['entry_price'] - exit_price) * pos['quantity']
        if pnl < 0:
            risk_mgr.daily_loss += abs(pnl)
        self.db.update_position_status(order_id, "CLOSED")
        trade_dict = {
            'order_id': order_id, 'symbol': pos['symbol'], 'direction': pos['direction'],
            'entry_price': pos['entry_price'], 'exit_price': exit_price, 'quantity': pos['quantity'],
            'pnl': pnl, 'entry_time': pos['entry_time'], 'exit_time': datetime.now().isoformat(),
            'reason': 'TP/SL/Manual'
        }
        self.db.record_trade(trade_dict)
        return pnl

# ============================================================================
# END MODULE: PositionManager
# ============================================================================
