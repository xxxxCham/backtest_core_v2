from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr', 'adx']

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
                min_val=2.0,
                max_val=4.5,
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
        # implement explicit LONG / SHORT / FLAT logic
        # warmup protection
        signals.iloc[:warmup] = 0.0
        # Extract indicators
        bb = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])
        # Prepare for crossovers
        close = df["close"].values
        middle = np.nan_to_num(bb["middle"])
        upper = np.nan_to_num(bb["upper"])
        lower = np.nan_to_num(bb["lower"])
        # Entry conditions
        rsi_overbought = params.get("rsi_overbought", 70)
        rsi_oversold = params.get("rsi_oversold", 30)
        adx_threshold = 20
        # Long entry: close < lower, rsi < oversold, adx > threshold
        long_entry = (close < lower) & (rsi < rsi_oversold) & (adx > adx_threshold)
        # Short entry: close > upper, rsi > overbought, adx > threshold
        short_entry = (close > upper) & (rsi > rsi_overbought) & (adx > adx_threshold)
        long_mask[long_entry] = True
        short_mask[short_entry] = True
        # Exit conditions
        # Cross below middle band or cross above middle band
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        cross_down_middle = (close < middle) & (prev_middle >= middle)
        cross_up_middle = (close > middle) & (prev_middle <= middle)
        cross_any_middle = cross_down_middle | cross_up_middle
        # RSI crosses 50
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        cross_down_rsi = (rsi < 50) & (prev_rsi >= 50)
        cross_up_rsi = (rsi > 50) & (prev_rsi <= 50)
        cross_any_rsi = cross_down_rsi | cross_up_rsi
        # Combined exit condition
        exit_condition = cross_any_middle | cross_any_rsi
        # For exit, we need to know when we are in a position
        # Simple approach: reset signals when exit occurs
        # Long exit
        long_exit = long_mask & exit_condition
        # Short exit
        short_exit = short_mask & exit_condition
        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[long_exit] = 0.0
        signals[short_exit] = 0.0
        # ATR-based risk management
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        entry_long = signals == 1.0
        entry_short = signals == -1.0
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
