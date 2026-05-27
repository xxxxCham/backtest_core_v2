"""Page Streamlit : statistiques indicateur x performance sur l'historique Builder.

Complementaire a `ui.model_stats_view` (focalisee modeles LLM) : ici on regarde
quels indicateurs apparaissent dans les bonnes vs mauvaises strategies, pour
nourrir le prompt systeme du Builder.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from analytics.indicator_stats import (
    Filters,
    available_dimensions,
    cooccurrence_pairs,
    diagnostic_distribution,
    export_prompt_block,
    format_indicator_tables_for_prompt,
    load_iterations,
    per_indicator_stats,
    unexpected_ranking,
)
from backtest.result_store import get_builder_sessions_dir
from config.indicator_history import load_policy, update_policy_field


def _sessions_signature(root: Path) -> tuple[int, float]:
    """Cle de cache : nb de sessions + mtime max racine."""
    if not root.exists():
        return (0, 0.0)
    try:
        names = [n for n in root.iterdir() if n.is_dir() and n.name and n.name[0].isdigit()]
    except OSError:
        return (0, 0.0)
    try:
        latest = max((p.stat().st_mtime for p in names), default=0.0)
    except OSError:
        latest = 0.0
    return (len(names), latest)


@st.cache_data(show_spinner="Chargement de l'historique Builder...", ttl=300)
def _cached_load(signature: tuple[int, float]) -> list[dict[str, Any]]:
    """Cache liste de dicts (les dataclasses ne sont pas hashables au pickling)."""
    rows = load_iterations()
    return [
        {
            "session_id": r.session_id,
            "iteration": r.iteration,
            "indicators_inferred": list(r.indicators_inferred),
            "indicators_declared": list(r.indicators_declared),
            "unexpected": list(r.unexpected),
            "telemetry_score": r.telemetry_score,
            "sharpe": r.sharpe,
            "return_pct": r.return_pct,
            "trades": r.trades,
            "diagnostic_category": r.diagnostic_category,
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "model_name": r.model_name,
            "start_time": r.start_time,
        }
        for r in rows
    ]


def _dicts_to_rows(dicts: list[dict[str, Any]]):
    from analytics.indicator_stats import IterationRow

    return [
        IterationRow(
            session_id=d["session_id"],
            iteration=d["iteration"],
            indicators_inferred=tuple(d["indicators_inferred"]),
            indicators_declared=tuple(d["indicators_declared"]),
            unexpected=tuple(d["unexpected"]),
            telemetry_score=d["telemetry_score"],
            sharpe=d["sharpe"],
            return_pct=d["return_pct"],
            trades=d["trades"],
            diagnostic_category=d["diagnostic_category"],
            symbol=d["symbol"],
            timeframe=d["timeframe"],
            model_name=d["model_name"],
            start_time=d["start_time"],
        )
        for d in dicts
    ]


def _build_filters_panel(dims: dict[str, list[str]]) -> tuple[Filters, str]:
    """UI filtres + mode d'agregat. Retourne (filters, mode)."""
    with st.expander("Filtres", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            symbols = set(
                st.multiselect("Symboles", dims["symbols"], default=[], key="ind_stats_symbols")
            )
        with c2:
            timeframes = set(
                st.multiselect("Timeframes", dims["timeframes"], default=[], key="ind_stats_tfs")
            )
        with c3:
            models = set(
                st.multiselect("Modeles LLM", dims["models"], default=[], key="ind_stats_models")
            )

        c4, c5, c6 = st.columns(3)
        with c4:
            exclude_no_trades = st.checkbox(
                "Exclure no_trades",
                value=True,
                help="73% des iterations finissent sans signal. Garder sauf debug.",
                key="ind_stats_exclude_nt",
            )
        with c5:
            min_trades = st.number_input(
                "Min trades par iteration",
                min_value=0,
                value=1,
                step=1,
                key="ind_stats_min_trades",
            )
        with c6:
            indicator_source = st.radio(
                "Source indicateurs",
                ["inferred", "declared"],
                help="inferred = ce que le LLM utilise reellement dans le code ; "
                "declared = ce qu'il dit utiliser",
                horizontal=True,
                key="ind_stats_src",
            )

        c7, c8, c9 = st.columns(3)
        with c7:
            window = st.selectbox(
                "Periode",
                ["Tout", "30 derniers jours", "7 derniers jours", "24h"],
                key="ind_stats_window",
            )
        with c8:
            mode = st.radio(
                "Mode d'agregat",
                ["iteration", "session_best"],
                help="iteration = toutes les iterations comptent ; "
                "session_best = une seule par session (meilleure)",
                horizontal=True,
                key="ind_stats_mode",
            )
        with c9:
            min_n = st.number_input(
                "Min n par indicateur",
                min_value=1,
                value=20,
                step=5,
                key="ind_stats_min_n",
            )

    start_after = None
    if window != "Tout":
        days = {"30 derniers jours": 30, "7 derniers jours": 7, "24h": 1}[window]
        start_after = datetime.now() - timedelta(days=days)

    filters = Filters(
        symbols=frozenset(symbols),
        timeframes=frozenset(timeframes),
        models=frozenset(models),
        min_trades=int(min_trades),
        exclude_no_trades=bool(exclude_no_trades),
        start_after=start_after,
        indicator_source=indicator_source,  # type: ignore[arg-type]
    )
    return filters, mode


def _render_overview(rows, filters: Filters) -> None:
    """Bandeau de quelques metriques globales."""
    matching = [r for r in rows if filters.matches(r)]
    diags = diagnostic_distribution(rows)
    total = len(rows)
    no_trades = next((d["n"] for d in diags if d["diagnostic"] == "no_trades"), 0)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Iterations totales", f"{total:,}")
    c2.metric("Apres filtres", f"{len(matching):,}")
    c3.metric(
        "Sans trades (no_trades)",
        f"{no_trades:,}",
        delta=f"{round(no_trades/max(total,1)*100,1)}%",
        delta_color="inverse",
    )
    sessions = len({r.session_id for r in matching})
    c4.metric("Sessions distinctes", f"{sessions:,}")


def _render_table_tab(rows, filters: Filters, mode: str, min_n: int) -> None:
    stats = per_indicator_stats(rows, filters=filters, mode=mode, min_n=min_n)  # type: ignore[arg-type]
    if not stats:
        st.warning("Pas assez de donnees apres filtrage. Baisse min_n ou les filtres.")
        return
    df = pd.DataFrame(stats)
    st.caption(
        f"{len(df)} indicateurs avec au moins {min_n} occurrences "
        f"(mode = `{mode}`, source = `{filters.indicator_source}`)"
    )
    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "indicator": st.column_config.TextColumn("Indicateur", width="medium"),
            "n": st.column_config.NumberColumn("n", width="small"),
            "mean_score": st.column_config.NumberColumn("Mean score", format="%.2f"),
            "lift": st.column_config.NumberColumn(
                "Lift vs reste",
                format="%.2f",
                help="Difference de telemetry_score moyen vs iterations sans cet indicateur",
            ),
            "mean_return_pct": st.column_config.NumberColumn("Return %", format="%.1f"),
            "win_rate_pct": st.column_config.NumberColumn("Win %", format="%.1f"),
            "mean_sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f"),
            "share_pct": st.column_config.NumberColumn(
                "Part %",
                format="%.1f",
                help="Part des iterations filtrees ou cet indicateur apparait",
            ),
        },
    )
    st.download_button(
        "Telecharger CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="indicator_stats.csv",
        mime="text/csv",
    )


