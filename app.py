# app.py
import os
import time
import logging
import threading
import datetime
from typing import Optional, Dict, List, Tuple, Any

# ---------- Robust SmartConnect Import ----------
try:
    from smartapi import SmartConnect
    from smartapi.smartConnect import SmartConnectException
except (ImportError, ModuleNotFoundError):
    try:
        from SmartConnect import SmartConnect
        SmartConnectException = Exception
    except (ImportError, ModuleNotFoundError):
        from smartapi.smartConnect import SmartConnect
        SmartConnectException = Exception

from db_handler import DBHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NiftyInstitutionalEngine")

class NiftyInstitutionalEngine:
    # Environment variables
    API_KEY = os.environ.get("ANGEL_API_KEY", "")
    CLIENT_ID = os.environ.get("ANGEL_CLIENT_ID", "")
    PASSWORD = os.environ.get("ANGEL_PASSWORD", "")
    TOTP_SECRET = os.environ.get("ANGEL_TOTP_SECRET", None)

    TRADE_SYMBOL = os.environ.get("TRADE_SYMBOL", "NIFTY").upper()
    INSTRUMENT_TYPE = "NSE"
    PRODUCT_TYPE = "INTRADAY"
    TIMEFRAME = "5m"

    SL_BUFFER_POINTS = 4.0
    RISK_REWARD_RATIO = 10.0
    TOLERANCE = 0.5
    LOOKBACK_CANDLES = 150
    QUANTITY = int(os.environ.get("TRADE_QUANTITY", 25))

    SYMBOL_TOKENS = {
        "NIFTY": 99926000,
        "BANKNIFTY": 99926009,
        "SENSEX": 99926010,
    }

    def __init__(self):
        if not self.API_KEY or not self.CLIENT_ID or not self.PASSWORD:
            raise ValueError("Missing Angel One credentials.")

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

        self.position_open = False
        self.order_ids = []          # [entry_id, sl_id, tp_id]
        self._lock = threading.Lock()
        self._entry_triggered = False
        self.running = False

        # Vector tracking
        self.last_swing_high = None
        self.last_swing_low = None
        self.last_vector_length = None
        self.pivot_0_5 = None
        self.parent_swing_high = None
        self.parent_swing_low = None
        self.parent_length = None
        self.parent_completed = False

        logger.info("Engine initialised (not logged in yet).")

    # ---------- Authentication ----------
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
                raise Exception(f"Login failed: {data}")
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

    # ---------- Market Data ----------
    def _get_ltp(self) -> float:
        resp = self.obj.ltpData(
            exchange=self.INSTRUMENT_TYPE,
            tradingsymbol=self.symbol,
            symboltoken=self.token
        )
        ltp = float(resp.get('data', {}).get('ltp', 0.0))
        if ltp == 0.0:
            raise ValueError("Zero LTP received")
        return ltp

    def _get_historical_candles(self, limit: int = 200) -> List[Dict]:
        end_date = datetime.datetime.now()
        start_date = end_date - datetime.timedelta(days=5)
        resp = self.obj.getCandleData(
            exchange=self.INSTRUMENT_TYPE,
            symboltoken=self.token,
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

    # ---------- Swing Detection with Backside Lookback ----------
    def _detect_all_swings(self, candles: List[Dict]) -> List[Dict]:
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        n = len(highs)
        pivots = []
        for i in range(2, n-1):
            if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                pivots.append({'type': 'high', 'price': highs[i], 'index': i})
            if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                pivots.append({'type': 'low', 'price': lows[i], 'index': i})
        pivots.sort(key=lambda x: x['index'])
        return pivots

    def _check_parent_completion(self, parent_swing: Dict, candles: List[Dict]) -> bool:
        if not parent_swing:
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

    def _detect_swing_vector(self, candles: List[Dict]) -> Tuple[float, float, float, int, Dict]:
        pivots = self._detect_all_swings(candles)
        if len(pivots) < 4:
            high = max(c['high'] for c in candles[-10:])
            low = min(c['low'] for c in candles[-10:])
            length = high - low
            direction = 1 if candles[-1]['close'] > candles[-10]['close'] else -1
            return high, low, length, direction, {}

        # Last two swings
        current = pivots[-1]
        parent = pivots[-2]
        if current['type'] == 'high' and parent['type'] == 'low':
            direction = 1
            swing_high = current['price']
            swing_low = parent['price']
        elif current['type'] == 'low' and parent['type'] == 'high':
            direction = -1
            swing_high = parent['price']
            swing_low = current['price']
        else:
            swing_high = max(current['price'], parent['price'])
            swing_low = min(current['price'], parent['price'])
            direction = 1 if swing_high > swing_low else -1

        length = swing_high - swing_low
        if length <= 0:
            length = 0.1

        parent_info = {}
        if len(pivots) >= 4:
            p_start = pivots[-3]
            p_end = pivots[-2]
            p_len = abs(p_end['price'] - p_start['price'])
            p_dir = 1 if p_end['type'] == 'high' and p_start['type'] == 'low' else -1
            parent_swing = {
                'direction': p_dir,
                'end_index': p_end['index'],
                'length': p_len,
                'end_price': p_end['price']
            }
            completed = self._check_parent_completion(parent_swing, candles)
            parent_info = {
                'high': max(p_start['price'], p_end['price']),
                'low': min(p_start['price'], p_end['price']),
                'length': p_len,
                'completed': completed
            }

        return swing_high, swing_low, length, direction, parent_info

    # ---------- Order Execution ----------
    def _place_orders(self, side: str, entry_price: float, sl_price: float, tp_price: float):
        entry_params = {
            "variety": "NORMAL",
            "tradingsymbol": self.symbol,
            "symboltoken": self.token,
            "transactiontype": side.upper(),
            "exchange": self.INSTRUMENT_TYPE,
            "ordertype": "MARKET",
            "producttype": self.PRODUCT_TYPE,
            "duration": "DAY",
            "price": "0",
            "quantity": str(self.QUANTITY)
        }
        resp = self.obj.placeOrder(entry_params)
        entry_id = resp.get('data', {}).get('orderid')
        if not entry_id:
            raise ValueError("Entry order failed")
        self.order_ids.append(entry_id)

        sl_side = "SELL" if side.upper() == "BUY" else "BUY"
        sl_params = {
            "variety": "STOPLOSS_MARKET",
            "tradingsymbol": self.symbol,
            "symboltoken": self.token,
            "transactiontype": sl_side,
            "exchange": self.INSTRUMENT_TYPE,
            "ordertype": "STOPLOSS_MARKET",
            "producttype": self.PRODUCT_TYPE,
            "duration": "DAY",
            "price": str(sl_price),
            "quantity": str(self.QUANTITY),
            "triggerprice": str(sl_price)
        }
        resp = self.obj.placeOrder(sl_params)
        sl_id = resp.get('data', {}).get('orderid')
        if not sl_id:
            self._cancel_all_orders()
            raise ValueError("SL order failed")
        self.order_ids.append(sl_id)

        tp_side = "SELL" if side.upper() == "BUY" else "BUY"
        tp_params = {
            "variety": "NORMAL",
            "tradingsymbol": self.symbol,
            "symboltoken": self.token,
            "transactiontype": tp_side,
            "exchange": self.INSTRUMENT_TYPE,
            "ordertype": "LIMIT",
            "producttype": self.PRODUCT_TYPE,
            "duration": "DAY",
            "price": str(tp_price),
            "quantity": str(self.QUANTITY),
            "triggerprice": "0"
        }
        resp = self.obj.placeOrder(tp_params)
        tp_id = resp.get('data', {}).get('orderid')
        if not tp_id:
            self._cancel_all_orders()
            raise ValueError("TP order failed")
        self.order_ids.append(tp_id)

        self.db.log_trade(self.symbol, side, entry_price, sl_price, tp_price, "OPEN")
        logger.info(f"Orders placed: entry {entry_id}, SL {sl_id}, TP {tp_id}")

    def _cancel_all_orders(self):
        for oid in self.order_ids:
            try:
                self.obj.cancelOrder(variety="NORMAL", orderid=oid)
                logger.info(f"Cancelled order {oid}")
            except Exception as e:
                logger.warning(f"Failed to cancel {oid}: {e}")
        self.order_ids.clear()

    # ---------- Position Monitoring (using orderBook) ----------
    def _check_position_closed(self) -> bool:
        if not self.position_open:
            return True
        if len(self.order_ids) < 3:
            self.position_open = False
            self._entry_triggered = False
            return True

        sl_id = self.order_ids[1]
        tp_id = self.order_ids[2]
        try:
            order_book = self.obj.orderBook()
            orders = order_book.get('data', [])
            sl_status = None
            tp_status = None
            for o in orders:
                if str(o.get('orderid')) == str(sl_id):
                    sl_status = o.get('status')
                if str(o.get('orderid')) == str(tp_id):
                    tp_status = o.get('status')
            if sl_status in ['COMPLETE', 'REJECTED', 'CANCELLED'] or \
               tp_status in ['COMPLETE', 'REJECTED', 'CANCELLED']:
                self.position_open = False
                self._entry_triggered = False
                self.order_ids.clear()
                logger.info("Position closed (SL/TP hit). Lock released.")
                return True
        except Exception as e:
            logger.warning(f"Order status check error: {e}")
        return False

    # ---------- Main Loop ----------
    def run(self):
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

                sh, sl, length, direction, parent_info = self._detect_swing_vector(candles)
                pivot = sl + length * 0.5

                self.db.save_vector(
                    self.symbol, sh, sl, length, pivot,
                    parent_info.get('high'), parent_info.get('low'),
                    parent_info.get('length'), parent_info.get('completed', False)
                )

                if abs(current_price - pivot) <= self.TOLERANCE and not self.position_open and not self._entry_triggered:
                    side = None
                    if direction == 1 and current_price >= pivot:
                        side = 'BUY'
                    elif direction == -1 and current_price <= pivot:
                        side = 'SELL'

                    if side:
                        if side == 'BUY':
                            sl_price = latest['low'] - self.SL_BUFFER_POINTS
                            entry_price = current_price
                            multiplier = self.RISK_REWARD_RATIO if parent_info.get('completed', False) else self.RISK_REWARD_RATIO * 0.5
                            tp_price = entry_price + multiplier * (entry_price - sl_price)
                        else:
                            sl_price = latest['high'] + self.SL_BUFFER_POINTS
                            entry_price = current_price
                            multiplier = self.RISK_REWARD_RATIO if parent_info.get('completed', False) else self.RISK_REWARD_RATIO * 0.5
                            tp_price = entry_price - multiplier * (sl_price - entry_price)

                        with self._lock:
                            self._place_orders(side, entry_price, sl_price, tp_price)
                            self.position_open = True
                            self._entry_triggered = True
                            logger.info(f"Trade executed: {side} at {entry_price}, SL {sl_price}, TP {tp_price}")

                time.sleep(5)

            except Exception as e:
                logger.error(f"Loop error: {e}", exc_info=True)
                time.sleep(5)

        logger.info("Engine stopped.")

    def stop(self):
        self.running = False
        self._cancel_all_orders()
        logger.info("Engine shut down.")
