from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='obv_ema_5m_momentum_volatility_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['obv', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 2.0, 'tp_atr_mult': 5.0, 'warmup': 20}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=10.0,
                default=5.0,
                param_type='float',
                step=0.1,
            ),
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=1,
                param_type='int',
                step=1,
            ),
        }

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        # Prepare indicator arrays
        close = df["close"].values
        ema = np.nan_to_num(indicators['ema'])
        obv = np.nan_to_num(indicators['obv'])
        atr = np.nan_to_num(indicators['atr'])

        # Previous values
        ema_prev = np.roll(ema, 1); ema_prev[0] = np.nan
        ema_prev2 = np.roll(ema_prev, 1); ema_prev2[0] = np.nan
        obv_prev = np.roll(obv, 1); obv_prev[0] = np.nan
        obv_prev2 = np.roll(obv_prev, 1); obv_prev2[0] = np.nan
        atr_prev = np.roll(atr, 1); atr_prev[0] = np.nan

        # Long and short entry masks
        long_mask = (
            (close > ema)
            & (ema > ema_prev)
            & (obv > obv_prev)
            & (obv_prev > obv_prev2)
            & (atr > atr_prev)
        )
        short_mask = (
            (close < ema)
            & (ema < ema_prev)
            & (obv < obv_prev)
            & (obv_prev < obv_prev2)
            & (atr > atr_prev)
        )

        # Exit masks using cross detection
        prev_close = np.roll(close, 1); prev_close[0] = np.nan
        prev_ema = np.roll(ema, 1); prev_ema[0] = np.nan
        cross_down = (close < ema) & (prev_close >= prev_ema)
        cross_up = (close > ema) & (prev_close <= prev_ema)

        long_exit = cross_down
        short_exit = cross_up

        # Apply entry signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Optional: reset signals on exit to flat (0.0)
        signals[long_exit] = 0.0
        signals[short_exit] = 0.0

        # Warmup protection
        signals.iloc[:50] = 0.0

        # ATR-based SL/TP levels
        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 5.0))

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = signals == 1.0
        entry_short_mask = signals == -1.0

        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
