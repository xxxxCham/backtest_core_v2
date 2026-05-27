"""Dedicated Streamlit page for Builder model statistics."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.observability import init_logging

init_logging()

import streamlit as st

from ui.model_stats_view import render_model_stats_page
from ui.theme import apply_theme


def _render_page_navigation() -> None:
    # CSS global appliqué via apply_theme (cf. ui.theme.streamlit_css).
    st.sidebar.markdown(
        """
<div class="bc-sidebar-nav-block">
  <div class="bc-sidebar-nav-title">Navigation</div>
  <div class="bc-sidebar-nav-links">
    <a class="bc-nav-link" href="/" target="_self">🏠 Application</a>
    <a class="bc-nav-link" href="/range_editor_page" target="_self">⚙️ Éditeur de plages</a>
    <a class="bc-nav-link active" href="/model_stats_page" target="_self">📊 Statistiques des modèles</a>
    <a class="bc-nav-link" href="/indicator_stats_page" target="_self">📈 Indicateurs × Perf</a>
    <a class="bc-nav-link" href="/results_store_page" target="_self">📚 Hub résultats</a>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Statistiques des modèles - Backtest Core",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_theme(force=True)
    _render_page_navigation()
    render_model_stats_page()


if __name__ == "__main__":
    main()
