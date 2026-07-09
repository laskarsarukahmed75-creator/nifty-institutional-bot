# app.py
import os
import time
import logging
import threading
import datetime
from typing import Optional, Dict, List, Tuple, Union, Any

# Angel One SmartConnect
try:
    from smartapi import SmartConnect
    from smartapi.smartConnect import SmartConnectException
except ImportError:
    from smartapi import SmartConnect
    SmartConnectException = Exception

# Local modules
from db_handler import DBHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NiftyInstitutionalEngine")

class NiftyInstitutionalEngine:
    """
    Pure mathematical 0.5 Clone Vector Engine – with Backside Lookback Validation.
    All fixes applied:
      - Correct trend direction using most recent swing.
      - Parent vector completion check (lookback over 100-200 candles).
      - Strict position lock (no duplicate orders).
      - Session renewal and error handling.
      - Angel One orderBook API for status checks.
    """

    # Angel One credentials from environment
    API_KEY = os.environ.get("ANGEL_API_KEY", "")
    CLIENT_ID = os.environ.get("ANGEL_CLIENT_ID", "")
    PASSWORD = os.environ.get("ANGEL_PASSWORD", "")
    TOTP_SECRET = os.environ.get("ANGEL_TOTP_SECRET", None)

    # Trading parameters
    TRADE_SYMBOL = os.environ.get("TRADE_SYMBOL", "NIFTY").upper()
    INSTRUMENT_TYPE = "NSE"          # or "NFO" for futures
    PRODUCT_TYPE = "INTRADAY"
    TIMEFRAME = "5m"                # 5‑minute candles

    # Risk parameters
    SL_BUFFER_POINTS = 4.0          # points outside pivot-testing candle
    RISK_REWARD_RATIO = 10.0        # base 1:10 (may be adjusted)
    TOLERANCE = 0.5                 # touch tolerance in points

    # Symbol token mapping (update with actual tokens from Angel One)
    SYMBOL_TOKENS = {
        "NIFTY": 99926000,
        "BANKNIFTY": 99926009,
        "SENSEX": 99926010,
    }

    # Lookback settings for parent vector detection
    LOOKBACK_CANDLES = 150          # number of candles to scan for swings

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
        self.order_ids = []          # list of order IDs (entry, SL, TP)
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

        # Prevent multiple entries on the same retest
        self._entry_triggered = False

        self.running = False

        logger.info("Engine initialised (not logged in yet).")

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def _login(self) -> None:
        """Authenticate with Angel One SmartConnect."""
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
        """Renew the session (call _login again)."""
        logger.warning("Renewing session...")
        self._login()

    def _ensure_session(self) -> None:
        """Check if session is active; renew if needed."""
        try:
            # Simple heart‑beat: fetch LTP
            self._get_ltp()
        except Exception:
            self._renew_session()

    # ------------------------------------------------------------------
    # Market Data
    # ------------------------------------------------------------------
    def _get_ltp(self, symbol: Optional[str] = None) -> float:
        """Get last traded price."""
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

    def _get_historical_candles(self, symbol: Optional[str] = None,
                                limit: int = 200) -> List[Dict]:
        """Fetch up to `limit` 5‑minute candles for swing detection."""
        sym = symbol or self.symbol
        token = self.SYMBOL_TOKENS.get(sym)
        if not token:
            raise ValueError(f"Unknown symbol: {sym}")

        # We need enough candles to look back
        end_date = datetime.datetime.now()
        # Request more than we need to ensure we have enough after filtering
        start_date = end_date - datetime.timedelta(days=5)  # safe margin
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
            # Return only the last `limit` candles
            return candles[-limit:] if len(candles) > limit else candles
        except Exception as e:
            logger.error(f"Historical data error: {e}")
            raise

    # ------------------------------------------------------------------
    # Swing Detection with Backside Lookback
    # ------------------------------------------------------------------
    def _detect_all_swings(self, candles: List[Dict]) -> List[Dict]:
        """
        Detect all swing highs and lows in the candle list.
        Returns a list of swings, each with:
            'type': 'high' or 'low',
            'price': float,
            'index': int
        Sorted chronologically.
        """
        if len(candles) < 10:
            return []

        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        n = len(highs)

        pivots = []

        # Detect pivot highs
        for i in range(2, n-1):
            if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                pivots.append({'type': 'high', 'price': highs[i], 'index': i})
        # Detect pivot lows
        for i in range(2, n-1):
            if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                pivots.append({'type': 'low', 'price': lows[i], 'index': i})

        # Sort by index
        pivots.sort(key=lambda x: x['index'])
        return pivots

    def _extract_last_two_swings(self, pivots: List[Dict]) -> Tuple[Dict, Dict]:
        """
        Given a list of alternating pivot points (high, low, high, ...),
        extract the last two complete swings.
        A swing is defined from one pivot to the next.
        Returns (current_swing, parent_swing) where each is a dict with:
            'start_type', 'start_price', 'start_index',
            'end_type', 'end_price', 'end_index',
            'direction' (1 for up, -1 for down),
            'length'
        """
        if len(pivots) < 4:
            # Not enough pivots to form two swings
            return None, None

        # We need the last two swings: the swing that ends at the last pivot,
        # and the swing that ends at the second last pivot.
        # However, a swing is defined between a low and a high (or high to low).
        # So we need to form swings from each pivot to the next.
        swings = []
        for i in range(len(pivots)-1):
            p1 = pivots[i]
            p2 = pivots[i+1]
            # Determine direction: if p1 is low and p2 is high => up, else down
            if p1['type'] == 'low' and p2['type'] == 'high':
                direction = 1  # up
            elif p1['type'] == 'high' and p2['type'] == 'low':
                direction = -1 # down
            else:
                # Skip invalid sequence (should not happen)
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

        # The last swing is the current one; the previous is the parent.
        current = swings[-1]
        parent = swings[-2]
        return current, parent

    def _check_parent_completion(self, parent_swing: Dict, candles: List[Dict]) -> bool:
        """
        Check if the parent swing completed its 100% extension.
        For an up swing (direction=1), check if price later went above end_price + length.
        For a down swing (direction=-1), check if price later went below end_price - length.
        """
        if parent_swing is None:
            return False
        direction = parent_swing['direction']
        end_idx = parent_swing['end_index']
        length = parent_swing['length']
        end_price = parent_swing['end_price']

        # Look at all candles after the end index
        for i in range(end_idx + 1, len(candles)):
            if direction == 1:  # up swing
                if candles[i]['high'] > end_price + length:
                    return True
            else:  # down swing
                if candles[i]['low'] < end_price - length:
                    return True
        return False

    def _detect_swing_vector(self, candles: List[Dict]) -> Tuple[float, float, float, int, Dict]:
        """
        Detect the most recent swing and its parent swing.
        Returns:
            swing_high, swing_low, length, direction, parent_info
        where parent_info is a dict with keys:
            'high', 'low', 'length', 'completed'
        """
        pivots = self._detect_all_swings(candles)
        if len(pivots) < 4:
            # Fallback: use simple min/max of last 10 candles
            high = max(c['high'] for c in candles[-10:])
            low = min(c['low'] for c in candles[-10:])
            length = high - low
            direction = 1 if candles[-1]['close'] > candles[-10]['close'] else -1
            return high, low, length, direction, {}

        current, parent = self._extract_last_two_swings(pivots)
        if current is None:
            # fallback
            high = max(c['high'] for c in candles[-10:])
            low = min(c['low'] for c in candles[-10:])
            length = high - low
            direction = 1 if candles[-1]['close'] > candles[-10]['close'] else -1
            return high, low, length, direction, {}

        # Current swing high and low
        if current['direction'] == 1:  # up swing
            swing_high = current['end_price']
            swing_low = current['start_price']
        else:  # down swing
            swing_high = current['start_price']
            swing_low = current['end_price']
        length = current['length']
        direction = current['direction']

        # Parent info
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
        """Return the exact 0.5 structural pivot."""
        return swing_low + (swing_high - swing_low) * 0.5

    # ------------------------------------------------------------------
    # Retest Check
    # ------------------------------------------------------------------
    def _check_retest(self, pivot: float, current_price: float,
                      candle_high: float, candle_low: float) -> Tuple[bool, float, float]:
        """
        Determine if current price touches the pivot within tolerance.
        Returns (retested, candle_high, candle_low) of the testing candle.
        """
        if abs(current_price - pivot) <= self.TOLERANCE:
            return True, candle_high, candle_low
        return False, 0.0, 0.0

    # ------------------------------------------------------------------
    # Order Execution
    # ------------------------------------------------------------------
    def _place_order(self, side: str, quantity: int,
                     entry_price: float, sl_price: float, tp_price: float) -> Dict:
        """Place market entry, SL and TP orders."""
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
            logger.info(f"Entry order placed: {order_id}")
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
            logger.info(f"SL order placed: {sl_id}")
        except Exception as e:
            logger.error(f"SL order failed: {e}")
            # Cancel entry if SL fails
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
            logger.info(f"TP order placed: {tp_id}")
        except Exception as e:
            logger.error(f"TP order failed: {e}")
            self._cancel_all_orders()
            raise

        # Log trade in DB
        self.db.log_trade(self.symbol, side, entry_price, sl_price, tp_price, "OPEN")
        return order_responses

    def _cancel_all_orders(self) -> None:
        """Cancel all pending orders."""
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
        """
        Check if the current position is closed (SL or TP hit) using orderBook.
        Returns True if no open position, False if still open.
        """
        if not self.position_open:
            return True

        if len(self.order_ids) < 3:
            # Something wrong; force reset.
            self.position_open = False
            self._entry_triggered = False
            return True

        sl_id = self.order_ids[1] if len(self.order_ids) > 1 else None
        tp_id = self.order_ids[2] if len(self.order_ids) > 2 else None
        if not sl_id or not tp_id:
            return False

        try:
            # Fetch order book
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

            # Consider closed if either SL or TP is filled/rejected/cancelled
            sl_closed = sl_status in ['COMPLETE', 'REJECTED', 'CANCELLED']
            tp_closed = tp_status in ['COMPLETE', 'REJECTED', 'CANCELLED']

            if sl_closed or tp_closed:
                self.position_open = False
                self._entry_triggered = False
                self.order_ids.clear()
                logger.info("Position closed (SL or TP hit). Lock released.")
                return True

        except Exception as e:
            logger.warning(f"Error checking order status: {e}")
            # If we can't check, assume still open to be safe.
            return False

        return False  # still open

    # ------------------------------------------------------------------
    # Main Trading Loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Infinite loop: monitor price, detect setup, execute trades."""
        # Perform login here (after Flask has started)
        self._login()
        self.running = True
        logger.info("Engine started. Monitoring for 0.5 pivot retests...")
        self._ensure_session()

        while self.running:
            try:
                # Refresh session
                self._ensure_session()

                # Check if existing position is closed
                self._check_position_closed()

                # Get candles and current price
                candles = self._get_historical_candles(limit=self.LOOKBACK_CANDLES)
                if not candles:
                    time.sleep(5)
                    continue
                latest = candles[-1]
                current_price = self._get_ltp()

                # Detect swing vector with parent info
                swing_high, swing_low, length, direction, parent_info = self._detect_swing_vector(candles)
                self.last_swing_high = swing_high
                self.last_swing_low = swing_low
                self.last_vector_length = length

                # Compute pivot
                pivot = self._compute_pivot_0_5(swing_high, swing_low)
                self.pivot_0_5 = pivot

                # Store parent info for DB
                self.parent_swing_high = parent_info.get('high')
                self.parent_swing_low = parent_info.get('low')
                self.parent_length = parent_info.get('length')
                self.parent_completed = parent_info.get('completed', False)

                # Save vector to DB (including parent)
                self.db.save_vector(
                    self.symbol, swing_high, swing_low, length, pivot,
                    parent_swing_high=self.parent_swing_high,
                    parent_swing_low=self.parent_swing_low,
                    parent_length=self.parent_length,
                    parent_completed=self.parent_completed
                )

                # Check retest
                retested, candle_high, candle_low = self._check_retest(
                    pivot, current_price, latest['high'], latest['low']
                )

                # Entry logic
                if retested and not self.position_open and not self._entry_triggered:
                    # Determine side based on vector direction:
                    # direction = 1 => up vector => long (BUY) on pullback to pivot
                    # direction = -1 => down vector => short (SELL) on rally to pivot
                    side = None
                    if direction == 1 and current_price >= pivot - self.TOLERANCE:
                        side = 'BUY'
                    elif direction == -1 and current_price <= pivot + self.TOLERANCE:
                        side = 'SELL'

                    if side:
                        # Compute SL and TP
                        if side == 'BUY':
                            sl_price = candle_low - self.SL_BUFFER_POINTS
                            entry_price = current_price
                            # Adjust TP based on parent completion?
                            # If parent completed, use full 1:10; else reduce target.
                            if self.parent_completed:
                                reward_multiplier = self.RISK_REWARD_RATIO
                            else:
                                # Reduce target by half if parent didn't complete
                                reward_multiplier = self.RISK_REWARD_RATIO * 0.5
                            tp_price = entry_price + reward_multiplier * (entry_price - sl_price)
                        else:  # SELL
                            sl_price = candle_high + self.SL_BUFFER_POINTS
                            entry_price = current_price
                            if self.parent_completed:
                                reward_multiplier = self.RISK_REWARD_RATIO
                            else:
                                reward_multiplier = self.RISK_REWARD_RATIO * 0.5
                            tp_price = entry_price - reward_multiplier * (sl_price - entry_price)

                        # Fixed quantity (can be made dynamic)
                        quantity = 1

                        # Place orders
                        with self._lock:
                            self._place_order(side, quantity, entry_price, sl_price, tp_price)
                            self.position_open = True
                            self._entry_triggered = True
                            self.last_entry_time = time.time()
                            logger.info(f"Trade executed: {side} at {entry_price}, SL {sl_price}, TP {tp_price}")

                # Sleep 5 seconds before next poll
                time.sleep(5)

            except Exception as e:
                logger.error(f"Loop error: {e}", exc_info=True)
                time.sleep(5)

        logger.info("Engine stopped.")

    def stop(self) -> None:
        """Graceful shutdown."""
        self.running = False
        self._cancel_all_orders()
        logger.info("Engine shut down.")
