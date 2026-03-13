from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_donchian_adx_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.75, 'tp_atr_mult': 2.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=6.0,
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

        # Extract indicators
        dc = indicators['donchian']
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        close = np.nan_to_num(df["close"].values)
        upper = np.nan_to_num(dc["upper"])
        lower = np.nan_to_num(dc["lower"])
        middle = np.nan_to_num(dc["middle"])
        adx_val = np.nan_to_num(adx_d["adx"])

        # Entry conditions
        long_condition = (close > upper) & (adx_val > 25)
        short_condition = (close < lower) & (adx_val > 25)

        long_mask[long_condition] = True
        short_mask[short_condition] = True

        # Exit conditions
        prev_close = np.roll(close, 1)
        prev_middle = np.roll(middle, 1)
        prev_close[0] = np.nan
        prev_middle[0] = np.nan

        cross_down = (close < middle) & (prev_close >= prev_middle)
        adx_weak = adx_val < 15

        exit_mask = cross_down | adx_weak

        # Apply exits to existing positions
        long_positions = signals == 1.0
        short_positions = signals == -1.0

        # Update signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Handle exits
        signals[long_positions & exit_mask] = 0.0
        signals[short_positions & exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 1.75)
        tp_atr_mult = params.get("tp_atr_mult", 2.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