def _render_cooccurrence_tab(rows, filters: Filters, mode: str) -> None:
    c1, c2 = st.columns([1, 3])
    with c1:
        top_k = st.number_input("Top K", min_value=10, value=50, step=10, key="ind_stats_coocc_k")
        min_n = st.number_input(
            "Min n", min_value=2, value=10, step=2, key="ind_stats_coocc_minn"
        )
    pairs = cooccurrence_pairs(
        rows, filters=filters, mode=mode, min_n=int(min_n), top_k=int(top_k)  # type: ignore[arg-type]
    )
    if not pairs:
        st.warning("Pas assez de paires apres filtrage.")
        return
    df = pd.DataFrame(pairs)
    st.caption(f"Top {len(df)} paires d'indicateurs co-occurrentes, triees par mean_score.")
    st.dataframe(df, hide_index=True, use_container_width=True)


def _render_unexpected_tab(rows, filters: Filters) -> None:
    st.markdown(
        "**Auto-honnetete du LLM** : indicateurs presents dans le code mais "
        "non listes par le LLM dans `used_indicators`. Plus le chiffre est haut, "
        "moins le modele est fiable sur ses propres declarations."
    )
    data = unexpected_ranking(rows, filters=filters, top_k=30)
    if not data:
        st.info("Aucun ecart declare/inferre detecte.")
        return
    df = pd.DataFrame(data)
    st.dataframe(df, hide_index=True, use_container_width=True)


