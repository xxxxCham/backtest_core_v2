"""
Module-ID: indicators.registry

Purpose: Registre centralisé des indicateurs pour calcul + mapping unifié.

Role in pipeline: core

Key components: IndicatorRegistry, register_indicator, calculate_indicator, get_indicator

Inputs: Nom indicateur, DataFrame OHLCV, paramètres

Outputs: Résultats indicateur (np.ndarray ou Dict)

Dependencies: Tous les modules indicators, pandas, numpy

Conventions: Registry singleton; API uniforme calculate_indicator(name, df, **params); fallback type checking.

Read-if: Ajout indicateur, modification API registre.

Skip-if: Vous appelez juste calculate_indicator().
"""

import os
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable, Dict, Optional, Tuple

import pandas as pd

# Cache du flag INDICATOR_CACHE_ENABLED au niveau module
# Évite os.getenv() à chaque appel calculate_indicator() (~10µs/appel sur Windows)
_CACHE_ENABLED = os.getenv("INDICATOR_CACHE_ENABLED", "1").strip() in (
    "1", "true", "yes", "on"
)

# Cache disque pour éviter recalculs répétés
from data.indicator_bank import get_indicator_bank

from .adx import adx, calculate_adx
from .aroon import AroonSettings, aroon
from .atr import ATRSettings, atr

# Imports relatifs des indicateurs
from .bollinger import BollingerSettings, bollinger_bands
from .cci import CCISettings, cci
from .donchian import DonchianSettings, donchian_channel
from .ema import EMASettings, ema, sma
from .keltner import KeltnerSettings, keltner_channel
from .macd import calculate_macd, macd
from .mfi import MFISettings, mfi
from .momentum import MomentumSettings, momentum
from .obv import OBVSettings, obv
from .roc import ROCSettings, roc
from .rsi import RSISettings, rsi
from .stochastic import stochastic
from .supertrend import SuperTrendSettings, supertrend

# Nouveaux indicateurs
from .vwap import VWAPSettings, vwap
from .williams_r import WilliamsRSettings, williams_r

_GPU_CALC = None
_GPU_QUEUES = None  # Conservé pour compatibilité (CPU-only)


def set_gpu_queues(request_queue, response_queue):
    """
    Configure les queues (compatibilité, GPU désactivé).

    Args:
        request_queue: multiprocessing.Queue
        response_queue: multiprocessing.Queue
    """
    global _GPU_QUEUES
    _GPU_QUEUES = (request_queue, response_queue)


def get_gpu_queues():
    """Retourne les queues configurées ou None."""
    return _GPU_QUEUES


def _gpu_enabled() -> bool:
    """
    Mode CPU-only: GPU toujours désactivé.
    """
    return False


def _get_gpu_calc():
    """
    Mode CPU-only: pas de calculateur GPU.
    """
    global _GPU_CALC
    _GPU_CALC = None
    return None


def _should_use_gpu(_calc, _n_samples: int) -> bool:
    return False


@dataclass
class IndicatorInfo:
    """Métadonnées d'un indicateur."""

    name: str
    function: Callable
    settings_class: Optional[type]
    required_columns: Tuple[str, ...]
    description: str


# Registre global des indicateurs
_INDICATOR_REGISTRY: Dict[str, IndicatorInfo] = {}


def register_indicator(
    name: str,
    function: Callable,
    settings_class: Optional[type] = None,
    required_columns: Tuple[str, ...] = ("close",),
    description: str = ""
) -> None:
    """Enregistre un nouvel indicateur."""
    _INDICATOR_REGISTRY[name.lower()] = IndicatorInfo(
        name=name,
        function=function,
        settings_class=settings_class,
        required_columns=required_columns,
        description=description
    )


def get_indicator(name: str) -> Optional[IndicatorInfo]:
    """Récupère les infos d'un indicateur."""
    return _INDICATOR_REGISTRY.get(name.lower())


def list_indicators() -> list[str]:
    """Liste tous les indicateurs disponibles."""
    return list(_INDICATOR_REGISTRY.keys())


