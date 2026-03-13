from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='builder_strategy')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'ema', 'atr', 'stochastic', 'bollinger']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=1,
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
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=4.5,
                default=3.0,
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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        signals.iloc[:warmup] = 0.0

        # Stochastic and RSI conditions for short signal
        try:
            stochastic = indicators['stochastic']
            bollinger = indicators['bollinger']
            atr = np.nan_to_num(indicators['atr'])
            close = df["close"].values

            short_condition = (indicators['stochastic']["stoch_k"] < 20.0) & (close < indicators['bollinger']["lower"])
            short_mask = short_condition

            # Write SL/TP columns into df if using ATR-based risk management
            stop_atr_mult = params.get("stop_atr_mult", 1.5)
            tp_atr_mult = params.get("tp_atr_mult", 2.0)

            entry_mask_short = short_mask
            df.loc[entry_mask_short, "bb_stop_short"] = close[entry_mask_short] + stop_atr_mult * atr[entry_mask_short]
            df.loc[entry_mask_short, "bb_tp_short"] = close[entry_mask_short] - tp_atr_mult * atr[entry_mask_short]

            signals[short_mask] = -1.0
        except KeyError as e:
            print(f"KeyError: {e}.  Check your indicators.")
            pass

        signals.iloc[:warmup] = 0.0
        return signals