def _render_prompt_export_tab(rows, filters: Filters, mode: str, min_n: int) -> None:
    st.markdown("### Injection automatique dans le prompt Builder")
    policy = load_policy(force_reload=True)
    currently_enabled = bool(policy.get("inject_stats_into_prompt", False))

    col_toggle, col_status = st.columns([2, 3])
    with col_toggle:
        new_value = st.toggle(
            "Injecter les tableaux dans chaque session Builder",
            value=currently_enabled,
            key="ind_stats_inject_toggle",
            help=(
                "ON : a chaque session PROPOSAL, les 3 tableaux ci-dessous sont injectes "
                "dans le prompt LLM (recalcules dynamiquement a partir des sessions existantes). "
                "OFF : aucun bloc injecte. Le flag est persistant (config/indicator_policy.json) "
                "et lu aussi par le builder autonome 24/24."
            ),
        )
    with col_status:
        if currently_enabled:
            st.success("✅ Injection ACTIVE — le bloc est ajoute a chaque session Builder.")
        else:
            st.info("⚪ Injection INACTIVE — les tableaux ne sont pas vus par le LLM.")

    if new_value != currently_enabled:
        update_policy_field("inject_stats_into_prompt", bool(new_value))
        st.toast(
            f"Injection {'activee' if new_value else 'desactivee'}. "
            f"Effet a la prochaine session Builder.",
            icon="✅" if new_value else "🔕",
        )
        st.rerun()

    with st.expander("Reglages avances (persistes dans le policy file)", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            cur_min_n = int(policy.get("inject_stats_min_n_known", 50))
            new_min_n = st.number_input(
                "Seuil n 'eprouve'",
                min_value=10,
                value=cur_min_n,
                step=10,
                key="ind_stats_pol_min_n",
                help="n minimum pour qu'un indicateur soit classe dans le top/flop "
                "(sinon classe en under-explored).",
            )
        with c2:
            cur_top = int(policy.get("inject_stats_top_n", 10))
            new_top = st.number_input(
                "Lignes max par tableau",
                min_value=3,
                value=cur_top,
                step=1,
                key="ind_stats_pol_top_n",
            )
        with c3:
            cur_ctx = bool(policy.get("inject_stats_filter_by_context", False))
            new_ctx = st.checkbox(
                "Filtrer par symbol/timeframe courants",
                value=cur_ctx,
                key="ind_stats_pol_ctx",
                help="Si active, restreint aux stats du couple symbol+timeframe de la session. "
                "Plus pertinent mais moins de volume.",
            )
        if (
            new_min_n != cur_min_n
            or new_top != cur_top
            or new_ctx != cur_ctx
        ):
            if st.button("Appliquer les reglages avances", key="ind_stats_pol_apply"):
                update_policy_field("inject_stats_min_n_known", int(new_min_n))
                update_policy_field("inject_stats_top_n", int(new_top))
                update_policy_field("inject_stats_filter_by_context", bool(new_ctx))
                st.toast("Reglages persistes.", icon="✅")
                st.rerun()

    st.markdown("---")
    st.markdown("### Apercu du bloc injecte (recalcule en direct)")
    preview = format_indicator_tables_for_prompt(
        rows,
        filters=filters,
        mode=mode,  # type: ignore[arg-type]
        top_n=int(policy.get("inject_stats_top_n", 10)),
        flop_n=int(policy.get("inject_stats_top_n", 10)),
        min_n_known=int(policy.get("inject_stats_min_n_known", 50)),
    )
    if preview:
        st.code(preview, language="markdown")
        st.caption(
            f"Bloc final : {len(preview)} caracteres "
            f"(~{len(preview.split())} mots). Mode = `{mode}`, source = `{filters.indicator_source}`."
        )
    else:
        st.warning("Pas assez de donnees pour generer un bloc avec les filtres actuels.")

    st.markdown("---")
    with st.expander("Variante legacy : bloc directif 'Prefer/Avoid' (non recommande)"):
        st.caption(
            "Format directif (autoritaire) plutot que tableaux bruts. "
            "A eviter : risque de boucle d'auto-renforcement."
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            top_n = st.number_input(
                "Nb a recommander", min_value=1, value=5, key="ind_stats_legacy_top_n"
            )
        with c2:
            flop_n = st.number_input(
                "Nb a deconseiller", min_value=1, value=5, key="ind_stats_legacy_flop_n"
            )
        with c3:
            min_lift = st.number_input(
                "Lift minimum",
                min_value=0.0,
                value=1.0,
                step=0.5,
                key="ind_stats_legacy_min_lift",
            )
        stats = per_indicator_stats(rows, filters=filters, mode=mode, min_n=min_n)  # type: ignore[arg-type]
        legacy_block = export_prompt_block(
            stats, top_n=int(top_n), flop_n=int(flop_n), min_lift=float(min_lift)
        )
        st.code(legacy_block, language="markdown")


def render_indicator_stats_page() -> None:
    st.title("📈 Statistiques indicateur × performance")
    st.caption(
        "Agregat cross-sessions du Strategy Builder. "
        "Identifie quels indicateurs sont sur/sous-representes dans les bonnes strategies."
    )

    root = get_builder_sessions_dir()
    signature = _sessions_signature(root)
    if signature[0] == 0:
        st.warning(f"Aucune session trouvee dans {root}.")
        return

    rows_dicts = _cached_load(signature)
    rows = _dicts_to_rows(rows_dicts)

    dims = available_dimensions(rows)
    filters, mode = _build_filters_panel(dims)

    _render_overview(rows, filters)
    st.markdown("---")

    tabs = st.tabs(
        ["📊 Tableau", "🔗 Co-occurrence", "🎭 Auto-honnetete LLM", "💉 Export prompt"]
    )
    min_n = int(st.session_state.get("ind_stats_min_n", 20))

    with tabs[0]:
        _render_table_tab(rows, filters, mode, min_n)
    with tabs[1]:
        _render_cooccurrence_tab(rows, filters, mode)
    with tabs[2]:
        _render_unexpected_tab(rows, filters)
    with tabs[3]:
        _render_prompt_export_tab(rows, filters, mode, min_n)


__all__ = ["render_indicator_stats_page"]
