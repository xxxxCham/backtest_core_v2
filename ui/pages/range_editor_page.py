"""
Page Streamlit dédiée à l'édition des plages de paramètres.

Cette page peut être lancée:
1. Standalone: streamlit run ui/pages/range_editor_page.py
2. Intégrée dans app.py via st.navigation

Usage:
    streamlit run ui/pages/range_editor_page.py
"""

import sys
from pathlib import Path

import streamlit as st

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.range_editor import render_range_editor


def main():
    """Point d'entrée principal de la page."""
    st.set_page_config(
        page_title="Éditeur de Plages - Backtest Core",
        page_icon="⚙️",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # CSS personnalisé
    st.markdown("""
    <style>
        .stApp {
            max-width: 100%;
        }
        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
        }
        div[data-testid="stMetric"] {
            background-color: #f0f2f6;
            border-radius: 5px;
            padding: 10px;
        }
        div[data-testid="stExpander"] {
            border: 1px solid #e0e0e0;
            border-radius: 5px;
            margin-bottom: 1rem;
        }
    </style>
    """, unsafe_allow_html=True)

    # Avertissement en en-tête
    st.warning(
        "⚠️ **Attention**: Les modifications des plages affectent toutes les stratégies utilisant ces paramètres. "
        "Une sauvegarde automatique (.bak) est créée avant chaque modification."
    )

    # Rendu de l'éditeur
    render_range_editor()

    # Footer
    st.markdown("---")
    st.caption(
        "💡 **Astuce**: Utilisez la recherche pour filtrer rapidement les paramètres. "
        "Les modifications sont appliquées immédiatement aux nouveaux backtests."
    )


if __name__ == "__main__":
    main()
