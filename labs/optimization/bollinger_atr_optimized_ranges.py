"""
Module-ID: labs.optimization.bollinger_atr_optimized_ranges

Purpose: Ranges optimises pour bollinger_atr (issus d'analyses de backtests).
"""

from __future__ import annotations

from typing import Dict

from utils.parameters import ParameterSpec


def get_parameter_specs() -> Dict[str, ParameterSpec]:
    """Spécifications optimisées basées sur l'analyse des résultats profitables.

    🎯 RANGES OPTIMISÉS via analyse de données réelles :
    - Analyse de XXX résultats de backtest
    - Focus sur top 25% des résultats par Sharpe ratio
    - Réduction des combinaisons : 100.0% ({combo_before:,} → {combo_after:,})
    - Accélération estimée : infx plus rapide
    """
    return {
        "bb_period": ParameterSpec(
            name="bb_period",
            min_val=29, max_val=29, default=29,  # 🎯 Optimisé: était (10-50)
            param_type="int",
            description="Période des Bandes de Bollinger",
        ),
        "bb_std": ParameterSpec(
            name="bb_std",
            min_val=2.5, max_val=2.5, default=2.5,  # 🎯 Optimisé: était (1.5-3.0)
            param_type="float",
            description="Écarts-types pour les bandes",
        ),
        "entry_z": ParameterSpec(
            name="entry_z",
            min_val=0.2, max_val=1.0, default=0.6,  # 🎯 Optimisé: était (1.0-3.0)
            param_type="float",
            description="Seuil z-score pour entree",
        ),
        "atr_period": ParameterSpec(
            name="atr_period",
            min_val=14, max_val=14, default=14,  # 🎯 Optimisé: était (7-21)
            param_type="int",
            description="Période de l'ATR",
        ),
        "atr_percentile": ParameterSpec(
            name="atr_percentile",
            min_val=30, max_val=30, default=30,  # 🎯 Optimisé: était (0-60)
            param_type="int",
            description="Percentile volatilite minimum (ATR)",
        ),
        "k_sl": ParameterSpec(
            name="k_sl",
            min_val=0.2, max_val=1.0, default=0.4,  # 🎯 Optimisé: était (1.0-3.0)
            param_type="float",
            description="Multiplicateur ATR pour stop-loss",
        ),
        "leverage": ParameterSpec(
            name="leverage",
            min_val=1, max_val=10, default=1,
            param_type="int",
            description="Levier de trading (non optimisé)",
            optimize=False,
        ),
    }
