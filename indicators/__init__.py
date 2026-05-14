"""Backtest Core - Indicators Package
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
from .chaikin_oscillator import (
    ChaikinOscillatorSettings,
    calculate_chaikin_oscillator,
    chaikin_oscillator,
)
from .choppiness_index import (
    ChoppinessIndexSettings,
    calculate_choppiness_index,
    choppiness_index,
)
from .cmf import CMFSettings, calculate_cmf, cmf
from .cmo import CMOSettings, calculate_cmo, cmo
from .coppock_curve import (
    CoppockCurveSettings,
    calculate_coppock_curve,
    coppock_curve,
)
from .donchian import DonchianSettings, donchian_channel
from .dpo import DPOSettings, calculate_dpo, dpo
from .elder_ray import ElderRaySettings, calculate_elder_ray, elder_ray
from .ema import EMASettings, ema, sma
from .eom import EOMSettings, calculate_eom, eom
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
from .fisher_transform import (
    FisherTransformSettings,
    calculate_fisher_transform,
    fisher_transform,
)
from .force_index import (
    ForceIndexSettings,
    calculate_force_index,
    force_index,
)
from .fva import calculate_fva
from .fvg import calculate_fvg_bearish, calculate_fvg_bullish, fvg
from .hma import HMASettings, calculate_hma, hma

# Indicateurs Phase 2 (13/12/2025)
from .ichimoku import calculate_ichimoku, ichimoku, ichimoku_signal
from .keltner import KeltnerSettings, keltner_channel
from .kst import KSTSettings, calculate_kst, kst
from .kvo import KVOSettings, calculate_kvo, kvo
from .macd import macd, macd_signal
from .markov_switching import calculate_markov_indicator, calculate_markov_switching
from .mass_index import MassIndexSettings, calculate_mass_index, mass_index
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
from .tma import TMASettings, calculate_tma, tma
from .trix import TRIXSettings, calculate_trix, trix
from .tsi import TSISettings, calculate_tsi, tsi
from .ultimate_oscillator import (
    UltimateOscillatorSettings,
    calculate_ultimate_oscillator,
    ultimate_oscillator,
)

# Additional indicators
from .volume_oscillator import (
    VolumeOscillatorSettings,
    calculate_volume_oscillator,
    volume_oscillator,
)
from .vix import VIXSettings, calculate_vix, vix
from .vortex import calculate_vortex, vortex, vortex_signal

# Indicateurs ajoutés 12/12/2025
from .vwap import VWAPSettings, vwap
from .williams_r import WilliamsRSettings, williams_r
from .wma import WMASettings, calculate_wma, wma

__all__ = [
    # Indicateurs de base
    "bollinger_bands",
    "BollingerSettings",
    "atr",
    "ATRSettings",
    "chaikin_oscillator",
    "calculate_chaikin_oscillator",
    "ChaikinOscillatorSettings",
    "choppiness_index",
    "calculate_choppiness_index",
    "ChoppinessIndexSettings",
    "cmf",
    "calculate_cmf",
    "CMFSettings",
    "cmo",
    "calculate_cmo",
    "CMOSettings",
    "coppock_curve",
    "calculate_coppock_curve",
    "CoppockCurveSettings",
    "rsi",
    "RSISettings",
    "ema",
    "sma",
    "EMASettings",
    "dpo",
    "calculate_dpo",
    "DPOSettings",
    "elder_ray",
    "calculate_elder_ray",
    "ElderRaySettings",
    "eom",
    "calculate_eom",
    "EOMSettings",
    "macd",
    "macd_signal",
    "calculate_markov_switching",
    "calculate_markov_indicator",
    "adx",
    "calculate_adx",
    "fisher_transform",
    "calculate_fisher_transform",
    "FisherTransformSettings",
    "force_index",
    "calculate_force_index",
    "ForceIndexSettings",
    "hma",
    "calculate_hma",
    "HMASettings",
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
    "kst",
    "calculate_kst",
    "KSTSettings",
    "kvo",
    "calculate_kvo",
    "KVOSettings",
    "mass_index",
    "calculate_mass_index",
    "MassIndexSettings",
    "aroon",
    "AroonSettings",
    "supertrend",
    "SuperTrendSettings",
    "tma",
    "calculate_tma",
    "TMASettings",
    "trix",
    "calculate_trix",
    "TRIXSettings",
    "tsi",
    "calculate_tsi",
    "TSISettings",
    "ultimate_oscillator",
    "calculate_ultimate_oscillator",
    "UltimateOscillatorSettings",
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
    "vix",
    "calculate_vix",
    "VIXSettings",
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
    "wma",
    "calculate_wma",
    "WMASettings",
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
