"""
Module-ID: agents.pipeline_instrumentation

Purpose: Instrumentation complète du pipeline Builder pour mesurer, tracer et
         analyser chaque étape de la boucle itérative (proposal → code → repair →
         precheck → backtest → telemetry scoring → diagnostic → decision).

Role in pipeline: observabilité / diagnostic / ablation

Key components:
  - PipelineTrace: dataclass enregistrant toutes les mesures d'une itération
  - PipelineInstrumentation: singleton attachable au Builder pour capturer les traces
  - AblationController: outil pour désactiver sélectivement des étapes du pipeline
  - DivergenceAnalyzer: compare deux traces pour identifier la source d'un écart
  - CanonicalCase: cas de test A/B/C avec entrées/sorties attendues

Dependencies: agents.builder_constants, agents.builder_diagnostics

Read-if: Diagnostic de performance du Builder, audit de pipeline, ablation testing.
Skip-if: Usage normal du Builder sans besoin de profiling.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional



# =====================================================================
# 1. Pipeline Phase Enum
# =====================================================================

class PipelinePhase(str, Enum):
    """Phases mesurables du pipeline Builder."""
    PROPOSAL = "proposal"
    CODE_GEN = "code_gen"
    CODE_REPAIR = "code_repair"
    CODE_VALIDATE = "code_validate"
    PRECHECK = "precheck"
    BACKTEST = "backtest"
    RUNTIME_FIX = "runtime_fix"
    SCORING = "scoring"
    DIAGNOSTIC = "diagnostic"
    ANALYSIS = "analysis"
    DECISION = "decision"
    BRANCHING = "branching"
    PRE_REFLECTION = "pre_reflection"


# =====================================================================
# 2. Phase Measurement
# =====================================================================

@dataclass
class PhaseMeasurement:
    """Mesure d'une phase individuelle du pipeline."""
    phase: str
    started_at: float = 0.0
    duration_sec: float = 0.0
    success: bool = True
    error: Optional[str] = None
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return not self.success


# =====================================================================
# 3. Pipeline Trace (une itération complète)
# =====================================================================

@dataclass
class PipelineTrace:
    """Trace complète d'une itération Builder."""
    iteration_num: int = 0
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)

    # Phases mesurées
    phases: List[PhaseMeasurement] = field(default_factory=list)

    # Résumé proposal
    proposal_change_type: str = ""
    proposal_indicators: List[str] = field(default_factory=list)
    proposal_hypothesis: str = ""
    proposal_source: str = ""  # "llm" | "deterministic_fallback"

    # Résumé code
    code_source: str = ""  # "llm" | "params_patch" | "deterministic_fallback" | "runtime_fix"
    code_lines: int = 0
    code_hash: str = ""
    validation_passed_first: bool = False
    repair_applied: bool = False
    fallback_used: bool = False
    fallback_variant: int = -1

    # Résumé precheck
    precheck_passed: Optional[bool] = None
    precheck_signal_count: int = 0
    precheck_error: Optional[str] = None

    # Résumé backtest
    backtest_ran: bool = False
    backtest_metrics: Dict[str, Any] = field(default_factory=dict)
    runtime_fix_applied: bool = False
    runtime_error: Optional[str] = None

    # Telemetry scoring (observability only)
    continuous_score: float = 0.0
    rank_score: float = float("-inf")
    score_components: Dict[str, float] = field(default_factory=dict)
    score_penalties: Dict[str, float] = field(default_factory=dict)

    # Diagnostic
    diagnostic_category: str = ""
    diagnostic_severity: str = ""
    diagnostic_change_type: str = ""

    # Decision
    decision: str = ""
    decision_overridden: bool = False
    decision_override_reason: str = ""

    # Stagnation
    stagnation_detected: bool = False
    stagnation_circuit_breaker: bool = False
    branching_enabled: bool = False
    branch_count: int = 0
    restriction_events: List[Dict[str, Any]] = field(default_factory=list)

    # Meta
    is_fallback: bool = False
    is_best_so_far: bool = False
    ablation_config: Dict[str, bool] = field(default_factory=dict)
    total_duration_sec: float = 0.0

    def add_phase(self, measurement: PhaseMeasurement) -> None:
        self.phases.append(measurement)

    def get_phase(self, phase: str) -> Optional[PhaseMeasurement]:
        for m in self.phases:
            if m.phase == phase:
                return m
        return None

    def phase_duration(self, phase: str) -> float:
        m = self.get_phase(phase)
        return m.duration_sec if m else 0.0

    def failed_phases(self) -> List[str]:
        return [m.phase for m in self.phases if m.failed]

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["telemetry_score"] = self.continuous_score
        payload["telemetry_rank_score"] = self.rank_score
        payload["telemetry_components"] = dict(self.score_components)
        payload["telemetry_penalties"] = dict(self.score_penalties)
        return payload

    @property
    def telemetry_score(self) -> float:
        return self.continuous_score

    @property
    def telemetry_rank_score(self) -> float:
        return self.rank_score

    @property
    def telemetry_components(self) -> Dict[str, float]:
        return self.score_components

    @property
    def telemetry_penalties(self) -> Dict[str, float]:
        return self.score_penalties

    def metrics_fingerprint(self) -> str:
        keys = ("total_return_pct", "max_drawdown_pct", "total_trades",
                "win_rate_pct", "profit_factor")
        parts = []
        for k in keys:
            v = self.backtest_metrics.get(k, 0) or 0
            parts.append(f"{k}={float(v):.4f}")
        return "|".join(parts)


