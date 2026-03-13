from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_volatility_rsrusdc')

    @property
    def required_indicators(self) -> List[str]:
        return ['obv', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 2.0, 'tp_atr_mult': 5.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        close = df["close"].values
        obv = np.nan_to_num(indicators['obv'])
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])

        # Compute previous values for crossovers
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_ema = np.roll(ema, 1)
        prev_ema[0] = np.nan
        prev_obv = np.roll(obv, 1)
        prev_obv[0] = np.nan

        # Entry long: close crosses above ema AND obv rises
        cross_up_ema = (close > ema) & (prev_close <= prev_ema)
        obv_rises = (obv > prev_obv)
        long_mask = cross_up_ema & obv_rises

        # Entry short: close crosses below ema AND obv falls
        cross_down_ema = (close < ema) & (prev_close >= prev_ema)
        obv_falls = (obv < prev_obv)
        short_mask = cross_down_ema & obv_falls

        # Exit: close crosses below ema OR close crosses above ema
        exit_long = cross_down_ema
        exit_short = cross_up_ema

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_long] = 0.0
        signals[exit_short] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Set ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 5.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = (signals == 1.0)
        entry_short = (signals == -1.0)

        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