def calculate_indicator(
    name: str,
    df: pd.DataFrame,
    params: Optional[Dict[str, Any]] = None,
    gpu_queues: Optional[tuple] = None
) -> Any:
    """
    Calcule un indicateur par son nom avec cache intelligent (CPU-only).

    Args:
        name: Nom de l'indicateur (bollinger, atr, rsi, ema, sma)
        df: DataFrame OHLCV
        params: Paramètres de l'indicateur
        gpu_queues: Ignoré en mode CPU-only

    Returns:
        Résultat du calcul (array ou tuple selon indicateur)

    Raises:
        ValueError: Si indicateur inconnu ou colonnes manquantes
    """
    name = name.lower()
    info = get_indicator(name)

    if info is None:
        available = ", ".join(list_indicators())
        raise ValueError(f"Indicateur inconnu: '{name}'. Disponibles: {available}")

    # Vérifier colonnes requises
    missing = [col for col in info.required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes pour {name}: {missing}")

    # Préparer les arguments
    params = params or {}

    # ═══════════════════════════════════════════════════════════════════════════
    # CACHE INTELLIGENT - Évite recalculs répétés (100→3 runs/sec FIX)
    # ═══════════════════════════════════════════════════════════════════════════
    # Vérifier si cache activé (résultat caché au niveau module pour éviter
    # os.getenv() à chaque appel — coûteux sur Windows: ~10µs/appel)
    cache_enabled = _CACHE_ENABLED

    backend = "cpu"

    data_hash = None
    if cache_enabled:
        try:
            bank = get_indicator_bank()

            # Réutiliser un hash de données stable (évite recalcul O(n) à chaque indicateur)
            try:
                data_hash = df.attrs.get("_indicator_data_hash")
            except Exception:
                data_hash = None
            if not data_hash:
                data_hash = bank.get_data_hash(df)
                try:
                    df.attrs["_indicator_data_hash"] = data_hash
                except Exception:
                    pass

            # Déterminer le backend (CPU) pour clé de cache correcte
            # Vérifier cache
            cached_result = bank.get(name, params, df, data_hash=data_hash, backend=backend)
            if cached_result is not None:
                return cached_result
        except Exception:
            # Si cache fail, continuer sans (degraded mode)
            pass

    # ═══════════════════════════════════════════════════════════════════════════
    # CALCUL DE L'INDICATEUR (ou récupération depuis cache ci-dessus)
    # ═══════════════════════════════════════════════════════════════════════════
    # Calculer le résultat (sera mis en cache ensuite)
    result = None

    if name == "bollinger":
        period = int(params.get("period", 20))
        std_dev = float(params.get("std_dev", 2.0))
        upper, middle, lower = bollinger_bands(
            df["close"],
            period=period,
            std_dev=std_dev
        )
        result = {"upper": upper, "middle": middle, "lower": lower}

    elif name == "atr":
        period = int(params.get("period", 14))
        result = atr(
            df["high"],
            df["low"],
            df["close"],
            period=period,
            method=params.get("method", "ema")
        )

    elif name == "rsi":
        period = int(params.get("period", 14))
        result = rsi(
            df["close"],
            period=period
        )

    elif name == "ema":
        period = int(params.get("period", 20))
        result = ema(
            df["close"],
            period=period
        )

    elif name == "sma":
        period = int(params.get("period", 20))
        result = sma(
            df["close"],
            period=period
        )

    elif name == "macd":
        fast_period = int(params.get("fast_period", 12))
        slow_period = int(params.get("slow_period", 26))
        signal_period = int(params.get("signal_period", 9))
        macd_line, signal_line, histogram = macd(
            df["close"],
            fast_period=fast_period,
            slow_period=slow_period,
            signal_period=signal_period
        )
        result = {"macd": macd_line, "signal": signal_line, "histogram": histogram}

    elif name == "adx":
        adx_val, plus_di, minus_di = adx(
            df["high"],
            df["low"],
            df["close"],
            period=int(params.get("period", 14))
        )
        result = {"adx": adx_val, "plus_di": plus_di, "minus_di": minus_di}

    elif name == "stochastic":
        stoch_k, stoch_d = stochastic(
            df["high"],
            df["low"],
            df["close"],
            k_period=int(params.get("k_period", 14)),
            d_period=int(params.get("d_period", 3)),
            smooth_k=int(params.get("smooth_k", 3))
        )
        result = {"stoch_k": stoch_k, "stoch_d": stoch_d}

    elif name == "vwap":
        result = vwap(
            df["high"], df["low"], df["close"], df["volume"],
            period=params.get("period", None)
        )

    elif name == "donchian":
        upper, middle, lower = donchian_channel(
            df["high"], df["low"],
            period=int(params.get("period", 20))
        )
        result = {"upper": upper, "middle": middle, "lower": lower}

    elif name == "cci":
        result = cci(
            df["high"], df["low"], df["close"],
            period=int(params.get("period", 20))
        )

    elif name == "keltner":
        middle, upper, lower = keltner_channel(
            df["high"], df["low"], df["close"],
            ema_period=int(params.get("ema_period", 20)),
            atr_period=int(params.get("atr_period", 10)),
            atr_multiplier=float(params.get("atr_multiplier", 2.0))
        )
        result = {"middle": middle, "upper": upper, "lower": lower}

    elif name == "mfi":
        result = mfi(
            df["high"], df["low"], df["close"], df["volume"],
            period=int(params.get("period", 14))
        )

    elif name == "williams_r":
        result = williams_r(
            df["high"], df["low"], df["close"],
            period=int(params.get("period", 14))
        )

    elif name == "momentum":
        result = momentum(
            df["close"],
            period=int(params.get("period", 14))
        )

    elif name == "obv":
        result = obv(df["close"], df["volume"])

    elif name == "roc":
        result = roc(
            df["close"],
            period=int(params.get("period", 12))
        )

    elif name == "aroon":
        aroon_up, aroon_down = aroon(
            df["high"], df["low"],
            period=int(params.get("period", 14))
        )
        result = {"aroon_up": aroon_up, "aroon_down": aroon_down}

    elif name == "supertrend":
        st_values, st_direction = supertrend(
            df["high"], df["low"], df["close"],
            atr_period=int(params.get("atr_period", 10)),
            multiplier=float(params.get("multiplier", 3.0))
        )
        result = {"supertrend": st_values, "direction": st_direction}

    else:
        # Appel générique
        result = info.function(df, **params)

    # ═══════════════════════════════════════════════════════════════════════════
    # MISE EN CACHE DU RÉSULTAT pour réutilisation (restaure 100 runs/sec!)
    # ═══════════════════════════════════════════════════════════════════════════
    if cache_enabled and result is not None:
        try:
            bank = get_indicator_bank()
            if not data_hash:
                try:
                    data_hash = df.attrs.get("_indicator_data_hash")
                except Exception:
                    data_hash = None
            if not data_hash:
                data_hash = bank.get_data_hash(df)
                try:
                    df.attrs["_indicator_data_hash"] = data_hash
                except Exception:
                    pass
            bank.put(name, params, df, result, data_hash=data_hash, backend=backend)
        except Exception:
            # Erreur cache non bloquante (degraded mode)
            pass

    return result


# Enregistrement des indicateurs de base
register_indicator(
    name="bollinger",
    function=bollinger_bands,
    settings_class=BollingerSettings,
    required_columns=("close",),
    description="Bandes de Bollinger - Mean reversion indicator"
)

register_indicator(
    name="atr",
    function=atr,
    settings_class=ATRSettings,
    required_columns=("high", "low", "close"),
    description="Average True Range - Volatility indicator"
)

register_indicator(
    name="rsi",
    function=rsi,
    settings_class=RSISettings,
    required_columns=("close",),
    description="Relative Strength Index - Momentum oscillator"
)

register_indicator(
    name="ema",
    function=ema,
    settings_class=EMASettings,
    required_columns=("close",),
    description="Exponential Moving Average"
)

register_indicator(
    name="sma",
    function=sma,
    settings_class=None,
    required_columns=("close",),
    description="Simple Moving Average"
)

register_indicator(
    name="macd",
    function=calculate_macd,
    settings_class=None,
    required_columns=("close",),
    description="Moving Average Convergence Divergence - Momentum indicator"
)

register_indicator(
    name="adx",
    function=calculate_adx,
    settings_class=None,
    required_columns=("high", "low", "close"),
    description="Average Directional Index - Trend strength indicator"
)

register_indicator(
    name="stochastic",
    function=stochastic,
    settings_class=None,
    required_columns=("high", "low", "close"),
    description="Stochastic Oscillator - Momentum indicator for overbought/oversold"
)

# Nouveaux indicateurs

register_indicator(
    name="vwap",
    function=vwap,
    settings_class=VWAPSettings,
    required_columns=("high", "low", "close", "volume"),
    description="Volume Weighted Average Price"
)

register_indicator(
    name="donchian",
    function=donchian_channel,
    settings_class=DonchianSettings,
    required_columns=("high", "low"),
    description="Donchian Channel - Breakout indicator"
)

register_indicator(
    name="cci",
    function=cci,
    settings_class=CCISettings,
    required_columns=("high", "low", "close"),
    description="Commodity Channel Index - Momentum oscillator"
)

register_indicator(
    name="keltner",
    function=keltner_channel,
    settings_class=KeltnerSettings,
    required_columns=("high", "low", "close"),
    description="Keltner Channel - Volatility channel based on EMA and ATR"
)

register_indicator(
    name="mfi",
    function=mfi,
    settings_class=MFISettings,
    required_columns=("high", "low", "close", "volume"),
    description="Money Flow Index - Volume-weighted RSI"
)

register_indicator(
    name="williams_r",
    function=williams_r,
    settings_class=WilliamsRSettings,
    required_columns=("high", "low", "close"),
    description="Williams %R - Momentum oscillator"
)

register_indicator(
    name="momentum",
    function=momentum,
    settings_class=MomentumSettings,
    required_columns=("close",),
    description="Momentum - Absolute price change over period"
)

register_indicator(
    name="obv",
    function=obv,
    settings_class=OBVSettings,
    required_columns=("close", "volume"),
    description="On-Balance Volume - Cumulative volume flow"
)

register_indicator(
    name="roc",
    function=roc,
    settings_class=ROCSettings,
    required_columns=("close",),
    description="Rate of Change - Percentage price change"
)

register_indicator(
    name="aroon",
    function=aroon,
    settings_class=AroonSettings,
    required_columns=("high", "low"),
    description="Aroon Indicator - Trend identification"
)

register_indicator(
    name="supertrend",
    function=supertrend,
    settings_class=SuperTrendSettings,
    required_columns=("high", "low", "close"),
    description="SuperTrend - ATR-based trend follower"
)

# Late imports for indicators that self-register to avoid circular imports.
for _module_name in (
    "amplitude_hunter",
    "fear_greed",
    "fibonacci",
    "ichimoku",
    "onchain_smoothing",
    "pi_cycle",
    "pivot_points",
    "psar",
    "standard_deviation",
    "volume_oscillator",
    "vortex",
):
    import_module(f"{__package__}.{_module_name}")


class IndicatorRegistry:
    """
    Classe wrapper pour le registre d'indicateurs.

    Permet une utilisation orientée objet et potentiellement
    le caching des résultats dans le futur.
    """

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._cache_enabled = False

    def enable_cache(self) -> None:
        """Active le cache des calculs."""
        self._cache_enabled = True

    def disable_cache(self) -> None:
        """Désactive et vide le cache."""
        self._cache_enabled = False
        self._cache.clear()

    def clear_cache(self) -> None:
        """Vide le cache."""
        self._cache.clear()

    def calculate(
        self,
        name: str,
        df: pd.DataFrame,
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Calcule un indicateur, avec mise en cache optionnelle.
        """
        cache_key = f"{name}_{hash(df.index[0])}_{hash(df.index[-1])}_{str(params)}"

        if self._cache_enabled and cache_key in self._cache:
            return self._cache[cache_key]

        result = calculate_indicator(name, df, params)

        if self._cache_enabled:
            self._cache[cache_key] = result

        return result

    def calculate_multiple(
        self,
        df: pd.DataFrame,
        indicator_configs: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Calcule plusieurs indicateurs d'un coup.

        Args:
            df: DataFrame OHLCV
            indicator_configs: Dict {nom_indicateur: {params}}

        Returns:
            Dict {nom_indicateur: résultat}
        """
        results = {}
        for name, params in indicator_configs.items():
            results[name] = self.calculate(name, df, params)
        return results

    @staticmethod
    def list_available() -> list[str]:
        """Liste les indicateurs disponibles."""
        return list_indicators()

    @staticmethod
    def get_info(name: str) -> Optional[IndicatorInfo]:
        """Récupère les infos d'un indicateur."""
        return get_indicator(name)


__all__ = [
    "IndicatorRegistry",
    "calculate_indicator",
    "list_indicators",
    "register_indicator",
    "get_indicator"
]
