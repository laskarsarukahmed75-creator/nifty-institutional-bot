from typing import Dict, List, Optional, Any, Tuple, Set
import logging
# ============================================================================
# START MODULE: SMCEngine
# Version: 1.0.0
# Dependencies: config, candle_engine
# Public Functions: analyze, get_signal
# Private Functions: _detect_swings, _find_liquidity_sweep, _find_order_block, _find_fvg, _check_displacement
# Upgrade Notes: Replace with different market structure logic. Maintain same output.
# ============================================================================

from datetime import datetime
from typing import List, Tuple, Optional, Dict
from config.config import Config
from .candle_engine import CandleEngine

class SMCEngine:
    def __init__(self, candle_engine: CandleEngine):
        self.candle_engine = candle_engine
        self.last_signal_time: Dict[str, datetime] = {}
    
    def _detect_swings(self, candles: List[Dict]) -> List[Dict]:
        if len(candles) < 5:
            return []
        swings = []
        for i in range(2, len(candles)-2):
            if candles[i]['high'] > candles[i-1]['high'] and candles[i]['high'] > candles[i-2]['high'] and \
               candles[i]['high'] > candles[i+1]['high'] and candles[i]['high'] > candles[i+2]['high']:
                swings.append({'price': candles[i]['high'], 'index': i, 'time': candles[i]['timestamp'], 'is_high': True})
            elif candles[i]['low'] < candles[i-1]['low'] and candles[i]['low'] < candles[i-2]['low'] and \
                 candles[i]['low'] < candles[i+1]['low'] and candles[i]['low'] < candles[i+2]['low']:
                swings.append({'price': candles[i]['low'], 'index': i, 'time': candles[i]['timestamp'], 'is_high': False})
        return swings
    
    def _find_liquidity_sweep(self, swings: List[Dict], current_price: float) -> bool:
        if len(swings) < 2:
            return False
        recent_high = max([s['price'] for s in swings[-3:] if s['is_high']], default=0)
        recent_low = min([s['price'] for s in swings[-3:] if not s['is_high']], default=float('inf'))
        return current_price > recent_high or current_price < recent_low
    
    def _find_order_block(self, candles: List[Dict]) -> Optional[Tuple[float, float]]:
        if len(candles) < 3:
            return None
        if candles[-1]['close'] > candles[-2]['high'] and candles[-2]['close'] < candles[-3]['close']:
            return (candles[-2]['low'], candles[-2]['high'])
        if candles[-1]['close'] < candles[-2]['low'] and candles[-2]['close'] > candles[-3]['close']:
            return (candles[-2]['low'], candles[-2]['high'])
        return None
    
    def _find_fvg(self, candles: List[Dict]) -> Optional[Tuple[float, float]]:
        if len(candles) < 3:
            return None
        c1, c2, c3 = candles[-3], candles[-2], candles[-1]
        if c1['high'] < c2['low'] and c3['low'] < c2['high']:
            return (c1['high'], c2['low'])
        if c1['low'] > c2['high'] and c3['high'] > c2['low']:
            return (c2['high'], c1['low'])
        return None
    
    def _check_displacement(self, candles: List[Dict]) -> bool:
        if len(candles) < 3:
            return False
        body = abs(candles[-1]['close'] - candles[-1]['open'])
        avg_range = (candles[-1]['high'] - candles[-1]['low'] + candles[-2]['high'] - candles[-2]['low']) / 2
        return body > avg_range * 1.5
    
    def analyze(self, symbol: str, tf: int = Config.TIMEFRAME_5M) -> Dict:
        candles = self.candle_engine.get_candles(symbol, tf, 200)
        if len(candles) < 50:
            return {'trend': 'SIDEWAYS', 'bos': False, 'choch': False, 'liquidity_sweep': False}
        closes = [c['close'] for c in candles]
        ema_vals = self.candle_engine.ema(closes, 50)
        current_ema = ema_vals[-1] if ema_vals else closes[-1]
        current_price = candles[-1]['close']
        trend = 'BULLISH' if current_price > current_ema else 'BEARISH'
        swings = self._detect_swings(candles)
        bos = False
        choch = False
        if len(swings) >= 2:
            if trend == 'BULLISH' and current_price > max([s['price'] for s in swings if s['is_high']]):
                bos = True
            elif trend == 'BEARISH' and current_price < min([s['price'] for s in swings if not s['is_high']]):
                bos = True
            if len(swings) >= 4:
                last_swing_high = max([s['price'] for s in swings[-2:] if s['is_high']], default=0)
                last_swing_low = min([s['price'] for s in swings[-2:] if not s['is_high']], default=float('inf'))
                if trend == 'BULLISH' and current_price < last_swing_low:
                    choch = True
                elif trend == 'BEARISH' and current_price > last_swing_high:
                    choch = True
        liquidity_sweep = self._find_liquidity_sweep(swings, current_price)
        order_block = self._find_order_block(candles)
        fvg = self._find_fvg(candles)
        displacement = self._check_displacement(candles)
        high_50 = max([c['high'] for c in candles[-50:]])
        low_50 = min([c['low'] for c in candles[-50:]])
        mid = (high_50 + low_50) / 2
        premium_zone = current_price > mid
        discount_zone = current_price < mid
        return {
            'trend': trend, 'bos': bos, 'choch': choch, 'liquidity_sweep': liquidity_sweep,
            'order_block': order_block, 'fvg': fvg, 'displacement': displacement,
            'premium_zone': premium_zone, 'discount_zone': discount_zone
        }
    
    def get_signal(self, symbol: str) -> Optional[Dict]:
        if symbol in self.last_signal_time:
            if (datetime.now() - self.last_signal_time[symbol]).total_seconds() < Config.COOLDOWN_SECONDS:
                return None
        struct_1m = self.analyze(symbol, Config.TIMEFRAME_1M)
        struct_5m = self.analyze(symbol, Config.TIMEFRAME_5M)
        struct_15m = self.analyze(symbol, Config.TIMEFRAME_15M)
        bullish_counts = sum([1 for s in [struct_1m, struct_5m, struct_15m] if s['trend'] == 'BULLISH'])
        bearish_counts = sum([1 for s in [struct_1m, struct_5m, struct_15m] if s['trend'] == 'BEARISH'])
        if bullish_counts >= 2:
            entry = self.candle_engine.get_candles(symbol, Config.TIMEFRAME_5M, 1)[-1]['close']
            stop_loss = entry * (1 - Config.SL_PERCENT / 100)
            take_profit = entry * (1 + Config.TP_PERCENT / 100)
            rr = (take_profit - entry) / (entry - stop_loss) if (entry - stop_loss) != 0 else 0
            if rr < Config.MIN_RISK_REWARD:
                return None
            if struct_1m['liquidity_sweep'] or struct_5m['order_block'] or struct_5m['fvg']:
                self.last_signal_time[symbol] = datetime.now()
                return {
                    'symbol': symbol, 'direction': 'BUY', 'entry': entry, 'stop_loss': stop_loss,
                    'take_profit': take_profit, 'risk_reward': rr,
                    'reason': 'Bullish alignment OB/FVG sweep', 'timestamp': datetime.now().isoformat()
                }
        elif bearish_counts >= 2:
            entry = self.candle_engine.get_candles(symbol, Config.TIMEFRAME_5M, 1)[-1]['close']
            stop_loss = entry * (1 + Config.SL_PERCENT / 100)
            take_profit = entry * (1 - Config.TP_PERCENT / 100)
            rr = (entry - take_profit) / (stop_loss - entry) if (stop_loss - entry) != 0 else 0
            if rr < Config.MIN_RISK_REWARD:
                return None
            if struct_1m['liquidity_sweep'] or struct_5m['order_block'] or struct_5m['fvg']:
                self.last_signal_time[symbol] = datetime.now()
                return {
                    'symbol': symbol, 'direction': 'SELL', 'entry': entry, 'stop_loss': stop_loss,
                    'take_profit': take_profit, 'risk_reward': rr,
                    'reason': 'Bearish alignment OB/FVG sweep', 'timestamp': datetime.now().isoformat()
                }
        return None

# ============================================================================
# END MODULE: SMCEngine
# ============================================================================
