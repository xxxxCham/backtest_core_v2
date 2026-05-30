"""Page Streamlit dédiée à l'édition des plages de paramètres.

Cette page peut être lancée:
1. Standalone: streamlit run ui/pages/range_editor_page.py
2. Intégrée dans app.py via st.navigation

Usage:
    streamlit run ui/pages/range_editor_page.py
"""

import sys
from pathlib import Path

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.observability import init_logging

init_logging()

import streamlit as st

from ui.range_editor import render_range_editor
from ui.theme import apply_theme


def _render_page_navigation() -> None:
    # CSS global appliqué via apply_theme (cf. ui.theme.streamlit_css).
    st.sidebar.markdown(
        """
<div class="bc-sidebar-nav-block">
  <div class="bc-sidebar-nav-title">Navigation</div>
  <div class="bc-sidebar-nav-links">
    <a class="bc-nav-link" href="/" target="_self">🏠 Application</a>
    <a class="bc-nav-link active" href="/range_editor_page" target="_self">⚙️ Éditeur de plages</a>
    <a class="bc-nav-link" href="/model_stats_page" target="_self">📊 Statistiques des modèles</a>
    <a class="bc-nav-link" href="/indicator_stats_page" target="_self">📈 Indicateurs × Perf</a>
    <a class="bc-nav-link" href="/results_store_page" target="_self">📚 Hub résultats</a>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def main():
    """Point d'entrée principal de la page."""
    st.set_page_config(
        page_title="Éditeur de Plages - Backtest Core",
        page_icon="⚙️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_theme(force=True)
    _render_page_navigation()

    # Avertissement en en-tête
    st.title("⚙️ Éditeur de plages")
    st.caption("Ajustez les bornes, steps et valeurs par défaut sans quitter l'interface principale.")
    st.warning(
        "⚠️ **Attention**: Les modifications des plages affectent toutes les stratégies utilisant ces paramètres. "
        "Une sauvegarde automatique (.bak) est créée avant chaque modification.",
    )

    # Rendu de l'éditeur
    render_range_editor()

    st.markdown("---")
    st.caption(
        "💡 Astuce: utilisez la recherche pour filtrer rapidement les paramètres. "
        "Les modifications s'appliqueront aux nouveaux backtests.",
    )


if __name__ == "__main__":
    main()
