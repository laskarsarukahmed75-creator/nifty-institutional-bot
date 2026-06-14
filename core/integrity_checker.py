# ============================================================================
# START MODULE: IntegrityChecker
# Version: 1.0.0
# Dependencies: database_manager, position_manager
# Public Functions: check_integrity
# Private Functions: _compare_local_broker
# Upgrade Notes: Add more cross-checks.
# ============================================================================

from typing import Dict, List
from broker.angel_client import AngelOneClient
from database.database_manager import DatabaseManager
from risk.position_manager import PositionManager

class IntegrityChecker:
    def __init__(self, broker: AngelOneClient, db: DatabaseManager, pos_mgr: PositionManager):
        self.broker = broker
        self.db = db
        self.pos_mgr = pos_mgr
    
    def check_integrity(self) -> Dict[str, bool]:
        issues = {}
        # Compare local positions with broker
        local = self.pos_mgr.get_all_positions()
        broker_pos = self.broker.get_positions()
        broker_map = {p.get('orderid'): p for p in broker_pos if p.get('netqty', 0) != 0}
        for oid, pos in local.items():
            if oid not in broker_map:
                issues[f"missing_broker_{oid}"] = False
            else:
                issues[f"match_{oid}"] = True
        return issues

# ============================================================================
# END MODULE: IntegrityChecker
# ============================================================================
