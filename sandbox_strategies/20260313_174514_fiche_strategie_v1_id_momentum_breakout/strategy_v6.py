from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ichimoku_volume_atr_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['ichimoku', 'volume_oscillator', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 2.0, 'tp_atr_mult': 4.0, 'warmup': 50}

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
        close = df["close"].values
        atr = np.nan_to_num(indicators['atr'])
        vol = np.nan_to_num(indicators['volume_oscillator'])
        ich = indicators['ichimoku']
        kijun = np.nan_to_num(ich["kijun"])

        long_mask = (close > kijun) & (vol > 0)
        short_mask = (close < kijun) & (vol < 0)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        signals.iloc[:warmup] = 0.0

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        long_entries = signals == 1.0
        df.loc[long_entries, "bb_stop_long"] = (
            close[long_entries] - params["stop_atr_mult"] * atr[long_entries]
        )
        df.loc[long_entries, "bb_tp_long"] = (
            close[long_entries] + params["tp_atr_mult"] * atr[long_entries]
        )

        short_entries = signals == -1.0
        df.loc[short_entries, "bb_stop_short"] = (
            close[short_entries] + params["stop_atr_mult"] * atr[short_entries]
        )
        df.loc[short_entries, "bb_tp_short"] = (
            close[short_entries] - params["tp_atr_mult"] * atr[short_entries]
        )
        signals.iloc[:warmup] = 0.0
        return signals
