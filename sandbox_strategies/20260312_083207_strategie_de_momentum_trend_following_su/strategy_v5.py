from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_sma_atr_trend_follow')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'sma', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'stop_atr_mult': 1.0,
         'tp_atr_mult': 2.0,
         'trend_strength_atr_mult': 1.5,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=3.0,
                default=1.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'trend_strength_atr_mult': ParameterSpec(
                name='trend_strength_atr_mult',
                min_val=1.0,
                max_val=3.0,
                default=1.5,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=20,
                max_val=100,
                default=50,
                param_type='int',
                step=10,
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

        signals.iloc[:warmup] = 0.0

        close = np.nan_to_num(df["close"].values)
        ema = np.nan_to_num(indicators['ema'])
        sma = np.nan_to_num(indicators['sma'])
        atr = np.nan_to_num(indicators['atr'])

        trend_strength = params["trend_strength_atr_mult"]

        long_cond = (ema > sma) & ((ema - sma) > trend_strength * atr)
        short_cond = (ema < sma) & ((sma - ema) > trend_strength * atr)

        long_mask[long_cond] = True
        short_mask[short_cond] = True

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit logic
        prev_close = np.roll(close, 1)
        prev_sma = np.roll(sma, 1)
        prev_close[0] = np.nan
        prev_sma[0] = np.nan

        exit_long = (close < sma) & (prev_close >= prev_sma)
        exit_short = (close > sma) & (prev_close <= prev_sma)

        signals[exit_long] = 0.0
        signals[exit_short] = 0.0

        # ATR-based SL/TP levels
        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - params["stop_atr_mult"] * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + params["tp_atr_mult"] * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + params["stop_atr_mult"] * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - params["tp_atr_mult"] * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