# =====================================================================
# 4. Pipeline Instrumentation Controller
# =====================================================================

class PipelineInstrumentation:
    """Contrôleur d'instrumentation attachable au Builder.

    Usage:
        instr = PipelineInstrumentation()
        # Au début d'une itération:
        trace = instr.begin_iteration(i, session_id)
        # Pour chaque phase:
        with instr.measure(trace, PipelinePhase.PROPOSAL) as m:
            proposal = builder._ask_proposal(...)
            m.metadata["indicators"] = proposal.get("used_indicators", [])
        # En fin d'itération:
        instr.finalize_iteration(trace)
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.traces: List[PipelineTrace] = []
        self._current_trace: Optional[PipelineTrace] = None
        self._session_id: str = ""

    def begin_iteration(
        self,
        iteration_num: int,
        session_id: str = "",
    ) -> PipelineTrace:
        trace = PipelineTrace(
            iteration_num=iteration_num,
            session_id=session_id or self._session_id,
            timestamp=time.time(),
        )
        self._current_trace = trace
        self._session_id = session_id or self._session_id
        return trace

    def finalize_iteration(self, trace: PipelineTrace) -> None:
        trace.total_duration_sec = sum(
            m.duration_sec for m in trace.phases
        )
        self.traces.append(trace)
        self._current_trace = None

    class _PhaseMeasurer:
        """Context manager pour mesurer une phase."""
        def __init__(self, trace: PipelineTrace, phase: str):
            self.trace = trace
            self.measurement = PhaseMeasurement(phase=phase)

        def __enter__(self) -> PhaseMeasurement:
            self.measurement.started_at = time.perf_counter()
            return self.measurement

        def __exit__(self, exc_type, exc_val, _exc_tb):
            self.measurement.duration_sec = (
                time.perf_counter() - self.measurement.started_at
            )
            if exc_type is not None:
                self.measurement.success = False
                self.measurement.error = f"{exc_type.__name__}: {exc_val}"
            self.trace.add_phase(self.measurement)
            return False  # don't swallow exceptions

    def measure(
        self,
        trace: PipelineTrace,
        phase: PipelinePhase,
    ) -> "_PhaseMeasurer":
        return self._PhaseMeasurer(trace, phase.value)

    # ------------------------------------------------------------------
    # Helpers de capture haut-niveau
    # ------------------------------------------------------------------

    def record_proposal(
        self,
        trace: PipelineTrace,
        proposal: Dict[str, Any],
        source: str = "llm",
        duration: float = 0.0,
    ) -> None:
        trace.proposal_change_type = proposal.get("change_type", "logic")
        trace.proposal_indicators = proposal.get("used_indicators", [])
        trace.proposal_hypothesis = proposal.get("hypothesis", "")
        trace.proposal_source = source

    def record_code(
        self,
        trace: PipelineTrace,
        code: str,
        source: str = "llm",
        valid_first: bool = True,
        repair_applied: bool = False,
        fallback_used: bool = False,
        fallback_variant: int = -1,
    ) -> None:
        trace.code_source = source
        trace.code_lines = len(code.splitlines()) if code else 0
        trace.code_hash = hashlib.md5(
            code.encode("utf-8", errors="replace")
        ).hexdigest()[:12] if code else ""
        trace.validation_passed_first = valid_first
        trace.repair_applied = repair_applied
        trace.fallback_used = fallback_used
        trace.fallback_variant = fallback_variant
        trace.is_fallback = fallback_used

    def record_precheck(
        self,
        trace: PipelineTrace,
        passed: bool,
        signal_count: int = 0,
        error: Optional[str] = None,
    ) -> None:
        trace.precheck_passed = passed
        trace.precheck_signal_count = signal_count
        trace.precheck_error = error

    def record_backtest(
        self,
        trace: PipelineTrace,
        metrics: Dict[str, Any],
        runtime_fix: bool = False,
        runtime_error: Optional[str] = None,
    ) -> None:
        trace.backtest_ran = True
        trace.backtest_metrics = dict(metrics or {})
        trace.runtime_fix_applied = runtime_fix
        trace.runtime_error = runtime_error

    def record_scoring(
        self,
        trace: PipelineTrace,
        score_payload: Dict[str, Any],
        rank_score: float,
    ) -> None:
        trace.continuous_score = float(
            score_payload.get("score", 0.0)
        )
        trace.rank_score = rank_score
        trace.score_components = dict(
            score_payload.get("components", {})
        )
        trace.score_penalties = dict(
            score_payload.get("penalties", {})
        )

    def record_diagnostic(
        self,
        trace: PipelineTrace,
        diag: Dict[str, Any],
    ) -> None:
        trace.diagnostic_category = diag.get("category", "")
        trace.diagnostic_severity = diag.get("severity", "")
        trace.diagnostic_change_type = diag.get("change_type", "")

    def record_decision(
        self,
        trace: PipelineTrace,
        decision: str,
        overridden: bool = False,
        override_reason: str = "",
    ) -> None:
        trace.decision = decision
        trace.decision_overridden = overridden
        trace.decision_override_reason = override_reason

    def record_stagnation(
        self,
        trace: PipelineTrace,
        detected: bool = False,
        circuit_breaker: bool = False,
        branching: bool = False,
        branch_count: int = 0,
    ) -> None:
        trace.stagnation_detected = detected
        trace.stagnation_circuit_breaker = circuit_breaker
        trace.branching_enabled = branching
        trace.branch_count = branch_count

    def record_restriction(
        self,
        trace: PipelineTrace,
        kind: str,
        *,
        effect: str,
        detail: str = "",
        phase: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        trace.restriction_events.append(
            {
                "kind": str(kind or "").strip(),
                "effect": str(effect or "").strip() or "neutral",
                "detail": str(detail or "").strip(),
                "phase": str(phase or "").strip(),
                "metadata": dict(metadata or {}),
            }
        )

    # ------------------------------------------------------------------
    # Export / reporting
    # ------------------------------------------------------------------

    def session_summary(self) -> Dict[str, Any]:
        """Résumé agrégé de toutes les itérations tracées."""
        if not self.traces:
            return {"iterations": 0}

        total_dur = sum(t.total_duration_sec for t in self.traces)
        phase_totals: Dict[str, float] = {}
        phase_counts: Dict[str, int] = {}
        phase_errors: Dict[str, int] = {}
        for t in self.traces:
            for m in t.phases:
                phase_totals[m.phase] = phase_totals.get(m.phase, 0) + m.duration_sec
                phase_counts[m.phase] = phase_counts.get(m.phase, 0) + 1
                if m.failed:
                    phase_errors[m.phase] = phase_errors.get(m.phase, 0) + 1

        code_sources = {}
        for t in self.traces:
            src = t.code_source or "unknown"
            code_sources[src] = code_sources.get(src, 0) + 1

        decisions = {}
        for t in self.traces:
            d = t.decision or "unknown"
            decisions[d] = decisions.get(d, 0) + 1

        telemetry_scores = [t.continuous_score for t in self.traces if t.backtest_ran]
        fallback_rate = (
            sum(1 for t in self.traces if t.fallback_used) / len(self.traces)
            if self.traces else 0.0
        )
        repair_rate = (
            sum(1 for t in self.traces if t.repair_applied) / len(self.traces)
            if self.traces else 0.0
        )
        runtime_fix_count = sum(1 for t in self.traces if t.runtime_fix_applied)
        precheck_skip_count = sum(1 for t in self.traces if t.precheck_passed is False)
        decision_override_count = sum(1 for t in self.traces if t.decision_overridden)
        restriction_counts: Dict[str, int] = {}
        blocker_counts: Dict[str, int] = {}
        helper_counts: Dict[str, int] = {}
        for t in self.traces:
            for event in list(t.restriction_events or []):
                kind = str(event.get("kind", "") or "").strip()
                if not kind:
                    continue
                restriction_counts[kind] = restriction_counts.get(kind, 0) + 1
                effect = str(event.get("effect", "") or "").strip().lower()
                if effect == "blocker":
                    blocker_counts[kind] = blocker_counts.get(kind, 0) + 1
                elif effect == "helper":
                    helper_counts[kind] = helper_counts.get(kind, 0) + 1

        phase_avg = {
            phase: round(phase_totals[phase] / phase_counts[phase], 2)
            for phase in phase_totals.keys()
            if phase_counts.get(phase)
        }

        return {
            "iterations": len(self.traces),
            "total_duration_sec": round(total_dur, 2),
            "avg_iteration_sec": round(total_dur / len(self.traces), 2),
            "phase_totals_sec": {k: round(v, 2) for k, v in phase_totals.items()},
            "phase_avg_sec": phase_avg,
            "phase_counts": phase_counts,
            "phase_errors": phase_errors,
            "code_sources": code_sources,
            "decisions": decisions,
            "fallback_rate": round(fallback_rate, 4),
            "repair_rate": round(repair_rate, 4),
            "runtime_fix_count": runtime_fix_count,
            "precheck_skip_count": precheck_skip_count,
            "decision_override_count": decision_override_count,
            "score_min": round(min(telemetry_scores), 2) if telemetry_scores else None,
            "score_max": round(max(telemetry_scores), 2) if telemetry_scores else None,
            "score_mean": round(sum(telemetry_scores) / len(telemetry_scores), 2)
            if telemetry_scores
            else None,
            "telemetry_score_min": round(min(telemetry_scores), 2) if telemetry_scores else None,
            "telemetry_score_max": round(max(telemetry_scores), 2) if telemetry_scores else None,
            "telemetry_score_mean": round(sum(telemetry_scores) / len(telemetry_scores), 2)
            if telemetry_scores
            else None,
            "stagnation_count": sum(1 for t in self.traces if t.stagnation_detected),
            "circuit_breaker_count": sum(1 for t in self.traces if t.stagnation_circuit_breaker),
            "restriction_events": restriction_counts,
            "blockers": [
                {"kind": kind, "count": count}
                for kind, count in sorted(
                    blocker_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ],
            "helpers": [
                {"kind": kind, "count": count}
                for kind, count in sorted(
                    helper_counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ],
        }

    def export_traces_json(self, path: Path) -> None:
        """Exporte toutes les traces en JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "session_id": self._session_id,
            "summary": self.session_summary(),
            "traces": [t.to_dict() for t in self.traces],
        }
        path.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )

    def reset(self) -> None:
        self.traces.clear()
        self._current_trace = None


