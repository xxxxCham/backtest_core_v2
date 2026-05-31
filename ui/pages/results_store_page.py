"""Dedicated Streamlit page for the centralized results store."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.observability import init_logging

init_logging()

import streamlit as st

from ui.results_store_view import render_results_store_page
from ui.theme import apply_theme


def _render_page_navigation() -> None:
    # CSS global appliqué via apply_theme (cf. ui.theme.streamlit_css).
    # On rend uniquement le HTML de navigation : les classes .bc-sidebar-nav-*
    # et .bc-nav-link sont stylées globalement par le thème.
    st.sidebar.markdown(
        """
<div class="bc-sidebar-nav-block">
  <div class="bc-sidebar-nav-title">Navigation</div>
  <div class="bc-sidebar-nav-links">
    <a class="bc-nav-link" href="/" target="_self">Application</a>
    <a class="bc-nav-link" href="/range_editor_page" target="_self">Éditeur de plages</a>
    <a class="bc-nav-link" href="/model_stats_page" target="_self">Statistiques des modèles</a>
    <a class="bc-nav-link" href="/indicator_stats_page" target="_self">Indicateurs × Perf</a>
    <a class="bc-nav-link active" href="/results_store_page" target="_self">Hub résultats</a>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Hub resultats - Backtest Core",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_theme(force=True)
    _render_page_navigation()
    render_results_store_page()


if __name__ == "__main__":
    main()
