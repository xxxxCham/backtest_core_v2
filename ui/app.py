"""
Module-ID: ui.app

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

# Charger les variables d'environnement depuis .env
try:
    from dotenv import load_dotenv
    env_path = ROOT_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv non installé, ignorer

import streamlit as st  # noqa: E402

from ui.context import BACKEND_AVAILABLE, IMPORT_ERROR, LLM_AVAILABLE  # noqa: E402
from ui.log_taps import install_best_pnl_tracker  # noqa: E402
from ui.main import render_controls, render_main, render_setup_previews  # noqa: E402
from ui.exec_tabs import render_exec_tabs  # noqa: E402
from ui.results import render_results  # noqa: E402
from ui.sidebar import render_sidebar  # noqa: E402
from utils.observability import init_logging  # noqa: E402

init_logging()


def _clear_execution_lock() -> None:
    """Clear UI execution lock flags to avoid stuck disabled controls."""
    st.session_state.is_running = False
    st.session_state.run_backtest_requested = False
    st.session_state.stop_requested = False


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

    best_pnl_tracker = install_best_pnl_tracker()

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

    render_setup_previews(sidebar_state)
    render_exec_tabs(sidebar_state)
    render_main(sidebar_state, run_button, status_container)
    render_results(sidebar_state, best_pnl_tracker)
    render_footer()


if __name__ == "__main__":
    main()
