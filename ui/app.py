"""Module-ID: ui.app

Purpose: Application Streamlit principale - UI orchestration, page config, sidebar/main/results.

Role in pipeline: user interface

Key components: configure_page(), install_best_pnl_tracker(), main()

Inputs: Streamlit state, user interactions

Outputs: Rendered UI pages (setup, backtest, results, analysis)

Dependencies: streamlit, ui.*, backtest.*, utils.observability

Conventions: PYTHONPATH setup; init_logging() first; st.set_page_config() before sidebar.

Read-if: Modification page layout ou flow control.

Skip-if: Vous lancez juste `streamlit run ui/app.py`.
"""

import sys
from pathlib import Path

# pylint: disable=wrong-import-position

# Ajouter le répertoire racine au PYTHONPATH pour les imports
ROOT_DIR = Path(__file__).parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backtest.result_store import load_project_env  # noqa: E402

# Charger les variables d'environnement depuis .env, même sans python-dotenv.
load_project_env()

import streamlit as st  # noqa: E402

from ui.context import BACKEND_AVAILABLE, IMPORT_ERROR, LLM_AVAILABLE  # noqa: E402
from ui.exec_tabs import render_exec_tabs  # noqa: E402
from ui.log_taps import install_best_pnl_tracker  # noqa: E402
from ui.main import (  # noqa: E402
    render_controls,
    render_main,
    render_primary_action_bar,
    render_setup_previews,
)
from ui.results import render_results  # noqa: E402
from ui.sidebar import render_sidebar  # noqa: E402
from ui.state import clear_execution_state  # noqa: E402
from utils.observability import init_logging  # noqa: E402

init_logging()


