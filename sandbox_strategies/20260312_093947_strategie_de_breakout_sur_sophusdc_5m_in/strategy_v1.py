from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='sophusdc_breakout_stoch_bollinger_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['stochastic', 'bollinger', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'bollinger_period': 20,
         'bollinger_std_dev': 2,
         'leverage': 1,
         'stochastic_d_period': 3,
         'stochastic_k_period': 14,
         'stop_atr_mult': 1.0,
         'tp_atr_mult': 2.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stochastic_k_period': ParameterSpec(
                name='stochastic_k_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'stochastic_d_period': ParameterSpec(
                name='stochastic_d_period',
                min_val=2,
                max_val=10,
                default=3,
                param_type='int',
                step=1,
            ),
            'bollinger_period': ParameterSpec(
                name='bollinger_period',
                min_val=10,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
            ),
            'bollinger_std_dev': ParameterSpec(
                name='bollinger_std_dev',
                min_val=1.5,
                max_val=3.0,
                default=2,
                param_type='float',
                step=0.1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=20,
                default=14,
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

        # unpack indicators with nan_to_num
        bb = indicators['bollinger']
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        stoch = indicators['stochastic']
        k = np.nan_to_num(stoch["stoch_k"])

        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Long entry: close > upper band and stoch K > 80
        long_mask = (close > upper) & (k > 80)

        # Short entry: close < lower band and stoch K < 20
        short_mask = (close < lower) & (k < 20)

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Prepare ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Compute SL/TP for long entries
        if long_mask.any():
            entry_long = close[long_mask]
            df.loc[long_mask, "bb_stop_long"] = entry_long - params["stop_atr_mult"] * atr[long_mask]
            df.loc[long_mask, "bb_tp_long"] = entry_long + params["tp_atr_mult"] * atr[long_mask]

        # Compute SL/TP for short entries
        if short_mask.any():
            entry_short = close[short_mask]
            df.loc[short_mask, "bb_stop_short"] = entry_short + params["stop_atr_mult"] * atr[short_mask]
            df.loc[short_mask, "bb_tp_short"] = entry_short - params["tp_atr_mult"] * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
