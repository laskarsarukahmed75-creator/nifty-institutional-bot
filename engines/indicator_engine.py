from typing import Dict, List, Optional, Any, Tuple, Set
import logging
# ============================================================================
# START MODULE: IndicatorEngine
# Version: 1.0.0
# Dependencies: numpy
# Public Functions: rsi, atr, vwap
# Private Functions: none
# Upgrade Notes: Add new indicators here.
# ============================================================================

import numpy as np
from typing import List, Tuple

class IndicatorEngine:
    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> List[float]:
        if len(prices) < period + 1:
            return []
        deltas = np.diff(prices[-period-1:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        rsi_vals = []
        for i in range(period, len(deltas)):
            if avg_loss == 0:
                rsi_vals.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_vals.append(100 - (100 / (1 + rs)))
            avg_gain = (avg_gain * (period-1) + gains[i]) / period
            avg_loss = (avg_loss * (period-1) + losses[i]) / period
        return rsi_vals
    
    @staticmethod
    def atr(high: List[float], low: List[float], close: List[float], period: int = 14) -> List[float]:
        if len(high) < period:
            return []
        tr = []
        for i in range(1, len(high)):
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i-1])
            lc = abs(low[i] - close[i-1])
            tr.append(max(hl, hc, lc))
        atr = []
        for i in range(period-1, len(tr)):
            if i == period-1:
                atr.append(sum(tr[:period]) / period)
            else:
                atr.append((atr[-1] * (period-1) + tr[i]) / period)
        return atr
    
    @staticmethod
    def vwap(price: List[float], volume: List[int]) -> List[float]:
        if not price or not volume:
            return []
        cum_pv = 0.0
        cum_vol = 0
        result = []
        for p, v in zip(price, volume):
            cum_pv += p * v
            cum_vol += v
            result.append(cum_pv / cum_vol if cum_vol > 0 else p)
        return result

# ============================================================================
# END MODULE: IndicatorEngine
# ============================================================================