def _render_workspace_navigation(active: str = "app") -> None:
    app_class = "bc-nav-link active" if active == "app" else "bc-nav-link"
    editor_class = "bc-nav-link active" if active == "range_editor" else "bc-nav-link"
    model_stats_class = "bc-nav-link active" if active == "model_stats" else "bc-nav-link"
    results_class = "bc-nav-link active" if active == "results_store" else "bc-nav-link"
    st.sidebar.markdown(
        f"""
<div class="bc-sidebar-nav-block">
    <div class="bc-sidebar-nav-title">Navigation</div>
    <div class="bc-sidebar-nav-links">
        <a class="{app_class}" href="/" target="_self">🏠 Application</a>
        <a class="{editor_class}" href="/range_editor_page" target="_self">⚙️ Éditeur de plages</a>
        <a class="{model_stats_class}" href="/model_stats_page" target="_self">📊 Statistiques des modèles</a>
        <a class="{results_class}" href="/results_store_page" target="_self">📚 Hub résultats</a>
    </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _clear_execution_lock() -> None:
    """Clear UI execution lock flags to avoid stuck disabled controls."""
    clear_execution_state(st.session_state, clear_builder_launch=True)


def configure_page() -> None:
    st.set_page_config(
        page_title="Backtest Core",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(
        """
<style>
:root {
    --bc-bg: #07111f;
    --bc-surface: rgba(10, 20, 35, 0.92);
    --bc-surface-2: rgba(15, 27, 45, 0.94);
    --bc-border: rgba(148, 163, 184, 0.20);
    --bc-text: #e5eefb;
    --bc-text-muted: #8fa8c6;
    --bc-accent: #60a5fa;
    --bc-content-pad: clamp(0.8rem, 1vw, 1.2rem);
}
html, body, [data-testid="stAppViewContainer"], .stApp {
    background:
        radial-gradient(circle at top left, rgba(37, 99, 235, 0.16), transparent 32%),
        radial-gradient(circle at top right, rgba(14, 165, 233, 0.10), transparent 28%),
        linear-gradient(180deg, var(--bc-bg) 0%, #091523 100%);
    color: var(--bc-text);
}
[data-testid="stAppViewContainer"] > .main {
    background: transparent;
}
[data-testid="stAppViewContainer"] .block-container {
    max-width: none;
    width: 100%;
    padding-top: 1.15rem;
    padding-bottom: 3rem;
    padding-left: var(--bc-content-pad);
    padding-right: var(--bc-content-pad);
}
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(7, 18, 33, 0.97), rgba(9, 20, 37, 0.98)) !important;
    border-right: 1px solid rgba(96, 165, 250, 0.12);
}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    padding-top: 0.55rem;
}
[data-testid="stMarkdownContainer"],
[data-testid="stText"],
label,
p,
li,
span,
div {
    color: var(--bc-text);
}
[data-testid="stCaptionContainer"] {
    color: var(--bc-text-muted);
}
h1, h2, h3 {
    color: #f8fbff;
    letter-spacing: -0.02em;
}
h1 {
    margin-top: 0.2rem;
    margin-bottom: 0.8rem;
}
hr {
    border-color: rgba(148, 163, 184, 0.14) !important;
}
div[data-testid="stMetric"] {
    background: linear-gradient(180deg, rgba(12, 22, 37, 0.96), rgba(14, 27, 45, 0.94));
    border: 1px solid var(--bc-border);
    border-radius: 16px;
    padding: 0.8rem 0.9rem;
    box-shadow: 0 16px 40px rgba(2, 8, 23, 0.18);
}
div[data-testid="stMetricLabel"] {
    color: var(--bc-text-muted);
}
div[data-testid="stExpander"] {
    border: 1px solid var(--bc-border);
    border-radius: 16px;
    background: linear-gradient(180deg, rgba(10, 20, 35, 0.95), rgba(13, 25, 43, 0.94));
    box-shadow: 0 16px 40px rgba(2, 8, 23, 0.14);
}
div[data-testid="stAlert"],
div[data-testid="stCodeBlock"] {
    border-radius: 16px;
}
[data-testid="stButton"] > button {
    border-radius: 14px;
    font-weight: 650;
    color: #eef6ff !important;
    border: 1px solid rgba(96, 165, 250, 0.35) !important;
    background: linear-gradient(180deg, rgba(17, 35, 67, 0.96), rgba(24, 49, 94, 0.94)) !important;
    box-shadow: 0 10px 24px rgba(2, 8, 23, 0.22);
}
[data-testid="stButton"] > button:hover {
    border-color: rgba(147, 197, 253, 0.72) !important;
    background: linear-gradient(180deg, rgba(28, 58, 109, 0.98), rgba(34, 70, 131, 0.96)) !important;
}
[data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 58%, #60a5fa 100%) !important;
    border: 1px solid rgba(147, 197, 253, 0.78) !important;
    color: #ffffff !important;
    box-shadow: 0 14px 30px rgba(30, 64, 175, 0.34) !important;
}
[data-testid="stButton"] > button[kind="secondary"] {
    background: linear-gradient(180deg, rgba(14, 30, 57, 0.96), rgba(21, 42, 78, 0.94)) !important;
    border: 1px solid rgba(96, 165, 250, 0.32) !important;
    color: #e0edff !important;
}
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 0.6rem;
    border-bottom: 1px solid rgba(96, 165, 250, 0.18);
    padding-bottom: 0.3rem;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    min-height: 3.15rem;
    padding: 0.7rem 1.1rem;
    border-radius: 16px 16px 0 0;
    border: 1px solid rgba(96, 165, 250, 0.18) !important;
    background: linear-gradient(180deg, rgba(14, 27, 45, 0.92), rgba(18, 34, 57, 0.94)) !important;
    color: #dbeafe !important;
    font-weight: 700;
    transition: border-color 140ms ease, background 140ms ease, transform 140ms ease;
}
[data-testid="stTabs"] [data-baseweb="tab"]:hover {
    border-color: rgba(147, 197, 253, 0.46) !important;
    background: linear-gradient(180deg, rgba(22, 43, 75, 0.96), rgba(28, 54, 91, 0.96)) !important;
}
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {
    background: linear-gradient(135deg, rgba(29, 78, 216, 0.96), rgba(59, 130, 246, 0.96)) !important;
    border-color: rgba(147, 197, 253, 0.88) !important;
    color: #ffffff !important;
    box-shadow: 0 12px 26px rgba(30, 64, 175, 0.26);
}
header[data-testid="stHeader"] {
    background: transparent !important;
}
[data-testid="stSidebar"] button[kind="header"],
[data-testid="stSidebar"] button[kind="headerNoPadding"],
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
[data-testid="stSidebar"] button[kind="header"],
[data-testid="stSidebar"] button[kind="headerNoPadding"] {
    min-width: 2.35rem !important;
    min-height: 2.35rem !important;
}
[data-testid="collapsedControl"] {
    position: fixed !important;
    top: 0.7rem;
    left: 0.7rem;
    z-index: 100000 !important;
}
[data-testid="stSidebar"] button[kind="header"] svg,
[data-testid="stSidebar"] button[kind="headerNoPadding"] svg,
[data-testid="collapsedControl"] svg {
    fill: #dbeafe !important;
}
[data-testid="stToolbar"],
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
div[style*="border-left: 4px solid rgba(0,0,0,0.2)"] code,
div[style*="border-left: 4px solid #666"] code {
    color: #111827 !important;
    background-color: rgba(255,255,255,0.65) !important;
    border: 1px solid rgba(15,23,42,0.25) !important;
}
</style>
""",
        unsafe_allow_html=True,
    )


def render_footer() -> None:
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Backtest Core v2.1**")
    optimization_mode = st.session_state.get("optimization_mode", "Backtest Simple")
    if optimization_mode == "🤖 Optimisation LLM":
        llm_status = "✅ LLM" if LLM_AVAILABLE else "❌ LLM"
        st.sidebar.caption(f"Architecture découplée UI/Moteur | {llm_status}")
    else:
        st.sidebar.caption("Architecture découplée UI/Moteur")


def main() -> None:
    configure_page()
    _render_workspace_navigation("app")

    best_pnl_tracker = install_best_pnl_tracker()

    try:
        from ui.builder_view import restore_builder_autonomous_ui_state_from_runtime

        explicit_mode = str(st.session_state.get("optimization_mode", "") or "").strip()
        builder_autonomous_flag = bool(
            st.session_state.get("builder_autonomous", False),
        )
        if not explicit_mode or (explicit_mode == "🏗️ Strategy Builder" and not builder_autonomous_flag):
            restore_builder_autonomous_ui_state_from_runtime()
    except Exception:
        pass

    if not BACKEND_AVAILABLE:
        _clear_execution_lock()
        st.error("❌ Backend non disponible")
        st.code(IMPORT_ERROR)
        st.stop()

    run_button, status_container = render_controls()

    try:
        sidebar_state = render_sidebar()
    except Exception as e:
        import traceback

        _clear_execution_lock()
        st.error(f"❌ Exception sidebar: {e}")
        st.code(traceback.format_exc())
        st.stop()

    if sidebar_state is None:
        _clear_execution_lock()
        st.error("❌ Erreur sidebar - rechargez la page")
        st.stop()

    render_exec_tabs(sidebar_state)
    render_primary_action_bar(sidebar_state)
    render_setup_previews(sidebar_state)
    render_main(sidebar_state, run_button, status_container)
    render_results(sidebar_state, best_pnl_tracker)
    render_footer()


if __name__ == "__main__":
    main()
