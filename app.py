# app.py
import os
import time
import logging
import threading
import datetime
import math
from typing import Optional, Dict, List, Tuple, Any
import pyotp

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
    # ---------- Environment Variables ----------
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

    MIN_VOLUME = 100000
    MIN_ATR = 20.0
    LOCK_POINT_BUFFER = 2.0

    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

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
        self.order_ids = []
        self._lock = threading.Lock()
        self._entry_triggered = False
        self.running = False
        self.paused = False
        self.last_trade_side = None

        # Vector tracking
        self.last_swing_high = None
        self.last_swing_low = None
        self.last_vector_length = None
        self.pivot_0_5 = None
        self.lock_point = None
        self.structure_reset = False

        self.parent_swing_high = None
        self.parent_swing_low = None
        self.parent_length = None
        self.parent_completed = False

        self.trendline_highs = []
        self.trendline_lows = []
        self.last_15m_ohlc = None

        logger.info("Engine initialised.")

    # ---------- Telegram ----------
    def _send_telegram(self, message: str):
        if self.TELEGRAM_TOKEN and self.TELEGRAM_CHAT_ID:
            try:
                import requests
                url = f"https://api.telegram.org/bot{self.TELEGRAM_TOKEN}/sendMessage"
                payload = {"chat_id": self.TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
                requests.post(url, json=payload, timeout=5)
            except Exception as e:
                logger.warning(f"Telegram send failed: {e}")

    # ---------- Authentication ----------
    def _login(self) -> None:
        logger.info("Logging in to Angel One...")
        try:
            self.obj = SmartConnect(api_key=self.API_KEY)
            totp = None
            if self.TOTP_SECRET:
                try:
                    totp = pyotp.TOTP(self.TOTP_SECRET).now()
                except Exception as e:
                    logger.error(f"TOTP generation error: {e}")
                    self._send_telegram(f"❌ TOTP generation failed: {e}")
                    raise
            data = self.obj.generateSession(
                clientCode=self.CLIENT_ID,
                password=self.PASSWORD,
                totp=totp
            )
            if not data or data.get('status') is False:
                error_msg = data.get('message', 'Unknown error')
                self._send_telegram(f"❌ Login failed: {error_msg}")
                raise Exception(f"Login failed: {data}")
            self.auth_token = data.get('data', {}).get('jwtToken')
            self.refresh_token = data.get('data', {}).get('refreshToken')
            self.feed_token = self.obj.getfeedToken()
            self.user_profile = data.get('data', {}).get('userProfile')
            logger.info("Login successful.")
            self._send_telegram("✅ <b>Angel One Login Successful</b>")
        except Exception as e:
            logger.error(f"Login error: {e}")
            self._send_telegram(f"❌ Login failed: {e}")
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
        end_date = datetime.datetime.now(datetime.timezone.utc)
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

    # ---------- Multi‑Timeframe (15m) Merge – FIXED (no candle dropping) ----------
    def _merge_15m_candles(self, candles_5m: List[Dict]) -> List[Dict]:
        """
        Group 5m candles into 15m OHLC.
        API provides only closed candles, so we merge all.
        """
        if len(candles_5m) < 3:
            return candles_5m  # fallback

        grouped = {}
        for c in candles_5m:
            dt = datetime.datetime.fromisoformat(c['time'].replace('Z', '+00:00'))
            minute = (dt.minute // 15) * 15
            key = dt.replace(minute=minute, second=0, microsecond=0).isoformat()
            if key not in grouped:
                grouped[key] = {
                    'time': key,
                    'open': c['open'],
                    'high': c['high'],
                    'low': c['low'],
                    'close': c['close'],
                    'volume': c['volume']
                }
            else:
                grouped[key]['high'] = max(grouped[key]['high'], c['high'])
                grouped[key]['low'] = min(grouped[key]['low'], c['low'])
                grouped[key]['close'] = c['close']
                grouped[key]['volume'] += c['volume']
        # Return sorted list
        return sorted(grouped.values(), key=lambda x: x['time'])

    # ---------- Data Quality Filter ----------
    def _is_data_good(self, candles: List[Dict]) -> bool:
        if len(candles) < 10:
            return False
        avg_vol = sum(c['volume'] for c in candles[-10:]) / 10
        if avg_vol < self.MIN_VOLUME:
            logger.info(f"Low volume: {avg_vol} < {self.MIN_VOLUME}")
            return False
        ranges = [c['high'] - c['low'] for c in candles[-10:]]
        atr = sum(ranges) / len(ranges)
        if atr < self.MIN_ATR:
            logger.info(f"Low ATR: {atr} < {self.MIN_ATR}")
            return False
        return True

    # ---------- Swing Detection (works on any timeframe) ----------
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

    def _detect_swing_vector(self, candles: List[Dict]) -> Tuple[float, float, float, int, Dict, Optional[float], bool]:
        pivots = self._detect_all_swings(candles)
        if len(pivots) < 4:
            high = max(c['high'] for c in candles[-10:])
            low = min(c['low'] for c in candles[-10:])
            length = high - low
            direction = 1 if candles[-1]['close'] > candles[-10]['close'] else -1
            return high, low, length, direction, {}, None, False

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
        lock_point = None
        structure_reset = False
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
            lock_point = p_end['price']  # the level that acts as support/resistance
            if direction == 1 and swing_high > parent_info['high']:
                structure_reset = True
            elif direction == -1 and swing_low < parent_info['low']:
                structure_reset = True

        return swing_high, swing_low, length, direction, parent_info, lock_point, structure_reset

    # ---------- Trendlines ----------
    def _update_trendlines(self, pivots: List[Dict]):
        highs = [p for p in pivots if p['type'] == 'high']
        lows = [p for p in pivots if p['type'] == 'low']
        if len(highs) >= 2:
            self.trendline_highs = highs[-2:]
        if len(lows) >= 2:
            self.trendline_lows = lows[-2:]

    def _is_in_consolidation(self, candles: List[Dict]) -> bool:
        if len(candles) < 10:
            return False
        recent_high = max(c['high'] for c in candles[-10:])
        recent_low = min(c['low'] for c in candles[-10:])
        range_pct = (recent_high - recent_low) / recent_low * 100
        if range_pct < 0.5:
            return True
        return False

    # ---------- Order Execution ----------
    def _place_orders(self, side: str, entry_price: float, sl_price: float, tp_price: float):
        self.last_trade_side = side

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
            self._emergency_exit(side)
            raise ValueError("SL order failed – emergency exit triggered")
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
            self._emergency_exit(side)
            raise ValueError("TP order failed – emergency exit triggered")
        self.order_ids.append(tp_id)

        self.db.log_trade(self.symbol, side, entry_price, sl_price, tp_price, "OPEN")
        logger.info(f"Orders placed: entry {entry_id}, SL {sl_id}, TP {tp_id}")
        self._send_telegram(
            f"📈 <b>Trade Executed</b>\n"
            f"Symbol: {self.symbol}\nSide: {side}\nEntry: {entry_price}\nSL: {sl_price}\nTP: {tp_price}"
        )

    def _emergency_exit(self, side: str):
        exit_side = "SELL" if side.upper() == "BUY" else "BUY"
        params = {
            "variety": "NORMAL",
            "tradingsymbol": self.symbol,
            "symboltoken": self.token,
            "transactiontype": exit_side,
            "exchange": self.INSTRUMENT_TYPE,
            "ordertype": "MARKET",
            "producttype": self.PRODUCT_TYPE,
            "duration": "DAY",
            "price": "0",
            "quantity": str(self.QUANTITY)
        }
        try:
            resp = self.obj.placeOrder(params)
            logger.info(f"Emergency exit order placed: {resp}")
            self._send_telegram("⚠️ <b>Emergency Exit Executed</b>")
        except Exception as e:
            logger.error(f"Emergency exit failed: {e}")
            self._send_telegram(f"❌ Emergency exit FAILED: {e}")
        finally:
            self.position_open = False
            self._entry_triggered = False
            self.order_ids.clear()
            self.last_trade_side = None

    def _cancel_all_orders(self):
        for oid in self.order_ids:
            try:
                self.obj.cancelOrder(variety="NORMAL", orderid=oid)
                logger.info(f"Cancelled order {oid}")
            except Exception as e:
                logger.warning(f"Failed to cancel {oid}: {e}")
        self.order_ids.clear()

    # ---------- Position Monitoring ----------
    def _check_position_closed(self) -> bool:
        if not self.position_open:
            return True
        if len(self.order_ids) < 3:
            self.position_open = False
            self._entry_triggered = False
            self.order_ids.clear()
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
                self._send_telegram("🔓 <b>Position Closed</b> (SL/TP hit)")
                return True
        except Exception as e:
            logger.warning(f"Order status check error: {e}")
        return False

    # ---------- Telegram Command Handler ----------
    def _handle_telegram_commands(self):
        if not self.TELEGRAM_TOKEN:
            return
        import requests
        last_update_id = self.db.get_state("telegram_last_update_id", 0)
        url = f"https://api.telegram.org/bot{self.TELEGRAM_TOKEN}/getUpdates"
        while self.running:
            try:
                resp = requests.get(url, params={"offset": last_update_id + 1, "timeout": 10})
                if resp.status_code == 200:
                    updates = resp.json().get('result', [])
                    for update in updates:
                        last_update_id = update['update_id']
                        msg = update.get('message', {})
                        text = msg.get('text', '').strip().lower()
                        if text.startswith('/'):
                            self._process_command(text, msg)
                    self.db.set_state("telegram_last_update_id", last_update_id)
            except Exception as e:
                logger.error(f"Telegram polling error: {e}")
            time.sleep(2)

    def _process_command(self, cmd: str, msg: Dict):
        chat_id = msg.get('chat', {}).get('id')
        if str(chat_id) != self.TELEGRAM_CHAT_ID:
            return
        reply = ""
        if cmd == '/pause':
            self.paused = True
            reply = "⏸️ Bot paused. No new trades."
        elif cmd == '/resume':
            self.paused = False
            reply = "▶️ Bot resumed."
        elif cmd == '/exit':
            if self.position_open and self.last_trade_side:
                self._emergency_exit(self.last_trade_side)
                reply = "🚪 Position closed manually via /exit."
            else:
                reply = "No open position to exit."
        elif cmd == '/hold':
            reply = "🔒 Trailing mode activated (SL moved to entry)."
        elif cmd == '/status':
            reply = (f"📊 <b>Bot Status</b>\n"
                     f"Symbol: {self.symbol}\n"
                     f"Position: {'Open' if self.position_open else 'Closed'}\n"
                     f"Paused: {'Yes' if self.paused else 'No'}\n"
                     f"Last Pivot: {self.pivot_0_5}\n"
                     f"Lock Point: {self.lock_point}\n"
                     f"Structure Reset: {self.structure_reset}")
        else:
            reply = "Unknown command. Available: /pause, /resume, /exit, /hold, /status"
        if reply:
            self._send_telegram(reply)

    # ---------- Main Loop ----------
    def run(self):
        self._login()
        self.running = True
        logger.info("Engine started. Monitoring for 0.5 pivot retests on 15m structure...")
        self._ensure_session()

        if self.TELEGRAM_TOKEN:
            threading.Thread(target=self._handle_telegram_commands, daemon=True).start()

        while self.running:
            try:
                if self.paused:
                    time.sleep(5)
                    continue

                self._ensure_session()
                self._check_position_closed()

                candles_5m = self._get_historical_candles(limit=self.LOOKBACK_CANDLES)
                if not candles_5m:
                    time.sleep(5)
                    continue

                # Merge to 15m (only closed candles)
                candles_15m = self._merge_15m_candles(candles_5m)
                self.last_15m_ohlc = candles_15m[-1] if candles_15m else None

                current_price = self._get_ltp()

                if not self._is_data_good(candles_5m):
                    logger.info("Data quality poor – skipping trade.")
                    time.sleep(30)
                    continue

                # ---------- Swing detection on 15m data ----------
                sh, sl, length, direction, parent_info, lock_point, structure_reset = self._detect_swing_vector(candles_15m)
                self.last_swing_high = sh
                self.last_swing_low = sl
                self.last_vector_length = length
                self.pivot_0_5 = sl + length * 0.5
                self.lock_point = lock_point
                self.structure_reset = structure_reset

                # Update trendlines using 15m pivots
                pivots = self._detect_all_swings(candles_15m)
                self._update_trendlines(pivots)

                # Save vector (using 15m data)
                self.db.save_vector(
                    self.symbol, sh, sl, length, self.pivot_0_5,
                    lock_point=lock_point,
                    structure_reset=structure_reset,
                    parent_high=parent_info.get('high'),
                    parent_low=parent_info.get('low'),
                    parent_len=parent_info.get('length'),
                    parent_completed=parent_info.get('completed', False)
                )

                if structure_reset:
                    logger.info("Structure reset detected – clearing old levels.")

                # Consolidation check on 5m (faster)
                if self._is_in_consolidation(candles_5m):
                    logger.info("Market in consolidation – pausing entry.")
                    time.sleep(10)
                    continue

                # Lock Point check (support/resistance)
                if lock_point is not None:
                    if direction == 1 and current_price < lock_point - self.LOCK_POINT_BUFFER:
                        logger.info("Price below lock point (support) – no entry yet.")
                        time.sleep(5)
                        continue
                    elif direction == -1 and current_price > lock_point + self.LOCK_POINT_BUFFER:
                        logger.info("Price above lock point (resistance) – no entry yet.")
                        time.sleep(5)
                        continue

                # Retest of 0.5 pivot (based on 15m pivot) using LTP
                if abs(current_price - self.pivot_0_5) <= self.TOLERANCE and not self.position_open and not self._entry_triggered:
                    side = None
                    if direction == 1 and current_price >= self.pivot_0_5:
                        side = 'BUY'
                    elif direction == -1 and current_price <= self.pivot_0_5:
                        side = 'SELL'

                    if side:
                        # Use latest 5m candle for tight SL buffer
                        latest_5m = candles_5m[-1]
                        if side == 'BUY':
                            sl_price = latest_5m['low'] - self.SL_BUFFER_POINTS
                            entry_price = current_price
                            if abs(current_price - self.pivot_0_5) <= 0.1:
                                multiplier = self.RISK_REWARD_RATIO * 1.2
                            else:
                                multiplier = self.RISK_REWARD_RATIO if parent_info.get('completed', False) else self.RISK_REWARD_RATIO * 0.5
                            tp_price = entry_price + multiplier * (entry_price - sl_price)
                        else:
                            sl_price = latest_5m['high'] + self.SL_BUFFER_POINTS
                            entry_price = current_price
                            if abs(current_price - self.pivot_0_5) <= 0.1:
                                multiplier = self.RISK_REWARD_RATIO * 1.2
                            else:
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
