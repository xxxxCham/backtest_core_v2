"""Dedicated Streamlit page for Builder model statistics."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.observability import init_logging

init_logging()

import streamlit as st

from ui.model_stats_view import render_model_stats_page


def _render_page_navigation() -> None:
    st.sidebar.markdown(
        """
<style>
header[data-testid="stHeader"] {
    background: transparent !important;
}
[data-testid="stSidebar"] button[kind="header"],
[data-testid="stSidebar"] button[kind="headerNoPadding"],
[data-testid="stExpandSidebarButton"],
[data-testid="collapsedControl"] {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    pointer-events: auto !important;
    align-items: center !important;
    justify-content: center !important;
    border-radius: 12px !important;
    background: rgba(15, 23, 42, 0.92) !important;
    border: 1px solid rgba(96, 165, 250, 0.35) !important;
    box-shadow: 0 10px 24px rgba(2, 8, 23, 0.30) !important;
}
[data-testid="stExpandSidebarButton"],
[data-testid="stSidebar"] button[kind="header"],
[data-testid="stSidebar"] button[kind="headerNoPadding"] {
    min-width: 2.35rem !important;
    min-height: 2.35rem !important;
}
[data-testid="stExpandSidebarButton"],
[data-testid="collapsedControl"] {
    position: fixed !important;
    top: 0.7rem;
    left: 0.7rem;
    z-index: 100000 !important;
}
[data-testid="stSidebar"] button[kind="header"] svg,
[data-testid="stSidebar"] button[kind="headerNoPadding"] svg,
[data-testid="stExpandSidebarButton"] svg,
[data-testid="collapsedControl"] svg {
    fill: #dbeafe !important;
}
[data-testid="stToolbar"] {
    background: transparent !important;
    box-shadow: none !important;
}
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
#MainMenu,
footer {
    display: none !important;
}
[data-testid="stSidebarNav"] {
    display: none !important;
}
.bc-sidebar-nav-block {
    margin: 0.35rem 0 1rem 0;
    padding: 0.85rem 0.8rem 0.9rem 0.8rem;
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 16px;
    background: linear-gradient(180deg, rgba(15, 23, 42, 0.96), rgba(20, 33, 56, 0.96));
}
.bc-sidebar-nav-title {
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #93c5fd;
    margin-bottom: 0.65rem;
}
.bc-sidebar-nav-links {
    display: grid;
    gap: 0.5rem;
}
.bc-nav-link {
    display: block;
    text-decoration: none;
    border-radius: 12px;
    padding: 0.7rem 0.85rem;
    font-weight: 600;
    color: #dbeafe !important;
    background: rgba(30, 41, 59, 0.92);
    border: 1px solid rgba(71, 85, 105, 0.75);
}
.bc-nav-link:hover {
    border-color: rgba(96, 165, 250, 0.9);
    background: rgba(30, 64, 175, 0.18);
}
.bc-nav-link.active {
    background: linear-gradient(135deg, rgba(29, 78, 216, 0.88), rgba(59, 130, 246, 0.88));
    border-color: rgba(96, 165, 250, 0.95);
    color: #ffffff !important;
    box-shadow: 0 8px 20px rgba(37, 99, 235, 0.28);
}
</style>
<div class="bc-sidebar-nav-block">
  <div class="bc-sidebar-nav-title">Navigation</div>
  <div class="bc-sidebar-nav-links">
    <a class="bc-nav-link" href="/" target="_self">🏠 Application</a>
    <a class="bc-nav-link" href="/range_editor_page" target="_self">⚙️ Éditeur de plages</a>
    <a class="bc-nav-link active" href="/model_stats_page" target="_self">📊 Statistiques des modèles</a>
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
    _render_page_navigation()
    render_model_stats_page()


if __name__ == "__main__":
    main()
