from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_rsi_momentum_strat')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=5,
                default=1,
                param_type='int',
                step=1,
            ),
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=50,
                default=14,
                param_type='int',
                step=1,
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
                max_val=5.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=20,
                max_val=100,
                default=50,
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
        # Initialize masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Get indicators
        ema = np.nan_to_num(indicators['ema'][0])  # type: ignore
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Warmup period
        signals.iloc[:warmup] = 0.0

        # Calculate EMA cross
        ema_prev = np.roll(ema, 1)
        ema_cross = (ema > ema_prev) & (ema_prev != 0)

        # Calculate RSI condition
        rsi_up = rsi > 50
        rsi_down = rsi < 50

        # Calculate price above/below EMA
        close = df["close"].values
        price_above_ema = close > ema
        price_below_ema = close < ema

        # Create long signals
        long_conditions = (
            ema_cross
            & rsi_up
            & price_above_ema
        )
        long_mask[long_conditions] = True

        # Create short signals
        short_conditions = (
            ema_cross
            & rsi_down
            & price_below_ema
        )
        short_mask[short_conditions] = True

        # Apply signals, ensuring no overlap
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Write ATR-based stops
        stop_mult = params.get("stop_atr_mult", 1.0)
        tp_mult = params.get("tp_atr_mult", 2.0)

        # Initialize columns with NaN
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        # Calculate stops on entry bars
        entry_mask = (signals == 1.0)
        df.loc[entry_mask, "bb_stop_long"] = close[entry_mask] - stop_mult * atr[entry_mask]
        df.loc[entry_mask, "bb_tp_long"] = close[entry_mask] + tp_mult * atr[entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
