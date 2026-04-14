"""
Module-ID: agents.indicator_context

Purpose: Construire un contexte indicateurs (stratégie vs lecture seule) pour LLM.

Role in pipeline: orchestration support

Key components: build_indicator_context, DEFAULT_READ_ONLY_INDICATORS

Inputs: DataFrame OHLCV, stratégie, paramètres courants

Outputs: Dict avec sections texte + warnings

Dependencies: numpy, pandas, indicators.registry, strategies.*
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from indicators.registry import calculate_indicator
from strategies.base import get_strategy
from strategies.indicators_mapping import (
    get_internal_indicators,
    get_required_indicators,
)

INDICATOR_SELECTION_REFERENCE: Dict[str, Dict[str, str]] = {
    "adx": {
        "label": "Average Directional Index",
        "summary": "Trend-strength gauge. Best used to filter breakouts or trend systems and avoid weak/noisy ranges.",
        "formula": "ADX = smoothed average of directional movement strength from +DI and -DI.",
    },
    "amplitude_hunter": {
        "label": "Amplitude Hunter",
        "summary": "Measures expansion/contraction of recent candle amplitude to detect volatility bursts or compression releases.",
        "formula": "Amplitude score = rolling range or body expansion versus recent baseline.",
    },
    "aroon": {
        "label": "Aroon",
        "summary": "Shows how recently highs and lows occurred. Useful for early trend emergence and loss of trend freshness.",
        "formula": "Aroon Up/Down = 100 * (period - bars since high/low) / period.",
    },
    "atr": {
        "label": "Average True Range",
        "summary": "Pure volatility distance, not direction. Good for stops, filters, and volatility-normalized thresholds.",
        "formula": "ATR = moving average of True Range.",
    },
    "bollinger": {
        "label": "Bollinger Bands",
        "summary": "Mean-reversion or breakout envelope around price. Useful for stretch, squeeze, and band expansion logic.",
        "formula": "Middle = SMA; Upper/Lower = SMA ± k * standard deviation.",
    },
    "cci": {
        "label": "Commodity Channel Index",
        "summary": "Unbounded oscillator for deviation from typical price mean. Useful for pullback exhaustion and regime swings.",
        "formula": "CCI = (Typical Price - SMA(TP)) / (0.015 * Mean Deviation).",
    },
    "chaikin_oscillator": {
        "label": "Chaikin Oscillator",
        "summary": "Volume-flow momentum derived from accumulation/distribution. Useful for confirming buying or selling pressure.",
        "formula": "Chaikin = EMA(ADL, short) - EMA(ADL, long).",
    },
    "cmf": {
        "label": "Chaikin Money Flow",
        "summary": "Volume-weighted accumulation/distribution signal. Helps confirm whether volume supports the move.",
        "formula": "CMF = sum(Money Flow Volume, n) / sum(Volume, n).",
    },
    "cmo": {
        "label": "Chande Momentum Oscillator",
        "summary": "Momentum oscillator symmetric around zero. Useful when you want momentum without RSI-style bounded scaling.",
        "formula": "CMO = 100 * (sum gains - sum losses) / (sum gains + sum losses).",
    },
    "coppock_curve": {
        "label": "Coppock Curve",
        "summary": "Longer-horizon momentum blend, often used to detect major upturns after deep weakness.",
        "formula": "Coppock = WMA(ROC(long1) + ROC(long2), smooth).",
    },
    "directional_bias": {
        "label": "Directional Bias",
        "summary": "Context score combining bullish and bearish evidence. Best as a confirmation or veto layer, not a standalone trigger.",
        "formula": "Net bias = bull score - bear score from structure and imbalance components.",
    },
    "donchian": {
        "label": "Donchian Channels",
        "summary": "Breakout channel from recent highs and lows. Strong for trend-following entries and channel exits.",
        "formula": "Upper = rolling highest high; Lower = rolling lowest low.",
    },
    "dpo": {
        "label": "Detrended Price Oscillator",
        "summary": "Removes longer trend to emphasize shorter cycles. Useful for cyclical pullback timing.",
        "formula": "DPO = shifted price - SMA(period).",
    },
    "elder_ray": {
        "label": "Elder Ray",
        "summary": "Separates bull and bear power around an EMA. Useful to see which side dominates around the trend anchor.",
        "formula": "Bull power = high - EMA; Bear power = low - EMA.",
    },
    "ema": {
        "label": "Exponential Moving Average",
        "summary": "Trend and dynamic support/resistance baseline with more weight on recent prices.",
        "formula": "EMA_t = alpha * price_t + (1 - alpha) * EMA_(t-1).",
    },
    "eom": {
        "label": "Ease of Movement",
        "summary": "Measures how easily price moves relative to volume. Useful for volume-efficiency and thrust confirmation.",
        "formula": "EOM = midpoint move / box ratio(volume versus range).",
    },
    "fear_greed": {
        "label": "Fear and Greed Proxy",
        "summary": "Sentiment-style composite used as a contextual regime filter rather than a fast entry trigger.",
        "formula": "Composite score from normalized market stress and risk-on proxies.",
    },
    "fibonacci_levels": {
        "label": "Fibonacci Levels",
        "summary": "Static retracement/extension zones from a recent range. Good for pullback targets or invalidation zones.",
        "formula": "Levels = swing range multiplied by Fibonacci ratios such as 0.382, 0.5, 0.618.",
    },
    "fisher_transform": {
        "label": "Fisher Transform",
        "summary": "Transforms price into a sharper oscillator to highlight turning points more clearly.",
        "formula": "Fisher = 0.5 * ln((1 + x) / (1 - x)) on normalized price input.",
    },
    "force_index": {
        "label": "Force Index",
        "summary": "Combines price change and volume to measure directional conviction.",
        "formula": "Force Index = volume * (close_t - close_(t-1)).",
    },
    "fva": {
        "label": "Fair Value Area",
        "summary": "Marks value zones where price traded efficiently. Useful for mean reversion toward value or value rejection setups.",
        "formula": "Value area = statistically inferred acceptance zone around traded range and volume distribution.",
    },
    "fvg": {
        "label": "Fair Value Gap",
        "summary": "Detects price imbalances or gaps between candles. Useful for inefficiency fill, continuation, or rejection logic.",
        "formula": "Gap state = candles leave an untraded zone between prior high/low structure.",
    },
    "hma": {
        "label": "Hull Moving Average",
        "summary": "Fast-smoothed trend average with reduced lag. Useful when EMA feels too slow but noise still matters.",
        "formula": "HMA = WMA(2*WMA(price,n/2) - WMA(price,n), sqrt(n)).",
    },
    "ichimoku": {
        "label": "Ichimoku Cloud",
        "summary": "Multi-part trend, momentum, and support/resistance framework. Best for richer regime structure than a single MA.",
        "formula": "Tenkan/Kijun/Senkou lines built from midpoint highs-lows over multiple windows.",
    },
    "keltner": {
        "label": "Keltner Channel",
        "summary": "ATR-based envelope around an EMA. Useful for smoother breakout or trend pullback systems than Bollinger.",
        "formula": "Middle = EMA; Upper/Lower = EMA ± ATR * multiplier.",
    },
    "kst": {
        "label": "Know Sure Thing",
        "summary": "Multi-horizon momentum aggregate. Useful when one ROC is too narrow and you want broader cycle confirmation.",
        "formula": "KST = weighted sum of smoothed ROCs across several lookbacks.",
    },
    "kvo": {
        "label": "Klinger Volume Oscillator",
        "summary": "Volume-force oscillator meant to capture longer accumulation/distribution swings.",
        "formula": "KVO = EMA(volume force, short) - EMA(volume force, long).",
    },
    "macd": {
        "label": "Moving Average Convergence Divergence",
        "summary": "Classic trend-momentum crossover tool. Useful for continuation, acceleration, and cross confirmations.",
        "formula": "MACD = EMA(fast) - EMA(slow); Signal = EMA(MACD).",
    },
    "markov_switching": {
        "label": "Markov Switching Regime Filter",
        "summary": "Probabilistic regime detector. Best to gate trades by macro state probability, not as a fast standalone trigger.",
        "formula": "Hidden-state model estimates regime probabilities from observed return dynamics.",
    },
    "mass_index": {
        "label": "Mass Index",
        "summary": "Expansion/contraction detector focused on range bulges that can precede reversals.",
        "formula": "Mass Index = sum over EMA(range) / EMA(EMA(range)).",
    },
    "mfi": {
        "label": "Money Flow Index",
        "summary": "Volume-weighted RSI-style oscillator. Useful when you want overbought/oversold with volume confirmation.",
        "formula": "MFI = 100 - 100 / (1 + money flow ratio).",
    },
    "momentum": {
        "label": "Momentum",
        "summary": "Simple rate of price change over a lookback. Good for direct acceleration or deceleration filters.",
        "formula": "Momentum = close_t - close_(t-n).",
    },
    "obv": {
        "label": "On-Balance Volume",
        "summary": "Cumulative volume flow tied to price direction. Useful for confirming whether volume leads price.",
        "formula": "OBV_t = OBV_(t-1) ± volume depending on close direction.",
    },
    "onchain_smoothing": {
        "label": "On-chain Smoothing",
        "summary": "Smoothed proxy signal for slower structural participation or macro flow. More contextual than tactical.",
        "formula": "Smoothed aggregate of on-chain style flow inputs across a chosen window.",
    },
    "pi_cycle": {
        "label": "Pi Cycle",
        "summary": "Cycle-oriented moving-average relation often used for macro tops/bottoms rather than short-term entries.",
        "formula": "Pi-style signal compares specific moving averages with a fixed multiple relationship.",
    },
    "pivot_points": {
        "label": "Pivot Points",
        "summary": "Session-style support and resistance levels. Useful for breakout, rejection, and target placement logic.",
        "formula": "Pivot = (high + low + close) / 3; derived S/R levels from the pivot.",
    },
    "psar": {
        "label": "Parabolic SAR",
        "summary": "Trailing trend/reversal indicator. Useful as a stop logic or trend-following flip condition.",
        "formula": "SAR follows price with an accelerating factor as the trend extends.",
    },
    "roc": {
        "label": "Rate of Change",
        "summary": "Percentage momentum over a lookback. Good when you want normalized price speed rather than absolute delta.",
        "formula": "ROC = 100 * (close_t - close_(t-n)) / close_(t-n).",
    },
    "rsi": {
        "label": "Relative Strength Index",
        "summary": "Bounded momentum oscillator for overbought/oversold and momentum shifts.",
        "formula": "RSI = 100 - 100 / (1 + RS), where RS = avg gain / avg loss.",
    },
    "smart_legs": {
        "label": "Smart Legs",
        "summary": "Structure leg detector that tries to isolate directional impulsive moves. Useful for trend leg continuation filters.",
        "formula": "Leg state inferred from swing and imbalance structure transitions.",
    },
    "standard_deviation": {
        "label": "Standard Deviation",
        "summary": "Raw volatility dispersion measure. Useful for regime filters or volatility normalization.",
        "formula": "StdDev = sqrt(mean((x - mean(x))^2)).",
    },
    "stochastic": {
        "label": "Stochastic Oscillator",
        "summary": "Shows where close sits inside the recent range. Useful for pullback timing and exhaustion.",
        "formula": "%K = 100 * (close - lowest low) / (highest high - lowest low).",
    },
    "stoch_rsi": {
        "label": "Stochastic RSI",
        "summary": "Applies stochastic logic to RSI itself, making a faster and more sensitive momentum oscillator.",
        "formula": "Stoch RSI = (RSI - min RSI) / (max RSI - min RSI).",
    },
    "supertrend": {
        "label": "Supertrend",
        "summary": "Trend-following overlay with ATR-based trailing logic. Useful for direction filters and dynamic exits.",
        "formula": "Trend band = median price ± ATR * multiplier with directional flip rules.",
    },
    "swing": {
        "label": "Swing High/Low",
        "summary": "Local pivot structure detector. Useful for structure-based entries, invalidations, and stop placement.",
        "formula": "Swing point = local extremum relative to neighboring candles over a pivot window.",
    },
    "tma": {
        "label": "Triangular Moving Average",
        "summary": "Double-smoothed moving average for a calmer trend baseline.",
        "formula": "TMA = SMA(SMA(price, n), n).",
    },
    "tsi": {
        "label": "True Strength Index",
        "summary": "Double-smoothed momentum oscillator. Useful for cleaner trend-momentum confirmation than raw ROC.",
        "formula": "TSI = 100 * double-smoothed price change / double-smoothed abs(price change).",
    },
    "ultimate_oscillator": {
        "label": "Ultimate Oscillator",
        "summary": "Multi-window momentum oscillator meant to reduce false divergences.",
        "formula": "Weighted average of buying pressure / true range across 3 lookbacks.",
    },
    "volume_oscillator": {
        "label": "Volume Oscillator",
        "summary": "Measures whether short-term volume is above or below longer-term volume trend.",
        "formula": "Volume Osc = MA(volume, short) - MA(volume, long) or normalized version.",
    },
    "vortex": {
        "label": "Vortex Indicator",
        "summary": "Trend-direction tool built from positive and negative movement flows. Useful for directional confirmation.",
        "formula": "VI+ and VI- compare directional movement sums to true range sum.",
    },
    "vwap": {
        "label": "Volume Weighted Average Price",
        "summary": "Fair-price anchor weighted by volume. Useful for mean reversion and intraday value location.",
        "formula": "VWAP = cumulative(price * volume) / cumulative(volume).",
    },
    "williams_r": {
        "label": "Williams %R",
        "summary": "Range-position oscillator similar to stochastic, focused on overbought/oversold extremes.",
        "formula": "%R = -100 * (highest high - close) / (highest high - lowest low).",
    },
    "wma": {
        "label": "Weighted Moving Average",
        "summary": "Moving average that gives more weight to recent prices without exponential decay.",
        "formula": "WMA = sum(weight_i * price_i) / sum(weights).",
    },
}

_INDICATOR_SELECTION_STOPWORDS = {
    # EN
    "about",
    "above",
    "after",
    "against",
    "already",
    "around",
    "because",
    "below",
    "between",
    "change",
    "choose",
    "clear",
    "current",
    "diagnostic",
    "directly",
    "entry",
    "exit",
    "from",
    "good",
    "helps",
    "indicator",
    "indicators",
    "into",
    "just",
    "logic",
    "market",
    "more",
    "over",
    "only",
    "phase",
    "price",
    "propose",
    "recent",
    "rule",
    "same",
    "session",
    "should",
    "signal",
    "signals",
    "simple",
    "standalone",
    "strategy",
    "than",
    "that",
    "them",
    "these",
    "this",
    "through",
    "trade",
    "trades",
    "used",
    "using",
    "when",
    "with",
    # FR
    "aussi",
    "autre",
    "avant",
    "avec",
    "bien",
    "car",
    "cette",
    "ces",
    "chaque",
    "comme",
    "dans",
    "des",
    "doit",
    "donc",
    "elle",
    "encore",
    "entre",
    "est",
    "faire",
    "les",
    "lors",
    "mais",
    "même",
    "moins",
    "notre",
    "par",
    "plus",
    "pour",
    "prix",
    "propose",
    "quand",
    "qui",
    "sont",
    "sur",
    "tout",
    "tous",
    "une",
    "vers",
}

_INDICATOR_OBJECTIVE_HINTS = {
    # EN + FR keywords
    "breakout": ("breakout", "trend", "volatility", "cassure", "percée"),
    "cassure": ("breakout", "trend", "volatility", "cassure", "percée"),
    "pullback": ("pullback", "mean", "reversion", "repli", "correction"),
    "repli": ("pullback", "mean", "reversion", "repli", "correction"),
    "reversion": ("mean", "reversion", "oversold", "overbought", "retour", "moyenne"),
    "retour": ("mean", "reversion", "oversold", "overbought", "retour", "moyenne"),
    "reversal": ("reversal", "oversold", "overbought", "retournement", "inversion"),
    "retournement": ("reversal", "oversold", "overbought", "retournement", "inversion"),
    "inversion": ("reversal", "oversold", "overbought", "retournement", "inversion"),
    "momentum": ("momentum", "acceleration", "continuation", "élan", "impulsion"),
    "élan": ("momentum", "acceleration", "continuation", "élan", "impulsion"),
    "impulsion": ("momentum", "acceleration", "continuation", "élan", "impulsion"),
    "trend": ("trend", "breakout", "continuation", "tendance"),
    "tendance": ("trend", "breakout", "continuation", "tendance"),
    "volume": ("volume", "flow", "pressure", "flux", "pression"),
    "volatility": ("volatility", "squeeze", "expansion", "volatilité", "compression"),
    "volatilité": ("volatility", "squeeze", "expansion", "volatilité", "compression"),
    "regime": ("regime", "macro", "probability", "régime", "probabilité"),
    "régime": ("regime", "macro", "probability", "régime", "probabilité"),
    "structure": ("structure", "imbalance", "pivot", "déséquilibre"),
    "support": ("support", "resistance", "levels", "résistance", "niveaux"),
    "resistance": ("support", "resistance", "levels", "résistance", "niveaux"),
    "résistance": ("support", "resistance", "levels", "résistance", "niveaux"),
    "oversold": ("oversold", "mean", "reversion", "survendu"),
    "survendu": ("oversold", "mean", "reversion", "survendu"),
    "overbought": ("overbought", "mean", "reversion", "suracheté"),
    "suracheté": ("overbought", "mean", "reversion", "suracheté"),
    "range": ("range", "mean", "reversion", "canal", "latéral"),
    "canal": ("range", "mean", "reversion", "canal", "latéral"),
    "latéral": ("range", "mean", "reversion", "canal", "latéral"),
    "squeeze": ("squeeze", "volatility", "breakout", "compression"),
    "compression": ("squeeze", "volatility", "breakout", "compression"),
    "imbalance": ("imbalance", "structure", "gap", "déséquilibre"),
    "déséquilibre": ("imbalance", "structure", "gap", "déséquilibre"),
}

_DICT_INDICATOR_BUILDER_ACCESS: Dict[str, str] = {
    "adx": 'adx_d = indicators["adx"]; adx = np.nan_to_num(adx_d["adx"]); adx_val = adx',
    "amplitude_hunter": 'amp = indicators["amplitude_hunter"]; range_pct = np.nan_to_num(amp["range_pct"]); score = np.nan_to_num(amp["score"])',
    "aroon": 'ar = indicators["aroon"]; up = np.nan_to_num(ar["aroon_up"]); down = np.nan_to_num(ar["aroon_down"])',
    "bollinger": 'bb = indicators["bollinger"]; upper = np.nan_to_num(bb["upper"]); middle = np.nan_to_num(bb["middle"]); lower = np.nan_to_num(bb["lower"])',
    "directional_bias": 'bias = indicators["directional_bias"]; bull_score = np.nan_to_num(bias["bull_score"]); bear_score = np.nan_to_num(bias["bear_score"]); net_bias = np.nan_to_num(bias["net_bias"])',
    "donchian": 'dc = indicators["donchian"]; upper = np.nan_to_num(dc["upper"]); middle = np.nan_to_num(dc["middle"]); lower = np.nan_to_num(dc["lower"])',
    "fvg": 'fvg = indicators["fvg"]; bull_gap = np.nan_to_num(fvg["fvg_bullish"]).astype(bool)',
    "ichimoku": 'ich = indicators["ichimoku"]; tenkan = np.nan_to_num(ich["tenkan"]); kijun = np.nan_to_num(ich["kijun"])',
    "keltner": 'kelt = indicators["keltner"]; upper = np.nan_to_num(kelt["upper"]); lower = np.nan_to_num(kelt["lower"])',
    "macd": 'macd_d = indicators["macd"]; macd_line = np.nan_to_num(macd_d["macd"]); signal = np.nan_to_num(macd_d["signal"])',
    "markov_switching": 'mk = indicators["markov_switching"]; regime = np.nan_to_num(mk["regime"]); bull_prob = np.nan_to_num(mk["prob_regime_0"])',
    "pivot_points": 'pp = indicators["pivot_points"]; pivot = np.nan_to_num(pp["pivot"]); r1 = np.nan_to_num(pp["r1"])',
    "psar": 'psar_d = indicators["psar"]; sar = np.nan_to_num(psar_d["sar"])',
    "smart_legs": 'legs = indicators["smart_legs"]; bull_leg = np.nan_to_num(legs["smart_leg_bullish"]).astype(bool)',
    "stochastic": 'stoch = indicators["stochastic"]; k = np.nan_to_num(stoch["stoch_k"]); d = np.nan_to_num(stoch["stoch_d"])',
    "stoch_rsi": 'srsi = indicators["stoch_rsi"]; k = np.nan_to_num(srsi["k"]); d = np.nan_to_num(srsi["d"])',
    "supertrend": 'st = indicators["supertrend"]; st_direction = np.nan_to_num(st["direction"]); direction = st_direction',
    "swing": 'sw = indicators["swing"]; swing_low = np.nan_to_num(sw["swing_low"]).astype(bool)',
    "vortex": 'vx = indicators["vortex"]; vip = np.nan_to_num(vx["vi_plus"]); vin = np.nan_to_num(vx["vi_minus"])',
}

_DICT_INDICATOR_STABLE_ALIAS_MAP: Dict[str, Dict[str, str]] = {
    "adx": {"adx_d": "adx_data", "adx": "adx_value", "adx_val": "adx_value"},
    "amplitude_hunter": {
        "amp": "amplitude_hunter_data",
        "range_pct": "amplitude_hunter_range_pct",
        "score": "amplitude_hunter_score",
    },
    "aroon": {"ar": "aroon_data", "up": "aroon_up", "down": "aroon_down"},
    "bollinger": {"bb": "bollinger_data", "upper": "bollinger_upper", "middle": "bollinger_middle", "lower": "bollinger_lower"},
    "directional_bias": {
        "bias": "directional_bias_data",
        "bull_score": "directional_bias_bull_score",
        "bear_score": "directional_bias_bear_score",
        "net_bias": "directional_bias_net",
    },
    "donchian": {"dc": "donchian_data", "upper": "donchian_upper", "middle": "donchian_middle", "lower": "donchian_lower"},
    "fvg": {"fvg": "fvg_data", "bull_gap": "fvg_bullish_gap"},
    "ichimoku": {"ich": "ichimoku_data", "tenkan": "ichimoku_tenkan", "kijun": "ichimoku_kijun"},
    "keltner": {"kelt": "keltner_data", "upper": "keltner_upper", "lower": "keltner_lower"},
    "macd": {"macd_d": "macd_data", "macd_line": "macd_line", "signal": "macd_signal"},
    "markov_switching": {"mk": "markov_data", "regime": "markov_regime", "bull_prob": "markov_bull_probability"},
    "pivot_points": {"pp": "pivot_points_data", "pivot": "pivot_points_pivot", "r1": "pivot_points_r1"},
    "psar": {"psar_d": "psar_data", "sar": "psar_sar"},
    "smart_legs": {"legs": "smart_legs_data", "bull_leg": "smart_legs_bull_leg"},
    "stochastic": {"stoch": "stochastic_data", "k": "stochastic_k", "d": "stochastic_d"},
    "stoch_rsi": {"srsi": "stoch_rsi_data", "k": "stoch_rsi_k", "d": "stoch_rsi_d"},
    "supertrend": {"st": "supertrend_data", "st_direction": "supertrend_direction", "direction": "supertrend_direction"},
    "swing": {"sw": "swing_data", "swing_low": "swing_low_flag"},
    "vortex": {"vx": "vortex_data", "vip": "vortex_vi_plus", "vin": "vortex_vi_minus"},
}


def _default_indicator_builder_access(indicator_name: str) -> str:
    key = str(indicator_name or "").strip().lower()
    if not key:
        return 'value = np.nan_to_num(indicators["indicator_name"])'
    return f'value = np.nan_to_num(indicators["{key}"])'


def _populate_indicator_reference_builder_access() -> None:
    """Injecte un exemple Builder dans chaque fiche indicateur centrale."""
    for indicator_name, meta in INDICATOR_SELECTION_REFERENCE.items():
        if not isinstance(meta, dict):
            continue
        meta.setdefault(
            "builder_access",
            _DICT_INDICATOR_BUILDER_ACCESS.get(
                indicator_name,
                _default_indicator_builder_access(indicator_name),
            ),
        )


_populate_indicator_reference_builder_access()

_INDICATOR_DIRECT_MATCH_BONUS = 6.0
_INDICATOR_DIAGNOSTIC_MATCH_BONUS = 3.0
_INDICATOR_PREVIOUS_DIVERSITY_PENALTY = 0.30
_INDICATOR_PREVIOUS_STABILITY_BONUS = 0.03
_INDICATOR_NOVELTY_BONUS = 0.40
_INDICATOR_NOISE_WEIGHT = 0.12
_INDICATOR_BASELINE_UTILITY_BONUS = 0.05

# Mapping indicateur → famille (chargé paresseusement, partagé en mémoire)
_INDICATOR_FAMILY_MAP_CACHE: Optional[Dict[str, str]] = None


def _get_indicator_family_map() -> Dict[str, str]:
    """Retourne le mapping indicateur→famille (construit une seule fois par processus)."""
    global _INDICATOR_FAMILY_MAP_CACHE
    if _INDICATOR_FAMILY_MAP_CACHE is None:
        try:
            from config.indicator_history import build_indicator_to_family_map
            _INDICATOR_FAMILY_MAP_CACHE = build_indicator_to_family_map()
        except Exception:
            _INDICATOR_FAMILY_MAP_CACHE = {}
    return _INDICATOR_FAMILY_MAP_CACHE


def _tokenize_indicator_selection_text(*texts: Any) -> set[str]:
    tokens: set[str] = set()
    for text in texts:
        raw = str(text or "").lower().replace("_", " ")
        for token in re.findall(r"[a-z0-9]+", raw):
            if len(token) < 3:
                continue
            if token in _INDICATOR_SELECTION_STOPWORDS:
                continue
            tokens.add(token)
    return tokens


def _build_indicator_query_tokens(
    objective: str = "",
    diagnostic: Optional[Dict[str, Any]] = None,
) -> set[str]:
    diagnostic = diagnostic or {}
    tokens = _tokenize_indicator_selection_text(
        objective,
        diagnostic.get("category", ""),
        diagnostic.get("summary", ""),
        diagnostic.get("severity", ""),
        diagnostic.get("change_type", ""),
    )

    expanded = set(tokens)
    for token in list(tokens):
        for hint in _INDICATOR_OBJECTIVE_HINTS.get(token, ()):
            expanded.add(hint)
    return expanded


def _indicator_reference_tokens(indicator_name: str) -> set[str]:
    meta = INDICATOR_SELECTION_REFERENCE.get(indicator_name.lower(), {})
    return _tokenize_indicator_selection_text(
        indicator_name,
        meta.get("label", ""),
        meta.get("summary", ""),
        meta.get("formula", ""),
    )


def _stable_indicator_order_noise(session_seed: str, indicator_name: str) -> float:
    payload = f"{session_seed}|{indicator_name}".encode("utf-8", errors="ignore")
    digest = hashlib.sha256(payload).hexdigest()
    return int(digest[:12], 16) / float(16 ** 12)


def get_indicator_builder_access_example(indicator_name: str) -> str:
    """Retourne un exemple d'acces compatible Builder/moteur pour un indicateur."""
    key = str(indicator_name or "").strip().lower()
    if not key:
        return 'value = np.nan_to_num(indicators["indicator_name"])'
    meta = INDICATOR_SELECTION_REFERENCE.get(key, {})
    builder_access = str(meta.get("builder_access", "") or "").strip()
    if builder_access:
        return builder_access
    if key in _DICT_INDICATOR_BUILDER_ACCESS:
        return _DICT_INDICATOR_BUILDER_ACCESS[key]
    return _default_indicator_builder_access(key)


