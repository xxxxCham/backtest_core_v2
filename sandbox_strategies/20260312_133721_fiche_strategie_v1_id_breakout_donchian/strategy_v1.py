from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_donchian_adx')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 4.0, 'warmup': 35}

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
        # Extract indicator arrays with nan_to_num
        close = np.nan_to_num(df["close"].values)
        atr = np.nan_to_num(indicators['atr'])
        dc = indicators['donchian']
        indicators['donchian']['upper'] = np.nan_to_num(dc["upper"])
        indicators['donchian']['middle'] = np.nan_to_num(dc["middle"])
        indicators['donchian']['lower'] = np.nan_to_num(dc["lower"])
        adx_d = indicators['adx']
        adx_val = np.nan_to_num(adx_d["adx"])

        # Helper cross_any
        prev_close = np.roll(close, 1)
        prev_middle = np.roll(indicators['donchian']['middle'], 1)
        prev_close[0] = np.nan
        prev_middle[0] = np.nan
        cross_any_mask = ((close > indicators['donchian']['middle']) & (prev_close <= prev_middle)) | \
                         ((close < indicators['donchian']['middle']) & (prev_close >= prev_middle))

        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Entry conditions
        long_mask = (close > indicators['donchian']['upper']) & (adx_val > 25)
        short_mask = (close < indicators['donchian']['lower']) & (adx_val > 25)

        # Exit conditions
        exit_mask = cross_any_mask | (adx_val < 15)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # Warmup
        signals.iloc[:warmup] = 0.0

        # Prepare SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 4.0))

        # ATR-based SL/TP for long entries
        df.loc[signals == 1.0, "bb_stop_long"] = close[signals == 1.0] - stop_atr_mult * atr[signals == 1.0]
        df.loc[signals == 1.0, "bb_tp_long"] = close[signals == 1.0] + tp_atr_mult * atr[signals == 1.0]

        # ATR-based SL/TP for short entries
        df.loc[signals == -1.0, "bb_stop_short"] = close[signals == -1.0] + stop_atr_mult * atr[signals == -1.0]
        df.loc[signals == -1.0, "bb_tp_short"] = close[signals == -1.0] - tp_atr_mult * atr[signals == -1.0]
        signals.iloc[:warmup] = 0.0
        return signals
