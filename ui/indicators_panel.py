"""Module-ID: ui.indicators_panel

Purpose: Panel d'indicateurs dynamique Streamlit - grouper et afficher indicateurs par catégorie (tendance, momentum, volatilite).

Role in pipeline: visualization / input

Key components: group_indicators_by_category(), render_indicator_panel(), selecteur interactif

Inputs: Registry indicateurs

Outputs: Interface sélection indicateurs avec catégories

Dependencies: streamlit, indicators.registry

Conventions: Catégories: 📈 Tendance, 📍 Momentum, 🎊 Volatilité, 💈 Volume

Read-if: Modification UI sélection indicateurs ou catégorisation.

Skip-if: Interface indicateurs déjà définie.
"""

import streamlit as st

from indicators.registry import get_indicator, list_indicators


def group_indicators_by_category() -> dict[str, list[str]]:
    """Groupe les indicateurs par catégorie fonctionnelle.

    Returns:
        Dict avec catégories comme clés et listes d'indicateurs comme valeurs

    """
    # Récupérer tous les indicateurs
    all_indicators = list_indicators()

    # Définir les catégories
    categories = {
        "📈 Tendance": [
            "ema",
            "sma",
            "adx",
            "macd",
            "aroon",
            "supertrend",
            "ichimoku",
            "psar",
            "vortex",
            "pi_cycle",
            "onchain_smoothing",
        ],
        "📊 Volatilité": [
            "atr",
            "bollinger",
            "keltner",
            "donchian",
            "standard_deviation",
            "amplitude_hunter",
        ],
        "⚡ Momentum": [
            "rsi",
            "stochastic",
            "cci",
            "momentum",
            "roc",
            "williams_r",
        ],
        "📦 Volume": [
            "vwap",
            "obv",
            "mfi",
            "volume_oscillator",
        ],
    }

    # Filtrer pour ne garder que les indicateurs existants
    filtered_categories = {}
    for category, indicators in categories.items():
        existing = [ind for ind in indicators if ind in all_indicators]
        if existing:
            filtered_categories[category] = existing

    # Ajouter une catégorie "Autres" pour les indicateurs non catégorisés
    categorized = set()
    for indicators in filtered_categories.values():
        categorized.update(indicators)

    uncategorized = [ind for ind in all_indicators if ind not in categorized]
    if uncategorized:
        filtered_categories["🔧 Autres"] = uncategorized

    return filtered_categories


def render_indicators_panel(expanded: bool = False):
    """Affiche le panel complet des indicateurs disponibles.

    Args:
        expanded: Si True, affiche toutes les catégories ouvertes

    """
    st.markdown("### 📊 Indicateurs Disponibles")

    # Récupérer les indicateurs groupés
    categories = group_indicators_by_category()

    # Compter le total
    total_indicators = sum(len(inds) for inds in categories.values())
    st.caption(f"**{total_indicators} indicateurs techniques** prêts à l'emploi")

    # Afficher par catégorie
    for category, indicator_names in categories.items():
        with st.expander(f"{category} ({len(indicator_names)})", expanded=expanded):
            for ind_name in sorted(indicator_names):
                info = get_indicator(ind_name)
                if info and info.description:
                    st.markdown(f"- **{ind_name.upper()}** : {info.description}")
                else:
                    st.markdown(f"- **{ind_name.upper()}**")


def render_indicators_summary():
    """Affiche un résumé compact des indicateurs disponibles."""
    categories = group_indicators_by_category()
    total = sum(len(inds) for inds in categories.values())

    st.markdown(f"""
    ### 📊 Indicateurs Intégrés

    **{total} indicateurs techniques** répartis en {len(categories)} catégories :
    """)

    for category, indicators in categories.items():
        # Formater la liste des indicateurs
        ind_list = ", ".join([ind.upper() for ind in sorted(indicators)])
        st.markdown(f"**{category}** : {ind_list}")

    st.info("💡 Les indicateurs sont chargés **automatiquement** selon la stratégie sélectionnée")


def render_indicators_table():
    """Affiche un tableau complet des indicateurs avec leurs métadonnées."""
    import pandas as pd

    st.markdown("### 📋 Table Complète des Indicateurs")

    all_indicators = list_indicators()

    # Créer les données du tableau
    data = []
    for ind_name in sorted(all_indicators):
        info = get_indicator(ind_name)
        if info:
            data.append(
                {
                    "Nom": ind_name.upper(),
                    "Colonnes Requises": ", ".join(info.required_columns),
                    "Description": info.description or "N/A",
                },
            )

    # Afficher le DataFrame
    df = pd.DataFrame(data)
    st.dataframe(df, width="stretch", hide_index=True)


def get_category_for_indicator(indicator_name: str) -> str:
    """Retourne la catégorie d'un indicateur.

    Args:
        indicator_name: Nom de l'indicateur

    Returns:
        Nom de la catégorie (sans emoji)

    """
    categories = group_indicators_by_category()

    for category, indicators in categories.items():
        if indicator_name in indicators:
            # Retirer l'emoji
            return category.split(" ", 1)[1] if " " in category else category

    return "Autres"


def format_indicator_name(indicator_name: str, with_description: bool = True) -> str:
    """Formate le nom d'un indicateur pour l'affichage.

    Args:
        indicator_name: Nom de l'indicateur
        with_description: Si True, inclut la description

    Returns:
        Nom formaté

    """
    info = get_indicator(indicator_name)

    if not info:
        return indicator_name.upper()

    if with_description and info.description:
        return f"**{indicator_name.upper()}** : {info.description}"
    return f"**{indicator_name.upper()}**"


__all__ = [
    "format_indicator_name",
    "get_category_for_indicator",
    "group_indicators_by_category",
    "render_indicators_panel",
    "render_indicators_summary",
    "render_indicators_table",
]
