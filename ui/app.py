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
from ui.theme import apply_theme  # noqa: E402
from utils.observability import init_logging  # noqa: E402

init_logging()


def _render_workspace_navigation(active: str = "app") -> None:
    app_class = "bc-nav-link active" if active == "app" else "bc-nav-link"
    editor_class = "bc-nav-link active" if active == "range_editor" else "bc-nav-link"
    model_stats_class = "bc-nav-link active" if active == "model_stats" else "bc-nav-link"
    indicator_stats_class = (
        "bc-nav-link active" if active == "indicator_stats" else "bc-nav-link"
    )
    results_class = "bc-nav-link active" if active == "results_store" else "bc-nav-link"
    st.sidebar.markdown(
        f"""
<div class="bc-sidebar-nav-block">
    <div class="bc-sidebar-nav-title">Navigation</div>
    <div class="bc-sidebar-nav-links">
        <a class="{app_class}" href="/" target="_self">Application</a>
        <a class="{editor_class}" href="/range_editor_page" target="_self">Éditeur de plages</a>
        <a class="{model_stats_class}" href="/model_stats_page" target="_self">Statistiques des modèles</a>
        <a class="{indicator_stats_class}" href="/indicator_stats_page" target="_self">Indicateurs × Perf</a>
        <a class="{results_class}" href="/results_store_page" target="_self">Hub résultats</a>
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

    # Thème global "Trading desk sombre, accent cyan-teal"
    # (palette + tokens définis dans ui/theme/colors.py, CSS dans ui/theme/streamlit_css.py)
    apply_theme(force=True)


def render_footer() -> None:
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Backtest Core v2.1**")
    optimization_mode = st.session_state.get("optimization_mode", "Backtest Simple")
    if optimization_mode == "Optimisation LLM":
        llm_status = "LLM" if LLM_AVAILABLE else "LLM"
        st.sidebar.caption(f"Architecture découplée UI/Moteur | {llm_status}")
    else:
        st.sidebar.caption("Architecture découplée UI/Moteur")


def main() -> None:
    configure_page()
    _render_workspace_navigation("app")

    best_pnl_tracker = install_best_pnl_tracker()

    try:
        from ui.builder_view import (
            reset_inactive_builder_live_thoughts,
        )

        reset_inactive_builder_live_thoughts(
            reason="app_start",
            respect_session_running=False,
        )
    except Exception:
        pass

    if not BACKEND_AVAILABLE:
        _clear_execution_lock()
        st.error("Backend non disponible")
        st.code(IMPORT_ERROR)
        st.stop()

    run_button, status_container = render_controls()

    try:
        sidebar_state = render_sidebar()
    except Exception as e:
        import traceback

        _clear_execution_lock()
        st.error(f"Exception sidebar: {e}")
        st.code(traceback.format_exc())
        st.stop()

    if sidebar_state is None:
        _clear_execution_lock()
        st.error("Erreur sidebar - rechargez la page")
        st.stop()

    render_exec_tabs(sidebar_state)
    render_primary_action_bar(sidebar_state)
    render_setup_previews(sidebar_state)
    render_main(sidebar_state, run_button, status_container)
    render_results(sidebar_state, best_pnl_tracker)
    render_footer()


if __name__ == "__main__":
    main()
