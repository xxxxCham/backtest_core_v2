from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_volume_obv_momentum')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'volume_oscillator', 'obv', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'ema_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 2.0,
         'volume_threshold': 0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=5,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'volume_threshold': ParameterSpec(
                name='volume_threshold',
                min_val=-1,
                max_val=1,
                default=0,
                param_type='float',
                step=0.1,
            ),
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

        ema = np.nan_to_num(indicators['ema'])
        volume_oscillator = np.nan_to_num(indicators['volume_oscillator'])
        obv = np.nan_to_num(indicators['obv'])
        atr = np.nan_to_num(indicators['atr'])

        # Entry conditions
        ema_prev = np.roll(ema, 1)
        ema_prev[0] = np.nan

        obv_prev_3 = np.roll(obv, 3)
        obv_prev_3[0] = obv_prev_3[1] = obv_prev_3[2] = np.nan

        # Long entry: EMA crossed above previous EMA, volume oscillator > threshold, OBV rising for 3 periods
        long_entry = (ema > ema_prev) & (volume_oscillator > params["volume_threshold"]) & (obv > obv_prev_3)

        # Short entry: EMA crossed below previous EMA, volume oscillator < threshold, OBV falling for 3 periods
        short_entry = (ema < ema_prev) & (volume_oscillator < params["volume_threshold"]) & (obv < obv_prev_3)

        # Exit conditions
        # Exit long: EMA crossed below previous EMA or volume oscillator < threshold
        long_exit = (ema < ema_prev) | (volume_oscillator < params["volume_threshold"])

        # Exit short: EMA crossed above previous EMA or volume oscillator > threshold
        short_exit = (ema > ema_prev) | (volume_oscillator > params["volume_threshold"])

        # Apply masks
        long_mask = long_entry
        short_mask = short_entry

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based risk management
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        close = df["close"].values

        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]

        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
