"""Module-ID: agents.builder_candidate_executor

Purpose: Internal Builder V2 candidate execution pipeline.

This module is intentionally imported lazily from `StrategyBuilder` methods to
avoid circular imports during the initial load of `agents.strategy_builder`.
"""

from __future__ import annotations

# pylint: disable=protected-access
# pylint: disable=broad-except
import concurrent.futures
import copy
import time as _time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pandas as pd

import agents.strategy_builder as strategy_builder_module
from agents.builder_code_repair import _auto_repair_vectorize, _repair_code
from agents.builder_code_validation import validate_generated_code
from agents.builder_diagnostics import (
    _metric_float,
    _telemetry_score_from_metrics,
    compute_builder_telemetry_score,
)
from agents.builder_proposal_helpers import (
    _normalize_change_type,
    _params_only_contract_respected,
    _proposal_changes_indicator_set_in_params_mode,
    _proposal_has_meaningful_param_delta,
    _rewrite_default_params_from_proposal,
)
from agents.builder_state import BuilderIteration, BuilderSession
from agents.builder_text_utils import _safe_format_exception
from agents.strategy_builder import (
    _build_deterministic_fallback_code,
    _extract_generate_signals_logic_block,
    _extract_python_from_response,
    _postprocess_llm_logic_block,
    _validate_llm_logic_block,
)


@dataclass
class CandidateExecutionContext:
    session: BuilderSession
    proposal: dict[str, Any]
    proposal_feedback: dict[str, Any]
    last_iteration: BuilderIteration | None
    iteration_num: int
    data: pd.DataFrame
    initial_capital: float
    fallback_count: int
    branch_label: str = "main"


@dataclass
class CodeAttempt:
    code: str = ""
    logic: str = ""
    logic_error: str = ""
    validation_error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.code) and not self.logic_error and not self.validation_error

    @property
    def error(self) -> str:
        return str(self.validation_error or self.logic_error or "").strip()


