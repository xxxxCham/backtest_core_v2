"""
Module-ID: agents.builder_candidate_executor

Purpose: Internal Builder V2 candidate execution pipeline.

This module is intentionally imported lazily from `StrategyBuilder` methods to
avoid circular imports during the initial load of `agents.strategy_builder`.
"""

from __future__ import annotations

import concurrent.futures
import copy
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pandas as pd

import agents.strategy_builder as strategy_builder_module
from agents.builder_code_repair import _repair_code
from agents.builder_code_validation import validate_generated_code
from agents.builder_state import BuilderIteration, BuilderSession
from agents.strategy_builder import (
    _build_deterministic_fallback_code,
    _extract_generate_signals_logic_block,
    _extract_python_from_response,
    _metric_float,
    _normalize_change_type,
    _params_only_contract_respected,
    _postprocess_llm_logic_block,
    _proposal_changes_indicator_set_in_params_mode,
    _proposal_has_meaningful_param_delta,
    _telemetry_score_from_metrics,
    _rewrite_default_params_from_proposal,
    _validate_llm_logic_block,
    compute_builder_telemetry_score,
)


@dataclass
class CandidateExecutionContext:
    session: BuilderSession
    proposal: Dict[str, Any]
    proposal_feedback: Dict[str, Any]
    last_iteration: Optional[BuilderIteration]
    iteration_num: int
    data: pd.DataFrame
    initial_capital: float
    fallback_count: int
    branch_label: str = "main"