def get_indicator_builder_stable_alias_map(indicator_name: str) -> Dict[str, str]:
    """Retourne les alias stables preferes pour un indicateur Builder."""
    key = str(indicator_name or "").strip().lower()
    alias_map = _DICT_INDICATOR_STABLE_ALIAS_MAP.get(key, {})
    if not isinstance(alias_map, dict):
        return {}
    return {
        str(short_name): str(stable_name)
        for short_name, stable_name in alias_map.items()
        if str(short_name).strip() and str(stable_name).strip()
    }


def rank_indicator_selection(
    available_indicators: Iterable[str],
    *,
    objective: str = "",
    diagnostic: Optional[Dict[str, Any]] = None,
    previous_indicators: Optional[Iterable[str]] = None,
    session_seed: str = "",
    prefer_diversity: bool = False,
    # ── Nouvelles options de diversité inter-sessions ──────────────────────
    banned_indicators: Optional[Iterable[str]] = None,
    previous_families: Optional[Iterable[str]] = None,
    family_penalty: float = 0.0,
    family_bonus: float = 0.0,
    inter_session_penalty: float = 0.0,
    inter_session_novelty_bonus: float = 0.0,
    inter_session_indicators: Optional[Iterable[str]] = None,
) -> List[str]:
    """Classe les indicateurs pour le prompt Builder.

    Le classement combine deux contraintes liées :
    - ordre pseudo-aléatoire mais stable pour une session donnée ;
    - biais de pertinence vis-à-vis de l'objectif et du diagnostic courant.

    Important : cette fonction ne retire jamais d'indicateur, ne maintient aucune
    mémoire punitive entre sessions, et n'utilise pas les performances passées pour
    "condamner" un indicateur (sauf via les arguments optionnels ci-dessous).
    Les ajustements de diversité restent conservateurs.

    Args supplémentaires (diversité inter-sessions) :
        banned_indicators: Indicateurs à filtrer complètement de la liste.
        previous_families: Familles récemment utilisées — leurs indicateurs
            reçoivent un malus ``family_penalty``.
        family_penalty: Malus appliqué aux indicateurs appartenant à une
            famille de ``previous_families``.
        family_bonus: Bonus pour les indicateurs dans une famille non récente.
        inter_session_penalty: Malus appliqué aux indicateurs présents dans
            ``inter_session_indicators`` (historique inter-sessions).
        inter_session_novelty_bonus: Bonus accordé aux indicateurs absents
            de l'historique inter-sessions.
        inter_session_indicators: Indicateurs vus dans les runs précédents
            (passé depuis ``config.indicator_history``).
    """
    query_tokens = _build_indicator_query_tokens(objective, diagnostic)
    previous = {
        str(ind or "").strip().lower()
        for ind in (previous_indicators or [])
        if str(ind or "").strip()
    }
    banned = {
        str(ind or "").strip().lower()
        for ind in (banned_indicators or [])
        if str(ind or "").strip()
    }
    recent_families = {
        str(fam or "").strip().lower()
        for fam in (previous_families or [])
        if str(fam or "").strip()
    }
    inter_session = {
        str(ind or "").strip().lower()
        for ind in (inter_session_indicators or [])
        if str(ind or "").strip()
    }

    # Charger le mapping famille une seule fois si on a besoin des malus/bonus
    family_map: Dict[str, str] = (
        _get_indicator_family_map()
        if (recent_families or family_penalty or family_bonus)
        else {}
    )

    # Filtrer les indicateurs bannis
    normalized = [
        str(ind or "").strip()
        for ind in (available_indicators or [])
        if str(ind or "").strip() and str(ind or "").strip().lower() not in banned
    ]
    if not normalized:
        return []

    effective_seed = str(session_seed or objective or "builder-indicators")
    ranking: List[tuple[float, str]] = []

    for indicator_name in normalized:
        key = indicator_name.lower()
        indicator_tokens = _indicator_reference_tokens(key)
        relevance_score = float(len(query_tokens & indicator_tokens))

        objective_lower = str(objective or "").lower()
        summary_lower = str((diagnostic or {}).get("summary", "") or "").lower()
        if key in objective_lower:
            relevance_score += _INDICATOR_DIRECT_MATCH_BONUS
        if key in summary_lower:
            relevance_score += _INDICATOR_DIAGNOSTIC_MATCH_BONUS

        # ── Pénalité/bonus intra-session (previous_indicators) ────────────
        if previous:
            if key in previous:
                relevance_score += (
                    -_INDICATOR_PREVIOUS_DIVERSITY_PENALTY
                    if prefer_diversity
                    else _INDICATOR_PREVIOUS_STABILITY_BONUS
                )
            elif prefer_diversity:
                relevance_score += _INDICATOR_NOVELTY_BONUS

        # ── Pénalité/bonus inter-sessions ─────────────────────────────────
        if inter_session:
            if key in inter_session:
                relevance_score -= inter_session_penalty
            elif inter_session_novelty_bonus:
                relevance_score += inter_session_novelty_bonus

        # ── Pénalité/bonus famille ─────────────────────────────────────────
        if family_map and (family_penalty or family_bonus):
            ind_family = family_map.get(key, "")
            if ind_family:
                if ind_family in recent_families and family_penalty:
                    relevance_score -= family_penalty
                elif ind_family not in recent_families and family_bonus:
                    relevance_score += family_bonus

        if key == "atr":
            relevance_score += _INDICATOR_BASELINE_UTILITY_BONUS

        noise = _stable_indicator_order_noise(effective_seed, key)
        composite_score = relevance_score + (_INDICATOR_NOISE_WEIGHT * noise)
        ranking.append((composite_score, indicator_name))

    ranking.sort(key=lambda item: (-item[0], item[1].lower()))
    return [indicator_name for _, indicator_name in ranking]