# =====================================================================
# 5. Ablation Controller
# =====================================================================

class AblationController:
    """Désactive sélectivement des étapes du pipeline Builder pour tester
    l'impact de chaque composant.

    Usage:
        ablation = AblationController()
        ablation.disable("code_repair")
        ablation.disable("precheck")
        # Pendant le pipeline:
        if ablation.is_enabled("code_repair"):
            code = _repair_code(code, req_inds)
    """

    # Étapes désactivables
    ABLATABLE_STEPS = frozenset({
        "code_repair",             # _repair_code()
        "precheck",                # _precheck_signal_counts()
        "postprocess_logic",       # _postprocess_llm_logic_block()
        "auto_fix_indicators",     # _auto_fix_required_indicators()
        "runtime_fix",             # _retry_code_runtime_fix()
        "deterministic_fallback",  # _build_deterministic_fallback_code()
        "stagnation_branching",    # branching on identical metrics
        "positive_progress_gate",  # early stop on insufficient positives
        "stop_override",           # policy override of LLM "stop"
        "accept_override",         # policy override of LLM "accept"
        "params_contract_check",   # _params_only_contract_respected()
        "indicator_binding",       # préambule de binding indicateurs
        "proposal_sanitize",       # _sanitize_proposal_payload()
        "prompt_leakage_filter",   # _strip_objective_prompt_leakage()
        "indicator_ranking",       # rank_indicator_selection() proposal + code
        "iteration_history",       # injection historique 5 dernières itérations
        "diagnostic_context",      # injection diagnostic/actions/donts dans prompts
        "pre_reflection",          # _ask_pre_reflection() — critique parallèle au backtest
        "llm_analysis",            # _ask_analysis() — 1 appel LLM par itération
    })

    def __init__(self) -> None:
        self._disabled: set[str] = set()

    def disable(self, step: str) -> None:
        if step not in self.ABLATABLE_STEPS:
            raise ValueError(
                f"Step '{step}' not ablatable. Choose from: "
                f"{sorted(self.ABLATABLE_STEPS)}"
            )
        self._disabled.add(step)

    def enable(self, step: str) -> None:
        self._disabled.discard(step)

    def is_enabled(self, step: str) -> bool:
        return step not in self._disabled

    def is_disabled(self, step: str) -> bool:
        return step in self._disabled

    def disable_all(self) -> None:
        self._disabled = set(self.ABLATABLE_STEPS)

    def enable_all(self) -> None:
        self._disabled.clear()

    def get_config(self) -> Dict[str, bool]:
        return {
            step: self.is_enabled(step)
            for step in sorted(self.ABLATABLE_STEPS)
        }

    def disabled_steps(self) -> List[str]:
        return sorted(self._disabled)


