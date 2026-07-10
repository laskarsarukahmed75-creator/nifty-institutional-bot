# app.py
import os
import time
import logging
import threading
import datetime
from typing import Optional, Dict, List, Tuple, Union, Any

# ---------- Ultimate SmartConnect Import Fix for Render Python 3.12 ----------
try:
    from smartapi import SmartConnect
    from smartapi.smartConnect import SmartConnectException
except (ImportError, ModuleNotFoundError):
    try:
        from SmartConnect import SmartConnect
        SmartConnectException = Exception
    except (ImportError, ModuleNotFoundError):
        try:
            import smartapi
            SmartConnect = smartapi.SmartConnect
            SmartConnectException = Exception
        except (ImportError, ModuleNotFoundError):
            import sys
            if 'smartapi' not in sys.modules:
                try:
                    import SmartConnect as sc
                    sys.modules['smartapi'] = sc
                    SmartConnect = sc.SmartConnect
                except ImportError:
                    raise ImportError("Angel One SmartAPI package missing from Render environment.")
            SmartConnectException = Exception

# Local modules
from db_handler import DBHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NiftyInstitutionalEngine")

class NiftyInstitutionalEngine:
    """
    Hedge-Fund Grade 0.5 Clone Vector Engine.
    All original logic preserved with Advanced Historical Trend Validation & Render Fixes.
    """

    # Angel One credentials from environment
    API_KEY = os.environ.get("ANGEL_API_KEY", "")
    CLIENT_ID = os.environ.get("ANGEL_CLIENT_ID", "")
    PASSWORD = os.environ.get("ANGEL_PASSWORD", "")
    TOTP_SECRET = os.environ.get("ANGEL_TOTP_SECRET", None)

    # Trading parameters
    TRADE_SYMBOL = os.environ.get("TRADE_SYMBOL", "NIFTY").upper()
    INSTRUMENT_TYPE = "NSE"          
    PRODUCT_TYPE = "INTRADAY"
    TIMEFRAME = "5m"                

    # Risk parameters
    SL_BUFFER_POINTS = 4.0          
    RISK_REWARD_RATIO = 10.0        
    TOLERANCE = 0.5                 
    QUANTITY = int(os.environ.get("TRADE_QUANTITY", 65))

    # Symbol token mapping
    SYMBOL_TOKENS = {
        "NIFTY": 99926000,
        "BANKNIFTY": 99926009,
        "SENSEX": 99926010,
    }

    # Lookback settings for high-accuracy historical data
    LOOKBACK_CANDLES = 150          

    def __init__(self):
        if not self.API_KEY or not self.CLIENT_ID or not self.PASSWORD:
            raise ValueError("Angel One credentials not set in environment.")

        self.db = DBHandler()
        self.obj: Optional[SmartConnect] = None
        self.auth_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.feed_token: Optional[str] = None
        self.user_profile: Optional[Dict] = None

        self.symbol = self.TRADE_SYMBOL
        self.token = self.SYMBOL_TOKENS.get(self.symbol)
        if not self.token:
            raise ValueError(f"Symbol {self.symbol} not in token map.")

        # State
        self.position_open = False
        self.last_entry_time = None
        self.order_ids = []          
        self._lock = threading.Lock()

        # Vector tracking
        self.last_swing_high = None
        self.last_swing_low = None
        self.last_vector_length = None
        self.pivot_0_5 = None

        # Parent vector info
        self.parent_swing_high = None
        self.parent_swing_low = None
        self.parent_length = None
        self.parent_completed = False

        self._entry_triggered = False
        self.running = False

        logger.info("Engine initialised with Institutional Trend Scanner.")

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def _login(self) -> None:
        logger.info("Logging in to Angel One...")
        try:
            self.obj = SmartConnect(api_key=self.API_KEY)
            data = self.obj.generateSession(
                clientCode=self.CLIENT_ID,
                password=self.PASSWORD,
                totp=self.TOTP_SECRET
            )
            if not data or data.get('status') is False:
                raise SmartConnectException(f"Login failed: {data}")
            self.auth_token = data.get('data', {}).get('jwtToken')
            self.refresh_token = data.get('data', {}).get('refreshToken')
            self.feed_token = self.obj.getfeedToken()
            self.user_profile = data.get('data', {}).get('userProfile')
            logger.info("Login successful.")
        except Exception as e:
            logger.error(f"Login error: {e}")
            raise

    def _renew_session(self) -> None:
        logger.warning("Renewing session...")
        self._login()

    def _ensure_session(self) -> None:
        try:
            self._get_ltp()
        except Exception:
            self._renew_session()

    # ------------------------------------------------------------------
    # Market Data
    # ------------------------------------------------------------------
    def _get_ltp(self, symbol: Optional[str] = None) -> float:
        sym = symbol or self.symbol
        token = self.SYMBOL_TOKENS.get(sym)
        if not token:
            raise ValueError(f"Unknown symbol: {sym}")
        try:
            resp = self.obj.ltpData(
                exchange=self.INSTRUMENT_TYPE,
                tradingsymbol=sym,
                symboltoken=token
            )
            ltp = float(resp.get('data', {}).get('ltp', 0.0))
            if ltp == 0.0:
                raise ValueError("Zero LTP received")
            return ltp
        except Exception as e:
            logger.error(f"LTP fetch error: {e}")
            raise

    def _get_historical_candles(self, symbol: Optional[str] = None, limit: int = 200) -> List[Dict]:
        sym = symbol or self.symbol
        token = self.SYMBOL_TOKENS.get(sym)
        if not token:
            raise ValueError(f"Unknown symbol: {sym}")

        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=5)  
        try:
            resp = self.obj.getCandleData(
                exchange=self.INSTRUMENT_TYPE,
                symboltoken=token,
                interval=self.TIMEFRAME,
                fromdate=start_date.strftime("%Y-%m-%d %H:%M:%S"),
                todate=end_date.strftime("%Y-%m-%d %H:%M:%S")
            )
            candles = []
            for row in resp.get('data', []):
                candles.append({
                    'time': row[0],
                    'open': float(row[1]),
                    'high': float(row[2]),
                    'low': float(row[3]),
                    'close': float(row[4]),
                    'volume': int(row[5])
                })
            return candles[-limit:] if len(candles) > limit else candles
        except Exception as e:
            logger.error(f"Historical data error: {e}")
            raise

    # ------------------------------------------------------------------
    # Swing Detection & Micro Trend Scanner
    # ------------------------------------------------------------------
    def _detect_all_swings(self, candles: List[Dict]) -> List[Dict]:
        if len(candles) < 10:
            return []

        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        n = len(highs)
        pivots = []

        for i in range(2, n-1):
            if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                pivots.append({'type': 'high', 'price': highs[i], 'index': i})
        for i in range(2, n-1):
            if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                pivots.append({'type': 'low', 'price': lows[i], 'index': i})

        pivots.sort(key=lambda x: x['index'])
        return pivots

    def _extract_last_two_swings(self, pivots: List[Dict]) -> Tuple[Dict, Dict]:
        if len(pivots) < 4:
            return None, None

        swings = []
        for i in range(len(pivots)-1):
            p1 = pivots[i]
            p2 = pivots[i+1]
            if p1['type'] == 'low' and p2['type'] == 'high':
                direction = 1  
            elif p1['type'] == 'high' and p2['type'] == 'low':
                direction = -1 
            else:
                continue
            length = abs(p2['price'] - p1['price'])
            swings.append({
                'start_type': p1['type'],
                'start_price': p1['price'],
                'start_index': p1['index'],
                'end_type': p2['type'],
                'end_price': p2['price'],
                'end_index': p2['index'],
                'direction': direction,
                'length': length
            })

        if len(swings) < 2:
            return None, None

        return swings[-1], swings[-2]

    def _check_parent_completion(self, parent_swing: Dict, candles: List[Dict]) -> bool:
        if parent_swing is None:
            return False
        direction = parent_swing['direction']
        end_idx = parent_swing['end_index']
        length = parent_swing['length']
        end_price = parent_swing['end_price']

        for i in range(end_idx + 1, len(candles)):
            if direction == 1:  
                if candles[i]['high'] > end_price + length:
                    return True
            else:  
                if candles[i]['low'] < end_price - length:
                    return True
        return False

    def _calculate_macro_trend(self, candles: List[Dict]) -> int:
        if len(candles) < 60:
            return 1
        half_len = len(candles) // 2
        first_half_avg = sum(c['close'] for c in candles[:half_len]) / half_len
        second_half_avg = sum(c['close'] for c in candles[half_len:]) / half_len
        if second_half_avg > first_half_avg:
            return 1  # Structural Up-Trend
        else:
            return -1 # Structural Down-Trend

    def _detect_swing_vector(self, candles: List[Dict]) -> Tuple[float, float, float, int, Dict]:
        pivots = self._detect_all_swings(candles)
        macro_trend = self._calculate_macro_trend(candles)

        if len(pivots) < 4:
            high = max(c['high'] for c in candles[-10:])
            low = min(c['low'] for c in candles[-10:])
            length = high - low
            return high, low, length, macro_trend, {}

        current, parent = self._extract_last_two_swings(pivots)
        if current is None:
            high = max(c['high'] for c in candles[-10:])
            low = min(c['low'] for c in candles[-10:])
            length = high - low
            return high, low, length, macro_trend, {}

        if current['direction'] == 1:  
            swing_high = current['end_price']
            swing_low = current['start_price']
        else:  
            swing_high = current['start_price']
            swing_low = current['end_price']
        length = current['length']
        
        direction = macro_trend if current['direction'] == macro_trend else current['direction']

        parent_info = {}
        if parent is not None:
            parent_high = max(parent['start_price'], parent['end_price'])
            parent_low = min(parent['start_price'], parent['end_price'])
            parent_length = parent['length']
            parent_completed = self._check_parent_completion(parent, candles)
            parent_info = {
                'high': parent_high,
                'low': parent_low,
                'length': parent_length,
                'completed': parent_completed
            }

        return swing_high, swing_low, length, direction, parent_info

    def _compute_pivot_0_5(self, swing_high: float, swing_low: float) -> float:
        return swing_low + (swing_high - swing_low) * 0.5

    # ------------------------------------------------------------------
    # Retest Check
    # ------------------------------------------------------------------
    def _check_retest(self, pivot: float, current_price: float,
                      candle_high: float, candle_low: float) -> Tuple[bool, float, float]:
        if abs(current_price - pivot) <= self.TOLERANCE:
            return True, candle_high, candle_low
        return False, 0.0, 0.0

    # ------------------------------------------------------------------
    # Order Execution (3-Order Bracket Chain)
    # ------------------------------------------------------------------
    def _place_order(self, side: str, quantity: int,
                     entry_price: float, sl_price: float, tp_price: float) -> Dict:
        token = self.SYMBOL_TOKENS.get(self.symbol)
        if not token:
            raise ValueError("Symbol token missing.")

        order_responses = {}

        # Entry Market Order
        entry_params = {
            "variety": "NORMAL",
            "tradingsymbol": self.symbol,
            "symboltoken": token,
            "transactiontype": side.upper(),
            "exchange": self.INSTRUMENT_TYPE,
            "ordertype": "MARKET",
            "producttype": self.PRODUCT_TYPE,
            "duration": "DAY",
            "price": "0",
            "quantity": str(quantity)
        }
        try:
            resp = self.obj.placeOrder(entry_params)
            order_id = resp.get('data', {}).get('orderid')
            if not order_id:
                raise ValueError("No order ID for entry.")
            order_responses['entry'] = order_id
            self.order_ids.append(order_id)
            logger.info(f"✅ Entry order placed: {order_id}")
        except Exception as e:
            logger.error(f"Entry order failed: {e}")
            raise

        # SL Order (Stop Loss Market)
        sl_side = "SELL" if side.upper() == "BUY" else "BUY"
        sl_params = {
            "variety": "STOPLOSS_MARKET",
            "tradingsymbol": self.symbol,
            "symboltoken": token,
            "transactiontype": sl_side,
            "exchange": self.INSTRUMENT_TYPE,
            "ordertype": "STOPLOSS_MARKET",
            "producttype": self.PRODUCT_TYPE,
            "duration": "DAY",
            "price": str(sl_price),
            "quantity": str(quantity),
            "triggerprice": str(sl_price)
        }
        try:
            resp = self.obj.placeOrder(sl_params)
            sl_id = resp.get('data', {}).get('orderid')
            order_responses['sl'] = sl_id
            self.order_ids.append(sl_id)
            logger.info(f"🛡️ SL order placed: {sl_id}")
        except Exception as e:
            logger.error(f"SL order failed: {e}")
            self._cancel_all_orders()
            raise

        # TP Order (Limit)
        tp_side = "SELL" if side.upper() == "BUY" else "BUY"
        tp_params = {
            "variety": "NORMAL",
            "tradingsymbol": self.symbol,
            "symboltoken": token,
            "transactiontype": tp_side,
            "exchange": self.INSTRUMENT_TYPE,
            "ordertype": "LIMIT",
            "producttype": self.PRODUCT_TYPE,
            "duration": "DAY",
            "price": str(tp_price),
            "quantity": str(quantity),
            "triggerprice": "0"
        }
        try:
            resp = self.obj.placeOrder(tp_params)
            tp_id = resp.get('data', {}).get('orderid')
            order_responses['tp'] = tp_id
            self.order_ids.append(tp_id)
            logger.info(f"🎯 TP order placed: {tp_id}")
        except Exception as e:
            logger.error(f"TP order failed: {e}")
            self._cancel_all_orders()
            raise

        self.db.log_trade(self.symbol, side, entry_price, sl_price, tp_price, "OPEN")
        return order_responses

    def _cancel_all_orders(self) -> None:
        for oid in self.order_ids:
            try:
                self.obj.cancelOrder(variety="NORMAL", orderid=oid)
                logger.info(f"Cancelled order {oid}")
            except Exception as e:
                logger.warning(f"Failed to cancel {oid}: {e}")
        self.order_ids.clear()

    # ------------------------------------------------------------------
    # Position Monitoring (using orderBook)
    # ------------------------------------------------------------------
    def _check_position_closed(self) -> bool:
        if not self.position_open:
            return True

        if len(self.order_ids) < 3:
            self.position_open = False
            self._entry_triggered = False
            return True

        sl_id = self.order_ids[1] if len(self.order_ids) > 1 else None
        tp_id = self.order_ids[2] if len(self.order_ids) > 2 else None
        if not sl_id or not tp_id:
            return False

        try:
            order_book_resp = self.obj.orderBook()
            orders = order_book_resp.get('data', [])

            sl_status = None
            tp_status = None
            for order in orders:
                oid = str(order.get('orderid'))
                if oid == str(sl_id):
                    sl_status = order.get('status')
                if oid == str(tp_id):
                    tp_status = order.get('status')

            sl_closed = sl_status in ['COMPLETE', 'REJECTED', 'CANCELLED']
            tp_closed = tp_status in ['COMPLETE', 'REJECTED', 'CANCELLED']

            if sl_closed or tp_closed:
                self.position_open = False
                self._entry_triggered = False
                self.order_ids.clear()
                logger.info("Position closed securely. Lock released.")
                return True
        except Exception as e:
            logger.warning(f"Error checking order status: {e}")
            return False
        return False  

    # ------------------------------------------------------------------
    # Main Trading Loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        self._login()
        self.running = True
        logger.info("Engine started. Monitoring for 0.5 pivot retests...")
        self._ensure_session()

        while self.running:
            try:
                self._ensure_session()
                self._check_position_closed()

                candles = self._get_historical_candles(limit=self.LOOKBACK_CANDLES)
                if not candles:
                    time.sleep(5)
                    continue
                latest = candles[-1]
                current_price = self._get_ltp()

                swing_high, swing_low, length, direction, parent_info = self._detect_swing_vector(candles)
                self.last_swing_high = swing_high
                self.last_swing_low = swing_low
                self.last_vector_length = length

                pivot = self._compute_pivot_0_5(swing_high, swing_low)
                self.pivot_0_5 = pivot

                self.parent_swing_high = parent_info.get('high')
                self.parent_swing_low = parent_info.get('low')
                self.parent_length = parent_info.get('length')
                self.parent_completed = parent_info.get('completed', False)

                self.db.save_vector(
                    self.symbol, swing_high, swing_low, length, pivot,
                    parent_swing_high=self.parent_swing_high,
                    parent_swing_low=self.parent_swing_low,
                    parent_length=self.parent_length,
                    parent_completed=self.parent_completed
                )

                retested, candle_high, candle_low = self._check_retest(
                    pivot, current_price, latest['high'], latest['low']
                )

                if retested and not self.position_open and not self._entry_triggered:
                    side = None
                    if direction == 1 and current_price >= pivot - self.TOLERANCE:
                        side = 'BUY'
                    elif direction == -1 and current_price <= pivot + self.TOLERANCE:
                        side = 'SELL'

                    if side:
                        if side == 'BUY':
                            sl_price = candle_low - self.SL_BUFFER_POINTS
                            entry_price = current_price
                            if self.parent_completed:
                                reward_multiplier = self.RISK_REWARD_RATIO
                            else:
                                reward_multiplier = self.RISK_REWARD_RATIO * 0.5
                            tp_price = entry_price + reward_multiplier * (entry_price - sl_price)
                        else:  
                            sl_price = candle_high + self.SL_BUFFER_POINTS
                            entry_price = current_price
                            if self.parent_completed:
                                reward_multiplier = self.RISK_REWARD_RATIO
                            else:
                                reward_multiplier = self.RISK_REWARD_RATIO * 0.5
                            tp_price = entry_price - reward_multiplier * (sl_price - entry_price)

                        with self._lock:
                            self._place_order(side, self.QUANTITY, entry_price, sl_price, tp_price)
                            self.position_open = True
                            self._entry_triggered = True
                            self.last_entry_time = time.time()
                            logger.info(f"🚀 Institutional Trade Executed: {side} at {entry_price}, SL {sl_price}, TP {tp_price}")

                time.sleep(5)
            except Exception as e:
                logger.error(f"Loop error: {e}", exc_info=True)
                time.sleep(5)

        logger.info("Engine stopped.")

    def stop(self) -> None:
        self.running = False
        self._cancel_all_orders()
        logger.info("Engine shut down.")
