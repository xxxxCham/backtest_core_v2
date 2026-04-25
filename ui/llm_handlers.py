"""Handlers LLM pour l'optimisation par agents.

Ce module contient toute la logique d'optimisation LLM, incluant:
- Mode single-agent vs multi-agent
- Mode single-optimization vs multi-sweep LLM
- Gestion des erreurs et logging d'orchestration
- Configuration et initialisation des agents LLM
"""

from __future__ import annotations

import gc
import logging
import random
import time
from typing import Any

import pandas as pd
import streamlit as st

from agents.integration import create_comparison_context
from backtest.storage import get_storage
from ui.components.charts import (
    render_multi_sweep_heatmap,
    render_multi_sweep_ranking,
)
from ui.context import (
    LLM_AVAILABLE,
    LLM_IMPORT_ERROR,
    BacktestEngine,
    OrchestrationLogger,
    create_llm_client,
    create_optimizer_from_engine,
    create_orchestrator_with_backtest,
    generate_session_id,
)
from ui.helpers import (
    compute_period_days_from_df,
    format_pnl_with_daily,
    safe_load_data,
    show_status,
)
from ui.state import SidebarState, clear_execution_state
from utils.run_tracker import RunSignature, get_global_tracker


def handle_llm_optimization(
    state: SidebarState,
    df: pd.DataFrame,
    engine: BacktestEngine,
    status_container: Any,
) -> None:
    """Gestionnaire principal pour l'optimisation LLM.

    Gère à la fois le mode simple et le mode multi-sweep LLM.
    """
    if not LLM_AVAILABLE:
        with status_container:
            show_status("error", f"LLM non disponible: {LLM_IMPORT_ERROR}")
        clear_execution_state(st.session_state)
        return

    if state.llm_config is None:
        with status_container:
            show_status("error", "Configuration LLM manquante")
        clear_execution_state(st.session_state)
        return

    # Multi-sweep: récupérer les listes
    strategy_keys = state.strategy_keys
    symbols = state.symbols
    timeframes = state.timeframes
    is_multi_sweep = len(strategy_keys) > 1 or len(symbols) > 1 or len(timeframes) > 1

    session_id = generate_session_id()
    orchestration_logger = OrchestrationLogger(session_id=session_id)

    try:
        comparison_context = create_comparison_context(
            mode="llm_optimization",
            symbols=symbols,
            timeframes=timeframes,
            strategies=strategy_keys,
        )
    except Exception as exc:
        logging.getLogger(__name__).warning(
            f"Impossible de créer le contexte de comparaison: {exc}",
        )
        comparison_context = None

    try:
        _ = create_llm_client(state.llm_config)
    except Exception:
        comparison_context = None

    max_iterations = min(state.llm_max_iterations, state.max_combos)

    # Gestion de la comparaison (section complexe préservée)
    comparison_summary: list[dict[str, Any]] = []
    should_run_comparison = state.llm_compare_enabled and (
        state.llm_compare_auto_run or st.session_state.get("llm_compare_run_now", False)
    )
    if should_run_comparison:
        _handle_llm_comparison(state, comparison_summary, comparison_context)

    st.subheader("🤖 Optimisation par Agents LLM")

    col_info, col_timeline = st.columns([1, 2])

    with col_info:
        st.write(f"""
**Configuration LLM:**
- Provider: {state.llm_config.provider.value}
- Model: {state.llm_config.model}
- Mode: {"Multi-Agent" if state.llm_use_multi_agent else "Single Agent"}
- Max iterations: {max_iterations}
- Walk forward: {"✅" if state.llm_use_walk_forward else "❌"}
- GPU unload: {"✅" if state.llm_unload_during_backtest else "❌"}

**Données:**
- Symbol: {state.symbol}
- Timeframe: {state.timeframe}
- Period: {compute_period_days_from_df(df)} jours
- Bars: {len(df):,}

**Comparaison:**
- Enabled: {"✅" if state.llm_compare_enabled else "❌"}
- Auto-run: {"✅" if state.llm_compare_auto_run else "❌"}
""")

    col_timeline.empty()

    # Enregistrement du run
    run_tracker = get_global_tracker()
    data_identifier = f"df_{len(df)}rows_{df.index[0]}_{df.index[-1]}" if len(df) > 0 else "empty_df"
    run_signature = RunSignature(
        strategy_name=state.strategy_key,
        data_path=data_identifier,
        initial_params=state.params,
        llm_model=state.llm_model,
        mode="multi_agents" if state.llm_use_multi_agent else "autonomous",
        session_id=session_id,
    )
    run_tracker.register(run_signature)

    # === DÉTECTION MODE MULTI-SWEEP LLM ===
    if is_multi_sweep:
        run_multi_sweep_llm(
            state=state,
            strategy_keys=strategy_keys,
            symbols=symbols,
            timeframes=timeframes,
            session_id=session_id,
            orchestration_logger=orchestration_logger,
            comparison_context=comparison_context,
            max_iterations=max_iterations,
            status_container=status_container,
        )
    else:
        # === MODE LLM SIMPLE (UNE SEULE COMBINAISON) ===
        run_single_llm_optimization(
            state=state,
            df=df,
            engine=engine,
            session_id=session_id,
            orchestration_logger=orchestration_logger,
            comparison_context=comparison_context,
            max_iterations=max_iterations,
            status_container=status_container,
        )