# =====================================================================
# 6. Divergence Analyzer
# =====================================================================

@dataclass
class Divergence:
    """Un point de divergence entre deux traces."""
    phase: str
    field: str
    trace_a_value: Any
    trace_b_value: Any
    severity: str  # "critical" | "warning" | "info"
    description: str


class DivergenceAnalyzer:
    """Compare deux PipelineTrace pour identifier précisément
    où et pourquoi les résultats divergent.

    Usage:
        analyzer = DivergenceAnalyzer()
        divergences = analyzer.compare(trace_baseline, trace_modified)
        report = analyzer.format_report(divergences)
    """

    # Champs critiques qui affectent directement le résultat
    CRITICAL_FIELDS = {
        "code_source", "code_hash", "fallback_used",
        "backtest_ran", "decision", "continuous_score",
    }
    # Champs importants mais non fatals
    WARNING_FIELDS = {
        "proposal_change_type", "proposal_indicators",
        "validation_passed_first", "repair_applied",
        "precheck_passed", "runtime_fix_applied",
        "diagnostic_category", "decision_overridden",
        "stagnation_detected",
    }

    def compare(
        self,
        trace_a: PipelineTrace,
        trace_b: PipelineTrace,
    ) -> List[Divergence]:
        """Compare deux traces et retourne les divergences ordonnées."""
        divergences: List[Divergence] = []

        # Compare les champs scalaires
        all_fields = set(self.CRITICAL_FIELDS | self.WARNING_FIELDS)
        for fld in sorted(all_fields):
            val_a = getattr(trace_a, fld, None)
            val_b = getattr(trace_b, fld, None)
            if val_a != val_b:
                severity = (
                    "critical" if fld in self.CRITICAL_FIELDS
                    else "warning"
                )
                divergences.append(Divergence(
                    phase=self._field_to_phase(fld),
                    field=fld,
                    trace_a_value=val_a,
                    trace_b_value=val_b,
                    severity=severity,
                    description=self._describe_divergence(fld, val_a, val_b),
                ))

        # Compare les métriques de backtest
        if trace_a.backtest_ran and trace_b.backtest_ran:
            metric_keys = (
                "total_return_pct", "sharpe_ratio", "max_drawdown_pct",
                "total_trades", "win_rate_pct", "profit_factor",
            )
            for mk in metric_keys:
                va = trace_a.backtest_metrics.get(mk)
                vb = trace_b.backtest_metrics.get(mk)
                if va is not None and vb is not None:
                    try:
                        diff = abs(float(va) - float(vb))
                    except (TypeError, ValueError):
                        diff = float("inf")
                    if diff > 1e-6:
                        severity = "critical" if mk in ("total_return_pct", "sharpe_ratio") else "warning"
                        divergences.append(Divergence(
                            phase="backtest",
                            field=f"metric_{mk}",
                            trace_a_value=va,
                            trace_b_value=vb,
                            severity=severity,
                            description=(
                                f"Metric '{mk}' differs: "
                                f"{va} vs {vb} (delta={diff:.4f})"
                            ),
                        ))

        # Compare les scores
        score_diff = abs(trace_a.continuous_score - trace_b.continuous_score)
        if score_diff > 0.5:
            # Détail des composants
            for comp_key in set(
                list(trace_a.score_components.keys())
                + list(trace_b.score_components.keys())
            ):
                ca = trace_a.score_components.get(comp_key, 0)
                cb = trace_b.score_components.get(comp_key, 0)
                if abs(ca - cb) > 0.1:
                    divergences.append(Divergence(
                        phase="scoring",
                        field=f"score_component_{comp_key}",
                        trace_a_value=round(ca, 3),
                        trace_b_value=round(cb, 3),
                        severity="info",
                        description=(
                            f"Score component '{comp_key}': "
                            f"{ca:.3f} vs {cb:.3f}"
                        ),
                    ))

        # Compare phases timing (>2x différence = warning)
        phases_a = {m.phase: m for m in trace_a.phases}
        phases_b = {m.phase: m for m in trace_b.phases}
        for phase_name in set(list(phases_a.keys()) + list(phases_b.keys())):
            ma = phases_a.get(phase_name)
            mb = phases_b.get(phase_name)
            if ma and mb and ma.duration_sec > 0 and mb.duration_sec > 0:
                ratio = max(ma.duration_sec, mb.duration_sec) / min(ma.duration_sec, mb.duration_sec)
                if ratio > 2.0:
                    divergences.append(Divergence(
                        phase=phase_name,
                        field="duration_sec",
                        trace_a_value=round(ma.duration_sec, 3),
                        trace_b_value=round(mb.duration_sec, 3),
                        severity="info",
                        description=(
                            f"Phase '{phase_name}' duration ratio: {ratio:.1f}x "
                            f"({ma.duration_sec:.2f}s vs {mb.duration_sec:.2f}s)"
                        ),
                    ))
            if ma and not mb:
                divergences.append(Divergence(
                    phase=phase_name,
                    field="phase_presence",
                    trace_a_value="present",
                    trace_b_value="absent",
                    severity="warning",
                    description=f"Phase '{phase_name}' only in trace A",
                ))
            elif mb and not ma:
                divergences.append(Divergence(
                    phase=phase_name,
                    field="phase_presence",
                    trace_a_value="absent",
                    trace_b_value="present",
                    severity="warning",
                    description=f"Phase '{phase_name}' only in trace B",
                ))

        # Trier par sévérité
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        divergences.sort(key=lambda d: severity_order.get(d.severity, 3))
        return divergences

    def format_report(
        self,
        divergences: List[Divergence],
        *,
        max_items: int = 50,
    ) -> str:
        """Formatage lisible des divergences."""
        if not divergences:
            return "Aucune divergence détectée entre les deux traces."

        lines = [
            f"=== Rapport de divergence ({len(divergences)} points) ===",
            "",
        ]

        by_severity = {"critical": [], "warning": [], "info": []}
        for d in divergences[:max_items]:
            by_severity.setdefault(d.severity, []).append(d)

        for sev in ("critical", "warning", "info"):
            items = by_severity.get(sev, [])
            if not items:
                continue
            lines.append(f"--- {sev.upper()} ({len(items)}) ---")
            for d in items:
                lines.append(
                    f"  [{d.phase}] {d.field}: "
                    f"{d.trace_a_value} → {d.trace_b_value}"
                )
                lines.append(f"    {d.description}")
            lines.append("")

        # Synthèse
        first_critical = next(
            (d for d in divergences if d.severity == "critical"), None
        )
        if first_critical:
            lines.append(
                f"⚡ Point de divergence racine probable: "
                f"[{first_critical.phase}] {first_critical.field}"
            )
        return "\n".join(lines)

    def root_cause_phase(self, divergences: List[Divergence]) -> Optional[str]:
        """Identifie la phase la plus probable comme cause racine."""
        phase_order = [
            PipelinePhase.PROPOSAL.value,
            PipelinePhase.CODE_GEN.value,
            PipelinePhase.CODE_REPAIR.value,
            PipelinePhase.CODE_VALIDATE.value,
            PipelinePhase.PRECHECK.value,
            PipelinePhase.BACKTEST.value,
            PipelinePhase.RUNTIME_FIX.value,
            PipelinePhase.SCORING.value,
            PipelinePhase.DIAGNOSTIC.value,
            PipelinePhase.ANALYSIS.value,
            PipelinePhase.DECISION.value,
        ]
        critical = [d for d in divergences if d.severity == "critical"]
        if not critical:
            critical = [d for d in divergences if d.severity == "warning"]
        if not critical:
            return None

        for phase in phase_order:
            for d in critical:
                if d.phase == phase:
                    return phase
        return critical[0].phase if critical else None

    @staticmethod
    def _field_to_phase(field: str) -> str:
        mapping = {
            "proposal_change_type": "proposal",
            "proposal_indicators": "proposal",
            "code_source": "code_gen",
            "code_hash": "code_gen",
            "validation_passed_first": "code_validate",
            "repair_applied": "code_repair",
            "fallback_used": "code_gen",
            "precheck_passed": "precheck",
            "backtest_ran": "backtest",
            "runtime_fix_applied": "runtime_fix",
            "diagnostic_category": "diagnostic",
            "decision": "decision",
            "decision_overridden": "decision",
            "continuous_score": "scoring",
            "stagnation_detected": "diagnostic",
        }
        return mapping.get(field, "unknown")

    @staticmethod
    def _describe_divergence(field: str, val_a: Any, val_b: Any) -> str:
        descriptions = {
            "code_source": (
                f"Code genere par '{val_a}' vs '{val_b}' — "
                "change le chemin complet en aval"
            ),
            "code_hash": (
                "Code different — toutes les metriques aval sont potentiellement impactees"
            ),
            "fallback_used": (
                "Fallback deterministe utilise dans une trace mais pas l'autre — "
                "la qualite du code differ fondamentalement"
            ),
            "decision": (
                f"Decision finale '{val_a}' vs '{val_b}' — "
                "issue de session differente"
            ),
            "continuous_score": (
                f"Score de telemetrie {val_a} vs {val_b} — "
                "ecart d'observabilite composite"
            ),
        }
        return descriptions.get(field, f"'{field}' changed: {val_a} → {val_b}")


