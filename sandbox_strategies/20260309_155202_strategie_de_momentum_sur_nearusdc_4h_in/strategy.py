from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_adx_atr_momentum_v3')

    @property
    def required_indicators(self) -> List[str]:
        # Only ADX and ATR are needed from the indicator engine;
        # EMA values are computed locally from price data.
        return ['adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'adx_period': 14,
            'atr_period': 14,
            'ema_fast_period': 10,
            'ema_slow_period': 30,
            'leverage': 1,
            'stop_atr_mult': 2.0,
            'tp_atr_mult': 5.0,
            'warmup': 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_fast_period': ParameterSpec(
                name='ema_fast_period',
                min_val=5,
                max_val=30,
                default=10,
                param_type='int',
                step=1,
            ),
            'ema_slow_period': ParameterSpec(
                name='ema_slow_period',
                min_val=20,
                max_val=60,
                default=30,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=30,
                default=14,
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
                max_val=10.0,
                default=5.0,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=20,
                max_val=200,
                default=50,
                param_type='int',
                step=1,
            ),
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=3,
                default=1,
                param_type='int',
                step=1,
            ),
        }

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any],
    ) -> pd.Series:
        """Generate long/short signals based on EMA crossovers filtered by ADX."""
        n = len(df)
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        # --- Indicator extraction -------------------------------------------------
        # ADX is provided by the engine as a dict indicator.
        adx_series = indicators['adx']['adx']  # numpy array

        # EMA values are computed locally from the close price series.
        close_prices = df['close'].astype(float)

        ema_fast_period = int(params.get('ema_fast_period', 10))
        ema_slow_period = int(params.get('ema_slow_period', 30))

        ema_fast = (
            close_prices.ewm(span=ema_fast_period, adjust=False).mean().values
        )
        ema_slow = (
            close_prices.ewm(span=ema_slow_period, adjust=False).mean().values
        )

        # --- Signal logic --------------------------------------------------------
        # Ensure masks are boolean arrays of length n.
        long_mask = (ema_fast > ema_slow) & (adx_series >= 20)
        short_mask = (ema_fast < ema_slow) & (adx_series >= 20)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warm‑up period: no positions
        warmup = int(params.get('warmup', 50))
        if warmup > 0:
            signals.iloc[:warmup] = 0.0

        return signals