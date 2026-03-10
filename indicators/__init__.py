"""
Backtest Core - Indicators Package
==================================

Indicateurs techniques vectorisés avec NumPy.
"""

from .adx import adx, calculate_adx
from .amplitude_hunter import (
    AmplitudeHunterSettings,
    amplitude_hunter,
    calculate_amplitude_hunter,
)
from .aroon import AroonSettings, aroon
from .atr import ATRSettings, atr
from .bollinger import BollingerSettings, bollinger_bands
from .cci import CCISettings, cci
from .donchian import DonchianSettings, donchian_channel
from .ema import EMASettings, ema, sma
from .fear_greed import (
    FearGreedSettings,
    calculate_fear_greed,
    fear_greed_index,
)
from .fibonacci import (
    FibonacciSettings,
    calculate_fibonacci_levels,
    fibonacci_levels,
)
from .fva import calculate_fva
from .fvg import calculate_fvg_bearish, calculate_fvg_bullish, fvg

# Indicateurs Phase 2 (13/12/2025)
from .ichimoku import calculate_ichimoku, ichimoku, ichimoku_signal
from .keltner import KeltnerSettings, keltner_channel
from .macd import macd, macd_signal
from .mfi import MFISettings, mfi
from .momentum import MomentumSettings, momentum
from .obv import OBVSettings, obv
from .onchain_smoothing import (
    OnchainSmoothingSettings,
    calculate_onchain_smoothing,
    onchain_smoothing,
)
from .pi_cycle import (
    PiCycleSettings,
    calculate_pi_cycle,
    pi_cycle,
)
from .pivot_points import (
    PivotPointsSettings,
    calculate_pivot_points,
    pivot_points,
)
from .psar import calculate_psar, parabolic_sar, psar_signal
from .registry import calculate_indicator, list_indicators
from .roc import ROCSettings, roc
from .rsi import RSISettings, rsi
from .scoring import calculate_bear_score, calculate_bull_score, directional_bias
from .smart_legs import calculate_smart_legs_bearish, calculate_smart_legs_bullish, smart_legs
from .standard_deviation import (
    StandardDeviationSettings,
    calculate_standard_deviation,
    standard_deviation,
)
from .stoch_rsi import calculate_stoch_rsi, stoch_rsi_signal, stochastic_rsi
from .stochastic import stochastic, stochastic_signal
from .supertrend import SuperTrendSettings, supertrend

# FairValOseille indicators (03/01/2026)
from .swing import calculate_swing_high, calculate_swing_low, swing

# Additional indicators
from .volume_oscillator import (
    VolumeOscillatorSettings,
    calculate_volume_oscillator,
    volume_oscillator,
)
from .vortex import calculate_vortex, vortex, vortex_signal

# Indicateurs ajoutés 12/12/2025
from .vwap import VWAPSettings, vwap
from .williams_r import WilliamsRSettings, williams_r

__all__ = [
    # Indicateurs de base
    "bollinger_bands",
    "BollingerSettings",
    "atr",
    "ATRSettings",
    "rsi",
    "RSISettings",
    "ema",
    "sma",
    "EMASettings",
    "macd",
    "macd_signal",
    "adx",
    "calculate_adx",
    "stochastic",
    "stochastic_signal",
    # Indicateurs 12/12/2025
    "vwap",
    "VWAPSettings",
    "donchian_channel",
    "DonchianSettings",
    "cci",
    "CCISettings",
    "keltner_channel",
    "KeltnerSettings",
    "mfi",
    "MFISettings",
    "williams_r",
    "WilliamsRSettings",
    "momentum",
    "MomentumSettings",
    "obv",
    "OBVSettings",
    "roc",
    "ROCSettings",
    "aroon",
    "AroonSettings",
    "supertrend",
    "SuperTrendSettings",
    # Phase 2 (13/12/2025)
    "ichimoku",
    "ichimoku_signal",
    "calculate_ichimoku",
    "parabolic_sar",
    "psar_signal",
    "calculate_psar",
    "stochastic_rsi",
    "stoch_rsi_signal",
    "calculate_stoch_rsi",
    "vortex",
    "vortex_signal",
    "calculate_vortex",
    # Additional indicators
    "volume_oscillator",
    "calculate_volume_oscillator",
    "VolumeOscillatorSettings",
    "standard_deviation",
    "calculate_standard_deviation",
    "StandardDeviationSettings",
    "fibonacci_levels",
    "calculate_fibonacci_levels",
    "FibonacciSettings",
    "pivot_points",
    "calculate_pivot_points",
    "PivotPointsSettings",
    "onchain_smoothing",
    "calculate_onchain_smoothing",
    "OnchainSmoothingSettings",
    "fear_greed_index",
    "calculate_fear_greed",
    "FearGreedSettings",
    "pi_cycle",
    "calculate_pi_cycle",
    "PiCycleSettings",
    "amplitude_hunter",
    "calculate_amplitude_hunter",
    "AmplitudeHunterSettings",
    # FairValOseille (03/01/2026)
    "swing",
    "calculate_swing_high",
    "calculate_swing_low",
    "fvg",
    "calculate_fvg_bullish",
    "calculate_fvg_bearish",
    "calculate_fva",
    "smart_legs",
    "calculate_smart_legs_bullish",
    "calculate_smart_legs_bearish",
    "directional_bias",
    "calculate_bull_score",
    "calculate_bear_score",
    # Registre
    "calculate_indicator",
    "list_indicators",
]
