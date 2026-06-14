# ============================================================================
# START MODULE: AngelOneClient
# Version: 2.1.0
# Dependencies: SmartApi, config, database_manager, threading
# Public Functions: connect, place_order, exit_position, get_order_status, cancel_order, get_positions, reconcile_positions, disconnect
# Private Functions: _generate_totp, _load_instrument_master, _wait_for_order_complete
# Upgrade Notes: Replace entire class if broker changes. Maintain same interface.
# ============================================================================

import time
import hmac
import base64
import hashlib
import threading
from typing import Optional, Dict, List, Any
from SmartApi import SmartConnect

from config.config import Config
from database.database_manager import DatabaseManager

class AngelOneClient:
    def __init__(self, db: DatabaseManager = None):
        self.api: Optional[SmartConnect] = None
        self.auth_token: Optional[str] = None
        self.feed_token: Optional[str] = None
        self.client_id = Config.ANGEL_CLIENT_ID
        self.token_map: Dict[str, str] = {}
        self.instrument_map: Dict[str, Dict] = {}
        self._lock = threading.RLock()
        self._connected = False
        self.db = db or DatabaseManager()
    
    def connect(self) -> bool:
        with self._lock:
            try:
                self.api = SmartConnect(api_key=Config.ANGEL_API_KEY)
                totp = self._generate_totp(Config.ANGEL_TOTP_SECRET)
                data = self.api.generateSession(
                    clientCode=Config.ANGEL_CLIENT_ID,
                    password=Config.ANGEL_PASSWORD,
                    totp=totp
                )
                if not data.get('status'):
                    return False
                self.auth_token = data['data']['jwtToken']
                self.feed_token = self.api.getFeedToken()
                self._connected = True
                self._load_instrument_master()
                return True
            except Exception:
                return False
    
    def _generate_totp(self, secret: str) -> str:
        secret_bytes = base64.b32decode(secret.upper())
        time_step = int(time.time()) // 30
        msg = time_step.to_bytes(8, 'big')
        h = hmac.new(secret_bytes, msg, hashlib.sha1).digest()
        o = h[19] & 0x0f
        code = (int.from_bytes(h[o:o+4], 'big') & 0x7fffffff) % 1000000
        return f"{code:06d}"
    
    def _load_instrument_master(self):
        for symbol in Config.SYMBOLS:
            try:
                resp = self.api.searchScrip(exchange=Config.EXCHANGE, searchtext=symbol)
                if not resp.get('status'):
                    continue
                data = resp.get('data')
                if not data or not isinstance(data, list) or len(data) == 0:
                    continue
                item = None
                for it in data:
                    if it.get('symbolname') == symbol:
                        item = it
                        break
                if not item:
                    item = data[0]
                token = item.get('symboltoken')
                trading_symbol = item.get('tradingsymbol', symbol)
                if not token:
                    continue
                self.token_map[symbol] = token
                self.instrument_map[symbol] = {
                    'token': token,
                    'tradingsymbol': trading_symbol,
                    'exchange': Config.EXCHANGE
                }
            except Exception:
                continue
    
    def get_trading_symbol(self, symbol: str) -> str:
        return self.instrument_map.get(symbol, {}).get('tradingsymbol', symbol)
    
    def get_token(self, symbol: str) -> str:
        return self.token_map.get(symbol, "")
    
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        methods = [
            ('orderStatus', lambda: self.api.orderStatus({"orderid": order_id})),
            ('orderstatus', lambda: self.api.orderstatus({"orderid": order_id})),
            ('getOrderBook', lambda: self.api.getOrderBook())
        ]
        for method_name, method_call in methods:
            if hasattr(self.api, method_name):
                try:
                    resp = method_call()
                    if resp and resp.get('status'):
                        data = resp.get('data')
                        if isinstance(data, list):
                            for order in data:
                                if str(order.get('orderid')) == str(order_id):
                                    status = order.get('orderstatus') or order.get('orderStatus') or order.get('status')
                                    if status:
                                        order['status'] = status.upper()
                                    return order
                        elif isinstance(data, dict):
                            status = data.get('orderstatus') or data.get('orderStatus') or data.get('status')
                            if status:
                                data['status'] = status.upper()
                            return data
                except Exception:
                    continue
        return None
    
    def cancel_order(self, order_id: str) -> bool:
        try:
            resp = self.api.cancelOrder({"orderid": order_id})
            if isinstance(resp, dict):
                return resp.get('status', False)
            return bool(resp)
        except Exception:
            return False
    
    def place_order(self, symbol: str, direction: str, quantity: int, price: float,
                    stop_loss: float, take_profit: float) -> Optional[Dict[str, str]]:
        try:
            transaction_type = "BUY" if direction == "BUY" else "SELL"
            symbol_token = self.get_token(symbol)
            trading_symbol = self.get_trading_symbol(symbol)
            if not symbol_token:
                return None
            
            # Main order
            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": trading_symbol,
                "symboltoken": symbol_token,
                "transactiontype": transaction_type,
                "exchange": Config.EXCHANGE,
                "ordertype": "LIMIT",
                "producttype": Config.PRODUCT_TYPE,
                "duration": "DAY",
                "price": str(price),
                "quantity": str(quantity)
            }
            resp = self.api.placeOrder(order_params)
            if isinstance(resp, str):
                main_order_id = resp
            elif isinstance(resp, dict) and resp.get('status'):
                main_order_id = resp.get('data', {}).get('orderid')
            else:
                return None
            
            # SL order
            sl_transaction = "SELL" if direction == "BUY" else "BUY"
            sl_params = {
                "variety": "STOPLOSS",
                "tradingsymbol": trading_symbol,
                "symboltoken": symbol_token,
                "transactiontype": sl_transaction,
                "exchange": Config.EXCHANGE,
                "ordertype": "STOPLOSS_LIMIT",
                "producttype": Config.PRODUCT_TYPE,
                "duration": "DAY",
                "price": str(stop_loss),
                "triggerprice": str(stop_loss),
                "quantity": str(quantity)
            }
            sl_resp = self.api.placeOrder(sl_params)
            sl_order_id = None
            if isinstance(sl_resp, str):
                sl_order_id = sl_resp
            elif isinstance(sl_resp, dict) and sl_resp.get('status'):
                sl_order_id = sl_resp.get('data', {}).get('orderid')
            
            # TP order
            tp_params = {
                "variety": "NORMAL",
                "tradingsymbol": trading_symbol,
                "symboltoken": symbol_token,
                "transactiontype": sl_transaction,
                "exchange": Config.EXCHANGE,
                "ordertype": "LIMIT",
                "producttype": Config.PRODUCT_TYPE,
                "duration": "DAY",
                "price": str(take_profit),
                "quantity": str(quantity)
            }
            tp_resp = self.api.placeOrder(tp_params)
            tp_order_id = None
            if isinstance(tp_resp, str):
                tp_order_id = tp_resp
            elif isinstance(tp_resp, dict) and tp_resp.get('status'):
                tp_order_id = tp_resp.get('data', {}).get('orderid')
            
            if not sl_order_id or not tp_order_id:
                self.cancel_order(main_order_id)
                return None
            
            return {"order_id": main_order_id, "sl_order_id": sl_order_id, "tp_order_id": tp_order_id}
        except Exception:
            return None
    
    def exit_position(self, symbol: str, direction: str, quantity: int) -> Optional[str]:
        try:
            transaction_type = "SELL" if direction == "BUY" else "BUY"
            symbol_token = self.get_token(symbol)
            trading_symbol = self.get_trading_symbol(symbol)
            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": trading_symbol,
                "symboltoken": symbol_token,
                "transactiontype": transaction_type,
                "exchange": Config.EXCHANGE,
                "ordertype": "MARKET",
                "producttype": Config.PRODUCT_TYPE,
                "duration": "DAY",
                "quantity": str(quantity)
            }
            resp = self.api.placeOrder(order_params)
            if isinstance(resp, str):
                return resp
            elif isinstance(resp, dict) and resp.get('status'):
                return resp.get('data', {}).get('orderid')
            return None
        except Exception:
            return None
    
    def get_positions(self) -> List[Dict]:
        if not hasattr(self.api, 'position'):
            return []
        try:
            resp = self.api.position()
            if resp.get('status'):
                data = resp.get('data', [])
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return [data] if data else []
        except Exception:
            pass
        return []
    
    def reconcile_positions(self, local_positions: List[Dict]) -> Dict[str, Dict]:
        broker_positions = self.get_positions()
        broker_map = {}
        for bp in broker_positions:
            netqty_str = bp.get('netqty', '0')
            try:
                netqty = int(netqty_str) if netqty_str else 0
            except (ValueError, TypeError):
                netqty = 0
            if netqty != 0:
                oid = bp.get('orderid')
                if oid:
                    broker_map[oid] = bp
        reconciled = {}
        for pos in local_positions:
            if pos['order_id'] in broker_map:
                reconciled[pos['order_id']] = pos
            else:
                self.db.update_position_status(pos['order_id'], "CLOSED")
        return reconciled
    
    def disconnect(self):
        with self._lock:
            if self.api:
                try:
                    self.api.logout()
                except:
                    pass
            self._connected = False

# ============================================================================
# END MODULE: AngelOneClient
# ============================================================================
