"""
Module-ID: agents.builder_loop

Purpose: Internal Builder V2 iteration loop.

This module is imported lazily from `StrategyBuilder.run()` to keep the public
facade stable while moving the orchestration logic out of
`agents.strategy_builder`.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

import pandas as pd

from agents.builder_policy import (
    DecisionPolicyFeedback,
    PolicyRestriction,
    evaluate_decision_policies,
    evaluate_positive_progress_gate,
)
from agents.builder_state import BuilderIteration
from agents.strategy_builder import (
    MAX_CONSECUTIVE_FAILURES,
    MAX_DETERMINISTIC_FALLBACKS,
    _builder_iteration_selection_key,
    _build_deterministic_proposal_fallback,
    _build_stagnation_branch_specs,
    _is_accept_candidate,
    _is_invalid_proposal,
    _metric_float,
    _metrics_fingerprint,
    _normalize_change_type,
    _policy_change_type_override,
    _previous_iteration_indicators,
    _proposal_issues,
    _safe_format_exception,
    _sanitize_proposal_payload,
    _select_best_branch_candidate,
    _should_enable_stagnation_branching,
    compute_builder_telemetry_score,
    compute_diagnostic,
    logger,
)


def _record_policy_restrictions(
    builder: Any,
    iteration_trace: Any,
    restrictions: List[PolicyRestriction],
) -> None:
    for restriction in restrictions:
        builder.instrumentation.record_restriction(
            iteration_trace,
            restriction.name,
            effect=restriction.effect,
            phase=restriction.phase,
        )


def run_builder_loop_v2(
    builder: Any,
    *,
    session: Any,
    data: pd.DataFrame,
    initial_capital: float,
    thought_stream: Any,
) -> Any:
    session_id = session.session_id
    max_iterations = session.max_iterations
    last_iteration: Optional[BuilderIteration] = None
    consecutive_failures = 0
    fallback_count = 0  # compteur de fallbacks déterministes dans la session

    for i in range(1, max_iterations + 1):
        iteration = BuilderIteration(iteration=i)
        # ── Instrumentation: début d'itération ──
        _itrace = builder.instrumentation.begin_iteration(i, session_id)
        _itrace.ablation_config = dict(builder.ablation.get_config())
        builder._emit_progress(
            "iteration_start",
            iteration=i,
            max_iterations=max_iterations,
        )
        thought_stream.iteration_start(i, max_iterations)

        # ── Circuit breaker ──
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            recovered, last_iteration, consecutive_failures, fallback_count, reset_event = (
                builder._attempt_session_auto_reset(
                    session,
                    iteration_num=i,
                    trigger="consecutive_failures",
                    reason=(
                        f"{consecutive_failures} échecs consécutifs "
                        f"(seuil={MAX_CONSECUTIVE_FAILURES})"
                    ),
                    last_iteration=last_iteration,
                    consecutive_failures=consecutive_failures,
                    fallback_count=fallback_count,
                )
            )
            if recovered:
                iteration.phase_feedback.setdefault("session_reset", {}).update(
                    reset_event
                )
                thought_stream.warning(
                    "Auto-reset Builder: reprise sur le meilleur ancrage stable "
                    "disponible avant nouvelle tentative."
                )
            else:
                thought_stream.circuit_breaker(consecutive_failures, MAX_CONSECUTIVE_FAILURES)
                logger.warning(
                    "builder_circuit_breaker consecutive=%d",
                    consecutive_failures,
                )
                session.status = "failed"
                break

        # ── Circuit breaker fallback ──
        if fallback_count >= MAX_DETERMINISTIC_FALLBACKS:
            recovered, last_iteration, consecutive_failures, fallback_count, reset_event = (
                builder._attempt_session_auto_reset(
                    session,
                    iteration_num=i,
                    trigger="deterministic_fallbacks",
                    reason=(
                        f"{fallback_count} fallbacks déterministes "
                        f"(seuil={MAX_DETERMINISTIC_FALLBACKS})"
                    ),
                    last_iteration=last_iteration,
                    consecutive_failures=consecutive_failures,
                    fallback_count=fallback_count,
                )
            )
            if recovered:
                iteration.phase_feedback.setdefault("session_reset", {}).update(
                    reset_event
                )
                thought_stream.warning(
                    "Auto-reset Builder: saturation fallback détectée, "
                    "redémarrage sur une base plus saine."
                )
            else:
                thought_stream.warning(
                    f"Arrêt: {fallback_count} fallbacks déterministes utilisés. "
                    "Le LLM ne parvient pas à générer du code valide pour cette API."
                )
                logger.warning(
                    "builder_fallback_circuit_breaker count=%d",
                    fallback_count,
                )
                session.status = "failed"
                break

        try:
            # ── Phase 1 : Proposition ──
            logger.info("builder_iter_%d_proposal", i)
            builder._emit_progress("phase_start", iteration=i, phase="proposal")
            prev_metrics: Optional[Dict[str, Any]] = (
                dict(last_iteration.backtest_result.metrics)
                if last_iteration is not None
                and last_iteration.backtest_result is not None
                and isinstance(getattr(last_iteration.backtest_result, "metrics", None), dict)
                else None
            )
            thought_stream.proposal_sent(
                has_previous=last_iteration is not None,
                prev_metrics=prev_metrics,
            )
            t0 = time.perf_counter()
            proposal, proposal_feedback = builder._ask_proposal(
                session, last_iteration
            )
            proposal_feedback = dict(proposal_feedback or {})
            iteration.phase_feedback["proposal"] = proposal_feedback
            dt_proposal = time.perf_counter() - t0

            # Garde : proposition vide → retry avec prompt simplifié
            if _is_invalid_proposal(proposal):
                thought_stream.warning(
                    "Proposition invalide après retry contractuel — fallback déterministe"
                )
                issues = _proposal_issues(proposal)
                proposal_feedback["issues_after_retry"] = issues
                proposal = _build_deterministic_proposal_fallback(
                    objective=session.objective,
                    available_indicators=builder.available_indicators,
                    last_iteration=last_iteration,
                )
                proposal = _sanitize_proposal_payload(
                    proposal,
                    available_indicators=builder.available_indicators,
                    objective=session.objective,
                    direction_constraint=session.direction_constraint,
                )
                proposal_feedback["fallback_deterministic_used"] = True
                proposal_feedback["source"] = "deterministic_fallback"
                iteration.phase_feedback["proposal"] = proposal_feedback
                if builder.instrumentation.enabled:
                    builder.instrumentation.record_restriction(
                        _itrace,
                        "proposal_fallback",
                        effect="helper",
                        phase="proposal",
                    )

            branch_specs: List[Dict[str, str]] = []
            proposal_candidates: List[Dict[str, Any]] = []
            if (
                _should_enable_stagnation_branching(last_iteration)
                and builder.ablation.is_enabled("stagnation_branching")
            ):
                branch_specs = _build_stagnation_branch_specs(
                    _previous_iteration_indicators(last_iteration)
                )
                for spec in branch_specs:
                    candidate_proposal, candidate_feedback = builder._ask_proposal(
                        session,
                        last_iteration,
                        branch_directive=spec["directive"],
                    )
                    proposal_candidates.append(
                        {
                            "branch_label": spec["label"],
                            "proposal": candidate_proposal,
                            "proposal_feedback": candidate_feedback,
                        }
                    )
                iteration.phase_feedback["proposal"] = {
                    "phase": "proposal",
                    "branching_enabled": True,
                    "branch_labels": [spec["label"] for spec in branch_specs],
                }
                if builder.instrumentation.enabled:
                    builder.instrumentation.record_restriction(
                        _itrace,
                        "stagnation_branching",
                        effect="helper",
                        phase="proposal",
                        metadata={"branches": len(branch_specs)},
                    )
                proposal = proposal_candidates[0]["proposal"]
            else:
                proposal_candidates.append(
                    {
                        "branch_label": "main",
                        "proposal": proposal,
                        "proposal_feedback": proposal_feedback,
                    }
                )
                proposal["change_type"] = _normalize_change_type(
                    proposal.get("change_type", "logic")
                )
                policy_ct = _policy_change_type_override(
                    session=session,
                    last_iteration=last_iteration,
                )
                if policy_ct and proposal["change_type"] != policy_ct:
                    proposal_feedback["change_type_overridden"] = {
                        "from": proposal["change_type"],
                        "to": policy_ct,
                        "reason": "diagnostic_policy",
                    }
                    iteration.phase_feedback["proposal"] = proposal_feedback
                    logger.info(
                        "builder_iter_%d_change_type_overridden from=%s to=%s",
                        i,
                        proposal["change_type"],
                        policy_ct,
                    )
                    proposal["change_type"] = policy_ct

            for candidate in proposal_candidates:
                candidate_used = candidate["proposal"].get("used_indicators", [])
                unknown = [
                    ind for ind in candidate_used
                    if ind.lower() not in (x.lower() for x in builder.available_indicators)
                ]
                if unknown:
                    logger.warning("builder_unknown_indicators unknown=%s", unknown)
                    candidate["proposal"]["used_indicators"] = [
                        ind for ind in candidate_used
                        if ind.lower() in (x.lower() for x in builder.available_indicators)
                    ]

            builder._emit_progress(
                "phase_done",
                iteration=i,
                phase="proposal",
                hypothesis=proposal.get("hypothesis", f"Itération {i}"),
            )
            thought_stream.proposal_received(proposal, dt_proposal)

            logger.info("builder_iter_%d_codegen", i)
            builder._emit_progress("phase_start", iteration=i, phase="code")
            thought_stream.codegen_sent()
            t0 = time.perf_counter()

            branch_outcomes: List[Dict[str, Any]] = []
            for candidate in proposal_candidates:
                candidate_outcome, fallback_count = builder._execute_proposal_candidate(
                    session=session,
                    proposal=candidate["proposal"],
                    proposal_feedback=candidate["proposal_feedback"],
                    last_iteration=last_iteration,
                    iteration_num=i,
                    data=data,
                    initial_capital=initial_capital,
                    fallback_count=fallback_count,
                    branch_label=candidate["branch_label"],
                )
                branch_outcomes.append(candidate_outcome)

            selected_outcome = _select_best_branch_candidate(branch_outcomes)
            if not selected_outcome or selected_outcome.get("error"):
                iteration.error = (selected_outcome or {}).get("error", "Aucune branche exploitable")
                consecutive_failures += 1
                iteration.phase_feedback.setdefault("proposal", {})["branching"] = {
                    "enabled": len(proposal_candidates) > 1,
                    "candidates": [
                        {
                            "branch": outcome.get("branch_label"),
                            "error": outcome.get("error"),
                            "rank_score": outcome.get("rank_score"),
                        }
                        for outcome in branch_outcomes
                    ],
                }
                session.iterations.append(iteration)
                builder._safe_save_session_summary(session)
                builder._emit_progress(
                    "iteration_error",
                    iteration=i,
                    phase="code",
                    error=iteration.error,
                )
                last_iteration = iteration
                continue

            proposal = selected_outcome["proposal"]
            iteration.hypothesis = proposal.get("hypothesis", f"Itération {i}")
            iteration.change_type = _normalize_change_type(proposal.get("change_type", "logic"))
            iteration.used_indicators = list(proposal.get("used_indicators", []) or [])
            code = selected_outcome["code"]
            bt_result = selected_outcome["bt_result"]
            sharpe = float(selected_outcome.get("sharpe", float("-inf")) or float("-inf"))
            iteration.code = code
            iteration.backtest_result = bt_result
            iteration.phase_feedback["proposal"] = selected_outcome.get("proposal_feedback", {})
            if len(proposal_candidates) > 1:
                iteration.phase_feedback.setdefault("proposal", {})["branching"] = {
                    "enabled": True,
                    "selected_branch": selected_outcome.get("branch_label"),
                    "candidates": [
                        {
                            "branch": outcome.get("branch_label"),
                            "used_indicators": (outcome.get("proposal") or {}).get("used_indicators", []),
                            "rank_score": outcome.get("rank_score"),
                            "sharpe": outcome.get("sharpe"),
                            "return_pct": ((outcome.get("metrics") or {}).get("total_return_pct") if outcome.get("metrics") else None),
                            "error": outcome.get("error"),
                            "is_fallback": outcome.get("is_fallback", False),
                        }
                        for outcome in branch_outcomes
                    ],
                }
                thought_stream.append(
                    f"🌿  BRANCHING STAGNATION — branche retenue: {selected_outcome.get('branch_label')}\n"
                )
            iteration.phase_feedback["code"] = selected_outcome.get("code_feedback", {})
            if selected_outcome.get("precheck_feedback"):
                iteration.phase_feedback["precheck"] = selected_outcome.get("precheck_feedback", {})
            if selected_outcome.get("pre_reflection_feedback"):
                iteration.phase_feedback["pre_reflection"] = selected_outcome.get("pre_reflection_feedback", {})
            if selected_outcome.get("backtest_feedback"):
                iteration.phase_feedback["backtest"] = selected_outcome.get("backtest_feedback", {})

            dt_code = time.perf_counter() - t0
            thought_stream.codegen_received(code, dt_code)

            logger.info("builder_iter_%d_backtest", i)
            builder._emit_progress("phase_start", iteration=i, phase="backtest")
            thought_stream.backtest_start()
            builder._emit_completed_backtest(
                bt_result,
                session=session,
                iteration_num=i,
            )
            builder._emit_progress(
                "phase_done",
                iteration=i,
                phase="backtest",
                sharpe=bt_result.metrics.get("sharpe_ratio", 0.0),
                total_return_pct=bt_result.metrics.get("total_return_pct", 0.0),
                backtest_skipped=bool(
                    iteration.phase_feedback.get("precheck", {}).get(
                        "backtest_skipped"
                    )
                ),
            )
            thought_stream.backtest_result(bt_result.metrics)

            # Backtest réussi → reset circuit breaker
            consecutive_failures = 0

            # ── Phase 6 : Mise à jour best ──
            # Detect if this iteration used a deterministic fallback
            _code_fb = iteration.phase_feedback.get("code", {})
            _prop_fb = iteration.phase_feedback.get("proposal", {})
            if (
                _code_fb.get("fallback_deterministic_used")
                or _code_fb.get("source") == "deterministic_fallback"
                or _prop_fb.get("fallback_deterministic_used")
                or _code_fb.get("runtime_fix_fallback_deterministic_used")
            ):
                iteration.is_fallback = True

            metrics_cur = bt_result.metrics or {}
            sharpe = _metric_float(metrics_cur, "sharpe_ratio", float("-inf"))
            score_payload = compute_builder_telemetry_score(
                metrics_cur,
                target_sharpe=session.target_sharpe,
            )
            iteration.phase_feedback.setdefault("scoring", {}).update(
                {
                    "telemetry_score": score_payload.get("score"),
                    "continuous_score": score_payload.get("score"),
                    "drawdown_excess_pct": score_payload.get("drawdown_excess_pct"),
                    "components": score_payload.get("components"),
                    "penalties": score_payload.get("penalties"),
                }
            )
            if math.isfinite(sharpe) and sharpe > session.best_sharpe:
                session.best_sharpe = sharpe

            candidate_selection_key = _builder_iteration_selection_key(
                metrics_cur,
                is_fallback=iteration.is_fallback,
                target_sharpe=session.target_sharpe,
            )
            should_promote_best = session.best_iteration is None
            if session.best_iteration is not None:
                best_metrics = (
                    session.best_iteration.backtest_result.metrics
                    if session.best_iteration.backtest_result is not None
                    and isinstance(session.best_iteration.backtest_result.metrics, dict)
                    else {}
                )
                best_selection_key = _builder_iteration_selection_key(
                    best_metrics,
                    is_fallback=bool(session.best_iteration.is_fallback),
                    target_sharpe=session.target_sharpe,
                )
                should_promote_best = candidate_selection_key > best_selection_key

            if should_promote_best:
                session.best_score = float(
                    score_payload.get("score", float("-inf")) or float("-inf")
                )
                session.best_iteration = iteration
                thought_stream.best_update(sharpe, i)

            # ── Phase 6b : Détection de stagnation ──
            cur_fp = _metrics_fingerprint(metrics_cur)
            if last_iteration and last_iteration.backtest_result:
                prev_fp = _metrics_fingerprint(
                    last_iteration.backtest_result.metrics or {}
                )
                if cur_fp == prev_fp:
                    iteration.phase_feedback.setdefault("stagnation", {})[
                        "identical_metrics"
                    ] = True
                    thought_stream.warning(
                        "Stagnation détectée: métriques identiques à "
                        "l'itération précédente — forçage changement radical."
                    )
                    logger.warning(
                        "builder_iter_%d_stagnation fingerprint=%s",
                        i, cur_fp,
                    )
                    # Injecter un signal fort dans la proposition pour
                    # forcer le LLM à changer d'approche à l'itération suivante
                    proposal["_stagnation_detected"] = True

            # ── Phase 7 : Diagnostic déterministe + Analyse LLM ──
            logger.info("builder_iter_%d_diagnostic", i)
            diag_history = [
                {
                    "sharpe": (
                        it.backtest_result.metrics.get("sharpe_ratio", 0)
                        if it.backtest_result else 0
                    ),
                    "diagnostic_category": it.diagnostic_category,
                }
                for it in session.iterations
            ]
            diag = compute_diagnostic(
                bt_result.metrics, diag_history, session.target_sharpe,
            )
            iteration.diagnostic_category = diag["category"]
            iteration.diagnostic_detail = diag
            if not iteration.change_type:
                iteration.change_type = _normalize_change_type(
                    diag.get("change_type", "logic")
                )
            thought_stream.diagnostic(diag)
            # ── Instrumentation: diagnostic ──
            if builder.instrumentation.enabled:
                builder.instrumentation.record_diagnostic(_itrace, diag)

            decision_feedback = DecisionPolicyFeedback()
            positive_gate_policy = evaluate_positive_progress_gate(
                session=session,
                iteration_num=i,
                metrics_cur=metrics_cur,
                enabled=builder.ablation.is_enabled("positive_progress_gate"),
            )
            if positive_gate_policy.feedback is not None:
                decision_feedback.positive_progress_gate = (
                    positive_gate_policy.feedback
                )
                iteration.phase_feedback.setdefault("decision", {}).update(
                    decision_feedback.to_dict()
                )

            if positive_gate_policy.triggered:
                gate_feedback = positive_gate_policy.feedback
                if positive_gate_policy.warning_message:
                    thought_stream.warning(positive_gate_policy.warning_message)
                if gate_feedback is not None:
                    logger.info(
                        "builder_iter_%d_positive_gate_stop observed=%d required=%d "
                        "llm=%d fallback=%d",
                        i,
                        gate_feedback.observed_positive,
                        gate_feedback.required_positive,
                        gate_feedback.llm_positive,
                        gate_feedback.fallback_positive,
                    )
                iteration.analysis = positive_gate_policy.analysis
                iteration.decision = positive_gate_policy.decision
                session.status = positive_gate_policy.session_status
                if builder.instrumentation.enabled:
                    _record_policy_restrictions(
                        builder,
                        _itrace,
                        positive_gate_policy.restrictions,
                    )
                    builder.instrumentation.record_decision(
                        _itrace,
                        iteration.decision,
                        overridden=False,
                        override_reason="positive_progress_gate",
                    )
                    builder.instrumentation.finalize_iteration(_itrace)
                session.iterations.append(iteration)
                builder._safe_save_session_summary(session)
                builder._emit_progress(
                    "iteration_done",
                    iteration=i,
                    decision=iteration.decision,
                    status=session.status,
                )
                last_iteration = iteration
                break

            if positive_gate_policy.feedback is not None:
                logger.info(
                    "builder_iter_%d_positive_gate_pass observed=%d required=%d",
                    i,
                    positive_gate_policy.feedback.observed_positive,
                    positive_gate_policy.feedback.required_positive,
                )

            logger.info(
                "builder_iter_%d_analysis diag=%s sev=%s",
                i, diag["category"], diag["severity"],
            )
            builder._emit_progress("phase_start", iteration=i, phase="analysis")
            thought_stream.analysis_sent()
            pre_reflection_text = ""
            t0 = time.perf_counter()
            if builder.ablation.is_enabled("llm_analysis"):
                analysis, decision = builder._ask_analysis(
                    session, iteration, diag,
                    pre_reflection=pre_reflection_text,
                )
            else:
                _rule_sharpe = float(metrics_cur.get("sharpe_ratio", 0) or 0)
                _rule_wr = float(metrics_cur.get("win_rate", 0) or 0)
                _rule_dd = abs(float(metrics_cur.get("max_drawdown", 1) or 1))
                _rule_pf = float(metrics_cur.get("profit_factor", 0) or 0)
                _rule_ct = str(diag.get("change_type", "") or "")
                _target = float(session.target_sharpe or 1.0)
                # Score multi-critères: accepter si sharpe atteint + au moins 2 critères secondaires
                _criteria_met = sum([
                    _rule_sharpe >= _target,        # critère principal
                    _rule_wr >= 0.38,               # taux de victoire viable
                    _rule_dd <= 0.30,               # drawdown maîtrisé
                    _rule_pf >= 1.1,                # profit factor positif
                ])
                if _rule_ct == "accept" or (_rule_sharpe >= _target and _criteria_met >= 2):
                    decision = "accept"
                elif i >= max_iterations:
                    decision = "stop"
                else:
                    decision = "continue"
                analysis = (
                    f"[rule-based] Sharpe {_rule_sharpe:.3f} "
                    f"{'≥' if _rule_sharpe >= _target else '<'} "
                    f"target {_target:.3f} | WR {_rule_wr:.1%} | "
                    f"DD {_rule_dd:.1%} | PF {_rule_pf:.2f} | "
                    f"critères {_criteria_met}/4 → {decision}"
                )
            dt_analysis = time.perf_counter() - t0

            decision_policy = evaluate_decision_policies(
                session=session,
                iteration_num=i,
                max_iterations=max_iterations,
                metrics_cur=metrics_cur,
                last_iteration=last_iteration,
                iteration=iteration,
                decision=decision,
                analysis=analysis,
                stop_override_enabled=builder.ablation.is_enabled("stop_override"),
                accept_override_enabled=builder.ablation.is_enabled("accept_override"),
            )
            decision = decision_policy.decision
            analysis = decision_policy.analysis
            decision_feedback.merge(decision_policy.feedback)
            decision_payload = decision_feedback.to_dict()
            if decision_payload:
                iteration.phase_feedback.setdefault("decision", {}).update(
                    decision_payload
                )

            if decision_policy.stagnation_warning_message:
                thought_stream.warning(
                    decision_policy.stagnation_warning_message
                )
                logger.info(
                    "builder_iter_%d_stagnation_circuit_breaker triggered",
                    i,
                )
            if decision_policy.stop_override_warning_message:
                thought_stream.warning(
                    decision_policy.stop_override_warning_message
                )
                logger.info(
                    "builder_iter_%d_stop_overridden successful_iters=%d "
                    "best_sharpe=%.3f target=%.3f",
                    i,
                    decision_policy.successful_iterations,
                    session.best_sharpe,
                    session.target_sharpe,
                )
            if decision_policy.accept_override_warning_message:
                thought_stream.warning(
                    decision_policy.accept_override_warning_message
                )
                logger.info(
                    "builder_iter_%d_accept_overridden reason=%s trades=%d "
                    "best_sharpe=%.3f target=%.3f max_dd=%.2f",
                    i,
                    decision_policy.accept_reason,
                    decision_policy.trades,
                    session.best_sharpe,
                    session.target_sharpe,
                    decision_policy.max_drawdown_pct,
                )
            if builder.instrumentation.enabled:
                _record_policy_restrictions(
                    builder,
                    _itrace,
                    decision_policy.restrictions,
                )

            iteration.analysis = analysis
            iteration.decision = decision
            thought_stream.analysis_received(
                analysis, decision, iteration.change_type, dt_analysis,
            )
            # ── Instrumentation: décision + stagnation + finalisation ──
            if builder.instrumentation.enabled:
                _dec_fb = iteration.phase_feedback.get("decision", {})
                builder.instrumentation.record_decision(
                    _itrace,
                    decision,
                    overridden=bool(
                        _dec_fb.get("stop_overridden")
                        or _dec_fb.get("accept_overridden")
                    ),
                    override_reason=(
                        "stop_overridden" if _dec_fb.get("stop_overridden")
                        else "accept_overridden" if _dec_fb.get("accept_overridden")
                        else ""
                    ),
                )
                _stag_fb = iteration.phase_feedback.get("stagnation", {})
                _stag_cb = _dec_fb.get("stagnation_circuit_breaker", {})
                builder.instrumentation.record_stagnation(
                    _itrace,
                    detected=bool(_stag_fb.get("identical_metrics")),
                    circuit_breaker=bool(_stag_cb.get("triggered")),
                    branching=bool(
                        iteration.phase_feedback.get("proposal", {}).get("branching_enabled")
                    ),
                    branch_count=len(
                        iteration.phase_feedback.get("proposal", {}).get("candidates", [])
                    ),
                )
                _itrace.is_best_so_far = (
                    session.best_iteration is iteration
                )
                builder.instrumentation.finalize_iteration(_itrace)

            session.iterations.append(iteration)
            builder._safe_save_session_summary(session)
            builder._emit_progress(
                "iteration_done",
                iteration=i,
                decision=decision,
                status="success" if decision == "accept" else "running",
                best_sharpe=session.best_sharpe,
            )
            last_iteration = iteration

            logger.info(
                "builder_iter_%d_done sharpe=%.3f decision=%s",
                i, sharpe, decision,
            )

            if decision == "accept":
                accept_now, accept_now_reason = _is_accept_candidate(
                    metrics_cur,
                    target_sharpe=session.target_sharpe,
                )
                if accept_now:
                    session.status = "success"
                else:
                    session.status = "failed"
                    logger.info(
                        "builder_iter_%d_accept_rejected reason=%s",
                        i,
                        accept_now_reason,
                    )
                break
            if decision == "stop":
                best_metrics = (
                    session.best_iteration.backtest_result.metrics
                    if session.best_iteration and session.best_iteration.backtest_result
                    else {}
                )
                best_ok, best_reason = _is_accept_candidate(
                    best_metrics,
                    target_sharpe=session.target_sharpe,
                )
                session.status = "success" if best_ok else "failed"
                if not best_ok:
                    logger.info(
                        "builder_iter_%d_stop_rejected_success reason=%s "
                        "best_sharpe=%.3f",
                        i,
                        best_reason,
                        session.best_sharpe,
                    )
                break

        except KeyboardInterrupt:
            logger.info(
                "builder_iter_%d_interrupted reason=keyboard_interrupt_or_interpreter_shutdown",
                i,
            )
            if builder.instrumentation.enabled:
                builder.instrumentation.finalize_iteration(_itrace)
            raise
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError) as e:
            iteration.error = f"{type(e).__name__}: {e}"
            thought_stream.error(i, str(e))
            consecutive_failures += 1
            logger.error(
                "builder_iter_%d_error error=%s\n%s",
                i, e, _safe_format_exception(e),
            )
            # ── Instrumentation: erreur d'itération ──
            if builder.instrumentation.enabled:
                builder.instrumentation.finalize_iteration(_itrace)
            session.iterations.append(iteration)
            builder._safe_save_session_summary(session)
            builder._emit_progress(
                "iteration_error",
                iteration=i,
                error=iteration.error,
            )
            last_iteration = iteration

    else:
        session.status = "max_iterations"

    return session