# =====================================================================
# 7. Canonical Test Cases
# =====================================================================

@dataclass
class CanonicalCase:
    """Cas de test canonique avec entrees/sorties attendues.

    Trois niveaux:
      A — Strategie profitable simple (EMA cross, Sharpe > 1)
      B — Strategie non profitable a reparer (logic structurellement OK mais parametres faibles)
      C — Code LLM casse (syntaxe invalide, indicateurs manquants, patterns interdits)
    """
    case_id: str
    level: str  # "A" | "B" | "C"
    description: str

    # Entrées
    proposal: Dict[str, Any]
    code_snippet: str  # fragment generate_signals
    metrics_before: Dict[str, Any]  # métriques simulées

    # Expectations
    expect_code_valid: bool
    expect_repair_needed: bool
    expect_fallback: bool
    expect_backtest_positive: Optional[bool]  # None = pas d'attente
    expect_min_score: Optional[float]
    expect_decision: Optional[str]  # "continue" | "accept" | "stop"


def build_canonical_cases() -> List[CanonicalCase]:
    """Construit la suite de cas canoniques A/B/C."""
    return [
        # --- Niveau A: stratégie simple et rentable ---
        CanonicalCase(
            case_id="A1_ema_cross_profitable",
            level="A",
            description="EMA 15/50 crossover — doit passer directement sans repair",
            proposal={
                "hypothesis": "EMA fast/slow crossover with ATR stop",
                "used_indicators": ["ema_fast", "ema_slow", "atr"],
                "change_type": "logic",
                "default_params": {
                    "fast_period": 15, "slow_period": 50,
                    "leverage": 1, "stop_atr_mult": 2.0, "tp_atr_mult": 4.0,
                },
            },
            code_snippet=textwrap.dedent("""\
                ema_fast = np.nan_to_num(indicators['ema_fast'])
                ema_slow = np.nan_to_num(indicators['ema_slow'])
                atr = np.nan_to_num(indicators['atr'])
                prev_fast = np.roll(ema_fast, 1); prev_fast[0] = np.nan
                prev_slow = np.roll(ema_slow, 1); prev_slow[0] = np.nan
                long_mask = (ema_fast > ema_slow) & (prev_fast <= prev_slow)
                short_mask = (ema_fast < ema_slow) & (prev_fast >= prev_slow)
                signals[long_mask] = 1.0
                signals[short_mask] = -1.0
                signals.iloc[:warmup] = 0.0
            """),
            metrics_before={
                "total_return_pct": 18.86, "sharpe_ratio": 1.2,
                "max_drawdown_pct": -23.4, "total_trades": 94,
                "win_rate_pct": 30.9, "profit_factor": 1.12,
            },
            expect_code_valid=True,
            expect_repair_needed=False,
            expect_fallback=False,
            expect_backtest_positive=True,
            expect_min_score=30.0,
            expect_decision="continue",
        ),
        # --- Niveau B: profitable mais faible, doit continuer ---
        CanonicalCase(
            case_id="B1_rsi_weak_params",
            level="B",
            description=(
                "RSI reversal avec parametres mous — trades mais return faible, "
                "le diagnostic doit recommander ajustement params"
            ),
            proposal={
                "hypothesis": "RSI mean reversion with fixed thresholds",
                "used_indicators": ["rsi", "atr"],
                "change_type": "params",
                "default_params": {
                    "rsi_period": 14, "overbought": 70, "oversold": 30,
                    "leverage": 1, "stop_atr_mult": 1.5, "tp_atr_mult": 3.0,
                },
            },
            code_snippet=textwrap.dedent("""\
                rsi = np.nan_to_num(indicators['rsi'])
                long_mask = rsi < params.get('oversold', 30)
                short_mask = rsi > params.get('overbought', 70)
                signals[long_mask] = 1.0
                signals[short_mask] = -1.0
                signals.iloc[:warmup] = 0.0
            """),
            metrics_before={
                "total_return_pct": 2.1, "sharpe_ratio": 0.35,
                "max_drawdown_pct": -15.2, "total_trades": 45,
                "win_rate_pct": 35.5, "profit_factor": 1.03,
            },
            expect_code_valid=True,
            expect_repair_needed=False,
            expect_fallback=False,
            expect_backtest_positive=True,
            expect_min_score=-10.0,
            expect_decision="continue",
        ),
        # --- Niveau C: code cassé — doit être réparé ou fallback ---
        CanonicalCase(
            case_id="C1_bare_indicator_name",
            level="C",
            description=(
                "Code utilisant coppock_curve nu sans binding — "
                "repair doit injecter l'alias"
            ),
            proposal={
                "hypothesis": "Coppock curve momentum filter",
                "used_indicators": ["coppock_curve", "ema_fast"],
                "change_type": "logic",
                "default_params": {"leverage": 1},
            },
            code_snippet=textwrap.dedent("""\
                ema_fast = np.nan_to_num(indicators['ema_fast'])
                long_mask = (coppock_curve > 0) & (ema_fast > np.roll(ema_fast, 1))
                signals[long_mask] = 1.0
                signals.iloc[:warmup] = 0.0
            """),
            metrics_before={},
            expect_code_valid=False,
            expect_repair_needed=True,
            expect_fallback=False,
            expect_backtest_positive=None,
            expect_min_score=None,
            expect_decision=None,
        ),
        CanonicalCase(
            case_id="C2_signals_loc_2d",
            level="C",
            description=(
                "Code utilisant signals.loc[mask, 'long'] = 1 — "
                "doit etre rejete ou repare"
            ),
            proposal={
                "hypothesis": "Dual bollinger breakout",
                "used_indicators": ["bollinger", "atr"],
                "change_type": "logic",
                "default_params": {"leverage": 1},
            },
            code_snippet=textwrap.dedent("""\
                bb = indicators['bollinger']
                upper = np.nan_to_num(bb['upper'])
                lower = np.nan_to_num(bb['lower'])
                close = df['close'].values
                long_mask = close > upper
                short_mask = close < lower
                signals.loc[long_mask, 'long'] = 1.0
                signals.loc[short_mask, 'short'] = -1.0
            """),
            metrics_before={},
            expect_code_valid=False,
            expect_repair_needed=True,
            expect_fallback=False,
            expect_backtest_positive=None,
            expect_min_score=None,
            expect_decision=None,
        ),
        CanonicalCase(
            case_id="C3_dict_indicator_direct_compare",
            level="C",
            description=(
                "Code comparant indicators['adx'] > 25 directement — "
                "indicateur dict, doit utiliser sous-cle"
            ),
            proposal={
                "hypothesis": "ADX trend filter with EMA",
                "used_indicators": ["adx", "ema_fast", "ema_slow"],
                "change_type": "logic",
                "default_params": {"leverage": 1},
            },
            code_snippet=textwrap.dedent("""\
                ema_fast = np.nan_to_num(indicators['ema_fast'])
                ema_slow = np.nan_to_num(indicators['ema_slow'])
                trend_filter = indicators['adx'] > 25
                long_mask = (ema_fast > ema_slow) & trend_filter
                signals[long_mask] = 1.0
                signals.iloc[:warmup] = 0.0
            """),
            metrics_before={},
            expect_code_valid=False,
            expect_repair_needed=True,
            expect_fallback=False,
            expect_backtest_positive=None,
            expect_min_score=None,
            expect_decision=None,
        ),
    ]


import textwrap  # noqa: E402 — used in canonical cases above
