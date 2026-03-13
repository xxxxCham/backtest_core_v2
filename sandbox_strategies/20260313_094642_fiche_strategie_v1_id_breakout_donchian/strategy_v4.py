from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_donchian_adx_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.75, 'tp_atr_mult': 2.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.75,
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

        # Extract indicators
        close = df["close"].values
        donchian = indicators['donchian']
        adx = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        # Get arrays with nan_to_num
        indicators['donchian']['upper'] = np.nan_to_num(indicators['donchian']["upper"])
        indicators['donchian']['lower'] = np.nan_to_num(indicators['donchian']["lower"])
        indicators['donchian']['middle'] = np.nan_to_num(indicators['donchian']["middle"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])

        # Entry conditions
        # Long entry: close crosses above upper band AND adx > 20
        prev_close = np.roll(close, 1)
        prev_dc_upper = np.roll(indicators['donchian']['upper'], 1)
        prev_dc_lower = np.roll(indicators['donchian']['lower'], 1)
        prev_dc_middle = np.roll(indicators['donchian']['middle'], 1)
        prev_adx_val = np.roll(adx_val, 1)

        prev_close[0] = np.nan
        prev_dc_upper[0] = np.nan
        prev_dc_lower[0] = np.nan
        prev_dc_middle[0] = np.nan
        prev_adx_val[0] = np.nan

        long_entry = (close > indicators['donchian']['upper']) & (prev_close <= prev_dc_upper) & (adx_val > 20)
        short_entry = (close < indicators['donchian']['lower']) & (prev_close >= prev_dc_lower) & (adx_val > 20)

        # Exit conditions
        exit_long = (close < indicators['donchian']['middle']) | (adx_val < 15)
        exit_short = (close > indicators['donchian']['middle']) | (adx_val < 15)

        # Initialize exit masks
        long_exit_mask = np.zeros(n, dtype=bool)
        short_exit_mask = np.zeros(n, dtype=bool)

        # Set exit masks using rolling
        prev_exit_long = np.roll(exit_long, 1)
        prev_exit_short = np.roll(exit_short, 1)
        prev_exit_long[0] = False
        prev_exit_short[0] = False

        long_exit_mask = exit_long & ~prev_exit_long
        short_exit_mask = exit_short & ~prev_exit_short

        # Set long and short masks
        long_mask = long_entry
        short_mask = short_entry

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exit signals
        signals[long_exit_mask] = 0.0
        signals[short_exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Set ATR-based SL/TP levels
        stop_atr_mult = params.get("stop_atr_mult", 1.75)
        tp_atr_mult = params.get("tp_atr_mult", 2.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
