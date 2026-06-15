from typing import Dict, List, Optional, Any, Tuple, Set
import logging
# ============================================================================
# START MODULE: HealthMonitor
# Version: 1.0.0
# Dependencies: threading, time, database_manager
# Public Functions: update_tick, stop
# Private Functions: _monitor
# Upgrade Notes: Add more health checks (CPU, memory, broker ping).
# ============================================================================

import threading
import time
from typing import Any

from database.database_manager import DatabaseManager

class HealthMonitor:
    def __init__(self, ws_manager: Any, telegram: Any, db: DatabaseManager):
        self.ws_manager = ws_manager
        self.telegram = telegram
        self.db = db
        self.last_tick_time = time.time()
        self.running = True
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        self.thread.start()
    
    def update_tick(self):
        self.last_tick_time = time.time()
    
    def _monitor(self):
        while self.running:
            time.sleep(30)
            now = time.time()
            if now - self.last_tick_time > 60:
                self.db.log_health("websocket_stalled", str(now - self.last_tick_time))
            ws_ok = self.ws_manager.is_connected if self.ws_manager else False
            self.db.log_health("ws_connected", str(ws_ok))
            self.db.log_health("uptime", str(now))
    
    def stop(self):
        self.running = False
        if self.thread.is_alive():
            self.thread.join(timeout=2)

# ============================================================================
# END MODULE: HealthMonitor
# ============================================================================