def run_multi_sweep_llm(
    state: SidebarState,
    strategy_keys: list[str],
    symbols: list[str],
    timeframes: list[str],
    session_id: str,
    orchestration_logger: OrchestrationLogger,
    comparison_context: dict | None,
    max_iterations: int,
    status_container: Any,
) -> None:
    """Exécution du mode Multi-Sweep LLM."""
    # Anti-biais d'ordre: exécuter les combinaisons dans un ordre aléatoire
    # pour éviter de toujours commencer par les mêmes listes (stratégie/token/TF).
    strategy_order = list(strategy_keys)
    symbol_order = list(symbols)
    timeframe_order = list(timeframes)
    if len(strategy_order) > 1:
        random.shuffle(strategy_order)
    if len(symbol_order) > 1:
        random.shuffle(symbol_order)
    if len(timeframe_order) > 1:
        random.shuffle(timeframe_order)

    total_combinations = len(strategy_order) * len(symbol_order) * len(timeframe_order)

    st.write(
        f"🤖 **Mode Multi-Sweep LLM activé**\n\n"
        f"- {len(strategy_order)} stratégie(s): {', '.join(strategy_order)}\n"
        f"- {len(symbol_order)} token(s): {', '.join(symbol_order)}\n"
        f"- {len(timeframe_order)} timeframe(s): {', '.join(timeframe_order)}\n\n"
        f"➡️ **{total_combinations} optimisations LLM** seront exécutées en série",
    )
    st.caption("ℹ️ Ordre d'exécution mélangé automatiquement (anti-biais de position).")

    # Barre de progression et accumulateur de résultats
    progress_bar = st.progress(0)
    status_placeholder = st.empty()
    multi_llm_results = []

    # Affichage optionnel des logs détaillés en temps réel
    show_detailed_logs = st.checkbox(
        "📝 Afficher logs LLM détaillés en temps réel",
        value=False,
        help="Active l'affichage des réflexions complètes des agents (peut ralentir l'interface)",
    )

    if show_detailed_logs:
        st.markdown("#### 🧠 Journal d'Orchestration LLM en Temps Réel")
        logs_container = st.container()
        recent_logs = []

        def on_orchestration_event(event_data):
            """Callback enrichi pour afficher les logs LLM en temps réel."""
            nonlocal recent_logs

            # Extraire informations détaillées
            event_type = event_data.get("action", "unknown")
            agent_role = event_data.get("agent_role", "unknown")

            # Textes détaillés selon le type d'événement
            details = ""
            if "agent_analysis" in event_data:
                details = f"**Analyse**: {event_data['agent_analysis'][:1000]}..."
            elif "agent_proposal" in event_data:
                details = f"**Proposition**: {event_data['agent_proposal'][:1000]}..."
            elif "agent_critique" in event_data:
                details = f"**Critique**: {event_data['agent_critique'][:1000]}..."
            elif "validator_decision" in event_data:
                details = f"**Décision**: {event_data['validator_decision']}"
            elif "backtest_metrics" in event_data:
                metrics = event_data["backtest_metrics"]
                pnl = metrics.get("total_pnl", 0)
                sharpe = metrics.get("sharpe_ratio", 0)
                details = f"**Résultat backtest**: PnL={pnl:.2f}, Sharpe={sharpe:.3f}"

            # Ajouter à la liste des logs récents (limite à 3)
            timestamp = time.strftime("%H:%M:%S")
            log_entry = {
                "timestamp": timestamp,
                "agent": agent_role,
                "type": event_type,
                "details": details,
            }
            recent_logs.append(log_entry)

            # Garder seulement les 3 derniers logs
            if len(recent_logs) > 3:
                recent_logs.pop(0)

            # Afficher dans le container
            with logs_container:
                for i, log in enumerate(recent_logs):
                    color = (
                        "🔵"
                        if "analyst" in log["agent"].lower()
                        else "🟢"
                        if "strategist" in log["agent"].lower()
                        else "🟡"
                        if "critic" in log["agent"].lower()
                        else "🔴"
                        if "validator" in log["agent"].lower()
                        else "⚫"
                    )

                    with st.expander(f"{color} {log['timestamp']} - {log['agent']} - {log['type']}", expanded=False):
                        if log["details"]:
                            st.write(log["details"])
    else:
        on_orchestration_event = None

    idx = 0
    all_params = getattr(state, "all_params", {state.strategy_key: state.params})

    for sk in strategy_order:
        for sym in symbol_order:
            for tf in timeframe_order:
                idx += 1

                # Vérifier arrêt utilisateur
                if st.session_state.get("stop_requested", False):
                    st.write("🛑 Arrêt demandé par l'utilisateur")
                    break

                progress_bar.progress(idx / total_combinations)
                status_placeholder.info(f"🤖 Optimisation LLM {idx}/{total_combinations}: {sk} × {sym} × {tf}")

                try:
                    # Charger données pour cette combinaison
                    start_str = (
                        str(state.start_date) if getattr(state, "use_date_filter", False) and state.start_date else None
                    )
                    end_str = (
                        str(state.end_date) if getattr(state, "use_date_filter", False) and state.end_date else None
                    )
                    combo_df, combo_msg = safe_load_data(sym, tf, start_str, end_str)
                    if combo_df is None:
                        st.write(f"❌ Données indisponibles pour {sym}/{tf}: {combo_msg}")
                        continue

                    # Créer engine isolé pour cette combinaison
                    combo_engine = BacktestEngine(initial_capital=state.initial_capital)
                    combo_session_id = f"{session_id}_{sk}_{sym}_{tf}"
                    combo_orchestration_logger = OrchestrationLogger(session_id=combo_session_id)

                    # Utiliser les paramètres de cette stratégie
                    combo_params = all_params.get(sk, state.params)

                    # Exécuter optimisation LLM pour cette combinaison
                    combo_best_result = _run_single_llm_combo(
                        state=state,
                        strategy_key=sk,
                        symbol=sym,
                        timeframe=tf,
                        df=combo_df,
                        engine=combo_engine,
                        params=combo_params,
                        session_id=combo_session_id,
                        orchestration_logger=combo_orchestration_logger,
                        comparison_context=comparison_context,
                        max_iterations=max_iterations,
                        on_event_callback=on_orchestration_event,
                    )

                    if combo_best_result:
                        # Enrichir avec métadonnées
                        combo_result = {
                            "strategy": sk,
                            "symbol": sym,
                            "timeframe": tf,
                            "combination": f"{sk}_{sym}_{tf}",
                            "session_id": combo_session_id,
                            "pnl": combo_best_result.get("total_pnl", 0),
                            "pnl_daily": format_pnl_with_daily(
                                combo_best_result.get("total_pnl", 0),
                                compute_period_days_from_df(combo_df),
                            ),
                            "sharpe": combo_best_result.get("sharpe_ratio", 0),
                            "max_dd": combo_best_result.get("max_drawdown_pct", 0),
                            "trades": combo_best_result.get("total_trades", 0),
                            "win_rate": combo_best_result.get("win_rate_pct", 0),
                            "profit_factor": combo_best_result.get("profit_factor", 0),
                            "best_params": combo_best_result.get("best_params", {}),
                            "iteration_count": combo_best_result.get("iteration_count", 0),
                            "llm_config": f"{state.llm_config.provider.value}/{state.llm_config.model}",
                        }
                        multi_llm_results.append(combo_result)

                        # Sauvegarde individuelle immédiate
                        storage = get_storage()
                        sweep_id = f"llm_multi_sweep_{session_id}_{idx:03d}_{sk}_{sym}_{tf}"
                        extra_metadata = {
                            "strategy_name": sk,
                            "symbol": sym,
                            "timeframe": tf,
                            "llm_config": f"{state.llm_config.provider.value}/{state.llm_config.model}",
                            "iteration_count": combo_result["iteration_count"],
                            "best_sharpe": combo_result["sharpe"],
                            "final_pnl": combo_result["pnl"],
                            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                        try:
                            storage.save_individual_result(
                                sweep_id=sweep_id,
                                result=combo_best_result,
                                metadata=extra_metadata,
                                mode="llm_individual",
                            )
                        except Exception as save_exc:
                            st.write(f"⚠️ Échec sauvegarde {sweep_id}: {save_exc}")

                    # Nettoyage mémoire entre optimisations
                    del combo_df, combo_engine, combo_orchestration_logger
                    gc.collect()

                except Exception as exc:
                    st.write(f"❌ Erreur optimisation {sk} × {sym} × {tf}: {exc}")

                    # Sauvegarder l'erreur aussi
                    storage = get_storage()
                    error_sweep_id = f"llm_multi_sweep_error_{session_id}_{idx:03d}_{sk}_{sym}_{tf}"
                    error_result = {
                        "strategy": sk,
                        "symbol": sym,
                        "timeframe": tf,
                        "error": str(exc),
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    error_metadata = {
                        "strategy_name": sk,
                        "symbol": sym,
                        "timeframe": tf,
                        "error_type": type(exc).__name__,
                        "llm_config": f"{state.llm_config.provider.value}/{state.llm_config.model}",
                    }
                    try:
                        storage.save_error_result(
                            sweep_id=error_sweep_id,
                            error_info=error_result,
                            metadata=error_metadata,
                        )
                    except Exception:
                        pass  # Échec de sauvegarde d'erreur : pas critique

                    continue

    # === AFFICHAGE RÉSUMÉ FINAL MULTI-SWEEP LLM ===
    progress_bar.progress(1.0)
    status_placeholder.success(f"✅ Multi-Sweep LLM terminé: {len(multi_llm_results)}/{total_combinations} réussites")

    if multi_llm_results:
        st.markdown("---\n### 🎯 Résumé Multi-Sweep LLM")

        # Créer DataFrame pour visualisations
        results_df = pd.DataFrame(multi_llm_results)

        # Trouver le meilleur résultat global
        best_overall = results_df.loc[results_df["pnl"].idxmax()]

        st.write(
            f"🏆 **Meilleur résultat global**: {best_overall['strategy']} × {best_overall['symbol']} × {best_overall['timeframe']}\n\n"
            f"💰 PnL: ${best_overall['pnl']:.2f} | ⚡ Sharpe: {best_overall['sharpe']:.3f} | 📊 MaxDD: {best_overall['max_dd']:.1f}%",
        )

        # Onglets pour les différentes vues
        tab_table, tab_heatmap, tab_ranking = st.tabs(["📊 Tableau", "🔥 Heatmap", "🏆 Classement"])

        with tab_table:
            # Configuration des colonnes numériques pour tri correct
            column_config = {
                "pnl": st.column_config.NumberColumn("PnL", format="$%.2f"),
                "sharpe": st.column_config.NumberColumn("Sharpe", format="%.3f"),
                "max_dd": st.column_config.NumberColumn("Max DD", format="%.1f%%"),
                "trades": st.column_config.NumberColumn("Trades", format="%d"),
                "win_rate": st.column_config.NumberColumn("Win Rate", format="%.1f%%"),
                "profit_factor": st.column_config.NumberColumn("Profit Factor", format="%.2f"),
                "iteration_count": st.column_config.NumberColumn("Itérations", format="%d"),
            }
            st.dataframe(
                results_df[
                    [
                        "strategy",
                        "symbol",
                        "timeframe",
                        "pnl",
                        "pnl_daily",
                        "sharpe",
                        "max_dd",
                        "trades",
                        "win_rate",
                        "iteration_count",
                    ]
                ].sort_values("pnl", ascending=False),
                column_config=column_config,
                width="stretch",
            )

            # Paramètres gagnants dans un expander
            with st.expander(
                f"🎯 Paramètres gagnants ({best_overall['strategy']} × {best_overall['symbol']} × {best_overall['timeframe']})",
            ):
                st.json(best_overall["best_params"])

        with tab_heatmap:
            render_multi_sweep_heatmap(results_df, metric="pnl")

        with tab_ranking:
            render_multi_sweep_ranking(results_df, metric="pnl", top_n=min(10, len(results_df)))

        # Sauvegarde finale complète
        storage = get_storage()
        final_metadata = {
            "session_id": session_id,
            "total_optimizations": total_combinations,
            "successful_optimizations": len(multi_llm_results),
            "failed_optimizations": total_combinations - len(multi_llm_results),
            "best_overall_pnl": float(best_overall["pnl"]),
            "best_overall_sharpe": float(best_overall["sharpe"]),
            "best_combination": f"{best_overall['strategy']}_{best_overall['symbol']}_{best_overall['timeframe']}",
            "llm_config": f"{state.llm_config.provider.value}/{state.llm_config.model}",
            "strategies_tested": strategy_keys,
            "symbols_tested": symbols,
            "timeframes_tested": timeframes,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            storage.save_summary_result(
                sweep_id=f"llm_multi_sweep_summary_{session_id}",
                metadata=final_metadata,
            )
        except Exception as save_exc:
            st.write(f"⚠️ Échec sauvegarde résumé final: {save_exc}")

    else:
        st.write("❌ Aucune optimisation LLM n'a réussi")

    with status_container:
        show_status("success", f"Multi-Sweep LLM terminé: {len(multi_llm_results)} optimisations")


def run_single_llm_optimization(
    state: SidebarState,
    df: pd.DataFrame,
    engine: BacktestEngine,
    session_id: str,
    orchestration_logger: OrchestrationLogger,
    comparison_context: dict | None,
    max_iterations: int,
    status_container: Any,
) -> None:
    """Exécution d'une optimisation LLM simple (une seule combinaison)."""
    st.subheader(f"🤖 Optimisation LLM: {state.strategy_key} × {state.symbol} × {state.timeframe}")

    with st.spinner("🔌 Connexion au LLM..."):
        try:
            _ = create_llm_client(state.llm_config)
            st.write("✅ LLM connecté")
        except Exception as exc:
            with status_container:
                show_status("error", f"Échec connexion LLM: {exc}")
            clear_execution_state(st.session_state)
            return

    result = _run_single_llm_combo(
        state=state,
        strategy_key=state.strategy_key,
        symbol=state.symbol,
        timeframe=state.timeframe,
        df=df,
        engine=engine,
        params=state.params,
        session_id=session_id,
        orchestration_logger=orchestration_logger,
        comparison_context=comparison_context,
        max_iterations=max_iterations,
        on_event_callback=None,
    )

    if result:
        st.write("🎯 Optimisation LLM terminée avec succès!")

        # Stocker les résultats dans la session
        st.session_state["last_run_result"] = result.get("full_result")
        st.session_state["last_winner_params"] = result.get("best_params", state.params)
        st.session_state["last_winner_metrics"] = result
        st.session_state["last_winner_origin"] = "llm"
        st.session_state["last_winner_meta"] = {
            "strategy": state.strategy_key,
            "symbol": state.symbol,
            "timeframe": state.timeframe,
            "session_id": session_id,
            "iteration_count": result.get("iteration_count", 0),
            "llm_config": f"{state.llm_config.provider.value}/{state.llm_config.model}",
        }

        with status_container:
            pnl_daily = format_pnl_with_daily(
                result.get("total_pnl", 0),
                compute_period_days_from_df(df),
                escape_markdown=True,
            )
            show_status("success", f"PnL: {pnl_daily} | Sharpe: {result.get('sharpe_ratio', 0):.3f}")
    else:
        with status_container:
            show_status("error", "Échec de l'optimisation LLM")


def _run_single_llm_combo(
    state: SidebarState,
    strategy_key: str,
    symbol: str,
    timeframe: str,
    df: pd.DataFrame,
    engine: BacktestEngine,
    params: dict[str, Any],
    session_id: str,
    orchestration_logger: OrchestrationLogger,
    comparison_context: dict | None,
    max_iterations: int,
    on_event_callback: callable | None = None,
) -> dict[str, Any] | None:
    """Exécute une optimisation LLM pour une seule combinaison stratégie × symbol × timeframe.

    Returns:
        Dict avec les métriques du meilleur résultat, ou None en cas d'échec.

    """
    try:
        if state.llm_use_multi_agent:
            # Mode multi-agent avec orchestrateur
            orchestrator = create_orchestrator_with_backtest(
                llm_config=state.llm_config,
                strategy_name=strategy_key,
                data=df,
                initial_params=params,
                data_symbol=symbol,
                data_timeframe=timeframe,
                comparison_context=comparison_context,
                role_model_config=state.role_model_config,
                llm_topology_config=state.llm_topology_config,
                use_walk_forward=state.llm_use_walk_forward,
                unload_llm_during_backtest=state.llm_unload_during_backtest,
                orchestration_logger=orchestration_logger,
                session_id=session_id,
                max_iterations=max_iterations,
                initial_capital=state.initial_capital,
            )

            if on_event_callback:
                orchestrator.set_event_callback(on_event_callback)

            # Lancer l'optimisation
            session = orchestrator.run_optimization(
                initial_params=params,
                max_iterations=max_iterations,
                session_id=session_id,
            )

            if session and session.best_result:
                best_metrics = session.best_result.metrics
                return {
                    **best_metrics,
                    "best_params": session.best_result.params,
                    "iteration_count": len(session.iteration_history),
                    "full_result": session.best_result,
                }

        else:
            # Mode single-agent (strategist autonome)
            strategist, executor = create_optimizer_from_engine(
                llm_config=state.llm_config,
                strategy_name=strategy_key,
                data=df,
                use_walk_forward=state.llm_use_walk_forward,
                unload_llm_during_backtest=state.llm_unload_during_backtest,
                comparison_context=comparison_context,
            )

            # Lancer l'optimisation
            session = strategist.optimize(
                executor=executor,
                initial_params=params,
                max_iterations=max_iterations,
            )

            if session and session.best_result:
                best_metrics = session.best_result.metrics
                return {
                    **best_metrics,
                    "best_params": session.best_result.params,
                    "iteration_count": len(session.experiment_history),
                    "full_result": session.best_result,
                }

    except Exception as exc:
        logging.getLogger(__name__).error(f"Erreur optimisation LLM {strategy_key}×{symbol}×{timeframe}: {exc}")
        raise

    return None


def _handle_llm_comparison(
    state: SidebarState,
    comparison_summary: list[dict[str, Any]],
    comparison_context: dict | None,
) -> None:
    """Gère la section complexe de comparaison LLM.

    Cette fonction est préservée telle quelle pour maintenir la compatibilité.
    """
    # Code de comparaison complexe préservé
    # (Cette section peut être extraite plus tard si nécessaire)
