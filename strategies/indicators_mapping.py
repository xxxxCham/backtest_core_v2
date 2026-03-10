"""
Module-ID: strategies.indicators_mapping

Purpose: Mapping centralisé stratégies → indicateurs pour chargement automatique UI.

Role in pipeline: core / data

Key components: StrategyIndicatorsMapping, get_strategy_indicators, IndicatorRequirement

Inputs: Strategy name, configuration

Outputs: Dict[str, List[IndicatorRequirement]] (required + internal + all)

Dependencies: strategies.base, indicators.registry, dataclasses

Conventions: required_indicators chargés par moteur; internal_indicators calculés par strat; all_indicators = union complète.

Read-if: Ajout nouvelle stratégie/indicateur, modification deps.

Skip-if: Vous ne changez qu'une stratégie.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set


@dataclass
class StrategyIndicators:
    """Définition des indicateurs pour une stratégie."""

    name: str
    required_indicators: List[str]  # Chargés par le moteur
    internal_indicators: List[str]  # Calculés par la stratégie
    description: str
    ui_label: str = ""
    ui_indicators: List[str] = field(default_factory=list)

    @property
    def all_indicators(self) -> Set[str]:
        """Tous les indicateurs utilisés (requis + internes)."""
        return set(self.required_indicators + self.internal_indicators)

    def display_label(self) -> str:
        """Libelle d'affichage pour l'UI."""
        return self.ui_label or self.name

    def ui_indicator_list(self) -> List[str]:
        """Indicateurs affiches dans l'UI (ordre preserve)."""
        if self.ui_indicators:
            return list(self.ui_indicators)
        combined = self.required_indicators + self.internal_indicators
        return list(dict.fromkeys(combined))


# =============================================================================
# MAPPING COMPLET STRATÉGIES → INDICATEURS
# =============================================================================

