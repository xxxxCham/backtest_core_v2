from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_stoch_bollinger_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'stochastic', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'stochastic_d_period': 3,
         'stochastic_k_period': 3,
         'stop_atr_mult': 1.0,
         'tp_atr_mult': 2.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stochastic_k_period': ParameterSpec(
                name='stochastic_k_period',
                min_val=1,
                max_val=10,
                default=3,
                param_type='int',
                step=1,
            ),
            'stochastic_d_period': ParameterSpec(
                name='stochastic_d_period',
                min_val=1,
                max_val=10,
                default=3,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=3.0,
                default=1.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.0,
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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Extract indicator arrays
        close = np.nan_to_num(df["close"].values)

        bb = indicators['bollinger']
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        stoch = indicators['stochastic']
        k = np.nan_to_num(stoch["stoch_k"])

        atr = np.nan_to_num(indicators['atr'])

        # Long entry: close above upper Bollinger and Stoch K > 80
        long_mask = (close > upper) & (k > 80)

        # Short entry: close below lower Bollinger and Stoch K < 20
        short_mask = (close < lower) & (k < 20)

        # Exit conditions: cross of close over/under middle Bollinger
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        cross_down = (close < middle) & (prev_close >= middle)  # long exit
        cross_up = (close > middle) & (prev_close <= middle)    # short exit
        exit_mask = cross_down | cross_up

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # Warmup
        signals.iloc[:warmup] = 0.0

        # ATR-based stop‑loss and take‑profit
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 1.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 2.0))

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]

        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
