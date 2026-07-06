#!/usr/bin/env python3
import time
import logging
import threading
from config.config import Config
from engines.candle_engine import CandleEngine
from engines.indicator_engine import IndicatorEngine
from engines.smc_engine import SMCEngine
from engines.signal_engine import SignalEngine
from monitoring.health_monitor import HealthMonitor

logger = logging.getLogger(__name__)

class MainEngine:
    def __init__(self, broker, db, risk_manager, position_manager, oco_manager, telegram):
        self.broker = broker
        self.db = db
        self.risk_manager = risk_manager
        self.position_manager = position_manager
        self.oco_manager = oco_manager
        self.telegram = telegram

        self.candle_engine = CandleEngine()
        self.indicator_engine = IndicatorEngine()
        self.smc_engine = SMCEngine(self.candle_engine)
        self.signal_engine = SignalEngine(self.smc_engine, self.risk_manager)

        from broker.websocket_manager import WebSocketManager
        self.ws_manager = WebSocketManager(
            auth_token=self.broker.auth_token,
            api_key=Config.ANGEL_API_KEY,
            client_id=Config.ANGEL_CLIENT_ID,
            feed_token=self.broker.feed_token
        )
        self.ws_manager.set_callback(self._on_tick)
        self.health_monitor = None
        self.running = False

    def start(self):
        logger.info("[MAIN] Starting Trading Bot...")
        Config.validate()

        tokens = []
        for sym in Config.SYMBOLS:
            token = self.broker.get_token(sym)
            if token:
                tokens.append(token)
                logger.info(f"[MAIN] Token for {sym}: {token}")

        if tokens:
            self.ws_manager.subscribe(tokens)
            self.ws_manager.connect()
            logger.info(f"[MAIN] WebSocket pipeline fully engaged.")
        else:
            logger.error("[MAIN] Missing tokens configuration.")

        self.health_monitor = HealthMonitor(self.ws_manager, self.telegram, self.db)
        self.running = True

        try:
            while self.running:
                if not Config.is_market_open():
                    time.sleep(60)
                    continue
                self._signal_loop()
                time.sleep(2)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _signal_loop(self):
        for symbol in Config.SYMBOLS:
            try:
                signal = self.signal_engine.generate_signal(symbol, None)
                if signal:
                    logger.info(f"[SIGNAL] {symbol} triggered. Executing...")
                    order_ids = self.broker.place_order(
                        symbol=signal['symbol'], direction=signal['direction'], quantity=signal['quantity'],
                        price=signal['entry'], stop_loss=signal['stop_loss'], take_profit=signal['take_profit']
                    )
                    if order_ids:
                        self.risk_manager.open_position(order_ids, signal)
                        self.telegram.send_signal(signal)
            except Exception as e:
                logger.error(f"[MAIN ERROR] Loop glitch for {symbol}: {e}")

    def _on_tick(self, tick_data: dict):
        try:
            token = tick_data.get('symboltoken', '')
            ltp = tick_data.get('ltp')
            volume = tick_data.get('volume', 0)
            if not token or ltp is None: return

            symbol = None
            for sym, tok in self.broker.token_map.items():
                if tok == token:
                    symbol = sym
                    break
            if not symbol: return

            price = float(ltp)
            self.candle_engine.update(symbol, price, int(volume), time.time())
            if self.health_monitor: self.health_monitor.update_tick()
        except Exception as e:
            logger.error(f"[TICK ERROR] processing failed: {e}")

    def stop(self):
        self.running = False
        if self.ws_manager: self.ws_manager.stop()
        if self.health_monitor: self.health_monitor.stop()
        self.broker.disconnect()
        logger.info("[MAIN] Bot shutdown complete.")
