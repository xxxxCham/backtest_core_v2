from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_adx_ema_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 4.0, 'warmup': 35}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=3.0,
                default=1.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=6.0,
                default=4.0,
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
        # Boolean masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Extract indicator arrays
        close = df["close"].values
        dc = indicators['donchian']
        upper = np.nan_to_num(dc["upper"])
        middle = np.nan_to_num(dc["middle"])
        lower = np.nan_to_num(dc["lower"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        ema_val = np.nan_to_num(indicators['ema'])
        atr_val = np.nan_to_num(indicators['atr'])

        # Entry conditions
        long_mask = (close > upper) & (adx_val > 25) & (close > ema_val)
        short_mask = (close < lower) & (adx_val > 25) & (close < ema_val)

        # Apply warmup
        signals.iloc[:warmup] = 0.0

        # Set entry signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Prepare SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_mult = float(params.get("stop_atr_mult", 1.5))
        tp_mult = float(params.get("tp_atr_mult", 4.0))

        # ATR based SL/TP for long entries
        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_mult * atr_val[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_mult * atr_val[long_mask]

        # ATR based SL/TP for short entries
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_mult * atr_val[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_mult * atr_val[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
