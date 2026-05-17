"""Schema central des indicateurs exposes au Strategy Builder.

Le registre reste la source de vérité pour le calcul effectif. Ce module
centralise le contrat de lecture autour du registre : alias, paramètres
acceptés, sorties dict, alias de sous-clés et exemples d'accès Builder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

OutputType = Literal["array", "dict"]
TokenCategory = Literal[
    "canonical_indicator",
    "indicator_alias",
    "output_key_alias",
    "parameter_alias",
    "parameterized_indicator_instance",
    "derived_feature",
    "local_variable_only",
    "noise_or_comment_only",
]


@dataclass(frozen=True)
class IndicatorSchema:
    name: str
    calculation_function: str = ""
    aliases: tuple[str, ...] = ()
    accepted_params: dict[str, Any] = field(default_factory=dict)
    required_columns: tuple[str, ...] = ()
    output_type: OutputType = "array"
    output_keys: tuple[str, ...] = ()
    output_key_aliases: dict[str, str] = field(default_factory=dict)
    builder_access: str = ""
    stable_alias_map: dict[str, str] = field(default_factory=dict)
    parameterized: bool = False


@dataclass(frozen=True)
class IndicatorInstance:
    alias: str
    name: str
    params: dict[str, Any]


@dataclass(frozen=True)
class DerivedFeatureSpec:
    alias: str
    source: str
    transform: str
    params: dict[str, Any]
    supported: bool
    reason: str = ""


@dataclass(frozen=True)
class TokenClassification:
    token: str
    category: TokenCategory
    canonical: str | None = None
    output_key: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("-", "_").replace(" ", "_")
    text = re.sub(r"_+", "_", text).strip("_")
    return text


INDICATOR_PARAM_DEFAULTS: dict[str, dict[str, Any]] = {
    "ad_line": {},
    "adx": {"period": 14},
    "amplitude_hunter": {"period": 20},
    "aroon": {"period": 14},
    "atr": {"period": 14, "method": "ema"},
    "bollinger": {"period": 20, "std_dev": 2.0},
    "cci": {"period": 20},
    "chaikin_oscillator": {"fast_period": 3, "slow_period": 10},
    "choppiness_index": {"period": 14},
    "cmf": {"period": 20},
    "cmo": {"period": 14},
    "coppock_curve": {"long_roc": 14, "short_roc": 11, "period": 10},
    "directional_bias": {},
    "donchian": {"period": 20},
    "dpo": {"period": 20},
    "elder_ray": {"period": 13},
    "ema": {"period": 20},
    "eom": {"period": 14},
    "fear_greed": {"column": "fear_greed", "smooth_period": 0, "method": "sma"},
    "fibonacci_levels": {"period": 50},
    "fisher_transform": {"period": 10},
    "force_index": {"period": 13},
    "fva": {},
    "fvg": {},
    "hma": {"period": 20},
    "ichimoku": {"tenkan_period": 9, "kijun_period": 26, "senkou_b_period": 52, "displacement": 26},
    "keltner": {"ema_period": 20, "atr_period": 10, "atr_multiplier": 2.0},
    "kst": {},
    "kvo": {"short_period": 34, "long_period": 55, "signal_period": 13},
    "macd": {"fast_period": 12, "slow_period": 26, "signal_period": 9},
    "markov_switching": {"resample_to": "1h", "k_regimes": 3, "min_periods": 252, "price_column": "close"},
    "mass_index": {"period": 9, "ema_period": 25},
    "mfi": {"period": 14},
    "momentum": {"period": 14},
    "obv": {},
    "onchain_smoothing": {"column": "close", "period": 14, "method": "ema"},
    "pi_cycle": {"short_period": 111, "long_period": 350, "long_multiplier": 2.0},
    "pivot_points": {"method": "classic"},
    "psar": {"af_start": 0.02, "af_increment": 0.02, "af_max": 0.2},
    "roc": {"period": 12},
    "rsi": {"period": 14},
    "sma": {"period": 20},
    "smart_legs": {},
    "standard_deviation": {"period": 20},
    "stoch_rsi": {"rsi_period": 14, "stoch_period": 14, "k_smooth": 3, "d_smooth": 3, "oversold": 20, "overbought": 80},
    "stochastic": {"k_period": 14, "d_period": 3, "smooth_k": 3},
    "supertrend": {"atr_period": 10, "multiplier": 3.0},
    "swing": {},
    "tma": {"period": 20},
    "trix": {"period": 18},
    "tsi": {"long_period": 25, "short_period": 13},
    "ultimate_oscillator": {"period1": 7, "period2": 14, "period3": 28},
    "vix": {"period": 20, "periods_per_year": 365.0},
    "volume_oscillator": {"short_period": 14, "long_period": 28, "method": "ema"},
    "vortex": {"period": 14, "threshold": 0.0},
    "vwap": {"period": None},
    "williams_r": {"period": 14},
    "wma": {"period": 14},
}

REQUIRED_COLUMN_OVERRIDES: dict[str, tuple[str, ...]] = {
    # The registry keeps this empty because the input column is configurable,
    # but the Builder contract must still expose the default runtime dependency.
    "fear_greed": ("fear_greed",),
}

DICT_INDICATOR_OUTPUT_KEYS: dict[str, tuple[str, ...]] = {
    "adx": ("adx", "plus_di", "minus_di"),
    "amplitude_hunter": ("range_pct", "score"),
    "aroon": ("aroon_up", "aroon_down"),
    "bollinger": ("upper", "middle", "lower"),
    "directional_bias": ("bull_score", "bear_score", "net_bias"),
    "donchian": ("upper", "middle", "lower"),
    "elder_ray": ("bull_power", "bear_power"),
    "fibonacci_levels": ("high", "low", "level_236", "level_382", "level_500", "level_618", "level_786"),
    "fisher_transform": ("fisher", "trigger"),
    "fvg": ("fvg_bullish", "fvg_bearish"),
    "ichimoku": ("tenkan", "kijun", "senkou_a", "senkou_b", "chikou", "cloud_position"),
    "keltner": ("middle", "upper", "lower"),
    "kvo": ("kvo", "signal"),
    "macd": ("macd", "signal", "histogram"),
    "markov_switching": ("regime", "prob_regime_0", "prob_regime_1", "prob_regime_2", "prob_regime_3"),
    "pi_cycle": ("short_ma", "long_ma", "signal"),
    "pivot_points": ("pivot", "r1", "s1", "r2", "s2", "r3", "s3"),
    "psar": ("sar", "trend", "signal"),
    "smart_legs": ("smart_leg_bullish", "smart_leg_bearish"),
    "stoch_rsi": ("k", "d", "signal"),
    "stochastic": ("stoch_k", "stoch_d"),
    "supertrend": ("supertrend", "direction"),
    "swing": ("swing_high", "swing_low"),
    "vortex": ("vi_plus", "vi_minus", "signal", "oscillator"),
}

DICT_INDICATOR_NAMES: frozenset[str] = frozenset(DICT_INDICATOR_OUTPUT_KEYS)

INDICATOR_ALIASES: dict[str, str] = {
    "average_true_range": "atr",
    "bb": "bollinger",
    "bbands": "bollinger",
    "bollinger_bands": "bollinger",
    "chop": "choppiness_index",
    "choppiness": "choppiness_index",
    "coppock": "coppock_curve",
    "coppock_momentum": "coppock_curve",
    "dmi": "adx",
    "donchian_breakout": "donchian",
    "donchian_channel": "donchian",
    "donchian_channels": "donchian",
    "ema_fast": "ema",
    "ema_slow": "ema",
    "fair_value_gap": "fvg",
    "fib_level": "fibonacci_levels",
    "fib_levels": "fibonacci_levels",
    "fibonacci": "fibonacci_levels",
    "fibonacci_level": "fibonacci_levels",
    "keltner_channel": "keltner",
    "klt": "keltner",
    "implied_volatility_proxy": "vix",
    "markov": "markov_switching",
    "market_choppiness_index": "choppiness_index",
    "market_volatility": "vix",
    "mci": "choppiness_index",
    "obvi": "obv",
    "parabolic_sar": "psar",
    "pivot": "pivot_points",
    "pivot_point": "pivot_points",
    "pivotpoints": "pivot_points",
    "pivots": "pivot_points",
    "rsci": "rsi",
    "stoch": "stochastic",
    "stochastic_rsi": "stoch_rsi",
    "stochrsi": "stoch_rsi",
    "super_trend": "supertrend",
    "true_range_atr": "atr",
    "chaikin_osc": "chaikin_oscillator",
    # 2026-05-15 - Patch Chaikin: alias additionnels pour eviter divagation LLM
    # (sessions ou le LLM creait ch_osc=0.0 placeholder au lieu d'utiliser l'indicateur).
    "chaikin": "chaikin_oscillator",
    "ch_osc": "chaikin_oscillator",
    "chaikin_o": "chaikin_oscillator",
    "chaikin_money_flow": "cmf",
    "chaikin_mf": "cmf",
    # 2026-05-15 - A/D Line (Accumulation/Distribution Line, base de la famille Chaikin)
    "ad": "ad_line",
    "adl": "ad_line",
    "ad_l": "ad_line",
    "accumulation_distribution": "ad_line",
    "accumulation_distribution_line": "ad_line",
    "accum_dist": "ad_line",
    "chaikin_ad": "ad_line",
    "chaikin_accumulation": "ad_line",
    "volatility": "vix",
    "vol_osc": "volume_oscillator",
    "vol_oscillator": "volume_oscillator",
    "volume_osc": "volume_oscillator",
    "volumeoscillator": "volume_oscillator",
    "vix_proxy": "vix",
    "williams": "williams_r",
    "williamsr": "williams_r",
}

OUTPUT_KEY_ALIASES: dict[str, dict[str, str]] = {
    "adx": {
        "adx_value": "adx",
        "adx_val": "adx",
        "plus_di": "plus_di",
        "di_plus": "plus_di",
        "diplus": "plus_di",
        "adx_plus": "plus_di",
        "adx_dplus": "plus_di",
        "adx_d_plus": "plus_di",
        "+di": "plus_di",
        "minus_di": "minus_di",
        "di_minus": "minus_di",
        "diminus": "minus_di",
        "adx_minus": "minus_di",
        "adx_dminus": "minus_di",
        "adx_d_minus": "minus_di",
        "-di": "minus_di",
    },
    "amplitude_hunter": {"amplitude_hunter_score": "score", "range_expansion_score": "score"},
    "aroon": {"up": "aroon_up", "down": "aroon_down", "aroon_up": "aroon_up", "aroon_down": "aroon_down", "aroon_upper": "aroon_up", "aroon_lower": "aroon_down"},
    "bollinger": {
        "bb_upper": "upper",
        "bb_middle": "middle",
        "bb_mid": "middle",
        "bb_lower": "lower",
        "bollinger_upper": "upper",
        "bollinger_middle": "middle",
        "bollinger_mid": "middle",
        "bollinger_lower": "lower",
        "upper_bollinger": "upper",
        "upper_band": "upper",
        "middle_bollinger": "middle",
        "middle_band": "middle",
        "mid_band": "middle",
        "mid_bollinger": "middle",
        "lower_bollinger": "lower",
        "lower_band": "lower",
        "higher_bollinger": "upper",
        "midline_bollinger": "middle",
    },
    "directional_bias": {
        "bull_score": "bull_score",
        "bear_score": "bear_score",
        "net_bias": "net_bias",
        "directional_bias_net": "net_bias",
    },
    "donchian": {
        "dc_upper": "upper",
        "dc_middle": "middle",
        "dc_mid": "middle",
        "dc_lower": "lower",
        "donchian_upper": "upper",
        "donchian_middle": "middle",
        "donchian_lower": "lower",
    },
    "elder_ray": {"bull_power": "bull_power", "bear_power": "bear_power"},
    "fibonacci_levels": {"fibonacci_levels_high": "high", "fibonacci_levels_low": "low"},
    "fisher_transform": {"fisher_signal": "trigger", "fisher_trigger": "trigger"},
    "fvg": {"fvg_bullish": "fvg_bullish", "fvg_bearish": "fvg_bearish", "bull_gap": "fvg_bullish", "bear_gap": "fvg_bearish"},
    "ichimoku": {
        "tenkan_sen": "tenkan",
        "conversion_line": "tenkan",
        "kijun_sen": "kijun",
        "base_line": "kijun",
        "senkou_span_a": "senkou_a",
        "senkou_span_b": "senkou_b",
        "chikou_span": "chikou",
        "ichimoku_tenkan": "tenkan",
        "ichimoku_kijun": "kijun",
        "ichimoku_senkou_a": "senkou_a",
        "ichimoku_senkou_b": "senkou_b",
        "ichimoku_chikou": "chikou",
        "ichimoku_cloud": "cloud_position",
    },
    "keltner": {
        "kelt_upper": "upper",
        "kelt_middle": "middle",
        "kelt_mid": "middle",
        "kelt_lower": "lower",
        "keltner_upper": "upper",
        "keltner_middle": "middle",
        "keltner_lower": "lower",
    },
    "kvo": {"kvo_signal": "signal"},
    "macd": {
        "line": "macd",
        "macd_line": "macd",
        "macd_signal": "signal",
        "signal_line": "signal",
        "macd_signal_line": "signal",
        "hist": "histogram",
        "macd_hist": "histogram",
        "macd_histogram": "histogram",
        "macdhist": "histogram",
    },
    "markov_switching": {
        "markov_regime": "regime",
        "regime_probability": "prob_regime_1",
        "markov_bull_probability": "prob_regime_1",
        "bull_probability": "prob_regime_1",
    },
    "pi_cycle": {"pi_short_ma": "short_ma", "pi_long_ma": "long_ma", "pi_signal": "signal"},
    "pivot_points": {
        "pivot": "pivot",
        "pivot_points_pivot": "pivot",
        "pivot_points_r1": "r1",
        "pivot_points_s1": "s1",
        "pivot_points_r2": "r2",
        "pivot_points_s2": "s2",
        "pivot_points_r3": "r3",
        "pivot_points_s3": "s3",
    },
    "psar": {"parabolic_sar": "sar", "psar_sar": "sar", "psar_trend": "trend", "psar_signal": "signal"},
    "smart_legs": {"smart_leg_bullish": "smart_leg_bullish", "smart_leg_bearish": "smart_leg_bearish"},
    "stoch_rsi": {"stoch_rsi_k": "k", "stoch_rsi_d": "d", "stoch_rsi_signal": "signal", "srsi_k": "k", "srsi_d": "d"},
    "stochastic": {
        "k": "stoch_k",
        "d": "stoch_d",
        "slowk": "stoch_k",
        "slowd": "stoch_d",
        "percent_k": "stoch_k",
        "percent_d": "stoch_d",
        "stoch_k": "stoch_k",
        "stoch_d": "stoch_d",
        "stochastic_k": "stoch_k",
        "stochastic_d": "stoch_d",
    },
    "supertrend": {
        "supertrend_value": "supertrend",
        "supertrend_line": "supertrend",
        "supertrend_direction": "direction",
        "supertrend_dir": "direction",
        "st_direction": "direction",
        "st_dir": "direction",
        "direction": "direction",
    },
    "swing": {"swing_high": "swing_high", "swing_low": "swing_low"},
    "vortex": {"vi_plus": "vi_plus", "vi_minus": "vi_minus", "vortex_plus": "vi_plus", "vortex_minus": "vi_minus", "vortex_signal": "signal", "vortex_oscillator": "oscillator"},
}

BUILDER_ACCESS_EXAMPLES: dict[str, str] = {
    "adx": 'adx_d = indicators["adx"]; adx = np.nan_to_num(adx_d["adx"]); plus_di = np.nan_to_num(adx_d["plus_di"]); minus_di = np.nan_to_num(adx_d["minus_di"])',
    "amplitude_hunter": 'amp = indicators["amplitude_hunter"]; range_pct = np.nan_to_num(amp["range_pct"]); score = np.nan_to_num(amp["score"])',
    "aroon": 'ar = indicators["aroon"]; aroon_up = np.nan_to_num(ar["aroon_up"]); aroon_down = np.nan_to_num(ar["aroon_down"])',
    "bollinger": 'bb = indicators["bollinger"]; upper = np.nan_to_num(bb["upper"]); middle = np.nan_to_num(bb["middle"]); lower = np.nan_to_num(bb["lower"])',
    "directional_bias": 'bias = indicators["directional_bias"]; bull_score = np.nan_to_num(bias["bull_score"]); bear_score = np.nan_to_num(bias["bear_score"]); net_bias = np.nan_to_num(bias["net_bias"])',
    "donchian": 'dc = indicators["donchian"]; upper = np.nan_to_num(dc["upper"]); middle = np.nan_to_num(dc["middle"]); lower = np.nan_to_num(dc["lower"])',
    "elder_ray": 'elder = indicators["elder_ray"]; bull_power = np.nan_to_num(elder["bull_power"]); bear_power = np.nan_to_num(elder["bear_power"])',
    "fibonacci_levels": 'fib = indicators["fibonacci_levels"]; fib_high = np.nan_to_num(fib["high"]); fib_low = np.nan_to_num(fib["low"])',
    "fisher_transform": 'fish = indicators["fisher_transform"]; fisher = np.nan_to_num(fish["fisher"]); trigger = np.nan_to_num(fish["trigger"])',
    "fvg": 'fvg = indicators["fvg"]; fvg_bullish = np.nan_to_num(fvg["fvg_bullish"]).astype(bool); fvg_bearish = np.nan_to_num(fvg["fvg_bearish"]).astype(bool)',
    "ichimoku": 'ich = indicators["ichimoku"]; tenkan = np.nan_to_num(ich["tenkan"]); kijun = np.nan_to_num(ich["kijun"]); senkou_a = np.nan_to_num(ich["senkou_a"]); senkou_b = np.nan_to_num(ich["senkou_b"])',
    "keltner": 'kelt = indicators["keltner"]; upper = np.nan_to_num(kelt["upper"]); middle = np.nan_to_num(kelt["middle"]); lower = np.nan_to_num(kelt["lower"])',
    "kvo": 'kvo_d = indicators["kvo"]; kvo = np.nan_to_num(kvo_d["kvo"]); kvo_signal = np.nan_to_num(kvo_d["signal"])',
    "macd": 'macd_d = indicators["macd"]; macd_line = np.nan_to_num(macd_d["macd"]); macd_signal = np.nan_to_num(macd_d["signal"]); macd_histogram = np.nan_to_num(macd_d["histogram"])',
    "markov_switching": 'mk = indicators["markov_switching"]; regime = np.nan_to_num(mk["regime"]); markov_bull_probability = np.nan_to_num(mk["prob_regime_1"])',
    "pi_cycle": 'pi = indicators["pi_cycle"]; short_ma = np.nan_to_num(pi["short_ma"]); long_ma = np.nan_to_num(pi["long_ma"]); pi_signal = np.nan_to_num(pi["signal"])',
    "pivot_points": 'pp = indicators["pivot_points"]; pivot = np.nan_to_num(pp["pivot"]); r1 = np.nan_to_num(pp["r1"]); s1 = np.nan_to_num(pp["s1"])',
    "psar": 'psar_d = indicators["psar"]; sar = np.nan_to_num(psar_d["sar"]); psar_trend = np.nan_to_num(psar_d["trend"])',
    "smart_legs": 'legs = indicators["smart_legs"]; smart_leg_bullish = np.nan_to_num(legs["smart_leg_bullish"]).astype(bool); smart_leg_bearish = np.nan_to_num(legs["smart_leg_bearish"]).astype(bool)',
    "stoch_rsi": 'srsi = indicators["stoch_rsi"]; stoch_rsi_k = np.nan_to_num(srsi["k"]); stoch_rsi_d = np.nan_to_num(srsi["d"])',
    "stochastic": 'stoch = indicators["stochastic"]; stoch_k = np.nan_to_num(stoch["stoch_k"]); stoch_d = np.nan_to_num(stoch["stoch_d"])',
    "supertrend": 'st = indicators["supertrend"]; supertrend_value = np.nan_to_num(st["supertrend"]); supertrend_direction = np.nan_to_num(st["direction"])',
    "swing": 'sw = indicators["swing"]; swing_high = np.nan_to_num(sw["swing_high"]).astype(bool); swing_low = np.nan_to_num(sw["swing_low"]).astype(bool)',
    "vortex": 'vx = indicators["vortex"]; vi_plus = np.nan_to_num(vx["vi_plus"]); vi_minus = np.nan_to_num(vx["vi_minus"])',
    # 2026-05-15 - Famille Chaikin: exemples explicites pour eviter divagation LLM
    # (sessions ou modeles creaient ch_osc=0.0 placeholder au lieu d'acceder a l'indicateur).
    # Tous les 3 sont des arrays (output_type="array"), pas des dicts.
    "chaikin_oscillator": 'ch_osc = np.nan_to_num(indicators["chaikin_oscillator"])',
    "cmf": 'cmf_val = np.nan_to_num(indicators["cmf"])',
    "ad_line": 'adl = np.nan_to_num(indicators["ad_line"])',
}

STABLE_ALIAS_MAP: dict[str, dict[str, str]] = {
    "adx": {"adx_d": "adx_data", "adx": "adx_value", "plus_di": "adx_plus_di", "minus_di": "adx_minus_di"},
    "amplitude_hunter": {"amp": "amplitude_hunter_data", "range_pct": "amplitude_hunter_range_pct", "score": "amplitude_hunter_score"},
    "aroon": {"ar": "aroon_data", "aroon_up": "aroon_up", "aroon_down": "aroon_down"},
    "bollinger": {"bb": "bollinger_data", "upper": "bollinger_upper", "middle": "bollinger_middle", "lower": "bollinger_lower"},
    "directional_bias": {"bias": "directional_bias_data", "bull_score": "directional_bias_bull_score", "bear_score": "directional_bias_bear_score", "net_bias": "directional_bias_net"},
    "donchian": {"dc": "donchian_data", "upper": "donchian_upper", "middle": "donchian_middle", "lower": "donchian_lower"},
    "fvg": {"fvg": "fvg_data", "fvg_bullish": "fvg_bullish", "fvg_bearish": "fvg_bearish"},
    "ichimoku": {"ich": "ichimoku_data", "tenkan": "ichimoku_tenkan", "kijun": "ichimoku_kijun"},
    "keltner": {"kelt": "keltner_data", "upper": "keltner_upper", "middle": "keltner_middle", "lower": "keltner_lower"},
    "macd": {"macd_d": "macd_data", "macd_line": "macd_line", "macd_signal": "macd_signal", "macd_histogram": "macd_histogram"},
    "markov_switching": {"mk": "markov_data", "regime": "markov_regime", "markov_bull_probability": "markov_bull_probability"},
    "pivot_points": {"pp": "pivot_points_data", "pivot": "pivot_points_pivot", "r1": "pivot_points_r1"},
    "psar": {"psar_d": "psar_data", "sar": "psar_sar"},
    "smart_legs": {"legs": "smart_legs_data", "smart_leg_bullish": "smart_legs_bullish", "smart_leg_bearish": "smart_legs_bearish"},
    "stoch_rsi": {"srsi": "stoch_rsi_data", "stoch_rsi_k": "stoch_rsi_k", "stoch_rsi_d": "stoch_rsi_d"},
    "stochastic": {"stoch": "stochastic_data", "stoch_k": "stochastic_k", "stoch_d": "stochastic_d"},
    "supertrend": {
        "st": "supertrend_data",
        "supertrend_value": "supertrend_value",
        "supertrend_direction": "supertrend_direction",
        "supertrend_dir": "supertrend_direction",
        "st_dir": "supertrend_direction",
    },
    "swing": {"sw": "swing_data", "swing_high": "swing_high", "swing_low": "swing_low"},
    "vortex": {"vx": "vortex_data", "vi_plus": "vortex_vi_plus", "vi_minus": "vortex_vi_minus"},
}

MODEL_DEMAND_HINTS: dict[str, dict[str, Any]] = {
    "adx": {"aliases": ("adx_plus", "adx_minus", "dmi", "+di", "-di"), "cue": "use canonical adx and read adx/+DI/-DI values from the adx dict."},
    "amplitude_hunter": {"aliases": ("amplitude_hunter_score", "range_expansion_score"), "cue": "use canonical amplitude_hunter for range expansion and compression-release ideas."},
    "atr": {"aliases": ("average_true_range", "true_range_atr", "atr_sma_20"), "cue": "use canonical atr for volatility stops; atr_sma_20 is a derived feature, not a base indicator."},
    "bollinger": {"aliases": ("bb_upper", "bb_lower", "bb_middle", "bollinger_upper", "bollinger_lower"), "cue": "use canonical bollinger and access upper/middle/lower from the dict."},
    "choppiness_index": {"aliases": ("mci", "chop", "choppiness", "market_choppiness_index"), "cue": "use canonical choppiness_index for range-vs-trend filtering."},
    "chaikin_oscillator": {"aliases": ("chaikin_osc",), "cue": "use canonical chaikin_oscillator for accumulation/distribution momentum."},
    "coppock_curve": {"aliases": ("coppock", "coppock_momentum", "coppock_curve_sma_5"), "cue": "use canonical coppock_curve; coppock_curve_sma_5 is a derived smoothing feature."},
    "donchian": {"aliases": ("donchian_breakout", "donchian_channels", "donchian_upper", "donchian_lower"), "cue": "use canonical donchian and access upper/middle/lower from the dict."},
    "ema": {"aliases": ("ema_fast", "ema_slow", "fast_ema", "slow_ema", "ema_21", "ema_50", "ema_200"), "cue": "use parameterized instances for multiple EMA periods: ema_21, ema_50, ema_200."},
    "fvg": {"aliases": ("fvg_bullish", "fvg_bearish", "fair_value_gap"), "cue": "use canonical fvg for imbalance and gap-fill logic."},
    "macd": {"aliases": ("macd_line", "macd_signal", "macd_hist", "macd_histogram"), "cue": "local MACD keys are macd, signal, histogram."},
    "markov_switching": {"aliases": ("markov", "markov_regime", "markov_bull_probability", "regime_probability"), "cue": "use canonical markov_switching for probabilistic regime gating."},
    "psar": {"aliases": ("sar", "parabolic_sar", "psar_sar"), "cue": "use canonical psar for trailing stop or reversal logic."},
    "stochastic": {"aliases": ("stoch", "stoch_k", "stoch_d", "stochastic_k", "stochastic_d"), "cue": "use canonical stochastic and access stoch_k/stoch_d from the dict."},
    "supertrend": {"aliases": ("super_trend", "supertrend_direction", "supertrend_dir", "st_dir"), "cue": "use canonical supertrend for ATR-based trend direction."},
    "trix": {"aliases": ("triple_ema_roc", "trix_zero_cross", "trix_momentum"), "cue": "use canonical trix for triple-smoothed momentum."},
    "vix": {"aliases": ("market_volatility", "volatility", "vix_proxy", "implied_volatility_proxy"), "cue": "use canonical vix as an OHLCV-only realized-volatility proxy."},
    "volume_oscillator": {"aliases": ("volume_osc", "vol_osc", "vol_oscillator"), "cue": "use canonical volume_oscillator for volume momentum."},
    "vortex": {"aliases": ("vortex_plus", "vortex_minus", "vi_plus", "vi_minus"), "cue": "use canonical vortex and access vi_plus/vi_minus."},
}

PARAMETER_ALIAS_ACCESS: dict[str, str] = {
    "warmup": "params.get('warmup', 50)",
    "leverage": "params.get('leverage', 1)",
    "atr_period": "params.get('atr_period', 14)",
    "atr_mult": "params.get('atr_mult', params.get('stop_atr_mult', 1.5))",
    "stop_atr_mult": "params.get('stop_atr_mult', 1.5)",
    "tp_atr_mult": "params.get('tp_atr_mult', 3.0)",
    "sl_factor": "params.get('stop_atr_mult', 1.5)",
    "tp_factor": "params.get('tp_atr_mult', 3.0)",
    "adx_threshold": "params.get('adx_threshold', 25)",
    "adx_filter": "params.get('adx_filter', 25)",
    "adx_min": "params.get('adx_min', 20)",
    "mfi_threshold_high": "params.get('mfi_threshold_high', 70)",
    "mfi_threshold_low": "params.get('mfi_threshold_low', 30)",
    "mfi_high": "params.get('mfi_threshold_high', 70)",
    "mfi_low": "params.get('mfi_threshold_low', 30)",
    "sl_mult": "params.get('stop_atr_mult', 1.5)",
    "tp_mult": "params.get('tp_atr_mult', 3.0)",
    "atr_stop_mult": "params.get('stop_atr_mult', 1.5)",
    "atr_tp_mult": "params.get('tp_atr_mult', 3.0)",
    "bb_std": "params.get('bb_std', params.get('std_dev', 2.0))",
    "cmf_threshold": "params.get('cmf_threshold', 0.0)",
    "std_dev": "params.get('std_dev', params.get('bb_std', 2.0))",
    "bias_min": "params.get('bias_min', 0.5)",
    "trend_filter": "params.get('trend_filter', 0.3)",
    "rsi_overbought": "params.get('rsi_overbought', 70)",
    "rsi_oversold": "params.get('rsi_oversold', 30)",
    "rsi_period": "params.get('rsi_period', 14)",
    "bias_strength_filter": "params.get('bias_strength_filter', 0.5)",
}

SAFE_DICT_INDICATOR_KEYS: dict[str, str] = {
    "adx": "adx",
    "amplitude_hunter": "score",
    "supertrend": "supertrend",
    "directional_bias": "net_bias",
    "markov_switching": "regime",
}

SAFE_DICT_INDICATOR_ASSIGNMENT_ALIASES: dict[str, set[str]] = {
    "adx": {"adx_val", "adx_value"},
    "amplitude_hunter": {"amp_score", "amplitude_score", "amplitude_hunter_score", "score", "vol_expansion_score", "volatility_expansion_score"},
    "directional_bias": {"directional_bias_net", "net_bias"},
    "markov_switching": {"markov_regime", "regime"},
    "supertrend": {"supertrend_value", "supertrend_level"},
}

INVALID_DICT_SUBKEY_REWRITE_HINTS: dict[tuple[str, str], str] = {
    ("bollinger", "close"): "np.nan_to_num(df['close'].values.astype(np.float64))",
    ("donchian", "close"): "np.nan_to_num(df['close'].values.astype(np.float64))",
    ("keltner", "close"): "np.nan_to_num(df['close'].values.astype(np.float64))",
    ("bollinger", "std"): "(np.nan_to_num(indicators['bollinger']['upper']) - np.nan_to_num(indicators['bollinger']['middle']))",
    ("bollinger", "width"): "(np.nan_to_num(indicators['bollinger']['upper']) - np.nan_to_num(indicators['bollinger']['lower']))",
    ("donchian", "width"): "(np.nan_to_num(indicators['donchian']['upper']) - np.nan_to_num(indicators['donchian']['lower']))",
    ("keltner", "width"): "(np.nan_to_num(indicators['keltner']['upper']) - np.nan_to_num(indicators['keltner']['lower']))",
    ("donchian", "supertrend"): "indicators['supertrend']['supertrend']",
    ("fvg", "fvg_bullish_gap"): "indicators['fvg']['fvg_bullish']",
    ("fvg", "fvg_bearish_gap"): "indicators['fvg']['fvg_bearish']",
    # 2026-05-15 - Patch IND001: sous-cles inventees par le LLM, observees sur 49 sessions baseline.
    # Supertrend n'a qu'une valeur unique (supertrend), pas de middle/upper/lower comme bollinger/keltner/donchian.
    ("supertrend", "middle"): "indicators['supertrend']['supertrend']",
    ("supertrend", "upper"): "indicators['supertrend']['supertrend']",
    ("supertrend", "lower"): "indicators['supertrend']['supertrend']",
    ("supertrend", "trend"): "indicators['supertrend']['supertrend']",
    # RSI est un array, pas un dict. LLM tente parfois indicators['rsi']['rsi'].
    ("rsi", "rsi"): "indicators['rsi']",
    ("rsi", "rsi_value"): "indicators['rsi']",
    ("rsi", "value"): "indicators['rsi']",
    ("rsi", "values"): "indicators['rsi']",
}


def _default_builder_access(indicator_name: str) -> str:
    return f'value = np.nan_to_num(indicators["{indicator_name}"])'


def _load_registry_names() -> tuple[str, ...]:
    try:
        from indicators.registry import list_indicators

        return tuple(sorted(str(name).strip().lower() for name in list_indicators() if str(name).strip()))
    except Exception:
        return tuple(sorted(set(INDICATOR_PARAM_DEFAULTS) | set(DICT_INDICATOR_OUTPUT_KEYS)))


def _load_required_columns(name: str) -> tuple[str, ...]:
    if name in REQUIRED_COLUMN_OVERRIDES:
        return REQUIRED_COLUMN_OVERRIDES[name]
    try:
        from indicators.registry import get_indicator

        info = get_indicator(name)
        if info is not None:
            return tuple(info.required_columns)
    except Exception:
        pass
    return ()


def _load_calculation_function_name(name: str) -> str:
    try:
        from indicators.registry import get_indicator

        info = get_indicator(name)
        function = getattr(info, "function", None)
        if function is not None:
            module = getattr(function, "__module__", "")
            func_name = getattr(function, "__name__", "")
            if module and func_name:
                return f"{module}.{func_name}"
            if func_name:
                return func_name
    except Exception:
        pass
    return ""


def _aliases_for(canonical: str) -> tuple[str, ...]:
    return tuple(sorted(alias for alias, target in INDICATOR_ALIASES.items() if target == canonical))


def _build_indicator_schemas() -> dict[str, IndicatorSchema]:
    schemas: dict[str, IndicatorSchema] = {}
    parameterized_names = {
        "atr",
        "cci",
        "choppiness_index",
        "cmo",
        "dpo",
        "ema",
        "hma",
        "mfi",
        "momentum",
        "roc",
        "rsi",
        "sma",
        "standard_deviation",
        "tma",
        "trix",
        "vix",
        "williams_r",
        "wma",
    }
    for name in _load_registry_names():
        output_keys = DICT_INDICATOR_OUTPUT_KEYS.get(name, ())
        schemas[name] = IndicatorSchema(
            name=name,
            calculation_function=_load_calculation_function_name(name),
            aliases=_aliases_for(name),
            accepted_params=dict(INDICATOR_PARAM_DEFAULTS.get(name, {})),
            required_columns=_load_required_columns(name),
            output_type="dict" if output_keys else "array",
            output_keys=output_keys,
            output_key_aliases=dict(OUTPUT_KEY_ALIASES.get(name, {})),
            builder_access=BUILDER_ACCESS_EXAMPLES.get(name, _default_builder_access(name)),
            stable_alias_map=dict(STABLE_ALIAS_MAP.get(name, {})),
            parameterized=name in parameterized_names,
        )
    return schemas


INDICATOR_SCHEMAS: dict[str, IndicatorSchema] = _build_indicator_schemas()


def canonicalize_indicator_alias(name: Any) -> str | None:
    key = _norm(name)
    if not key:
        return None
    if key in INDICATOR_SCHEMAS:
        return key
    if key in INDICATOR_ALIASES:
        return INDICATOR_ALIASES[key]
    instance = parse_parameterized_indicator_instance(key)
    if instance is not None:
        return instance.alias
    derived = parse_derived_feature(key)
    if derived is not None:
        return derived.alias
    return None


def canonical_indicator_name(name: Any) -> str | None:
    key = _norm(name)
    if not key:
        return None
    if key in INDICATOR_SCHEMAS:
        return key
    if key in INDICATOR_ALIASES:
        return INDICATOR_ALIASES[key]
    instance = parse_parameterized_indicator_instance(key)
    if instance is not None:
        return instance.name
    derived = parse_derived_feature(key)
    if derived is not None:
        return derived.source
    return None


def get_indicator_schema(name_or_alias: Any) -> IndicatorSchema | None:
    canonical = canonical_indicator_name(name_or_alias)
    if not canonical:
        return None
    return INDICATOR_SCHEMAS.get(canonical)


def get_indicator_calculation_function(name_or_alias: Any) -> str:
    schema = get_indicator_schema(name_or_alias)
    return schema.calculation_function if schema else ""


def is_dict_indicator(indicator: Any) -> bool:
    schema = get_indicator_schema(indicator)
    return bool(schema and schema.output_type == "dict")


def get_output_key_alias(indicator: Any, key_or_alias: Any) -> str | None:
    schema = get_indicator_schema(indicator)
    key = _norm(key_or_alias)
    if not schema or not key:
        return None
    if key in schema.output_keys:
        return key
    return schema.output_key_aliases.get(key)


def get_builder_access_example(indicator: Any) -> str:
    schema = get_indicator_schema(indicator)
    if schema:
        return schema.builder_access
    key = _norm(indicator) or "indicator_name"
    return _default_builder_access(key)


def get_stable_alias_map(indicator: Any) -> dict[str, str]:
    schema = get_indicator_schema(indicator)
    if not schema:
        return {}
    return dict(schema.stable_alias_map)


def get_indicator_output_alias_hints() -> dict[str, str]:
    hints: dict[str, str] = {}
    for indicator_name, schema in INDICATOR_SCHEMAS.items():
        for alias, key in schema.output_key_aliases.items():
            hints[alias] = f"indicators['{indicator_name}']['{key}']"
    return hints


def get_indicator_alias_hints() -> dict[str, str]:
    hints: dict[str, str] = {}
    for alias, canonical in INDICATOR_ALIASES.items():
        hints[alias] = f"indicators['{canonical}']"
    hints.update(get_indicator_output_alias_hints())
    return hints


INDICATOR_ACCESS_ALIASES: dict[str, str] = get_indicator_alias_hints()
SEMANTIC_INDICATOR_ALIASES: dict[str, str] = {
    alias: expr
    for alias, expr in INDICATOR_ACCESS_ALIASES.items()
    if alias
    in {
        "higher_bollinger",
        "lower_bollinger",
        "middle_bollinger",
        "mid_bollinger",
        "midline_bollinger",
        "upper_bollinger",
        "bb_upper",
        "bb_lower",
        "bb_middle",
        "macd_line",
        "macd_signal",
        "macd_hist",
        "macd_histogram",
        "stoch_k",
        "stoch_d",
        "adx_plus",
        "adx_minus",
        "tenkan_sen",
        "kijun_sen",
        "markov_bull_probability",
    }
}


_PARAMETERIZED_BASE_ALIASES = {
    "chop": "choppiness_index",
    "choppiness": "choppiness_index",
}


def parse_parameterized_indicator_instance(token: Any) -> IndicatorInstance | None:
    key = _norm(token)
    if not key:
        return None
    match = re.fullmatch(r"(?P<base>[a-z_]+)_(?P<period>\d{1,4})", key)
    if not match:
        return None
    base_raw = match.group("base")
    base = _PARAMETERIZED_BASE_ALIASES.get(base_raw, base_raw)
    if base not in INDICATOR_SCHEMAS:
        base = INDICATOR_ALIASES.get(base, base)
    schema = INDICATOR_SCHEMAS.get(base)
    if not schema or not schema.parameterized:
        return None
    period = int(match.group("period"))
    if period <= 0:
        return None
    return IndicatorInstance(alias=key, name=base, params={"period": period})


def parse_derived_feature(token: Any) -> DerivedFeatureSpec | None:
    key = _norm(token)
    if not key:
        return None
    match = re.fullmatch(r"(?P<source>atr|rsi|obv|coppock_curve|coppock|trix|ema|sma|wma)_sma(?:_(?P<window>\d{1,4}))?", key)
    if match:
        source = canonical_indicator_name(match.group("source")) or match.group("source")
        window = int(match.group("window") or 20)
        return DerivedFeatureSpec(
            alias=key,
            source=source,
            transform="sma",
            params={"window": window},
            supported=True,
        )
    if "divergence" in key:
        source = canonical_indicator_name(key.split("_", 1)[0]) or key.split("_", 1)[0]
        return DerivedFeatureSpec(
            alias=key,
            source=source,
            transform="divergence",
            params={},
            supported=False,
            reason="Les divergences doivent être codées explicitement dans generate_signals avec une logique vectorisée.",
        )
    return None


def calculate_derived_feature(name: Any, df: pd.DataFrame, params: dict[str, Any] | None = None) -> np.ndarray:
    spec = parse_derived_feature(name)
    if spec is None:
        raise ValueError(f"Feature dérivée inconnue: {name!r}")
    if not spec.supported:
        raise ValueError(f"Feature dérivée non supportée '{spec.alias}': {spec.reason}")

    from indicators.registry import calculate_indicator

    user_params = dict(params or {})
    source_params = dict(user_params.get("source_params", {}))
    source_period = user_params.get("source_period")
    if source_period is not None and "period" in INDICATOR_PARAM_DEFAULTS.get(spec.source, {}):
        source_params["period"] = source_period
    source_values = calculate_indicator(spec.source, df, source_params)
    if isinstance(source_values, dict):
        raise ValueError(f"Feature dérivée '{spec.alias}' attend une source array, pas un dict.")
    arr = np.asarray(source_values, dtype=np.float64)
    if spec.transform == "sma":
        window = int(user_params.get("window", spec.params.get("window", 20)))
        window = max(1, window)
        return pd.Series(arr).rolling(window=window, min_periods=1).mean().to_numpy(dtype=np.float64)
    raise ValueError(f"Transform dérivé non supporté: {spec.transform}")


def classify_indicator_token(token: Any) -> TokenClassification:
    key = _norm(token)
    if not key:
        return TokenClassification(token=str(token or ""), category="noise_or_comment_only", reason="empty")
    if key in INDICATOR_SCHEMAS:
        return TokenClassification(token=key, category="canonical_indicator", canonical=key)
    if key in INDICATOR_ALIASES:
        return TokenClassification(token=key, category="indicator_alias", canonical=INDICATOR_ALIASES[key])
    for indicator_name, aliases in OUTPUT_KEY_ALIASES.items():
        if key in aliases:
            return TokenClassification(
                token=key,
                category="output_key_alias",
                canonical=indicator_name,
                output_key=aliases[key],
            )
    if key in PARAMETER_ALIAS_ACCESS:
        return TokenClassification(token=key, category="parameter_alias", reason=PARAMETER_ALIAS_ACCESS[key])
    instance = parse_parameterized_indicator_instance(key)
    if instance is not None:
        return TokenClassification(
            token=key,
            category="parameterized_indicator_instance",
            canonical=instance.name,
            params=dict(instance.params),
        )
    derived = parse_derived_feature(key)
    if derived is not None:
        return TokenClassification(
            token=key,
            category="derived_feature",
            canonical=derived.source,
            params=dict(derived.params),
            reason=derived.reason or ("supported" if derived.supported else "unsupported"),
        )
    if re.search(r"_(mask|entry|exit|signal|cond|condition|prev|raw|arr|data|value|values)$", key) or key.startswith("prev_"):
        return TokenClassification(token=key, category="local_variable_only", reason="builder local variable pattern")
    return TokenClassification(token=key, category="noise_or_comment_only", reason="not registered, aliased, parameterized, or supported derived")


__all__ = [
    "BUILDER_ACCESS_EXAMPLES",
    "DICT_INDICATOR_NAMES",
    "DICT_INDICATOR_OUTPUT_KEYS",
    "INDICATOR_ACCESS_ALIASES",
    "INDICATOR_PARAM_DEFAULTS",
    "INDICATOR_SCHEMAS",
    "INVALID_DICT_SUBKEY_REWRITE_HINTS",
    "MODEL_DEMAND_HINTS",
    "OUTPUT_KEY_ALIASES",
    "PARAMETER_ALIAS_ACCESS",
    "SAFE_DICT_INDICATOR_ASSIGNMENT_ALIASES",
    "SAFE_DICT_INDICATOR_KEYS",
    "SEMANTIC_INDICATOR_ALIASES",
    "STABLE_ALIAS_MAP",
    "DerivedFeatureSpec",
    "IndicatorInstance",
    "IndicatorSchema",
    "TokenClassification",
    "calculate_derived_feature",
    "canonical_indicator_name",
    "canonicalize_indicator_alias",
    "classify_indicator_token",
    "get_builder_access_example",
    "get_indicator_alias_hints",
    "get_indicator_calculation_function",
    "get_indicator_output_alias_hints",
    "get_indicator_schema",
    "get_output_key_alias",
    "get_stable_alias_map",
    "is_dict_indicator",
    "parse_derived_feature",
    "parse_parameterized_indicator_instance",
]