class BuilderCandidateExecutorV2:
    """Internal candidate pipeline extracted from StrategyBuilder."""

    def __init__(self, builder: Any, context: CandidateExecutionContext) -> None:
        self.builder = builder
        self.ctx = context
        self.candidate_proposal = copy.deepcopy(context.proposal)
        self.candidate_feedback = copy.deepcopy(context.proposal_feedback)
        self.outcome: dict[str, Any] = {
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
            "checkpoint_file": "runtime_checkpoint.json",
        }
        self.change_type = _normalize_change_type(
            self.candidate_proposal.get("change_type", "logic"),
        )
        self.has_stable_base_code = bool(
            context.last_iteration
            and context.last_iteration.code
            and context.last_iteration.error is None
            and context.last_iteration.backtest_result is not None,
        )
        self.code_feedback: dict[str, Any] = {
            "phase": "code",
            "initial_kind": "local_patch",
            "realign_attempts": 0,
            "realign_success": False,
            "final_valid": True,
        }
        self.precheck_feedback: dict[str, Any] = {}
        self.backtest_feedback: dict[str, Any] = {}
        self.pre_reflection_feedback: dict[str, Any] = {}
        self.current_stage = "init"
        self.req_inds = [
            str(x).strip().lower()
            for x in self.candidate_proposal.get("used_indicators", [])
            if isinstance(x, str) and str(x).strip()
        ]

    def execute(self) -> tuple[dict[str, Any], int]:
        try:
            self._apply_change_type_policy()
            code = self._resolve_candidate_code()
            self._checkpoint("code_generated", "ok")
            self.current_stage = "save_and_load"
            self._phase_start(
                "save_and_load",
                detail="écriture du candidat et chargement dynamique",
            )
            self._checkpoint("save_and_load", "start")
            strategy_cls = self.builder._save_and_load(
                self.ctx.session,
                code,
                self.ctx.iteration_num,
            )
            self._checkpoint("save_and_load", "ok")
            self._phase_done("save_and_load", status="ok", detail="stratégie chargée")
            if self.builder.ablation.is_enabled("auto_fix_indicators"):
                strategy_cls = self.builder._auto_fix_required_indicators(
                    strategy_cls,
                    code,
                )
            self.current_stage = "precheck"
            self._phase_start(
                "precheck",
                detail="validation densité / répartition des signaux",
            )
            self._checkpoint("precheck", "start")
            signal_probe = self.builder._precheck_signal_counts(
                strategy_cls,
                self.ctx.data,
                self.candidate_proposal.get("default_params", {}),
            )
            self.precheck_feedback.update(
                {
                    "signal_count": int(signal_probe.get("total_signals", 0) or 0),
                    "bar_count": len(self.ctx.data.index),
                },
            )
            self._checkpoint(
                "precheck",
                "ok",
                extra={"signal_probe": dict(signal_probe or {})},
            )
            # ── Micro-benchmark generate_signals ──
            if signal_probe.get("ok"):
                perf_bench = self._benchmark_generate_signals(strategy_cls)
                self.code_feedback["perf_benchmark"] = perf_bench
            else:
                perf_bench = {"ok": False, "median_ms": 0.0, "is_slow": False}
            code, bt_result = self._execute_backtest_pipeline(
                strategy_cls,
                code,
                signal_probe,
            )
            self.current_stage = "finalize"
            self._finalize_success(code, bt_result)
            self._checkpoint("iteration_complete", "ok")
            self.builder._instrument_candidate_outcome(
                self.outcome,
                self.ctx.iteration_num,
            )
            return self.outcome, self.ctx.fallback_count
        except BaseException as exc:
            failure_text = f"{type(exc).__name__}: {exc}"
            traceback_tail = _safe_format_exception(exc)
            self.outcome["error"] = failure_text
            self.outcome["failure_stage"] = self.current_stage
            self.outcome["traceback_tail"] = traceback_tail
            self.outcome["proposal_feedback"] = self.candidate_feedback
            self.outcome["code_feedback"] = self.code_feedback
            self.outcome["precheck_feedback"] = self.precheck_feedback
            self.outcome["pre_reflection_feedback"] = self.pre_reflection_feedback
            self.outcome["backtest_feedback"] = self.backtest_feedback
            if self.current_stage and self.current_stage != "init":
                self._phase_done(
                    self.current_stage,
                    status="error",
                    detail=failure_text,
                )
            self._checkpoint(
                self.current_stage or "unknown",
                "error",
                error=failure_text,
                traceback_tail=traceback_tail,
            )
            self.builder._instrument_candidate_outcome(
                self.outcome,
                self.ctx.iteration_num,
            )
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            return self.outcome, self.ctx.fallback_count

    def _checkpoint(
        self,
        stage: str,
        status: str,
        *,
        error: str = "",
        traceback_tail: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.builder._persist_runtime_checkpoint(
            self.ctx.session,
            iteration_num=self.ctx.iteration_num,
            stage=stage,
            status=status,
            branch_label=self.ctx.branch_label,
            error=error,
            traceback_tail=traceback_tail,
            proposal_feedback=self.candidate_feedback,
            code_feedback=self.code_feedback,
            precheck_feedback=self.precheck_feedback,
            backtest_feedback=self.backtest_feedback,
            extra=extra,
        )

    def _phase_start(self, phase: str, *, detail: str = "") -> None:
        self.builder._emit_progress(
            "phase_start",
            iteration=self.ctx.iteration_num,
            phase=phase,
            branch_label=self.ctx.branch_label,
            detail=detail,
        )

    def _phase_done(
        self,
        phase: str,
        *,
        status: str = "done",
        detail: str = "",
        **payload: Any,
    ) -> None:
        self.builder._emit_progress(
            "phase_done",
            iteration=self.ctx.iteration_num,
            phase=phase,
            branch_label=self.ctx.branch_label,
            status=status,
            detail=detail,
            **payload,
        )

    def _apply_change_type_policy(self) -> None:
        last_iteration = self.ctx.last_iteration
        if self.change_type == "params" and self.has_stable_base_code and last_iteration and last_iteration.code:
            params_override_reasons: list[str] = []
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
        if self.change_type == "params" and self.has_stable_base_code and last_iteration and last_iteration.code:
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
                    self.code_feedback["params_contract_fallback"] = "reused_previous_code"

        return self._validate_candidate_code(code)

    def _extract_logic_attempt(
        self,
        raw_code: str,
        *,
        prefer_generate_signals_block: bool = False,
    ) -> CodeAttempt:
        logic_block = _extract_generate_signals_logic_block(raw_code) if prefer_generate_signals_block else ""
        if not logic_block.strip():
            logic_block = _extract_python_from_response(raw_code)
        if self.builder.ablation.is_enabled("postprocess_logic"):
            logic_block = _postprocess_llm_logic_block(logic_block, self.req_inds)
        logic_ok, logic_err = _validate_llm_logic_block(logic_block)
        return CodeAttempt(
            logic=logic_block,
            logic_error="" if logic_ok else str(logic_err or "invalid_logic"),
        )

    def _build_code_attempt_from_logic(
        self,
        attempt: CodeAttempt,
        *,
        repair_and_validate: bool,
    ) -> CodeAttempt:
        if attempt.logic_error:
            return attempt
        attempt.code = strategy_builder_module._build_deterministic_strategy_code(
            self.candidate_proposal,
            attempt.logic,
        )
        if not repair_and_validate:
            return attempt
        attempt.code = self._repair_candidate_code(attempt.code)
        is_valid, validation_error = validate_generated_code(attempt.code)
        if not is_valid:
            attempt.validation_error = str(validation_error or "invalid_code")
        return attempt

    def _retry_code_attempt(self, *, repair_and_validate: bool) -> CodeAttempt:
        retry_logic_raw = self.builder._retry_code_simple(self.candidate_proposal)
        attempt = self._extract_logic_attempt(retry_logic_raw)
        return self._build_code_attempt_from_logic(
            attempt,
            repair_and_validate=repair_and_validate,
        )

    def _repair_candidate_code(self, code: str) -> str:
        repaired_code = (
            _repair_code(
                code,
                self.req_inds,
                enable_indicator_binding=self.builder.ablation.is_enabled(
                    "indicator_binding",
                ),
            )
            if self.builder.ablation.is_enabled("code_repair")
            else code
        )
        repaired_code, vectorize_fixes = _auto_repair_vectorize(repaired_code)
        if vectorize_fixes:
            self.code_feedback["vectorize_fixes"] = vectorize_fixes
        return repaired_code

    def _validated_deterministic_fallback(
        self,
        *,
        invalid_fallback_error: str,
        mark_code_fallback: bool = True,
        runtime_feedback_key: str | None = None,
    ) -> str:
        fallback_code = self._next_fallback_code()
        is_valid_fb, fallback_error = validate_generated_code(fallback_code)
        if not is_valid_fb:
            self.outcome["error"] = invalid_fallback_error.replace(
                "{fallback_error}",
                str(fallback_error or "invalid_fallback"),
            )
            self.outcome["code_feedback"] = self.code_feedback
            self.outcome["backtest_feedback"] = self.backtest_feedback
            raise RuntimeError(str(self.outcome["error"]))
        self.code_feedback["source"] = "deterministic_fallback"
        self.code_feedback["fallback_variant"] = self.ctx.fallback_count - 1
        if mark_code_fallback:
            self.code_feedback["fallback_deterministic_used"] = True
        if runtime_feedback_key:
            self.backtest_feedback[runtime_feedback_key] = True
        return fallback_code

    def _infer_indicator_contract_gap(
        self,
        code: str,
    ) -> tuple[list[str], list[str]]:
        inferred = list(
            strategy_builder_module._infer_required_indicator_names_from_code(
                code,
                self.req_inds,
            ),
        )
        unexpected = [ind for ind in inferred if ind not in self.req_inds]
        return inferred, unexpected

    def _build_code_from_llm_response(self, raw_code: str) -> str:
        if self.code_feedback.get("source") == "params_patch":
            return raw_code

        first_attempt = self._build_code_attempt_from_logic(
            self._extract_logic_attempt(
                raw_code,
                prefer_generate_signals_block=True,
            ),
            repair_and_validate=False,
        )
        if first_attempt.ok:
            return first_attempt.code

        self.code_feedback["validation_error"] = first_attempt.error
        retry_attempt = self._retry_code_attempt(repair_and_validate=False)
        if retry_attempt.ok:
            self.code_feedback["logic_retry_used"] = True
            return retry_attempt.code

        self.code_feedback["validation_error_retry"] = retry_attempt.error
        return self._validated_deterministic_fallback(
            invalid_fallback_error=(
                "Bloc logique LLM invalide après retry + fallback invalide: "
                f"{retry_attempt.error or first_attempt.error} | {{fallback_error}}"
            ),
        )

    def _validate_candidate_code(self, code: str) -> str:
        repaired_code = self._repair_candidate_code(code)
        is_valid, error_msg = validate_generated_code(repaired_code)
        if is_valid:
            return self._enforce_indicator_contract(repaired_code, allow_retry=True)

        self.code_feedback["validation_error"] = error_msg
        retry_attempt = self._retry_code_attempt(repair_and_validate=True)
        if retry_attempt.ok:
            return self._enforce_indicator_contract(
                retry_attempt.code,
                allow_retry=False,
            )

        self.code_feedback["validation_error_retry"] = retry_attempt.error
        return self._validated_deterministic_fallback(
            invalid_fallback_error=(
                f"Validation échouée: {error_msg} | retry: {retry_attempt.error} | fallback: {{fallback_error}}"
            ),
        )

    def _enforce_indicator_contract(self, code: str, *, allow_retry: bool) -> str:
        if not self.req_inds:
            return code

        inferred, unexpected = self._infer_indicator_contract_gap(code)
        if not unexpected:
            return code

        self.code_feedback["indicator_contract_violation"] = {
            "declared": list(self.req_inds),
            "inferred": list(inferred),
            "unexpected": list(unexpected),
        }
        self.code_feedback["indicator_contract_status"] = "retry" if allow_retry else "fallback"

        if allow_retry:
            retry_attempt = self._retry_code_attempt(repair_and_validate=True)
            if retry_attempt.ok:
                retry_inferred, retry_unexpected = self._infer_indicator_contract_gap(
                    retry_attempt.code,
                )
                if not retry_unexpected:
                    self.code_feedback["indicator_contract_retry_used"] = True
                    return retry_attempt.code
                self.code_feedback["indicator_contract_retry_violation"] = {
                    "declared": list(self.req_inds),
                    "inferred": list(retry_inferred),
                    "unexpected": list(retry_unexpected),
                }
            elif retry_attempt.validation_error:
                self.code_feedback["indicator_contract_retry_validation_error"] = retry_attempt.validation_error
            else:
                self.code_feedback["indicator_contract_retry_logic_error"] = retry_attempt.logic_error

        return self._validated_deterministic_fallback(
            invalid_fallback_error=("Indicator contract fallback invalide: {fallback_error}"),
        )

    def _execute_backtest_pipeline(
        self,
        strategy_cls: Any,
        code: str,
        signal_probe: dict[str, Any],
    ) -> tuple[str, Any]:
        if not signal_probe.get("ok"):
            self.precheck_feedback["backtest_skipped"] = True
            self._phase_done(
                "precheck",
                status="blocked",
                detail="précheck bloquant: aucun signal exploitable",
            )
            self._checkpoint(
                "precheck",
                "blocked",
                extra={"signal_probe": dict(signal_probe or {})},
            )
            return code, self._empty_backtest_result()

        if self.builder._is_pathological_signal_profile(signal_probe) and self.builder.ablation.is_enabled("precheck"):
            self.precheck_feedback.update(
                {
                    "pathological_signal_density": True,
                    "skip_reason": "pathological_signal_density",
                    "backtest_skipped": True,
                },
            )
            self._phase_done(
                "precheck",
                status="blocked",
                detail="précheck bloquant: densité de signaux pathologique",
            )
            self._checkpoint(
                "precheck",
                "blocked",
                extra={"signal_probe": dict(signal_probe or {})},
            )
            return code, self.builder._build_precheck_overtrading_result(signal_probe)

        signal_count = int(signal_probe.get("total_signals", 0) or 0)
        self._phase_done(
            "precheck",
            status="ok",
            detail=f"{signal_count} signaux détectés avant backtest",
        )

        pre_reflection_future = None
        pre_reflection_pool: concurrent.futures.ThreadPoolExecutor | None = None
        try:
            if self.builder.ablation.is_enabled("pre_reflection"):
                try:
                    pre_reflection_pool = strategy_builder_module._new_streamlit_aware_thread_pool(
                        max_workers=1,
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
                self.current_stage = "backtest"
                self._phase_start("backtest", detail="simulation de la stratégie")
                self._checkpoint("backtest", "start")
                bt_result = self._run_backtest(strategy_cls)
                self._checkpoint("backtest", "ok")
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

            best_params = self.backtest_feedback.get("params_used")
            if isinstance(best_params, dict) and best_params:
                self.candidate_proposal["default_params"] = dict(best_params)
                parameter_specs = self.candidate_proposal.get("parameter_specs", {})
                if isinstance(parameter_specs, dict):
                    for param_name, param_value in best_params.items():
                        spec = parameter_specs.get(param_name)
                        if isinstance(spec, dict):
                            spec["default"] = param_value
                patched_code = _rewrite_default_params_from_proposal(
                    code,
                    self.candidate_proposal,
                )
                if patched_code:
                    code = patched_code
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
        self.backtest_feedback["runtime_traceback_tail"] = _safe_format_exception(
            bt_exc,
        )
        self.current_stage = "runtime_fix"
        self._phase_start("runtime_fix", detail=bt_error)
        self._checkpoint(
            "backtest",
            "error",
            error=bt_error,
            traceback_tail=self.backtest_feedback["runtime_traceback_tail"],
        )
        if self.builder.ablation.is_enabled("runtime_fix"):
            self._checkpoint("runtime_fix", "start")
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
            retry_code = self._validated_deterministic_fallback(
                invalid_fallback_error=(
                    f"Runtime-fix invalide et fallback déterministe invalide: {retry_err} | {{fallback_error}}"
                ),
                mark_code_fallback=False,
                runtime_feedback_key="runtime_fix_fallback_deterministic_used",
            )
            used_runtime_fallback = True

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
            retry_bt_error = f"{type(retry_bt_exc).__name__}: {retry_bt_exc}"
            self.backtest_feedback["runtime_fix_retry_error"] = retry_bt_error
            self._checkpoint(
                "runtime_fix",
                "error",
                error=retry_bt_error,
                traceback_tail=_safe_format_exception(retry_bt_exc),
            )
            self._phase_done(
                "runtime_fix",
                status="error",
                detail=retry_bt_error,
            )
            if used_runtime_fallback:
                self.outcome["error"] = retry_bt_error
                self.outcome["code_feedback"] = self.code_feedback
                self.outcome["backtest_feedback"] = self.backtest_feedback
                raise RuntimeError(str(self.outcome["error"])) from retry_bt_exc  # pylint: disable=raise-missing-from

            fallback_code = self._validated_deterministic_fallback(
                invalid_fallback_error=(
                    "Runtime-fix backtest failed and deterministic fallback is invalid: {fallback_error}"
                ),
                mark_code_fallback=False,
                runtime_feedback_key="runtime_fix_fallback_deterministic_used",
            )
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
            self._phase_start(
                "runtime_fix_fallback_backtest",
                detail="fallback déterministe après échec du patch runtime",
            )
            self._checkpoint("runtime_fix_fallback_backtest", "start")
            bt_result = self._run_backtest(fallback_cls)
            self._checkpoint("runtime_fix_fallback_backtest", "ok")
            self._phase_done(
                "runtime_fix_fallback_backtest",
                status="ok",
                detail="fallback runtime validé",
            )
            retry_code = fallback_code

        self.backtest_feedback["runtime_fix_applied"] = True
        self._checkpoint("runtime_fix", "ok")
        self._phase_done("runtime_fix", status="ok", detail="patch runtime appliqué")
        return retry_code, bt_result

    def _run_backtest(self, strategy_cls: Any) -> Any:
        if (
            self.candidate_feedback.get("fallback_deterministic_used")
            or self.candidate_feedback.get("source") == "deterministic_fallback"
        ):
            params = dict(self.candidate_proposal.get("default_params", {}) or {})
            self.backtest_feedback.update(
                {
                    "mode": "single",
                    "params_used": dict(params),
                    "sweep_skipped_reason": "deterministic_fallback",
                },
            )
            return self.builder._run_backtest(
                strategy_cls,
                self.ctx.data,
                params,
                self.ctx.initial_capital,
                symbol=self.ctx.session.symbol,
                timeframe=self.ctx.session.timeframe,
                fees_bps=self.ctx.session.fees_bps,
                slippage_bps=self.ctx.session.slippage_bps,
                direction_constraint=self.ctx.session.direction_constraint,
            )

        bt_result, feedback = self.builder._run_backtest_with_optional_sweep(
            strategy_cls,
            self.ctx.data,
            self.candidate_proposal,
            initial_capital=self.ctx.initial_capital,
            symbol=self.ctx.session.symbol,
            timeframe=self.ctx.session.timeframe,
            fees_bps=self.ctx.session.fees_bps,
            slippage_bps=self.ctx.session.slippage_bps,
            direction_constraint=self.ctx.session.direction_constraint,
            target_sharpe=self.ctx.session.target_sharpe,
        )
        if isinstance(feedback, dict):
            self.backtest_feedback.update(feedback)
        return bt_result

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
                "runtime_fix_fallback_deterministic_used",
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
                "code_quality_score": self._compute_code_quality_score(),
            },
        )

    # ── Micro-benchmark ────────────────────────────────────────────────

    _BENCH_N_RUNS: int = 5
    _BENCH_MAX_BARS: int = 5000
    _BENCH_THRESHOLD_MS: float = 50.0

    def _benchmark_generate_signals(self, strategy_cls: Any) -> dict[str, Any]:
        """Median generate_signals latency over *_BENCH_N_RUNS* runs."""
        from backtest.engine import BacktestEngine
        from utils.observability import generate_run_id

        try:
            engine = BacktestEngine(
                initial_capital=10_000.0,
                run_id=generate_run_id(),
            )
            inst = strategy_cls()
            params = dict(getattr(inst, "default_params", {}) or {})
            params.update(self.candidate_proposal.get("default_params", {}) or {})

            bench_df = self.ctx.data.iloc[: self._BENCH_MAX_BARS].copy(deep=True)
            indicators = engine.calculate_indicators(bench_df, inst, params)

            # Warmup (JIT / caches)
            inst.generate_signals(bench_df, indicators, params)

            timings: list[float] = []
            for _ in range(self._BENCH_N_RUNS):
                t0 = _time.perf_counter()
                inst.generate_signals(bench_df, indicators, params)
                timings.append((_time.perf_counter() - t0) * 1000.0)

            timings.sort()
            median_ms = timings[len(timings) // 2]
            return {
                "ok": True,
                "median_ms": round(median_ms, 3),
                "min_ms": round(timings[0], 3),
                "max_ms": round(timings[-1], 3),
                "n_bars": len(bench_df),
                "n_runs": self._BENCH_N_RUNS,
                "threshold_ms": self._BENCH_THRESHOLD_MS,
                "is_slow": median_ms > self._BENCH_THRESHOLD_MS,
            }
        except Exception:  # noqa: BLE001
            return {"ok": False, "median_ms": 0.0, "is_slow": False}

    # ── Code-quality score ─────────────────────────────────────────────

    def _compute_code_quality_score(self) -> float:
        """0–1 composite: 1 = fast + clean LLM code, 0 = slow / many repairs / fallback."""
        bench = self.code_feedback.get("perf_benchmark") or {}
        median_ms = float(bench.get("median_ms", 0.0) or 0.0)
        threshold = float(bench.get("threshold_ms", self._BENCH_THRESHOLD_MS) or self._BENCH_THRESHOLD_MS)

        # Speed component: 1.0 if <= 5 ms, 0.0 if >= threshold
        if threshold > 0 and median_ms > 0:
            perf = max(0.0, 1.0 - median_ms / threshold)
        else:
            perf = 1.0

        # Repair penalty: each fix costs 0.05, cap 0.4
        vectorize_fixes = int(self.code_feedback.get("vectorize_fixes", 0) or 0)
        logic_retry = 1 if self.code_feedback.get("logic_retry_used") else 0
        repair_penalty = min((vectorize_fixes + logic_retry) * 0.05, 0.4)

        # Fallback penalty
        fallback_penalty = 0.5 if self.outcome.get("is_fallback") else 0.0

        return round(max(0.0, perf - repair_penalty - fallback_penalty), 4)

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
    proposal: dict[str, Any],
    proposal_feedback: dict[str, Any],
    last_iteration: BuilderIteration | None,
    iteration_num: int,
    data: pd.DataFrame,
    initial_capital: float,
    fallback_count: int,
    branch_label: str = "main",
) -> tuple[dict[str, Any], int]:
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
