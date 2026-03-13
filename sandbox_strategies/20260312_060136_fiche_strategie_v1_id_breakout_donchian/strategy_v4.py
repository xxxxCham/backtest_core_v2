from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_adx_breakout_v4')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.75, 'tp_atr_mult': 6.0, 'warmup': 50}

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
                max_val=10.0,
                default=6.0,
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
        donchian = indicators['donchian']
        upper_band = np.nan_to_num(indicators['donchian']["upper"])
        lower_band = np.nan_to_num(indicators['donchian']["lower"])
        adx = np.nan_to_num(indicators['adx']["adx"])
        atr = np.nan_to_num(indicators['atr'])

        # Long signals: price above upper band and ADX strong
        long_cond = (df["close"].values >= upper_band) & (adx >= 25)
        long_mask = long_cond

        # Short signals: price below lower band and ADX strong
        short_cond = (df["close"].values <= lower_band) & (adx >= 25)
        short_mask = short_cond

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Calculate ATR-based stop and TP levels
        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Initialize SL/TP columns with NaN
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Calculate stop and TP for long entries
        entry_mask_long = (signals == 1.0)
        close = df["close"].values
        df.loc[entry_mask_long, "bb_stop_long"] = (
            close[entry_mask_long] - 
            stop_atr_mult * atr[entry_mask_long]
        )
        df.loc[entry_mask_long, "bb_tp_long"] = (
            close[entry_mask_long] + 
            tp_atr_mult * atr[entry_mask_long]
        )

        # Calculate stop and TP for short entries
        entry_mask_short = (signals == -1.0)
        df.loc[entry_mask_short, "bb_stop_short"] = (
            close[entry_mask_short] + 
            stop_atr_mult * atr[entry_mask_short]
        )
        df.loc[entry_mask_short, "bb_tp_short"] = (
            close[entry_mask_short] - 
            tp_atr_mult * atr[entry_mask_short]
        )
        signals.iloc[:warmup] = 0.0
        return signals