# Indicateurs contextuels (lecture seule). Modifiable côté code.
DEFAULT_READ_ONLY_INDICATORS: List[Tuple[str, Dict[str, Any]]] = [
    ("adx", {"period": 14}),
    ("atr", {"period": 14}),
    ("rsi", {"period": 14}),
    ("macd", {"fast_period": 12, "slow_period": 26, "signal_period": 9}),
    ("stochastic", {"k_period": 14, "d_period": 3, "smooth_k": 3}),
    ("stoch_rsi", {"rsi_period": 14, "stoch_period": 14, "k_smooth": 3, "d_smooth": 3, "oversold": 20, "overbought": 80}),
    ("cci", {"period": 20}),
    ("williams_r", {"period": 14}),
    ("momentum", {"period": 14}),
    ("roc", {"period": 12}),
    ("aroon", {"period": 14}),
    ("supertrend", {"atr_period": 10, "multiplier": 3.0}),
    ("vortex", {"period": 14, "threshold": 0.0}),
    ("psar", {"af_start": 0.02, "af_increment": 0.02, "af_max": 0.2}),
    ("ichimoku", {"tenkan_period": 9, "kijun_period": 26, "senkou_b_period": 52, "displacement": 26}),
    ("bollinger", {"period": 20, "std_dev": 2.0}),
    ("keltner", {"ema_period": 20, "atr_period": 10, "atr_multiplier": 2.0}),
    ("donchian", {"period": 20}),
    ("standard_deviation", {"period": 20}),
    ("vwap", {"period": 20}),
    ("obv", {}),
    ("mfi", {"period": 14}),
    ("volume_oscillator", {"short_period": 14, "long_period": 28, "method": "ema"}),
    ("amplitude_hunter", {"period": 20}),
    ("pivot_points", {"method": "classic"}),
    ("fibonacci_levels", {"period": 50}),
]

