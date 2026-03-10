"""
Module-ID: ui.constants

Purpose: Constantes UI - limites paramètres, descriptions stratégies, options modes, styles.

Role in pipeline: configuration

Key components: PARAM_CONSTRAINTS dict, get_strategy_description(), MODE_OPTIONS, CSS

Inputs: None (static definitions)

Outputs: Constants exported

Dependencies: strategies.indicators_mapping

Conventions: Min/max/step pour chaque param; descriptions UI-friendly; CSS button inline.

Read-if: Modification ranges params ou descriptions stratégies.

Skip-if: Vous appelez get_strategy_description(strategy_name).
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from strategies.indicators_mapping import STRATEGY_INDICATORS_MAP, get_ui_indicators

# Contraintes des parametres (min, max, step, description)
# Plages etendues pour permettre plus de combinaisons de test
PARAM_CONSTRAINTS: Dict[str, Dict[str, object]] = {
    # Bollinger ATR Strategy
    "bb_period": {
        "min": 2, "max": 200, "step": 1, "default": 20,
        "description": "Période des Bollinger Bands (2-200)",
    },
    "bb_std": {
        "min": 0.5, "max": 5.0, "step": 0.1, "default": 2.0,
        "description": "Écart-type des bandes (0.5-5.0)",
    },
    "bb_window": {
        "min": 10, "max": 50, "step": 1, "default": 20,
        "description": "Periode Bollinger (10-50)",
    },
    "ma_window": {
        "min": 5, "max": 30, "step": 1, "default": 10,
        "description": "Periode MA (5-30)",
    },
    "trailing_pct": {
        "min": 0.5, "max": 1.0, "step": 0.05, "default": 0.8,
        "description": "Trailing stop (0.5-1.0)",
    },
    "short_stop_pct": {
        "min": 0.1, "max": 0.5, "step": 0.01, "default": 0.37,
        "description": "Stop loss short (0.1-0.5)",
    },
    "atr_period": {
        "min": 2, "max": 100, "step": 1, "default": 14,
        "description": "Periode ATR (2-100)",
    },
    "atr_percentile": {
        "min": 0, "max": 100, "step": 1, "default": 30,
        "description": "Percentile ATR (0-100)",
    },
    "entry_z": {
        "min": 0.5, "max": 5.0, "step": 0.1, "default": 2.0,
        "description": "Z-score d'entrée (0.5-5.0)",
    },
    "k_sl": {
        "min": 0.1, "max": 10.0, "step": 0.1, "default": 1.5,
        "description": "Multiplicateur stop-loss (0.1-10.0)",
    },
    # Commun
    "leverage": {
        "min": 1, "max": 10, "step": 1, "default": 1,
        "description": "Levier de trading (1-10) - défaut: 1 pour éviter ruine du compte",
    },
    # EMA Cross / MA Crossover Strategy
    "fast_period": {
        "min": 2, "max": 200, "step": 1, "default": 12,
        "description": "Période MA rapide (2-200)",
    },
    "slow_period": {
        "min": 2, "max": 500, "step": 1, "default": 26,
        "description": "Période MA lente (2-500)",
    },
    "ema_fast": {
        "min": 10, "max": 50, "step": 1, "default": 20,
        "description": "Période EMA rapide (10-50)",
    },
    "ema_slow": {
        "min": 30, "max": 100, "step": 1, "default": 50,
        "description": "Période EMA lente (30-100)",
    },
    # MACD Cross Strategy
    "signal_period": {
        "min": 2, "max": 50, "step": 1, "default": 9,
        "description": "Période ligne signal MACD (2-50)",
    },
    # RSI Reversal Strategy
    "rsi_period": {
        "min": 2, "max": 100, "step": 1, "default": 14,
        "description": "Période RSI (2-100)",
    },
    "oversold_level": {
        "min": 1, "max": 49, "step": 1, "default": 30,
        "description": "Seuil survente RSI (1-49)",
    },
    "overbought_level": {
        "min": 51, "max": 99, "step": 1, "default": 70,
        "description": "Seuil surachat RSI (51-99)",
    },
    # ATR Channel Strategy
    "atr_mult": {
        "min": 0.1, "max": 10.0, "step": 0.1, "default": 2.0,
        "description": "Multiplicateur ATR pour canal (0.1-10.0)",
    },
    # EMA Stochastic Scalp Strategy
    "fast_ema": {
        "min": 2, "max": 200, "step": 1, "default": 50,
        "description": "Période EMA rapide scalp (2-200)",
    },
    "slow_ema": {
        "min": 2, "max": 500, "step": 1, "default": 100,
        "description": "Période EMA lente scalp (2-500)",
    },
    "stoch_k": {
        "min": 2, "max": 100, "step": 1, "default": 14,
        "description": "Période Stochastic %K (2-100)",
    },
    "stoch_d": {
        "min": 1, "max": 50, "step": 1, "default": 3,
        "description": "Période Stochastic %D (1-50)",
    },
    "stoch_oversold": {
        "min": 1, "max": 49, "step": 1, "default": 20,
        "description": "Seuil survente Stochastic (1-49)",
    },
    "stoch_overbought": {
        "min": 51, "max": 99, "step": 1, "default": 80,
        "description": "Seuil surachat Stochastic (51-99)",
    },
}

_STRATEGY_TYPE_RE = re.compile(r"\(([^)]+)\)\s*$")
_LEADING_NONWORD_RE = re.compile(r"^\W+\s*")


def get_strategy_ui_label(strategy_key: str) -> str:
    info = STRATEGY_INDICATORS_MAP.get(strategy_key)
    if not info:
        return strategy_key
    return info.display_label()


def get_strategy_display_name(strategy_key: str) -> str:
    label = get_strategy_ui_label(strategy_key)
    label = _LEADING_NONWORD_RE.sub("", label).strip()
    label = _STRATEGY_TYPE_RE.sub("", label).strip()
    return label or strategy_key


def get_strategy_type(strategy_key: str) -> str:
    label = get_strategy_ui_label(strategy_key)
    match = _STRATEGY_TYPE_RE.search(label)
    if not match:
        return "Autre"
    return match.group(1).strip()


def get_strategy_description(strategy_key: str) -> str:
    info = STRATEGY_INDICATORS_MAP.get(strategy_key)
    if not info:
        return ""
    return info.description or ""


def get_strategy_ui_indicators(strategy_key: str) -> List[str]:
    try:
        return get_ui_indicators(strategy_key)
    except KeyError:
        return []


MODE_BUTTON_CSS = """
<style>
    .mode-button {
        width: 100%;
        padding: 12px 16px;
        margin: 6px 0;
        border: 2px solid transparent;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        text-align: center;
        transition: all 0.3s ease;
    }
    .mode-button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    .mode-inactive {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        opacity: 0.6;
    }
    .mode-active {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        opacity: 1;
        border-color: #ffd700;
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    }
</style>
"""

MODE_OPTIONS: List[Tuple[str, str, str]] = [
    ("Backtest Simple", "📊", "1 combinaison de paramètres"),
    ("Grille de Paramètres", "🔢", "Exploration min/max/step"),
    ("🤖 Optimisation LLM", "🧠", "Agents IA + Deep Trace intégré"),
    ("🏗️ Strategy Builder", "🔧", "Création de stratégies par IA"),
]


def build_strategy_options(available_strategies: List[str]) -> Dict[str, str]:
    return {get_strategy_ui_label(k): k for k in available_strategies}


