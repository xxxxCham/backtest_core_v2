from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_adx_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 3.0, 'tp_atr_mult': 4.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        signals.iloc[:warmup] = 0.0

        # Extract indicator arrays with nan_to_num
        donch = indicators['donchian']
        upper = np.nan_to_num(donch["upper"])
        lower = np.nan_to_num(donch["lower"])
        middle = np.nan_to_num(donch["middle"])

        adx_d = indicators['adx']
        adx_val = np.nan_to_num(adx_d["adx"])

        atr_arr = np.nan_to_num(indicators['atr'])
        close_arr = df["close"].values

        # Entry conditions
        long_mask = (close_arr > upper) & (adx_val > 20.0)
        short_mask = (close_arr < lower) & (adx_val > 20.0)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based SL/TP for entry bars
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 3.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 4.0))

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        df.loc[entry_long, "bb_stop_long"] = close_arr[entry_long] - stop_atr_mult * atr_arr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close_arr[entry_long] + tp_atr_mult * atr_arr[entry_long]

        df.loc[entry_short, "bb_stop_short"] = close_arr[entry_short] + stop_atr_mult * atr_arr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close_arr[entry_short] - tp_atr_mult * atr_arr[entry_short]

        # Exit condition (not used to modify signals but kept for completeness)
        # cross_any between close and middle band
        prev_close = np.roll(close_arr, 1)
        prev_middle = np.roll(middle, 1)
        prev_close[0] = np.nan
        prev_middle[0] = np.nan
        cross_any = ((close_arr > middle) & (prev_close <= prev_middle)) | \
                    ((close_arr < middle) & (prev_close >= prev_middle))
        exit_mask = cross_any | (adx_val < 15.0)

        # Optional: reset to flat on exit (if desired)
        # signals[exit_mask] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
