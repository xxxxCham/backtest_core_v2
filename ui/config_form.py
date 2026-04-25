"""Module-ID: ui.config_form

Purpose: Gère la configuration via st.form() pour éviter les reloads inutiles.

Role in pipeline: UI configuration avec pattern draft/validation/execution

Key components:
- render_config_form() : Formulaire de configuration
- compute_config_preview() : Preview sans chargement lourd
- validate_and_freeze_config() : Figer configuration pour exécution

Architecture:
    Phase 1: Configuration (draft) - widgets dans st.form()
    Phase 2: Validation - bouton submit, stockage dans session_state
    Phase 3: Preview - calculs légers (nb combos, estimation durée)
    Phase 4: Execution - bouton Run utilise config figée

Dependencies: streamlit, ui.state, ui.context

Conventions:
- cfg_draft : configuration en cours d'édition
- cfg_validated : configuration validée, prête à exécuter
- cfg_frozen : copie immutable pour exécution

Read-if: Modification du pattern de configuration UI
Skip-if: Logique backend pure
"""

from __future__ import annotations

import copy
from typing import Any

import streamlit as st

from ui.context import (
    discover_available_data,
    list_strategies,
)


def compute_nb_combos(param_ranges: dict[str, dict[str, float]]) -> int:
    """Calcule le nombre de combinaisons sans charger les données.

    Args:
        param_ranges: Dict {param_name: {"min": val, "max": val, "step": val}}

    Returns:
        Nombre de combinaisons

    """
    if not param_ranges:
        return 1

    try:
        combos = 1
        for param_name, range_def in param_ranges.items():
            min_val = range_def.get("min", 0)
            max_val = range_def.get("max", min_val)
            step = range_def.get("step", 1)

            if step <= 0:
                step = 1

            # Calculer nombre de valeurs dans la plage
            if max_val >= min_val:
                n_values = int((max_val - min_val) / step) + 1
                combos *= n_values

        return max(1, combos)
    except Exception:
        return 1


def estimate_duration(nb_combos: int, n_workers: int = 1) -> float:
    """Estime la durée d'exécution (heuristique).

    Args:
        nb_combos: Nombre de combinaisons
        n_workers: Nombre de workers parallèles

    Returns:
        Durée estimée en secondes

    """
    # Heuristique: ~10-50ms par combo selon complexité
    # Utilisons 20ms comme moyenne
    ms_per_combo = 20
    total_ms = nb_combos * ms_per_combo

    # Parallélisation (avec overhead)
    parallel_efficiency = 0.85  # 85% d'efficacité
    if n_workers > 1:
        total_ms = total_ms / (n_workers * parallel_efficiency)

    return total_ms / 1000  # Convertir en secondes