STRATEGY_INDICATORS_MAP: Dict[str, StrategyIndicators] = {

    # 1. ATR Channel
    "atr_channel": StrategyIndicators(
        name="ATR Channel",
        ui_label="📏 ATR Channel (Breakout)",
        required_indicators=["atr", "ema"],
        # ATR pour canal, EMA fournie en externe
        internal_indicators=[],  # Canal calculé à partir de l'EMA + ATR
        description="Breakout sur canal ATR avec filtre EMA",
        ui_indicators=["atr_channel", "atr"],
    ),

    # 2. EMA Cross
    "ema_cross": StrategyIndicators(
        name="EMA Cross",
        ui_label="📈 EMA Crossover (Trend Following)",
        required_indicators=[],
        internal_indicators=["ema"],  # EMA rapide/lente calculées internement
        description="Croisement EMA simple (Golden/Death Cross)",
        ui_indicators=["ema"],
    ),

    # 2b. EMA RSI Regime
    "ema_rsi_regime": StrategyIndicators(
        name="EMA RSI Regime",
        ui_label="📈 EMA + RSI Regime",
        required_indicators=["rsi"],
        internal_indicators=["ema"],
        description="Trend-following EMA avec confirmation momentum RSI",
        ui_indicators=["ema", "rsi"],
    ),

    # 3. Bollinger ATR
    "bollinger_atr": StrategyIndicators(
        name="Bollinger ATR",
        ui_label="📉 Bollinger + ATR (Mean Reversion)",
        required_indicators=["bollinger", "atr"],
        internal_indicators=[],
        description="Mean-reversion Bollinger avec filtre volatilité ATR",
        ui_indicators=["bollinger", "atr"],
    ),

    # 3b. Bollinger Best Longe 3i (levels on band scale)
    "bollinger_best_longe_3i": StrategyIndicators(
        name="Bollinger Best Longe 3i",
        ui_label="📉 Bollinger Best Longe 3i (Levels)",
        required_indicators=["bollinger", "atr"],
        internal_indicators=[],
        description="Long-only Bollinger levels: entry 0.0-0.2, SL -0.8 to -0.3, TP 0.7-2.0",
        ui_indicators=["bollinger", "atr"],
    ),

    # 3c. Bollinger Best Short 3i (mirror levels)
    "bollinger_best_short_3i": StrategyIndicators(
        name="Bollinger Best Short 3i",
        ui_label="📉 Bollinger Best Short 3i (Mirror Levels)",
        required_indicators=["bollinger", "atr"],
        internal_indicators=[],
        description="Short-only Bollinger levels: entry 0.8-1.0, SL 1.3-1.8, TP 0.0-0.3",
        ui_indicators=["bollinger", "atr"],
    ),

    # 4. MACD Cross
    "macd_cross": StrategyIndicators(
        name="MACD Cross",
        ui_label="📊 MACD Crossover (Momentum)",
        required_indicators=["macd"],
        internal_indicators=[],
        description="Croisement MACD avec ligne signal",
        ui_indicators=["macd"],
    ),

    # 5. RSI Reversal
    "rsi_reversal": StrategyIndicators(
        name="RSI Reversal",
        ui_label="🔄 RSI Reversal (Mean Reversion)",
        required_indicators=["rsi"],
        internal_indicators=[],
        description="Mean-reversion sur niveaux RSI (survente/surachat)",
        ui_indicators=["rsi"],
    ),

    # 6. MA Crossover
    "ma_crossover": StrategyIndicators(
        name="MA Crossover",
        ui_label="📐 MA Crossover (SMA Trend)",
        required_indicators=[],
        internal_indicators=["sma"],
        description="Croisement SMA rapide/lente",
        ui_indicators=["ma"],
    ),

    # 7. EMA Stochastic Scalp
    "ema_stochastic_scalp": StrategyIndicators(
        name="EMA Stochastic Scalp",
        ui_label="⚡ EMA + Stochastic (Scalping)",
        required_indicators=["stochastic"],
        internal_indicators=["ema"],
        description="Scalping avec filtre EMA et timing Stochastic",
        ui_indicators=["ema", "stochastic"],
    ),

    # 8. Bollinger Dual
    "bollinger_dual": StrategyIndicators(
        name="Bollinger Dual",
        ui_label="📊 Bollinger Dual (Mean Reversion)",
        required_indicators=["bollinger"],
        internal_indicators=["sma", "ema"],
        description="Bollinger + franchissement MA",
        ui_indicators=["bollinger", "ma"],
    ),

    # 9. RSI Trend Filtered
    "rsi_trend_filtered": StrategyIndicators(
        name="RSI Trend Filtered",
        ui_label="🔄 RSI Trend Filtered (Mean Rev.)",
        required_indicators=["rsi"],
        internal_indicators=["ema"],
        description="RSI filtre par tendance EMA",
        ui_indicators=["rsi", "ema"],
    ),

    # 10. Scalp EMA+BB+RSI (Labs)
    "scalp_ema_bb_rsi_labs": StrategyIndicators(
        name="Scalp EMA+BB+RSI (Labs)",
        ui_label="🧪 Scalp EMA+BB+RSI (Labs)",
        required_indicators=["ema", "rsi", "bollinger", "atr"],
        internal_indicators=[],
        description="Labs: Scalp continuation pullback EMA + Bollinger + RSI cross (grid exploratoire)",
        ui_indicators=["ema", "rsi", "bollinger", "atr"],
    ),

    # 11. Scalping Bollinger + VWAP + ATR
    "scalping_bollinger_vwap_atr": StrategyIndicators(
        name="Scalping BB+VWAP+ATR",
        ui_label="⚡ Scalping BB + VWAP + ATR",
        required_indicators=["bollinger", "vwap", "atr"],
        internal_indicators=[],
        description="Scalping Bollinger filtré VWAP avec stop/TP basés sur ATR",
        ui_indicators=["bollinger", "vwap", "atr"],
    ),

    # 12. Scalp EMA RSI Pullback
    "scalp_ema_rsi_pullback": StrategyIndicators(
        name="Scalp EMA RSI Pullback",
        ui_label="⚡ Scalp EMA RSI Pullback",
        required_indicators=["rsi"],
        internal_indicators=["ema"],
        description="Continuation de tendance EMA après micro-pullback, validée par cross RSI",
        ui_indicators=["ema", "rsi"],
    ),

    # 13. Scalp BB VWAP RSI
    "scalp_bb_vwap_rsi": StrategyIndicators(
        name="Scalp BB VWAP RSI",
        ui_label="⚡ Scalp BB + VWAP + RSI",
        required_indicators=["bollinger", "vwap", "rsi"],
        internal_indicators=[],
        description="Mean reversion court-terme sur extrêmes Bollinger avec filtre VWAP/RSI",
        ui_indicators=["bollinger", "vwap", "rsi"],
    ),

    # 14. Scalp Donchian ADX Breakout
    "scalp_donchian_adx_breakout": StrategyIndicators(
        name="Scalp Donchian ADX Breakout",
        ui_label="⚡ Scalp Donchian + ADX Breakout",
        required_indicators=["donchian", "adx"],
        internal_indicators=[],
        description="Breakout de range Donchian filtré par force de tendance ADX/+DI/-DI",
        ui_indicators=["donchian", "adx"],
    ),

    # 15. Breakout Donchian ADX (Builder)
    "breakout_donchian_adx": StrategyIndicators(
        name="Breakout Donchian ADX",
        ui_label="🧱 Breakout Donchian + ADX",
        required_indicators=["donchian", "adx", "rsi", "atr"],
        internal_indicators=[],
        description="Breakout Donchian filtre ADX avec stop/tp ATR",
        ui_indicators=["donchian", "adx", "rsi", "atr"],
    ),

    # 16. Mean Reversion Bollinger RSI (Builder)
    "mean_reversion_bollinger_rsi": StrategyIndicators(
        name="Mean Reversion Bollinger RSI",
        ui_label="🧱 Mean Reversion Bollinger + RSI",
        required_indicators=["bollinger", "rsi", "adx", "atr"],
        internal_indicators=[],
        description="Mean reversion Bollinger/RSI avec filtre ADX et risk ATR",
        ui_indicators=["bollinger", "rsi", "adx", "atr"],
    ),

    # 17. Momentum MACD (Builder)
    "momentum_macd": StrategyIndicators(
        name="Momentum MACD",
        ui_label="🧱 Momentum MACD",
        required_indicators=["macd", "bollinger", "atr"],
        internal_indicators=[],
        description="Momentum sur croisements MACD avec filtre Bollinger",
        ui_indicators=["macd", "bollinger", "atr"],
    ),

    # 18. Trend Supertrend (Builder)
    "trend_supertrend": StrategyIndicators(
        name="Trend Supertrend",
        ui_label="🧱 Trend Supertrend",
        required_indicators=["supertrend", "adx", "rsi", "atr"],
        internal_indicators=[],
        description="Suivi de tendance via Supertrend + ADX avec gestion ATR",
        ui_indicators=["supertrend", "adx", "rsi", "atr"],
    ),

    # 19. Vol Amplitude Breakout (Builder)
    "vol_amplitude_breakout": StrategyIndicators(
        name="Vol Amplitude Breakout",
        ui_label="🧱 Volatility Amplitude Breakout",
        required_indicators=["amplitude_hunter", "donchian", "adx", "atr"],
        internal_indicators=[],
        description="Breakout range/volatilite avec filtre ADX et risk ATR",
        ui_indicators=["amplitude_hunter", "donchian", "adx", "atr"],
    ),
}


# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================

def get_required_indicators(strategy_name: str) -> List[str]:
    """
    Retourne la liste des indicateurs requis pour une stratégie.

    Args:
        strategy_name: Nom de la stratégie (ex: "bollinger_atr")

    Returns:
        Liste des indicateurs requis (ex: ["bollinger", "atr"])

    Raises:
        KeyError: Si la stratégie n'existe pas
    """
    if strategy_name not in STRATEGY_INDICATORS_MAP:
        raise KeyError(
            f"Stratégie '{strategy_name}' inconnue. "
            f"Disponibles: {list(STRATEGY_INDICATORS_MAP.keys())}"
        )

    return STRATEGY_INDICATORS_MAP[strategy_name].required_indicators


def get_all_indicators(strategy_name: str) -> Set[str]:
    """
    Retourne tous les indicateurs utilisés par une stratégie.

    Args:
        strategy_name: Nom de la stratégie

    Returns:
        Set de tous les indicateurs (requis + internes)
    """
    if strategy_name not in STRATEGY_INDICATORS_MAP:
        raise KeyError(f"Stratégie '{strategy_name}' inconnue")

    return STRATEGY_INDICATORS_MAP[strategy_name].all_indicators


def get_internal_indicators(strategy_name: str) -> List[str]:
    """
    Retourne les indicateurs calculés internement par une stratégie.

    Args:
        strategy_name: Nom de la stratégie

    Returns:
        Liste des indicateurs internes
    """
    if strategy_name not in STRATEGY_INDICATORS_MAP:
        raise KeyError(f"Stratégie '{strategy_name}' inconnue")

    return STRATEGY_INDICATORS_MAP[strategy_name].internal_indicators