TUPLE_LABELS: Dict[str, Tuple[str, ...]] = {
    "bollinger": ("upper", "middle", "lower"),
    "stochastic": ("k", "d"),
}

DICT_KEY_ALIASES: Dict[str, str] = {
    "histogram": "hist",
}


def build_indicator_context(
    df: pd.DataFrame,
    strategy_name: str,
    params: Dict[str, Any],
    read_only_indicators: Optional[Iterable[Tuple[str, Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """
    Construit un contexte indicateurs séparé en:
    - strategy_indicators: indicateurs liés à la stratégie (modifiables via params)
    - read_only_indicators: indicateurs contexte (lecture seule)
    """
    warnings: List[str] = []

    # Strategy indicators
    strategy_lines: List[str] = []
    try:
        strategy_cls = get_strategy(strategy_name)
        strategy = strategy_cls()
    except Exception as exc:
        return {
            "strategy": "",
            "read_only": "",
            "warnings": [f"Impossible de charger la stratégie '{strategy_name}': {exc}"],
        }

    try:
        required = get_required_indicators(strategy_name)
        internal = get_internal_indicators(strategy_name)
    except Exception:
        required = list(getattr(strategy, "required_indicators", []) or [])
        internal = []

    strategy_indicators = list(dict.fromkeys(required + internal))

    for indicator_name in strategy_indicators:
        strategy_lines.extend(
            _summarize_indicator(
                df=df,
                indicator_name=indicator_name,
                params=params,
                strategy=strategy,
                warnings=warnings,
                is_strategy=True,
            )
        )

    # Read-only indicators
    read_only_lines: List[str] = []
    ro_specs = list(read_only_indicators) if read_only_indicators else list(DEFAULT_READ_ONLY_INDICATORS)

    for indicator_name, indicator_params in ro_specs:
        # Eviter doublons si deja present en strategie
        if indicator_name in strategy_indicators:
            continue
        read_only_lines.extend(
            _summarize_indicator(
                df=df,
                indicator_name=indicator_name,
                params=indicator_params,
                strategy=None,
                warnings=warnings,
                is_strategy=False,
            )
        )

    return {
        "strategy": "\n".join(strategy_lines).strip(),
        "read_only": "\n".join(read_only_lines).strip(),
        "warnings": warnings,
    }


def build_indicator_selection_guide(
    available_indicators: Iterable[str],
) -> List[str]:
    """Retourne un guide compact pour aider le LLM a choisir les indicateurs.

    Chaque ligne expose l'abreviation, le nom complet, l'usage principal et un
    rappel de formule ou de mecanique, afin d'eviter un prompt limite a une
    simple liste de noms.
    """
    guide_lines: List[str] = []
    seen: set[str] = set()

    for indicator_name in available_indicators or []:
        raw_name = str(indicator_name or "").strip()
        if not raw_name:
            continue
        key = raw_name.lower()
        if key in seen:
            continue
        seen.add(key)
        meta = INDICATOR_SELECTION_REFERENCE.get(key)
        if meta is None:
            pretty_name = raw_name.replace("_", " ").title()
            guide_lines.append(
                f"- {raw_name}: {pretty_name}. Use only if its mechanics clearly fit the hypothesis; inspect name semantics before choosing. Builder access: {get_indicator_builder_access_example(raw_name)}"
            )
            continue

        guide_lines.append(
            f"- {raw_name} ({meta['label']}): {meta['summary']} Formula/mnemonic: {meta['formula']} Builder access: {get_indicator_builder_access_example(raw_name)} Preferred stable aliases: "
            + ", ".join(
                f"{short_name}->{stable_name}"
                for short_name, stable_name in get_indicator_builder_stable_alias_map(raw_name).items()
            )
        )

    return guide_lines


def _summarize_indicator(
    df: pd.DataFrame,
    indicator_name: str,
    params: Dict[str, Any],
    strategy: Any,
    warnings: List[str],
    is_strategy: bool,
) -> List[str]:
    lines: List[str] = []

    # Parametrage base
    indicator_params: Dict[str, Any] = {}
    if is_strategy and strategy is not None:
        try:
            indicator_params = strategy.get_indicator_params(indicator_name, params)
        except Exception:
            indicator_params = {}
    else:
        indicator_params = dict(params or {})

    # Heuristiques EMA/SMA internes (fast/slow)
    if indicator_name in ("ema", "sma") and not indicator_params:
        fast = _first_param(params, ["fast_period", "fast"])
        slow = _first_param(params, ["slow_period", "slow"])
        if fast is not None:
            lines.extend(
                _summarize_single_indicator(
                    df, indicator_name, {"period": int(fast)}, f"{indicator_name}_fast", warnings
                )
            )
        if slow is not None:
            lines.extend(
                _summarize_single_indicator(
                    df, indicator_name, {"period": int(slow)}, f"{indicator_name}_slow", warnings
                )
            )
        if lines:
            return lines

    return _summarize_single_indicator(
        df, indicator_name, indicator_params, indicator_name, warnings
    )


def _summarize_single_indicator(
    df: pd.DataFrame,
    indicator_name: str,
    params: Dict[str, Any],
    label_name: str,
    warnings: List[str],
) -> List[str]:
    try:
        result = calculate_indicator(indicator_name, df, params)
    except Exception as exc:
        warnings.append(f"{indicator_name}: {exc}")
        return []

    label = _format_indicator_label(label_name, params)

    if result is None:
        return [f"- {label}: N/A"]

    if isinstance(result, dict):
        parts = []
        for key, values in result.items():
            last = _last_valid_value(values)
            if last is not None:
                key_label = DICT_KEY_ALIASES.get(key, key)
                parts.append(f"{key_label}={_fmt(last)}")
        if parts:
            return [f"- {label}: " + ", ".join(parts)]
        return [f"- {label}: N/A"]

    if isinstance(result, tuple):
        parts = []
        key_labels = TUPLE_LABELS.get(indicator_name, tuple(f"v{i}" for i in range(len(result))))
        for key, values in zip(key_labels, result):
            last = _last_valid_value(values)
            if last is not None:
                parts.append(f"{key}={_fmt(last)}")
        if parts:
            return [f"- {label}: " + ", ".join(parts)]
        return [f"- {label}: N/A"]

    stats = _series_stats(result)
    if not stats:
        return [f"- {label}: N/A"]

    return [
        "- "
        + f"{label}: last={_fmt(stats['last'])}, "
        + f"mean={_fmt(stats['mean'])}, "
        + f"min={_fmt(stats['min'])}, "
        + f"max={_fmt(stats['max'])}"
    ]


def _series_stats(values: Any) -> Optional[Dict[str, float]]:
    arr = _to_array(values)
    if arr is None or arr.size == 0:
        return None

    mask = np.isfinite(arr)
    if not mask.any():
        return None

    arr_valid = arr[mask]
    last = arr_valid[-1]

    return {
        "last": float(last),
        "mean": float(np.mean(arr_valid)),
        "min": float(np.min(arr_valid)),
        "max": float(np.max(arr_valid)),
    }


def _last_valid_value(values: Any) -> Optional[float]:
    arr = _to_array(values)
    if arr is None or arr.size == 0:
        return None
    mask = np.isfinite(arr)
    if not mask.any():
        return None
    return float(arr[mask][-1])


def _to_array(values: Any) -> Optional[np.ndarray]:
    if values is None:
        return None
    if isinstance(values, pd.Series):
        arr = values.values
    else:
        arr = np.asarray(values)
    if arr.ndim != 1:
        arr = arr.reshape(-1)
    return arr.astype("float64", copy=False)


def _format_indicator_label(name: str, params: Dict[str, Any]) -> str:
    if not params:
        return name
    parts = []
    for key in sorted(params.keys()):
        val = params[key]
        parts.append(f"{key}={_fmt(val)}")
    return f"{name}(" + ", ".join(parts) + ")"


def _fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    try:
        val = float(value)
    except Exception:
        return str(value)
    return f"{val:.4f}"


def _first_param(params: Dict[str, Any], keys: Iterable[str]) -> Optional[float]:
    for key in keys:
        if key in params:
            try:
                return float(params[key])
            except Exception:
                return None
    return None
