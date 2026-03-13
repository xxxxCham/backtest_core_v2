from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_adx_breakout_v6')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'stop_atr_mult': 1.5,
         'stop_atr_mult_long': 1.75,
         'stop_atr_mult_short': 1.75,
         'tp_atr_mult': 3.5,
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
            'stop_atr_mult_long': ParameterSpec(
                name='stop_atr_mult_long',
                min_val=0.5,
                max_val=4.0,
                default=1.75,
                param_type='float',
                step=0.1,
            ),
            'stop_atr_mult_short': ParameterSpec(
                name='stop_atr_mult_short',
                min_val=0.5,
                max_val=4.0,
                default=1.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=3.5,
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
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=2.0,
                default=1.5,
                param_type='float',
                step=0.1,
            ),
        }

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        # Generate long signals when close breaks above donchian upper and adx is above 25
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)  # this line is already in the context, so it's not needed here but included for clarity
        prev_upper = np.roll(indicators['donchian']["upper"], 1)  # Get previous upper band shifted by one period to compare with current close
        current_close = df['close']  # Assuming 'close' is a column in df, as it's standard in trading dataframes
        long_mask = (current_close > prev_upper) & (indicators['adx']["adx"] > 25)  # Vectorized operation ensuring both conditions are met for long signals
        signals[long_mask] = 1.0  # Assign long signal where conditions are met

        # Generate short signals when close breaks below donchian lower and adx is above 25
        prev_lower = np.roll(indicators['donchian']["lower"], 1)  # Get previous lower band shifted by one period for comparison
        short_mask = (current_close < prev_lower) & (indicators['adx']["adx"] > 25)  # Vectorized operation ensuring both conditions are met for short signals
        signals[short_mask] = -1.0  # Assign short signal where conditions are met

        # Reset signals to 0 where no conditions are met; this is optional but ensures the signals are only non-zero when active
        no_activity = ~((current_close > prev_upper) | (current_close < prev_lower))  # Where neither long nor short conditions are met
        signals[no_activity] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
