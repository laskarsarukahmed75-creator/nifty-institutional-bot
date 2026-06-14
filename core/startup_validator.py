# ============================================================================
# START MODULE: StartupValidator
# Version: 1.0.0
# Dependencies: config, angel_client, telegram_notifier, database_manager
# Public Functions: validate_all
# Private Functions: _validate_angel, _validate_telegram, _validate_db, _validate_symbols
# Upgrade Notes: Add new validation steps (e.g., network, time sync).
# ============================================================================

import asyncio
from typing import List
from ..config.config import Config
from ..broker.angel_client import AngelOneClient
from ..notifications.telegram_notifier import TelegramNotifier
from ..database.database_manager import DatabaseManager

class StartupValidator:
    def __init__(self, broker: AngelOneClient, telegram: TelegramNotifier, db: DatabaseManager):
        self.broker = broker
        self.telegram = telegram
        self.db = db
    
    def validate_all(self) -> bool:
        if not self._validate_angel():
            return False
        if not self._validate_telegram():
            return False
        if not self._validate_db():
            return False
        if not self._validate_symbols():
            return False
        return True
    
    def _validate_angel(self) -> bool:
        if not self.broker.connect():
            return False
        if not self.broker.feed_token:
            return False
        return True
    
    def _validate_telegram(self) -> bool:
        try:
            loop = None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
            if loop and loop.is_running():
                asyncio.create_task(self.telegram._send("🟢 Startup validation OK"))
            else:
                asyncio.run(self.telegram._send("🟢 Startup validation OK"))
            return True
        except Exception:
            return False
    
    def _validate_db(self) -> bool:
        try:
            self.db.log_health("startup", "success")
            return True
        except Exception:
            return False
    
    def _validate_symbols(self) -> bool:
        for sym in Config.SYMBOLS:
            if not self.broker.get_token(sym):
                return False
        return True

# ============================================================================
# END MODULE: StartupValidator
# ============================================================================