def get_ui_indicators(strategy_name: str) -> List[str]:
    """
    Retourne la liste des indicateurs a afficher dans l'UI.
    """
    if strategy_name not in STRATEGY_INDICATORS_MAP:
        raise KeyError(f"Stratégie '{strategy_name}' inconnue")

    return STRATEGY_INDICATORS_MAP[strategy_name].ui_indicator_list()


def list_strategies() -> List[str]:
    """Liste toutes les stratégies disponibles."""
    return list(STRATEGY_INDICATORS_MAP.keys())


def get_strategy_info(strategy_name: str) -> StrategyIndicators:
    """
    Retourne les informations complètes sur une stratégie.

    Args:
        strategy_name: Nom de la stratégie

    Returns:
        StrategyIndicators avec toutes les infos
    """
    if strategy_name not in STRATEGY_INDICATORS_MAP:
        raise KeyError(f"Stratégie '{strategy_name}' inconnue")

    return STRATEGY_INDICATORS_MAP[strategy_name]


def format_strategy_summary() -> str:
    """
    Génère un résumé formaté de toutes les stratégies et leurs indicateurs.

    Returns:
        Résumé en format texte
    """
    lines = ["=" * 80]
    lines.append("RÉFÉRENCE STRATÉGIES → INDICATEURS")
    lines.append("=" * 80)
    lines.append("")

    for strategy_name, info in STRATEGY_INDICATORS_MAP.items():
        lines.append(f"📊 {info.name} ({strategy_name})")
        lines.append(f"   Description: {info.description}")
        required = ", ".join(info.required_indicators) or "Aucun"
        internal = ", ".join(info.internal_indicators) or "Aucun"
        lines.append(f"   Requis:      {required}")
        lines.append(f"   Internes:    {internal}")
        lines.append("")

    lines.append("=" * 80)
    return "\n".join(lines)


# =============================================================================
# VALIDATION
# =============================================================================

def validate_strategy_indicators(
    strategy_name: str,
    strategy_instance
) -> bool:
    """
    Valide que les indicateurs déclarés dans le mapping correspondent
    aux indicateurs requis de la stratégie.

    Args:
        strategy_name: Nom de la stratégie
        strategy_instance: Instance de la stratégie

    Returns:
        True si cohérent, False sinon
    """
    if strategy_name not in STRATEGY_INDICATORS_MAP:
        return False

    expected = set(STRATEGY_INDICATORS_MAP[strategy_name].required_indicators)
    actual = set(strategy_instance.required_indicators)

    return expected == actual


__all__ = [
    "StrategyIndicators",
    "STRATEGY_INDICATORS_MAP",
    "get_required_indicators",
    "get_all_indicators",
    "get_internal_indicators",
    "get_ui_indicators",
    "list_strategies",
    "get_strategy_info",
    "format_strategy_summary",
    "validate_strategy_indicators",
]
