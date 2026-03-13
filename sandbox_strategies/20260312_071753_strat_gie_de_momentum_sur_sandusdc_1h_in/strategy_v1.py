from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_ema_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Warmup period
        signals.iloc[:warmup] = 0.0

        # Get indicators
        close = df["close"].values
        ema = np.nan_to_num(indicators['ema'])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Calculate EMA trend
        ema_trend = ema > np.roll(ema, 1)

        # Set long signals when RSI is oversold and EMA is uptrending
        long_condition = (rsi < 30) & ema_trend
        long_mask[warmup:] = long_condition[warmup:]

        # Set short signals when RSI is overbought and EMA is downtrending
        short_condition = (rsi > 70) & (ema < np.roll(ema, 1))
        short_mask[warmup:] = short_condition[warmup:]

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Write stop and target levels for risk management
        entry_mask = (signals == 1.0) | (signals == -1.0)
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Calculate levels for long entries
        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - 2 * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + 1 * atr[long_mask]

        # Calculate levels for short entries
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + 2 * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - 1 * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
