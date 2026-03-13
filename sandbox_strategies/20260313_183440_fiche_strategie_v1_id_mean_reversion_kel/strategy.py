from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_keltner_stoch_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['keltner', 'stoch_rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'keltner_multiplier': 2.0,
         'keltner_period': 20,
         'leverage': 1,
         'stoch_rsi_period': 14,
         'stoch_rsi_smooth_d': 3,
         'stoch_rsi_smooth_k': 3,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'keltner_period': ParameterSpec(
                name='keltner_period',
                min_val=5,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'keltner_multiplier': ParameterSpec(
                name='keltner_multiplier',
                min_val=1.0,
                max_val=3.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'stoch_rsi_period': ParameterSpec(
                name='stoch_rsi_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'stoch_rsi_smooth_k': ParameterSpec(
                name='stoch_rsi_smooth_k',
                min_val=1,
                max_val=5,
                default=3,
                param_type='int',
                step=1,
            ),
            'stoch_rsi_smooth_d': ParameterSpec(
                name='stoch_rsi_smooth_d',
                min_val=1,
                max_val=5,
                default=3,
                param_type='int',
                step=1,
            ),
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
        # Boolean masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Extract indicators with nan_to_num
        kelt = indicators['keltner']
        indicators['keltner']['upper'] = np.nan_to_num(kelt["upper"])
        indicators['keltner']['middle'] = np.nan_to_num(kelt["middle"])
        indicators['keltner']['lower'] = np.nan_to_num(kelt["lower"])

        stoch = indicators['stoch_rsi']
        indicators['stochastic']['stoch_k'] = np.nan_to_num(stoch["k"])
        indicators['stochastic']['stoch_d'] = np.nan_to_num(stoch["d"])

        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Entry logic
        long_mask = (close < indicators['keltner']['lower']) & (indicators['stochastic']['stoch_k'] < 20.0) & (indicators['stochastic']['stoch_d'] < 20.0)
        short_mask = (close > indicators['keltner']['upper']) & (indicators['stochastic']['stoch_k'] > 80.0) & (indicators['stochastic']['stoch_d'] > 80.0)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Helper for cross_any
        def cross_any(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            cross_up = (x > y) & (prev_x <= prev_y)
            cross_down = (x < y) & (prev_x >= prev_y)
            return cross_up | cross_down

        # Exit logic
        exit_mask = cross_any(close, indicators['keltner']['middle']) | cross_any(indicators['stochastic']['stoch_k'], 50.0)
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR-based SL/TP for long entries
        long_entry = signals == 1.0
        df.loc[long_entry, "bb_stop_long"] = close[long_entry] - params["stop_atr_mult"] * atr[long_entry]
        df.loc[long_entry, "bb_tp_long"] = close[long_entry] + params["tp_atr_mult"] * atr[long_entry]

        # ATR-based SL/TP for short entries
        short_entry = signals == -1.0
        df.loc[short_entry, "bb_stop_short"] = close[short_entry] + params["stop_atr_mult"] * atr[short_entry]
        df.loc[short_entry, "bb_tp_short"] = close[short_entry] - params["tp_atr_mult"] * atr[short_entry]
        signals.iloc[:warmup] = 0.0
        return signals
