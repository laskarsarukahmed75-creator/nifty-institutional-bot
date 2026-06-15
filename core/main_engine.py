from typing import Dict, List, Optional, Any, Tuple, Set
import logging
# ============================================================================
# START MODULE: MainEngine
# Version: 2.0.0
# Dependencies: all other modules
# Public Functions: start, stop
# Private Functions: _on_tick, _signal_loop
# Upgrade Notes: Replace main loop logic while keeping same interfaces.
# ============================================================================

import time
import logging
from typing import Optional

from config.config import Config
from database.database_manager import DatabaseManager
from broker.angel_client import AngelOneClient
from broker.websocket_manager import WebSocketManager
from broker.broker_sync import BrokerSync
from engines.candle_engine import CandleEngine
from engines.indicator_engine import IndicatorEngine
from engines.smc_engine import SMCEngine
from engines.signal_engine import SignalEngine
from engines.backtest_engine import BacktestEngine
from risk.risk_manager import RiskManager
from risk.position_manager import PositionManager
from risk.oco_manager import OCOManager
from notifications.telegram_notifier import TelegramNotifier
from monitoring.health_monitor import HealthMonitor
from .startup_validator import StartupValidator
from .diagnostics import Diagnostics
from .integrity_checker import IntegrityChecker

logger = logging.getLogger(__name__)

class MainEngine:
    def __init__(self):
        # Initialize all modules
        self.db = DatabaseManager()
        self.broker = AngelOneClient(self.db)
        self.telegram = TelegramNotifier()
        self.validator = StartupValidator(self.broker, self.telegram, self.db)
        self.diagnostics = Diagnostics()
        self.position_manager = PositionManager(self.db)
        self.oco_manager = OCOManager()
        self.risk_manager = RiskManager(self.db, self.position_manager, self.oco_manager)
        self.candle_engine = CandleEngine()
        self.smc_engine = SMCEngine(self.candle_engine)
        self.signal_engine = SignalEngine(self.smc_engine, self.risk_manager)
        self.broker_sync = BrokerSync(self.broker, self.db)
        self.health_monitor = None
        self.ws_manager: Optional[WebSocketManager] = None
        self.running = False
    
    def start(self):
        logger.info("Starting Trading Bot...")
        Config.validate()
        
        # Run diagnostics
        diag = self.diagnostics.run_diagnostics()
        if not all(diag.values()):
            logger.error(f"Diagnostics failed: {diag}")
            return
        
        # Validate startup
        if not self.validator.validate_all():
            self.telegram.send("❌ Startup validation failed")
            return
        
        # Setup WebSocket
        self.ws_manager = WebSocketManager(
            auth_token=self.broker.auth_token,
            api_key=Config.ANGEL_API_KEY,
            client_id=Config.ANGEL_CLIENT_ID,
            feed_token=self.broker.feed_token,
            db=self.db
        )
        self.ws_manager.set_callback(self._on_tick)
        
        tokens = [self.broker.get_token(sym) for sym in Config.SYMBOLS if self.broker.get_token(sym)]
        if tokens:
            self.ws_manager.subscribe(tokens)
            self.ws_manager.connect()
        
        self.health_monitor = HealthMonitor(self.ws_manager, self.telegram, self.db)
        self.running = True
        self.telegram.send("✅ Bot started successfully")
        
        # Main loop
        try:
            while self.running:
                if not Config.is_market_open():
                    time.sleep(60)
                    continue
                self._signal_loop()
                time.sleep(2)
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
        finally:
            self.stop()
    
    def _signal_loop(self):
        for symbol in Config.SYMBOLS:
            signal = self.signal_engine.generate_signal(symbol)
            if signal:
                order_ids = self.broker.place_order(
                    symbol=signal['symbol'],
                    direction=signal['direction'],
                    quantity=signal['quantity'],
                    price=signal['entry'],
                    stop_loss=signal['stop_loss'],
                    take_profit=signal['take_profit']
                )
                if order_ids:
                    self.risk_manager.open_position(order_ids, signal)
                    self.telegram.send_signal(signal)
                else:
                    self.risk_manager.record_order_failure()
    
    def _on_tick(self, tick_data: dict):
        try:
            token = tick_data.get('symboltoken', '')
            ltp = tick_data.get('ltp')
            volume = tick_data.get('volume', 0)
            if not token or ltp is None:
                return
            symbol = None
            for sym, tok in self.broker.token_map.items():
                if tok == token:
                    symbol = sym
                    break
            if not symbol:
                return
            price = float(ltp)
            self.candle_engine.update(symbol, price, int(volume), time.time())
            if self.health_monitor:
                self.health_monitor.update_tick()
            for order_id, pos in self.risk_manager.position_manager.get_all_positions().items():
                self.risk_manager.update_trailing_stop(order_id, price)
                if self.risk_manager.check_exit(order_id, price):
                    pnl = self.risk_manager.close_position(order_id, price, self.broker)
                    self.telegram.send(f"🚨 Position closed {order_id} @ {price} PnL: {pnl:.2f}")
        except Exception as e:
            logger.error(f"Tick error: {e}", exc_info=True)
    
    def stop(self):
        self.running = False
        if self.ws_manager:
            self.ws_manager.stop()
        if self.health_monitor:
            self.health_monitor.stop()
        self.broker.disconnect()
        self.telegram.stop()
        logger.info("Bot stopped")

# ============================================================================
# END MODULE: MainEngine
# ============================================================================