def format_duration(seconds: float) -> str:
    """Formate une durée en secondes en format lisible.

    Args:
        seconds: Durée en secondes

    Returns:
        Chaîne formatée (ex: "2m 30s", "45s", "1h 15m")

    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        minutes = int(seconds // 60)
        remaining_seconds = int(seconds % 60)
        return f"{minutes}m {remaining_seconds}s"
    hours = int(seconds // 3600)
    remaining_minutes = int((seconds % 3600) // 60)
    return f"{hours}h {remaining_minutes}m"


def render_config_preview(cfg_draft: dict[str, Any]) -> None:
    """Affiche une preview de la configuration sans charger de données.

    Args:
        cfg_draft: Configuration draft depuis session_state

    """
    st.markdown("---")
    st.subheader("📋 Preview Configuration")

    # Résumé configuration
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Stratégie", cfg_draft.get("strategy_key", "N/A"))

    with col2:
        st.metric("Symbole", cfg_draft.get("symbol", "N/A"))

    with col3:
        st.metric("Timeframe", cfg_draft.get("timeframe", "N/A"))

    # Calculer espace de recherche
    param_ranges = cfg_draft.get("param_ranges", {})
    n_workers = cfg_draft.get("n_workers", 1)

    if param_ranges:
        nb_combos = compute_nb_combos(param_ranges)
        estimated_sec = estimate_duration(nb_combos, n_workers)

        col1, col2 = st.columns(2)

        with col1:
            st.metric(
                "Combinaisons",
                f"{nb_combos:,}",
                help="Nombre total de combinaisons de paramètres à tester",
            )

        with col2:
            st.metric(
                "Durée estimée",
                format_duration(estimated_sec),
                help=f"Estimation avec {n_workers} worker(s) parallèle(s)",
            )

        # Détail des ranges
        with st.expander("📊 Détail des paramètres", expanded=False):
            for param_name, range_def in param_ranges.items():
                min_val = range_def.get("min", 0)
                max_val = range_def.get("max", min_val)
                step = range_def.get("step", 1)
                n_values = compute_nb_combos({param_name: range_def})

                st.caption(
                    f"**{param_name}**: {min_val} → {max_val} (step {step}) = {n_values} valeurs",
                )
    else:
        st.info("Aucun range de paramètres défini - exécution simple")


def init_config_draft() -> None:
    """Initialise cfg_draft dans session_state s'il n'existe pas."""
    if "cfg_draft" not in st.session_state:
        st.session_state["cfg_draft"] = {
            "debug_enabled": False,
            "symbol": "BTCUSDC",
            "timeframe": "1h",
            "strategy_key": "bollinger_atr",
            "use_date_filter": False,
            "start_date": None,
            "end_date": None,
            "param_ranges": {},
            "n_workers": 1,
            "initial_capital": 100000.0,
            "leverage": 1.0,
            "leverage_enabled": False,
            "optimization_mode": "grid",
            "max_combos": 1000,
        }


def render_minimal_config_form() -> bool:
    """Affiche un formulaire de configuration minimal dans la sidebar.

    Returns:
        True si configuration validée (submit button pressed)

    """
    # Initialiser draft si nécessaire
    init_config_draft()

    with st.sidebar:
        st.header("⚙️ Configuration")

        # Découvrir données disponibles (léger, pas de chargement)
        try:
            available_tokens, available_timeframes = discover_available_data()
            if not available_tokens:
                available_tokens = ["BTCUSDC", "ETHUSDC"]
            if not available_timeframes:
                available_timeframes = ["1h", "4h", "1d"]
        except Exception:
            available_tokens = ["BTCUSDC", "ETHUSDC"]
            available_timeframes = ["1h", "4h", "1d"]

        # Liste stratégies (léger)
        try:
            strategies = list_strategies()
            strategy_keys = list(strategies.keys())
            if not strategy_keys:
                strategy_keys = ["bollinger_atr"]
        except Exception:
            strategy_keys = ["bollinger_atr"]

        # FORMULAIRE DE CONFIGURATION
        with st.form("backtest_config_form", clear_on_submit=False):
            st.subheader("📊 Paramètres de base")

            # Stratégie
            current_strategy = st.session_state["cfg_draft"].get("strategy_key", strategy_keys[0])
            if current_strategy not in strategy_keys:
                current_strategy = strategy_keys[0]

            strategy_idx = strategy_keys.index(current_strategy) if current_strategy in strategy_keys else 0

            strategy_key = st.selectbox(
                "Stratégie",
                strategy_keys,
                index=strategy_idx,
                help="Stratégie de trading à backtester",
            )

            # Symbole
            current_symbol = st.session_state["cfg_draft"].get("symbol", available_tokens[0])
            if current_symbol not in available_tokens:
                current_symbol = available_tokens[0]

            symbol_idx = available_tokens.index(current_symbol) if current_symbol in available_tokens else 0

            symbol = st.selectbox(
                "Symbole",
                available_tokens,
                index=symbol_idx,
                help="Paire de trading",
            )

            # Timeframe
            current_timeframe = st.session_state["cfg_draft"].get("timeframe", available_timeframes[0])
            if current_timeframe not in available_timeframes:
                current_timeframe = available_timeframes[0]

            timeframe_idx = (
                available_timeframes.index(current_timeframe) if current_timeframe in available_timeframes else 0
            )

            timeframe = st.selectbox(
                "Timeframe",
                available_timeframes,
                index=timeframe_idx,
                help="Intervalle de temps des bougies",
            )

            # Capital initial
            initial_capital = st.number_input(
                "Capital Initial ($)",
                min_value=100.0,
                max_value=10_000_000.0,
                value=st.session_state["cfg_draft"].get("initial_capital", 100000.0),
                step=1000.0,
                help="Capital de départ pour le backtest",
            )

            # Nombre de workers
            n_workers = st.number_input(
                "Workers parallèles",
                min_value=1,
                max_value=32,
                value=st.session_state["cfg_draft"].get("n_workers", 1),
                help="Nombre de processus parallèles pour sweep",
            )

            # Bouton submit DANS le formulaire
            submitted = st.form_submit_button(
                "✅ Valider Configuration",
                type="primary",
                width="stretch",
            )

            if submitted:
                # Stocker la configuration validée
                st.session_state["cfg_draft"] = {
                    "debug_enabled": st.session_state["cfg_draft"].get("debug_enabled", False),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "strategy_key": strategy_key,
                    "use_date_filter": False,
                    "start_date": None,
                    "end_date": None,
                    "param_ranges": {},  # TODO: implémenter édition ranges
                    "n_workers": n_workers,
                    "initial_capital": initial_capital,
                    "leverage": 1.0,
                    "leverage_enabled": False,
                    "optimization_mode": "grid",
                    "max_combos": 1000,
                }

                # Marquer comme validée
                st.session_state["cfg_validated"] = True
                st.session_state["cfg_validated_timestamp"] = st.session_state.get("_last_rerun_time", 0)

        # PREVIEW (HORS du formulaire - ne déclenche pas de rerun)
        if st.session_state.get("cfg_validated", False):
            st.success("✅ Configuration validée")
            render_config_preview(st.session_state["cfg_draft"])
        else:
            st.info("💡 Validez la configuration pour continuer")

        return st.session_state.get("cfg_validated", False)


def get_frozen_config() -> dict[str, Any] | None:
    """Retourne une copie immutable de la configuration validée.

    Returns:
        Copie profonde de cfg_draft si validée, None sinon

    """
    if not st.session_state.get("cfg_validated", False):
        return None

    return copy.deepcopy(st.session_state.get("cfg_draft", {}))


def reset_validation() -> None:
    """Reset le flag de validation (après exécution ou changement config)."""
    st.session_state["cfg_validated"] = False
    if "cfg_validated_timestamp" in st.session_state:
        del st.session_state["cfg_validated_timestamp"]


__all__ = [
    "compute_nb_combos",
    "estimate_duration",
    "get_frozen_config",
    "init_config_draft",
    "render_config_preview",
    "render_minimal_config_form",
    "reset_validation",
]