class BuilderCandidateExecutorV2:
    """Internal candidate pipeline extracted from StrategyBuilder."""

    def __init__(self, builder: Any, context: CandidateExecutionContext) -> None:
        self.builder = builder
        self.ctx = context
        self.candidate_proposal = copy.deepcopy(context.proposal)
        self.candidate_feedback = copy.deepcopy(context.proposal_feedback)
        self.outcome: Dict[str, Any] = {
            "branch_label": context.branch_label,
            "proposal": self.candidate_proposal,
            "proposal_feedback": self.candidate_feedback,
            "code_feedback": {},
            "backtest_feedback": {},
            "precheck_feedback": {},
            "pre_reflection_feedback": {},
            "error": None,
            "is_fallback": False,
            "rank_score": float("-inf"),
            "telemetry_rank_score": float("-inf"),
            "sharpe": float("-inf"),
            "target_sharpe": float(context.session.target_sharpe or 1.0),
            "telemetry_score": None,
        }
        self.change_type = _normalize_change_type(
            self.candidate_proposal.get("change_type", "logic")
        )
        self.has_stable_base_code = bool(
            context.last_iteration
            and context.last_iteration.code
            and context.last_iteration.error is None
            and context.last_iteration.backtest_result is not None
        )
        self.code_feedback: Dict[str, Any] = {
            "phase": "code",
            "initial_kind": "local_patch",
            "realign_attempts": 0,
            "realign_success": False,
            "final_valid": True,
        }
        self.precheck_feedback: Dict[str, Any] = {}
        self.backtest_feedback: Dict[str, Any] = {}
        self.pre_reflection_feedback: Dict[str, Any] = {}
        self.req_inds = [
            str(x).strip().lower()
            for x in self.candidate_proposal.get("used_indicators", [])
            if isinstance(x, str) and str(x).strip()
        ]

    def execute(self) -> tuple[Dict[str, Any], int]:
        try:
            self._apply_change_type_policy()
            code = self._resolve_candidate_code()
            strategy_cls = self.builder._save_and_load(
                self.ctx.session,
                code,
                self.ctx.iteration_num,
            )
            if self.builder.ablation.is_enabled("auto_fix_indicators"):
                strategy_cls = self.builder._auto_fix_required_indicators(
                    strategy_cls,
                    code,
                )
            signal_probe = self.builder._precheck_signal_counts(
                strategy_cls,
                self.ctx.data,
                self.candidate_proposal.get("default_params", {}),
            )
            code, bt_result = self._execute_backtest_pipeline(
                strategy_cls,
                code,
                signal_probe,
            )
            self._finalize_success(code, bt_result)
            self.builder._instrument_candidate_outcome(
                self.outcome,
                self.ctx.iteration_num,
            )
            return self.outcome, self.ctx.fallback_count
        except Exception as exc:
            self.outcome["error"] = f"{type(exc).__name__}: {exc}"
            self.builder._instrument_candidate_outcome(
                self.outcome,
                self.ctx.iteration_num,
            )
            return self.outcome, self.ctx.fallback_count

    def _apply_change_type_policy(self) -> None:
        last_iteration = self.ctx.last_iteration
        if (
            self.change_type == "params"
            and self.has_stable_base_code
            and last_iteration
            and last_iteration.code
        ):
            params_override_reasons: List[str] = []
            if _proposal_changes_indicator_set_in_params_mode(
                last_iteration.code,
                self.candidate_proposal,
            ):
                params_override_reasons.append("indicator_set_changed")
            if not _proposal_has_meaningful_param_delta(
                last_iteration.code,
                self.candidate_proposal,
            ):
                params_override_reasons.append("no_meaningful_param_delta")
            if params_override_reasons:
                override_reason = "+".join(params_override_reasons)
                self.candidate_feedback["change_type_overridden"] = {
                    "from": "params",
                    "to": "logic",
                    "reason": override_reason,
                }
                self.change_type = "logic"
                self.candidate_proposal["change_type"] = "logic"

        if self.change_type == "params" and not self.has_stable_base_code:
            self.candidate_feedback["change_type_overridden"] = {
                "from": "params",
                "to": "logic",
                "reason": "no_stable_base_code",
            }
            self.change_type = "logic"
            self.candidate_proposal["change_type"] = "logic"

    def _resolve_candidate_code(self) -> str:
        raw_code = ""
        last_iteration = self.ctx.last_iteration
        if (
            self.change_type == "params"
            and self.has_stable_base_code
            and last_iteration
            and last_iteration.code
        ):
            patched = _rewrite_default_params_from_proposal(
                last_iteration.code,
                self.candidate_proposal,
            )
            if patched:
                code = patched
                self.code_feedback["source"] = "params_patch"
                self.code_feedback["final_kind"] = "python"
            else:
                raw_code, self.code_feedback = self.builder._ask_code(
                    self.ctx.session,
                    self.candidate_proposal,
                    last_iteration,
                )
                code = self._build_code_from_llm_response(raw_code)
        else:
            raw_code, self.code_feedback = self.builder._ask_code(
                self.ctx.session,
                self.candidate_proposal,
                last_iteration,
            )
            code = self._build_code_from_llm_response(raw_code)

        if (
            self.change_type == "params"
            and last_iteration
            and last_iteration.code
            and self.builder.ablation.is_enabled("params_contract_check")
        ):
            contract_ok, _ = _params_only_contract_respected(
                last_iteration.code,
                code,
            )
            if not contract_ok:
                patched = _rewrite_default_params_from_proposal(
                    last_iteration.code,
                    self.candidate_proposal,
                )
                if patched:
                    code = patched
                else:
                    code = last_iteration.code
                    self.code_feedback["params_contract_fallback"] = (
                        "reused_previous_code"
                    )

        return self._validate_candidate_code(code)

    def _build_code_from_llm_response(self, raw_code: str) -> str:
        if self.code_feedback.get("source") == "params_patch":
            return raw_code

        logic_block = _extract_generate_signals_logic_block(raw_code)
        if not logic_block.strip():
            logic_block = _extract_python_from_response(raw_code)
        if self.builder.ablation.is_enabled("postprocess_logic"):
            logic_block = _postprocess_llm_logic_block(logic_block, self.req_inds)
        logic_ok, logic_err = _validate_llm_logic_block(logic_block)
        if logic_ok:
            return strategy_builder_module._build_deterministic_strategy_code(
                self.candidate_proposal,
                logic_block,
            )

        self.code_feedback["validation_error"] = logic_err
        retry_logic_raw = self.builder._retry_code_simple(self.candidate_proposal)
        retry_logic = _extract_python_from_response(retry_logic_raw)
        if self.builder.ablation.is_enabled("postprocess_logic"):
            retry_logic = _postprocess_llm_logic_block(retry_logic, self.req_inds)
        retry_ok, retry_err = _validate_llm_logic_block(retry_logic)
        if retry_ok:
            self.code_feedback["logic_retry_used"] = True
            return strategy_builder_module._build_deterministic_strategy_code(
                self.candidate_proposal,
                retry_logic,
            )

        self.code_feedback["validation_error_retry"] = retry_err
        fallback_code = self._next_fallback_code()
        is_valid_fb, error_msg_fb = validate_generated_code(fallback_code)
        if not is_valid_fb:
            self.outcome["error"] = (
                "Bloc logique LLM invalide après retry + fallback invalide: "
                f"{error_msg_fb or retry_err}"
            )
            self.outcome["code_feedback"] = self.code_feedback
            raise RuntimeError(str(self.outcome["error"]))
        self.code_feedback["fallback_deterministic_used"] = True
        self.code_feedback["source"] = "deterministic_fallback"
        self.code_feedback["fallback_variant"] = self.ctx.fallback_count - 1
        return fallback_code

    def _validate_candidate_code(self, code: str) -> str:
        repaired_code = (
            _repair_code(
                code,
                self.req_inds,
                enable_indicator_binding=self.builder.ablation.is_enabled("indicator_binding"),
            )
            if self.builder.ablation.is_enabled("code_repair")
            else code
        )
        is_valid, error_msg = validate_generated_code(repaired_code)
        if is_valid:
            return repaired_code

        self.code_feedback["validation_error"] = error_msg
        retry_logic_raw = self.builder._retry_code_simple(self.candidate_proposal)
        retry_logic = _extract_python_from_response(retry_logic_raw)
        if self.builder.ablation.is_enabled("postprocess_logic"):
            retry_logic = _postprocess_llm_logic_block(retry_logic, self.req_inds)
        logic_ok, logic_err = _validate_llm_logic_block(retry_logic)
        if not logic_ok:
            retry_code = ""
            is_valid_retry = False
            retry_error = logic_err
        else:
            retry_code = strategy_builder_module._build_deterministic_strategy_code(
                self.candidate_proposal,
                retry_logic,
            )
            retry_code = _repair_code(
                retry_code,
                self.req_inds,
                enable_indicator_binding=self.builder.ablation.is_enabled("indicator_binding"),
            )
            is_valid_retry, retry_error = validate_generated_code(retry_code)

        if is_valid_retry:
            return retry_code

        self.code_feedback["validation_error_retry"] = retry_error
        fallback_code = self._next_fallback_code()
        is_valid_fb, error_msg_fb = validate_generated_code(fallback_code)
        if not is_valid_fb:
            self.outcome["error"] = (
                f"Validation échouée: {error_msg} | retry: {retry_error} | "
                f"fallback: {error_msg_fb}"
            )
            self.outcome["code_feedback"] = self.code_feedback
            raise RuntimeError(str(self.outcome["error"]))
        self.code_feedback["fallback_deterministic_used"] = True
        self.code_feedback["source"] = "deterministic_fallback"
        self.code_feedback["fallback_variant"] = self.ctx.fallback_count - 1
        return fallback_code

    def _execute_backtest_pipeline(
        self,
        strategy_cls: Any,
        code: str,
        signal_probe: Dict[str, Any],
    ) -> tuple[str, Any]:
        if not signal_probe.get("ok"):
            self.precheck_feedback["backtest_skipped"] = True
            return code, self._empty_backtest_result()

        if (
            self.builder._is_pathological_signal_profile(signal_probe)
            and self.builder.ablation.is_enabled("precheck")
        ):
            self.precheck_feedback.update(
                {
                    "pathological_signal_density": True,
                    "skip_reason": "pathological_signal_density",
                    "backtest_skipped": True,
                }
            )
            return code, self.builder._build_precheck_overtrading_result(signal_probe)

        pre_reflection_future = None
        pre_reflection_pool: Optional[
            concurrent.futures.ThreadPoolExecutor
        ] = None
        try:
            try:
                pre_reflection_pool = strategy_builder_module._new_streamlit_aware_thread_pool(
                    max_workers=1
                )
                pre_reflection_future = pre_reflection_pool.submit(
                    self.builder._ask_pre_reflection,
                    self.ctx.session,
                    self.candidate_proposal,
                    code,
                    self.ctx.iteration_num,
                )
            except (
                ValueError,
                KeyError,
                RuntimeError,
                AttributeError,
                TypeError,
                IndexError,
            ):
                pre_reflection_future = None

            try:
                bt_result = self._run_backtest(strategy_cls)
            except (
                ValueError,
                KeyError,
                RuntimeError,
                AttributeError,
                TypeError,
                IndexError,
                NameError,
            ) as bt_exc:
                code, bt_result = self._recover_runtime_failure(code, bt_exc)
            return code, bt_result
        finally:
            if pre_reflection_future is not None:
                try:
                    pre_reflection_text = pre_reflection_future.result(timeout=5)
                    if pre_reflection_text:
                        self.pre_reflection_feedback = {"text": pre_reflection_text}
                except concurrent.futures.TimeoutError:
                    self.pre_reflection_feedback = {"timeout": True}
                except (
                    ValueError,
                    KeyError,
                    RuntimeError,
                    AttributeError,
                    TypeError,
                    IndexError,
                ):
                    pass
            if pre_reflection_pool is not None:
                pre_reflection_pool.shutdown(wait=False)

    def _recover_runtime_failure(
        self,
        code: str,
        bt_exc: BaseException,
    ) -> tuple[str, Any]:
        bt_error = f"{type(bt_exc).__name__}: {bt_exc}"
        self.backtest_feedback["runtime_error"] = bt_error
        if self.builder.ablation.is_enabled("runtime_fix"):
            retry_code = self.builder._retry_code_runtime_fix(
                proposal=self.candidate_proposal,
                failing_code=code,
                runtime_error=bt_error,
            )
            retry_code = _repair_code(
                retry_code,
                self.req_inds,
                enable_indicator_binding=self.builder.ablation.is_enabled("indicator_binding"),
            )
            valid_retry, retry_err = validate_generated_code(retry_code)
        else:
            valid_retry = False
            retry_err = "runtime_fix ablated"
        used_runtime_fallback = False
        if not valid_retry:
            self.backtest_feedback["runtime_fix_validation_error"] = retry_err
            fallback_code = self._next_fallback_code()
            valid_fb, fb_err = validate_generated_code(fallback_code)
            if not valid_fb:
                self.outcome["error"] = (
                    "Runtime-fix invalide et fallback déterministe invalide: "
                    f"{retry_err} | {fb_err}"
                )
                self.outcome["code_feedback"] = self.code_feedback
                self.outcome["backtest_feedback"] = self.backtest_feedback
                raise RuntimeError(str(self.outcome["error"]))
            retry_code = fallback_code
            used_runtime_fallback = True
            self.backtest_feedback[
                "runtime_fix_fallback_deterministic_used"
            ] = True
            self.code_feedback["source"] = "deterministic_fallback"

        retry_cls = self.builder._save_and_load(
            self.ctx.session,
            retry_code,
            self.ctx.iteration_num,
        )
        if self.builder.ablation.is_enabled("auto_fix_indicators"):
            retry_cls = self.builder._auto_fix_required_indicators(
                retry_cls,
                retry_code,
            )
        try:
            bt_result = self._run_backtest(retry_cls)
        except (
            ValueError,
            KeyError,
            RuntimeError,
            AttributeError,
            TypeError,
            IndexError,
            NameError,
        ) as retry_bt_exc:
            if used_runtime_fallback:
                self.outcome["error"] = (
                    f"{type(retry_bt_exc).__name__}: {retry_bt_exc}"
                )
                self.outcome["code_feedback"] = self.code_feedback
                self.outcome["backtest_feedback"] = self.backtest_feedback
                raise RuntimeError(str(self.outcome["error"]))

            self.backtest_feedback["runtime_fix_retry_error"] = (
                f"{type(retry_bt_exc).__name__}: {retry_bt_exc}"
            )
            fallback_code = self._next_fallback_code()
            valid_fb2, fb_err2 = validate_generated_code(fallback_code)
            if not valid_fb2:
                self.outcome["error"] = (
                    "Runtime-fix backtest failed and deterministic fallback is "
                    f"invalid: {fb_err2}"
                )
                self.outcome["code_feedback"] = self.code_feedback
                self.outcome["backtest_feedback"] = self.backtest_feedback
                raise RuntimeError(str(self.outcome["error"]))
            fallback_cls = self.builder._save_and_load(
                self.ctx.session,
                fallback_code,
                self.ctx.iteration_num,
            )
            if self.builder.ablation.is_enabled("auto_fix_indicators"):
                fallback_cls = self.builder._auto_fix_required_indicators(
                    fallback_cls,
                    fallback_code,
                )
            bt_result = self._run_backtest(fallback_cls)
            retry_code = fallback_code
            self.backtest_feedback[
                "runtime_fix_fallback_deterministic_used"
            ] = True
            self.code_feedback["source"] = "deterministic_fallback"

        self.backtest_feedback["runtime_fix_applied"] = True
        return retry_code, bt_result

    def _run_backtest(self, strategy_cls: Any) -> Any:
        return self.builder._run_backtest(
            strategy_cls,
            self.ctx.data,
            self.candidate_proposal.get("default_params", {}),
            self.ctx.initial_capital,
            symbol=self.ctx.session.symbol,
            timeframe=self.ctx.session.timeframe,
            fees_bps=self.ctx.session.fees_bps,
            slippage_bps=self.ctx.session.slippage_bps,
            direction_constraint=self.ctx.session.direction_constraint,
        )

    def _finalize_success(self, code: str, bt_result: Any) -> None:
        metrics_cur = bt_result.metrics or {}
        sharpe = _metric_float(metrics_cur, "sharpe_ratio", float("-inf"))
        rank_score = _telemetry_score_from_metrics(
            metrics_cur,
            target_sharpe=self.ctx.session.target_sharpe,
        )
        scoring_payload = compute_builder_telemetry_score(
            metrics_cur,
            target_sharpe=self.ctx.session.target_sharpe,
        )
        if (
            self.code_feedback.get("fallback_deterministic_used")
            or self.code_feedback.get("source") == "deterministic_fallback"
            or self.backtest_feedback.get(
                "runtime_fix_fallback_deterministic_used"
            )
        ):
            self.outcome["is_fallback"] = True

        self.outcome.update(
            {
                "proposal": self.candidate_proposal,
                "proposal_feedback": self.candidate_feedback,
                "code": code,
                "code_feedback": self.code_feedback,
                "precheck_feedback": self.precheck_feedback,
                "pre_reflection_feedback": self.pre_reflection_feedback,
                "backtest_feedback": self.backtest_feedback,
                "bt_result": bt_result,
                "metrics": metrics_cur,
                "rank_score": rank_score,
                "telemetry_rank_score": rank_score,
                "sharpe": sharpe,
                "telemetry_score": scoring_payload.get("score"),
                "continuous_score": scoring_payload.get("score"),
                "telemetry_payload": scoring_payload,
                "scoring_payload": scoring_payload,
            }
        )

    def _next_fallback_code(self) -> str:
        if not self.builder.ablation.is_enabled("deterministic_fallback"):
            raise RuntimeError("deterministic_fallback ablated — no fallback allowed")
        fallback_code = _build_deterministic_fallback_code(
            self.candidate_proposal,
            variant=self.ctx.fallback_count,
        )
        self.ctx.fallback_count += 1
        return _repair_code(
            fallback_code,
            self.req_inds,
            enable_indicator_binding=self.builder.ablation.is_enabled("indicator_binding"),
        )

    @staticmethod
    def _empty_backtest_result() -> SimpleNamespace:
        return SimpleNamespace(
            success=True,
            metrics={
                "total_return_pct": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "calmar_ratio": 0.0,
                "max_drawdown_pct": 0.0,
                "total_trades": 0,
                "win_rate_pct": 0.0,
                "profit_factor": 1.0,
                "expectancy": 0.0,
            },
            sharpe_ratio=0.0,
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            total_trades=0,
            execution_time_ms=0,
        )


def execute_proposal_candidate_v2(
    builder: Any,
    *,
    session: BuilderSession,
    proposal: Dict[str, Any],
    proposal_feedback: Dict[str, Any],
    last_iteration: Optional[BuilderIteration],
    iteration_num: int,
    data: pd.DataFrame,
    initial_capital: float,
    fallback_count: int,
    branch_label: str = "main",
) -> tuple[Dict[str, Any], int]:
    executor = BuilderCandidateExecutorV2(
        builder,
        CandidateExecutionContext(
            session=session,
            proposal=proposal,
            proposal_feedback=proposal_feedback,
            last_iteration=last_iteration,
            iteration_num=iteration_num,
            data=data,
            initial_capital=initial_capital,
            fallback_count=fallback_count,
            branch_label=branch_label,
        ),
    )
    return executor.execute()
