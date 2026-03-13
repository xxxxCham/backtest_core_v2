from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bb_mean_reversion_adx_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=4.5,
                default=3.0,
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
        # Boolean masks for long/short entries
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Extract indicator arrays
        bb = indicators['bollinger']
        lower = np.nan_to_num(bb["lower"])
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        adx = np.nan_to_num(indicators['adx']["adx"])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Entry conditions
        long_mask = (close < lower) & (adx < 25)
        short_mask = (close > upper) & (adx < 25)

        # Exit conditions
        exit_long_mask = ((close > middle) | (adx > 25)) & (~long_mask)
        exit_short_mask = ((close < middle) | (adx > 25)) & (~short_mask)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Prepare SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Compute ATR-based levels on entry bars
        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
