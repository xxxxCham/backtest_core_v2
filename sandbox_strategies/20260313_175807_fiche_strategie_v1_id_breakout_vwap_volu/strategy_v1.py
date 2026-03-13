from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_vwap_volume')

    @property
    def required_indicators(self) -> List[str]:
        return ['vwap', 'volume_oscillator', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_volatility_threshold': 0.5,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 3.0,
         'warmup': 50}

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
                max_val=6.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'atr_volatility_threshold': ParameterSpec(
                name='atr_volatility_threshold',
                min_val=0.1,
                max_val=2.0,
                default=0.5,
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

        # unwrap indicators
        vwap = np.nan_to_num(indicators['vwap'])
        vol_osc = np.nan_to_num(indicators['volume_oscillator'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # entry conditions
        long_cond = (close > vwap) & (vol_osc > 0) & (atr > params["atr_volatility_threshold"])
        short_cond = (close < vwap) & (vol_osc < 0) & (atr > params["atr_volatility_threshold"])
        long_mask = long_cond
        short_mask = short_cond

        # exit condition: any cross of close and vwap
        prev_close = np.roll(close, 1)
        prev_vwap = np.roll(vwap, 1)
        prev_close[0] = np.nan
        prev_vwap[0] = np.nan
        cross_up = (close > vwap) & (prev_close <= prev_vwap)
        cross_down = (close < vwap) & (prev_close >= prev_vwap)
        exit_mask = cross_up | cross_down

        # assign signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        # exit signals should not override entries on the same bar
        signals[exit_mask & ~long_mask & ~short_mask] = 0.0

        # warmup protection
        signals.iloc[:warmup] = 0.0

        # prepare ATR‑based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # compute levels on entry bars only
        entry_long = signals == 1.0
        entry_short = signals == -1.0
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
