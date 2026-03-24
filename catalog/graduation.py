"""
Module-ID: catalog.graduation

Purpose: Pipeline canonique de post-filtrage des stratégies sandbox / imports positifs.

P0 — Inventaire unifié : fusion sandbox + imports positifs.
P1 — Normalisation : rattachement stratégie, params, run source, métriques.
P2 — Positif observé : au moins une itération ou un run > 0%.
P3 — Benchmark suite : validation multi-token / multi-timeframe sur benchmarks fixes.
P4 — Sensibilité paramétrique : mini-sweep autour des meilleurs params.
P5 — Walk-Forward : validation temporelle multi-contexte.
P6 — Promotion finale : synchronisation catalog + export optionnel.

Usage:
    from catalog.graduation import scan_sandbox, GraduationConfig
    config = GraduationConfig()
    candidates = scan_sandbox(config)
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import re
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from backtest.result_store import (
    get_artifacts_root_dir,
    get_builder_sessions_dir,
    get_results_root_dir,
    get_saved_runs_dir,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SANDBOX_DIR = get_builder_sessions_dir()


def _default_postfilter_benchmark_names() -> List[str]:
    try:
        from config.market_selection import get_postfilter_benchmark_names

        names = get_postfilter_benchmark_names()
        if names:
            return names
    except Exception:
        pass
    return [
        "crypto_liquid_benchmark_v1_core",
        "crypto_liquid_benchmark_v2_breadth",
        "crypto_liquid_benchmark_v3_balanced",
    ]


def _default_promotion_dir() -> Path:
    raw = os.environ.get("BACKTEST_STRATEGY_PROMOTION_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path("strategies/graduated")


@dataclass
class RepechageThresholds:
    """Seuils Phase 1 — critères OR (filet large)."""

    min_return_pct: float = 0.0        # return > 0% sur au moins 1 itération
    min_score: float = 40.0            # score continu > 40
    min_profit_factor: float = 1.1     # PF > 1.1 sur au moins 1 itération
    auto_include_success: bool = True   # status == "success" → inclusion auto
    auto_include_max_iter: bool = True  # status == "max_iterations" → inclusion auto


@dataclass
class GraduationConfig:
    """Configuration complète du pipeline canonique de post-filtrage."""

    sandbox_dir: Path = field(default_factory=lambda: SANDBOX_DIR)
    repechage: RepechageThresholds = field(default_factory=RepechageThresholds)
    postfilter_schema_version: int = 2
    benchmark_names: List[str] = field(default_factory=_default_postfilter_benchmark_names)
    token_count: int = 5
    required_benchmark_name: str = "crypto_liquid_benchmark_v1_core"
    min_benchmarks_pass: int = 2
    no_silent_replacement: bool = True

    # Phase 3 — Benchmark suite
    validation_tokens: List[str] = field(default_factory=lambda: [
        "BTCUSDC",   # majeur / trend
        "SOLUSDC",   # mid-cap / momentum volatile
        "AVAXUSDC",  # small-cap / stress test
    ])
    validation_timeframes: List[str] = field(default_factory=lambda: ["1h", "4h"])
    min_contexts_pass: int = 2
    min_context_coverage_pct: float = 70.0
    max_drawdown_abs: float = 50.0
    min_trades_per_context: int = 20
    min_profit_factor_per_context: float = 1.0
    min_sharpe_per_context: float = 0.0

    # Phase 4 — Sweep sensibilité
    sweep_neighborhood: float = 0.10    # ±10% autour des params
    sweep_min_profitable_pct: float = 20.0
    sweep_max_combinations: int = 81
    sweep_max_drawdown_drift_pct: float = 15.0

    # Phase 5 — WFA
    wfa_folds: int = 5
    wfa_min_stability: float = 0.5
    wfa_min_test_sharpe: float = 0.1
    wfa_max_overfitting_ratio: float = 2.5

    # Output
    output_dir: Path = field(default_factory=lambda: Path("catalog/graduation_results"))
    promotion_dir: Path = field(default_factory=_default_promotion_dir)
    catalog_path: Path = field(default_factory=lambda: Path("config/strategy_catalog.json"))
    sync_catalog: bool = False
    positive_progress_filename: str = "positive_imports_progress.json"


# ---------------------------------------------------------------------------
# Dataclass candidat
# ---------------------------------------------------------------------------

@dataclass
class GraduationCandidate:
    """Un candidat au post-filtrage canonique."""

    session_id: str
    session_dir: Path
    candidate_id: str = ""
    strategy_name: str = ""
    strategy_params: Dict[str, Any] = field(default_factory=dict)
    objective: str = ""
    origin_status: str = ""             # success / failed / max_iterations / running
    source_kind: str = "sandbox"
    source_mode: str = "sandbox"
    source_run_id: str = ""
    source_symbol: str = ""
    source_timeframe: str = ""

    # Meilleure itération (par score, puis par return)
    best_iteration: int = 0
    best_return_pct: float = 0.0
    best_profit_factor: float = 0.0
    best_score: float = 0.0
    best_sharpe: float = 0.0
    best_trades: int = 0
    best_max_drawdown_pct: float = 0.0
    best_win_rate_pct: float = 0.0

    # Raisons d'inclusion / admission
    inclusion_reasons: List[str] = field(default_factory=list)

    # Phases suivantes (rempli progressivement)
    phase: str = "P0"
    decision: str = "PENDING"           # PENDING, PROMOTED, WATCHLIST, REJECTED
    p2_verdict: str = "PENDING"
    p3_verdict: str = "PENDING"
    p4_verdict: str = "PENDING"
    p5_verdict: str = "PENDING"
    p6_verdict: str = "PENDING"
    multi_ctx_results: Dict[str, Any] = field(default_factory=dict)
    benchmark_results: Dict[str, Any] = field(default_factory=dict)
    benchmark_consensus: Dict[str, Any] = field(default_factory=dict)
    configured_contexts: List[str] = field(default_factory=list)
    loaded_contexts: List[str] = field(default_factory=list)
    missing_contexts: List[str] = field(default_factory=list)
    tested_timeframes: List[str] = field(default_factory=list)
    coverage_pct: Optional[float] = None
    sweep_robustness_pct: Optional[float] = None
    wfa_stability: Optional[float] = None
    wfa_avg_test_return_pct: Optional[float] = None
    wfa_avg_test_sharpe: Optional[float] = None
    wfa_overfitting_ratio: Optional[float] = None
    wfa_is_robust: Optional[bool] = None
    rejection_reason: str = ""
    catalog_category: Optional[str] = None
    catalog_entry_id: Optional[str] = None

    # Fichier stratégie associé
    strategy_file: str = ""             # chemin relatif vers le .py

    def to_dict(self) -> Dict[str, Any]:
        multi_ctx = self.multi_ctx_results or {}
        contexts = multi_ctx.get("contexts") or {}
        tested_tokens = {str(key).split("_", 1)[0] for key in contexts.keys() if "_" in str(key)}
        for payload in (self.benchmark_results or {}).values():
            if not isinstance(payload, dict):
                continue
            for token in payload.get("tokens", []) or []:
                token_str = str(token).strip()
                if token_str:
                    tested_tokens.add(token_str)
        tested_tokens_sorted = sorted(tested_tokens)
        total_contexts = int(multi_ctx.get("total_contexts") or 0)
        passed_contexts = int(multi_ctx.get("passed_count") or 0)
        configured_context_keys = [str(key) for key in self.configured_contexts if str(key).strip()]
        loaded_context_keys = [str(key) for key in self.loaded_contexts if str(key).strip()]
        missing_context_keys = [str(key) for key in self.missing_contexts if str(key).strip()]
        benchmark_names = sorted(str(name) for name in (self.benchmark_results or {}).keys())
        benchmarks_passed = sorted(str(name) for name in (self.benchmark_consensus or {}).get("benchmarks_passed", []))
        benchmark_pass_summary = (
            f"{len(benchmarks_passed)}/{len(benchmark_names)}"
            if benchmark_names
            else ""
        )
        context_pass_summary = f"{passed_contexts}/{total_contexts}" if total_contexts else ""
        return {
            "candidate_id": self.candidate_id or self.session_id,
            "session_id": self.session_id,
            "strategy_name": self.strategy_name,
            "source_kind": self.source_kind,
            "source_mode": self.source_mode,
            "source_run_id": self.source_run_id,
            "source_symbol": self.source_symbol,
            "source_timeframe": self.source_timeframe,
            "objective": self.objective[:120],
            "origin_status": self.origin_status,
            "best_iteration": self.best_iteration,
            "best_return_pct": _safe_round(self.best_return_pct, 2),
            "best_profit_factor": _safe_round(self.best_profit_factor, 4),
            "best_score": _safe_round(self.best_score, 2),
            "best_sharpe": _safe_round(self.best_sharpe, 4),
            "best_trades": self.best_trades,
            "best_max_drawdown_pct": _safe_round(self.best_max_drawdown_pct, 2),
            "best_win_rate_pct": _safe_round(self.best_win_rate_pct, 2),
            "inclusion_reasons": self.inclusion_reasons,
            "phase": self.phase,
            "decision": self.decision,
            "p2_verdict": self.p2_verdict,
            "p3_verdict": self.p3_verdict,
            "p4_verdict": self.p4_verdict,
            "p5_verdict": self.p5_verdict,
            "p6_verdict": self.p6_verdict,
            "strategy_file": self.strategy_file,
            "multi_ctx_results": _json_safe(self.multi_ctx_results),
            "benchmark_results": _json_safe(self.benchmark_results),
            "benchmark_consensus": _json_safe(self.benchmark_consensus),
            "multi_ctx_pass": context_pass_summary,
            "context_pass_summary": context_pass_summary,
            "passed_context_count": passed_contexts,
            "total_context_count": total_contexts,
            "tokens_tested": ",".join(tested_tokens_sorted),
            "tested_tokens": ",".join(tested_tokens_sorted),
            "tested_benchmark_names": ",".join(benchmark_names),
            "passed_benchmark_names": ",".join(benchmarks_passed),
            "benchmark_pass_summary": benchmark_pass_summary,
            "configured_contexts": configured_context_keys,
            "loaded_contexts": loaded_context_keys,
            "missing_contexts": missing_context_keys,
            "configured_context_count": len(configured_context_keys),
            "loaded_context_count": len(loaded_context_keys),
            "missing_context_count": len(missing_context_keys),
            "timeframes_tested": ",".join(sorted({str(tf) for tf in self.tested_timeframes if str(tf).strip()})),
            "tested_timeframes": list(sorted({str(tf) for tf in self.tested_timeframes if str(tf).strip()})),
            "coverage_pct": self.coverage_pct,
            "sweep_robustness_pct": self.sweep_robustness_pct,
            "wfa_stability": self.wfa_stability,
            "wfa_avg_test_return_pct": self.wfa_avg_test_return_pct,
            "wfa_avg_test_sharpe": self.wfa_avg_test_sharpe,
            "wfa_overfitting_ratio": self.wfa_overfitting_ratio,
            "wfa_is_robust": self.wfa_is_robust,
            "rejection_reason": self.rejection_reason,
            "catalog_category": self.catalog_category,
            "catalog_entry_id": self.catalog_entry_id,
        }


def _safe_round(value: Any, digits: int) -> Optional[float]:
    """Arrondit en gérant None, NaN et inf."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _json_safe(value: Any) -> Any:
    """Normalise les types pour une sérialisation JSON propre."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item") and callable(getattr(value, "item")):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    return value


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _benchmark_label(name: str, payload: Dict[str, Any]) -> str:
    label = str((payload or {}).get("label") or "").strip()
    return label or name


def _split_context_key(key: str) -> tuple[str, str]:
    token, _, timeframe = str(key).partition("_")
    return token, timeframe


def _build_candidate_id(candidate: GraduationCandidate) -> str:
    if candidate.candidate_id:
        return candidate.candidate_id
    base = str(candidate.source_run_id or candidate.session_id or candidate.catalog_entry_id or "").strip()
    if base:
        return base
    return f"{candidate.strategy_name or 'candidate'}|{candidate.source_symbol or 'MULTI'}|{candidate.source_timeframe or 'MULTI'}"


def _load_postfilter_benchmark_config() -> Dict[str, Any]:
    try:
        from config.market_selection import get_postfilter_benchmark_config

        payload = get_postfilter_benchmark_config()
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        logger.debug("Unable to load postfilter benchmark config: %s", exc)
    return {}


def _resolve_postfilter_benchmarks(config: GraduationConfig) -> Dict[str, Dict[str, Any]]:
    payload = _load_postfilter_benchmark_config()
    benchmark_map = payload.get("benchmarks", {}) if isinstance(payload, dict) else {}
    if not isinstance(benchmark_map, dict):
        benchmark_map = {}

    resolved: Dict[str, Dict[str, Any]] = {}
    for name in config.benchmark_names:
        benchmark = benchmark_map.get(name)
        if not isinstance(benchmark, dict):
            continue
        tokens = [str(token).strip().upper() for token in benchmark.get("tokens", []) if str(token).strip()]
        token_count = max(1, min(int(config.token_count), len(tokens) or int(config.token_count)))
        resolved[name] = {
            "name": name,
            "label": _benchmark_label(name, benchmark),
            "tokens": tokens[:token_count],
        }
    if resolved:
        return resolved

    fallback_tokens = [str(token).strip().upper() for token in config.validation_tokens if str(token).strip()]
    resolved["fallback_validation_tokens"] = {
        "name": "fallback_validation_tokens",
        "label": "Fallback Validation Tokens",
        "tokens": fallback_tokens[: max(1, min(int(config.token_count), len(fallback_tokens) or int(config.token_count)))],
    }
    return resolved


def _resolve_validation_contexts(config: GraduationConfig) -> Dict[str, Any]:
    from data import discover_data_inventory

    inventory = discover_data_inventory()
    timeframes = [str(tf).strip() for tf in config.validation_timeframes if str(tf).strip()]
    benchmarks = _resolve_postfilter_benchmarks(config)

    configured_contexts: List[str] = []
    loaded_contexts: Dict[str, Any] = {}
    missing_contexts: List[str] = []
    benchmark_contexts: Dict[str, List[str]] = {}

    for benchmark_name, benchmark in benchmarks.items():
        keys: List[str] = []
        for token in benchmark.get("tokens", []):
            token_inventory = inventory.get(token, {})
            for tf in timeframes:
                key = f"{token}_{tf}"
                configured_contexts.append(key)
                keys.append(key)
                tf_payload = token_inventory.get(tf)
                if isinstance(tf_payload, dict) and tf_payload.get("n_bars"):
                    loaded_contexts[key] = tf_payload
                else:
                    missing_contexts.append(key)
        benchmark_contexts[benchmark_name] = keys

    coverage_pct = 0.0
    if configured_contexts:
        coverage_pct = round(len(loaded_contexts) / len(configured_contexts) * 100.0, 1)

    return {
        "timeframes": timeframes,
        "benchmarks": benchmarks,
        "configured_contexts": configured_contexts,
        "loaded_contexts": loaded_contexts,
        "missing_contexts": missing_contexts,
        "benchmark_contexts": benchmark_contexts,
        "coverage_pct": coverage_pct,
    }


def _candidate_progress_payload(candidate: Optional[GraduationCandidate]) -> Dict[str, Any]:
    if candidate is None:
        return {}
    return {
        "candidate_id": candidate.candidate_id or candidate.session_id,
        "session_id": candidate.session_id,
        "strategy_name": candidate.strategy_name,
        "source_mode": candidate.source_mode,
        "source_run_id": candidate.source_run_id,
        "source_symbol": candidate.source_symbol,
        "source_timeframe": candidate.source_timeframe,
        "phase": candidate.phase,
        "decision": candidate.decision,
        "best_return_pct": _safe_round(candidate.best_return_pct, 2),
        "benchmark_consensus": _json_safe(candidate.benchmark_consensus),
        "catalog_entry_id": candidate.catalog_entry_id,
    }


def _save_progress_state(
    output_dir: Path,
    filename: str,
    payload: Dict[str, Any],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    safe_payload = _json_safe(dict(payload))
    safe_payload["updated_at"] = _utc_now_iso()
    path.write_text(
        json.dumps(safe_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Phase 1 — Repêchage (scan sandbox)
# ---------------------------------------------------------------------------

def _extract_best_iteration(iterations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Sélectionne la meilleure itération (score max, puis return max en cas d'égalité)."""
    valid = [
        it for it in iterations
        if it.get("continuous_score") is not None
        and it.get("return_pct") is not None
    ]
    if not valid:
        return {}

    return max(
        valid,
        key=lambda it: (
            float(it.get("continuous_score") or -999),
            float(it.get("return_pct") or -999),
        ),
    )


def _check_inclusion(
    summary: Dict[str, Any],
    thresholds: RepechageThresholds,
) -> tuple[bool, List[str], Dict[str, Any]]:
    """
    Vérifie si une session doit être incluse en Phase 1.

    Returns:
        (included, reasons, best_iteration_data)
    """
    reasons: List[str] = []
    status = summary.get("status", "")
    iterations = summary.get("iterations", [])

    if not iterations:
        return False, [], {}

    # Auto-include par statut
    if thresholds.auto_include_success and status == "success":
        reasons.append("status=success")

    if thresholds.auto_include_max_iter and status == "max_iterations":
        reasons.append("status=max_iterations")

    # Scan toutes les itérations pour critères métriques
    best_return = max(
        (float(it.get("return_pct") or -999) for it in iterations),
        default=-999,
    )
    best_score = max(
        (float(it.get("continuous_score") or -999) for it in iterations),
        default=-999,
    )
    best_pf = max(
        (float(it.get("profit_factor") or 0) for it in iterations),
        default=0,
    )

    if best_return > thresholds.min_return_pct:
        reasons.append(f"return={best_return:.1f}%>0")

    if best_score > thresholds.min_score:
        reasons.append(f"score={best_score:.1f}>{thresholds.min_score}")

    if best_pf > thresholds.min_profit_factor:
        reasons.append(f"PF={best_pf:.2f}>{thresholds.min_profit_factor}")

    included = len(reasons) > 0
    best_it = _extract_best_iteration(iterations) if included else {}

    return included, reasons, best_it


def _find_strategy_file(session_dir: Path, best_iteration: int) -> str:
    """Trouve le fichier .py de la meilleure itération."""
    # D'abord chercher strategy_vN.py
    versioned = session_dir / f"strategy_v{best_iteration}.py"
    if versioned.exists():
        return str(versioned.relative_to(session_dir.parent))

    # Sinon strategy.py (le dernier écrit)
    default = session_dir / "strategy.py"
    if default.exists():
        return str(default.relative_to(session_dir.parent))

    return ""


def _parse_objective(raw_objective: str) -> str:
    """Extrait un objectif lisible depuis le champ brut (peut être du JSON imbriqué)."""
    if not raw_objective:
        return ""

    def _extract_from_payload(payload: str) -> Optional[str]:
        try:
            parsed = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return None
        if isinstance(parsed, dict):
            for key in ("objective", "goal", "prompt", "idea", "task"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    direct = _extract_from_payload(raw_objective)
    if direct:
        return direct[:200]

    fenced_blocks = re.findall(r"```(?:json)?\s*(.*?)```", raw_objective, flags=re.DOTALL | re.IGNORECASE)
    for block in fenced_blocks:
        extracted = _extract_from_payload(block.strip())
        if extracted:
            return extracted[:200]

    quoted_match = re.search(
        r'"(?:objective|goal|prompt|idea|task)"\s*:\s*"([^"]+)"',
        raw_objective,
        flags=re.IGNORECASE,
    )
    if quoted_match:
        return quoted_match.group(1).strip()[:200]

    cleaned_lines = []
    for line in raw_objective.splitlines():
        stripped = line.strip().strip("`")
        if stripped:
            cleaned_lines.append(stripped)
    if cleaned_lines:
        return cleaned_lines[0][:200]

    return raw_objective.strip()[:200]


def scan_sandbox(
    config: Optional[GraduationConfig] = None,
) -> List[GraduationCandidate]:
    """
    Phase 1 — Repêchage.

    Scanne tous les session_summary.json du sandbox.
    Applique des critères larges (OR) pour retenir les candidats prometteurs.

    Returns:
        Liste de GraduationCandidate triée par best_score décroissant.
    """
    if config is None:
        config = GraduationConfig()

    sandbox = config.sandbox_dir
    if not sandbox.exists():
        logger.warning("Sandbox directory not found: %s", sandbox)
        return []

    candidates: List[GraduationCandidate] = []
    scanned = 0
    skipped_running = 0

    for summary_path in sorted(sandbox.glob("*/session_summary.json")):
        scanned += 1
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("Skip %s: %s", summary_path, e)
            continue

        # Ignorer les sessions encore en cours
        if summary.get("status") == "running":
            skipped_running += 1
            continue

        included, reasons, best_it = _check_inclusion(summary, config.repechage)
        if not included:
            continue

        session_dir = summary_path.parent
        best_iter_num = int(best_it.get("iteration", 0))

        candidate = GraduationCandidate(
            session_id=summary.get("session_id", session_dir.name),
            session_dir=session_dir,
            objective=_parse_objective(summary.get("objective", "")),
            origin_status=summary.get("status", ""),
            best_iteration=best_iter_num,
            best_return_pct=float(best_it.get("return_pct") or 0),
            best_profit_factor=float(best_it.get("profit_factor") or 0),
            best_score=float(best_it.get("continuous_score") or 0),
            best_sharpe=float(best_it.get("sharpe") or 0),
            best_trades=int(best_it.get("trades") or 0),
            best_max_drawdown_pct=float(best_it.get("max_drawdown_pct") or 0),
            best_win_rate_pct=float(best_it.get("win_rate_pct") or 0),
            inclusion_reasons=reasons,
            strategy_file=_find_strategy_file(session_dir, best_iter_num),
        )

        candidates.append(candidate)

    # Tri par score décroissant, puis return décroissant
    candidates.sort(
        key=lambda c: (c.best_score, c.best_return_pct),
        reverse=True,
    )

    logger.info(
        "Phase 1 scan: %d scanned, %d running (skipped), %d candidates retained",
        scanned, skipped_running, len(candidates),
    )

    return candidates


# ---------------------------------------------------------------------------
# Positive import candidates
# ---------------------------------------------------------------------------

def _metric_as_float(metrics: Dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        value = metrics.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _metric_as_int(metrics: Dict[str, Any], *keys: str, default: int = 0) -> int:
    for key in keys:
        value = metrics.get(key)
        if value is None:
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return default


def scan_positive_import_candidates(
    config: Optional[GraduationConfig] = None,
) -> List[GraduationCandidate]:
    """
    Construit des candidats de graduation à partir des entrées `positive_import`
    déjà présentes dans le strategy catalog.
    """
    if config is None:
        config = GraduationConfig()

    from catalog.strategy_catalog import list_entries

    entries = list_entries(path=config.catalog_path, tags=["positive_import"], status="active")
    workspace_root = _workspace_root()
    candidates: List[GraduationCandidate] = []

    for entry in entries:
        metrics = dict(entry.get("last_metrics_snapshot") or {})
        meta = dict(entry.get("meta") or {})
        builder_session_id = str(meta.get("builder_session_id") or "").strip()
        source_params = meta.get("source_params")
        if not isinstance(source_params, dict):
            source_params = {}

        source_symbol = str(meta.get("source_symbol") or entry.get("symbol") or "").strip()
        source_timeframe = str(meta.get("source_timeframe") or entry.get("timeframe") or "").strip()
        strategy_name = str(
            entry.get("strategy_name") or meta.get("source_strategy_name") or ""
        ).strip()

        session_dir = config.sandbox_dir / builder_session_id if builder_session_id else workspace_root
        best_iteration = _metric_as_int(meta, "builder_iteration", default=0)
        strategy_file = ""
        if builder_session_id and session_dir.exists():
            strategy_file = _find_strategy_file(session_dir, best_iteration)

        return_pct = _metric_as_float(metrics, "total_return_pct", "total_return", default=0.0)
        if "total_return_pct" not in metrics and "total_return" in metrics:
            return_pct *= 100.0

        objective = str(meta.get("builder_objective") or entry.get("note") or "").strip()

        candidate = GraduationCandidate(
            session_id=builder_session_id or str(entry.get("id") or ""),
            session_dir=session_dir,
            strategy_name=strategy_name,
            strategy_params=dict(source_params),
            objective=objective[:200],
            origin_status=str(entry.get("source") or "positive_import"),
            source_kind=str(meta.get("import_source_kind") or entry.get("source") or "positive_import"),
            source_run_id=str(meta.get("source_run_id") or "").strip(),
            source_symbol=source_symbol,
            source_timeframe=source_timeframe,
            best_iteration=best_iteration,
            best_return_pct=return_pct,
            best_profit_factor=_metric_as_float(metrics, "profit_factor", default=0.0),
            best_score=_metric_as_float(metrics, "quality_score", default=0.0),
            best_sharpe=_metric_as_float(metrics, "sharpe_ratio", "sharpe", default=0.0),
            best_trades=_metric_as_int(metrics, "total_trades", "trades", default=0),
            best_max_drawdown_pct=_metric_as_float(metrics, "max_drawdown_pct", "max_drawdown", default=0.0),
            best_win_rate_pct=_metric_as_float(metrics, "win_rate_pct", "win_rate", default=0.0),
            inclusion_reasons=[
                "positive_import",
                f"return={return_pct:.1f}%>0",
            ],
            catalog_category=entry.get("category"),
            catalog_entry_id=entry.get("id"),
            strategy_file=strategy_file,
        )
        candidates.append(candidate)

    candidates.sort(
        key=lambda candidate: (
            candidate.best_return_pct,
            candidate.best_sharpe,
            candidate.best_profit_factor,
        ),
        reverse=True,
    )

    logger.info("Positive import scan: %d candidates found in %s", len(candidates), config.catalog_path)
    return candidates


def run_positive_observed_filter(
    candidates: List[GraduationCandidate],
    *,
    source_mode: str,
) -> List[GraduationCandidate]:
    """
    P2 — Admission par positif observé.

    Un candidat est admis s'il a déjà démontré au moins un return positif
    sur une itération sandbox ou un run importé.
    """
    survivors: List[GraduationCandidate] = []
    for candidate in candidates:
        candidate.candidate_id = _build_candidate_id(candidate)
        candidate.source_mode = source_mode
        candidate.phase = "P2"

        reasons = list(candidate.inclusion_reasons or [])
        if candidate.best_return_pct > 0:
            if not any(str(reason).startswith("positive_observed") for reason in reasons):
                reasons.append(f"positive_observed return={candidate.best_return_pct:.1f}%>0")
            candidate.inclusion_reasons = reasons
            candidate.p2_verdict = "PASSED"
            candidate.decision = "WATCHLIST"
            survivors.append(candidate)
        else:
            candidate.p2_verdict = "REJECTED"
            candidate.decision = "REJECTED"
            candidate.rejection_reason = candidate.rejection_reason or "P2 positive_observed missing"

    logger.info("Phase 2 positive_observed: %d/%d survived", len(survivors), len(candidates))
    return survivors


# ---------------------------------------------------------------------------
# Rapport Phase 1
# ---------------------------------------------------------------------------

def save_graduation_report(
    candidates: List[GraduationCandidate],
    output_dir: Optional[Path] = None,
    *,
    phase: str = "P1_repechage",
    filename: Optional[str] = None,
    stats: Optional[Dict[str, Any]] = None,
) -> Path:
    """Sauvegarde le rapport de graduation en JSON."""
    if output_dir is None:
        output_dir = Path("catalog/graduation_results")

    output_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "phase": phase,
        "total_candidates": len(candidates),
        "by_status": {},
        "by_phase": {},
        "by_decision": {},
        "stats": _json_safe(stats or {}),
        "candidates": [c.to_dict() for c in candidates],
    }

    for c in candidates:
        status = c.origin_status
        report["by_status"][status] = report["by_status"].get(status, 0) + 1
        report["by_phase"][c.phase] = report["by_phase"].get(c.phase, 0) + 1
        report["by_decision"][c.decision] = report["by_decision"].get(c.decision, 0) + 1

    report_name = filename
    if not report_name:
        report_name = "graduation_p1.json" if phase == "P1_repechage" else "graduation_full.json"

    report_path = output_dir / report_name
    report_path.write_text(
        json.dumps(_json_safe(report), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info("Graduation report saved: %s (%d candidates)", report_path, len(candidates))
    return report_path


# ---------------------------------------------------------------------------
# Positive artifact import (legacy/current runs, sweeps, backtests)
# ---------------------------------------------------------------------------

def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_positive_artifact_roots() -> List[Path]:
    def _resolve_root(path: Path) -> Path:
        try:
            return path.resolve()
        except OSError:
            return path

    def _append_unique(root_list: List[Path], candidate: Path) -> None:
        if not candidate.exists():
            return
        resolved = _resolve_root(candidate)
        if all(_resolve_root(existing) != resolved for existing in root_list):
            root_list.append(resolved)

    roots: List[Path] = []
    _append_unique(roots, _workspace_root())
    _append_unique(roots, get_artifacts_root_dir())

    extra_roots = str(os.environ.get("BACKTEST_EXTRA_ARTIFACT_ROOTS", "")).strip()
    if extra_roots:
        for raw_root in re.split(r"[;\n]+", extra_roots):
            value = str(raw_root or "").strip()
            if value:
                _append_unique(roots, Path(value).expanduser())

    for candidate in (
        Path(r"C:\Users\o3-Pro\Documents\backtest_results"),
        Path(r"C:\Users\o3-Pro\Documents\run_resultats saucvegarde"),
        Path("D:/backtest_core"),
    ):
        _append_unique(roots, candidate)
    return roots


_NUMERIC_TEXT_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_ARTIFACT_TEXT_KEYS = {
    "artifact_type",
    "builder_objective",
    "builder_session_id",
    "extra_builder_objective",
    "extra_builder_session_id",
    "extra_fold_id",
    "extra_origin",
    "extra_parent_run_id",
    "id",
    "mode",
    "origin",
    "parent_scope",
    "path",
    "run_id",
    "schema",
    "source_run_id",
    "status",
    "strategy",
    "strategy_name",
    "symbol",
    "timeframe",
}


def _coerce_artifact_scalar(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text == "":
        return None
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"none", "null", "nan", "n/a"}:
        return None
    if _NUMERIC_TEXT_RE.match(text):
        try:
            number = float(text)
        except ValueError:
            return text
        if number.is_integer() and "." not in text and "e" not in lowered:
            try:
                return int(text)
            except ValueError:
                return number
        return number
    return text


def _normalize_artifact_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in (payload or {}).items():
        key_str = str(key)
        if isinstance(value, dict):
            normalized[key_str] = _normalize_artifact_payload(value)
        elif isinstance(value, list):
            normalized[key_str] = [
                _normalize_artifact_payload(item) if isinstance(item, dict) else _coerce_artifact_scalar(item)
                for item in value
            ]
        elif isinstance(value, str) and key_str in _ARTIFACT_TEXT_KEYS:
            normalized[key_str] = value.strip()
        else:
            normalized[key_str] = _coerce_artifact_scalar(value)
    return normalized


def _extract_artifact_return_pct(payload: Dict[str, Any]) -> float:
    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        total_return_pct = metrics.get("total_return_pct")
        if total_return_pct is not None:
            try:
                return float(total_return_pct)
            except (TypeError, ValueError):
                return 0.0
        total_return = metrics.get("total_return")
        if total_return is not None:
            try:
                return float(total_return) * 100.0
            except (TypeError, ValueError):
                return 0.0

    total_return_pct = payload.get("metrics_total_return_pct")
    if total_return_pct is not None:
        try:
            return float(total_return_pct)
        except (TypeError, ValueError):
            return 0.0

    total_return = payload.get("metrics_total_return")
    if total_return is not None:
        try:
            return float(total_return) * 100.0
        except (TypeError, ValueError):
            return 0.0

    return 0.0


@contextmanager
def _safe_engine_mode():
    """
    Force le moteur à utiliser le simulateur Python de référence.

    Utile pour les batchs massifs `positive_import`, où certains parcours Numba
    peuvent provoquer un crash natif Windows sous forte charge.
    """
    try:
        import backtest.engine as backtest_engine_module
    except Exception:
        yield
        return

    previous_use_fast = getattr(backtest_engine_module, "USE_FAST_SIMULATOR", None)
    if previous_use_fast is None:
        yield
        return

    backtest_engine_module.USE_FAST_SIMULATOR = False
    try:
        yield
    finally:
        backtest_engine_module.USE_FAST_SIMULATOR = previous_use_fast


def _artifact_identity(payload: Dict[str, Any], source_root: Path) -> str:
    run_id = str(payload.get("run_id") or payload.get("id") or "").strip()
    if run_id:
        return f"run_id:{run_id}"

    source_path = str(payload.get("path") or "").strip()
    if source_path:
        return f"path:{source_root.resolve()}::{source_path}"

    extra = payload.get("extra_metadata") if isinstance(payload.get("extra_metadata"), dict) else {}
    session_id = str(extra.get("builder_session_id") or "").strip()
    iteration = str(extra.get("builder_iteration") or "").strip()
    if session_id:
        return f"builder:{session_id}:{iteration}"

    strategy = str(payload.get("strategy") or payload.get("strategy_name") or "").strip()
    symbol = str(payload.get("symbol") or "").strip()
    timeframe = str(payload.get("timeframe") or "").strip()
    return f"fallback:{strategy}|{symbol}|{timeframe}|{source_root.resolve()}"


def _copy_builder_session_dir(
    *,
    source_root: Path,
    session_id: str,
    sandbox_target_dir: Path,
) -> str:
    if not session_id:
        return "missing"

    source_dir = get_builder_sessions_dir(source_root) / session_id
    if not source_dir.exists():
        source_dir = source_root / "sandbox_strategies" / session_id
    target_dir = sandbox_target_dir / session_id

    if not source_dir.exists():
        return "missing"

    try:
        if source_dir.resolve() == target_dir.resolve():
            return "existing"
    except OSError:
        pass

    if target_dir.exists():
        return "existing"

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target_dir)
    return "copied"


def _looks_like_results_root(path: Path) -> bool:
    return any(
        (path / marker).exists()
        for marker in ("_catalog", "index.csv", "index.json", "golden_runs.csv", "runs")
    )


def import_positive_artifacts_to_catalog(
    config: Optional[GraduationConfig] = None,
    *,
    source_roots: Optional[Iterable[Path]] = None,
    min_return_pct: float = 0.0,
    copy_builder_sessions: bool = True,
    report_filename: str = "positive_artifacts_import.json",
) -> Dict[str, Any]:
    """
    Importe tous les artefacts à return positif (runs/backtests/sweeps/metadata builder)
    dans le strategy catalog, en les rangeant au minimum en `p2_positive_observed`.

    Les sessions builder legacy liées à ces artefacts sont copiées vers le sandbox courant
    lorsque `builder_session_id` est disponible.
    """
    if config is None:
        config = GraduationConfig()

    from catalog.strategy_catalog import upsert_entry, upsert_from_saved_run

    roots = [Path(root) for root in (source_roots or _default_positive_artifact_roots())]
    seen_artifacts: set[str] = set()
    touched_entries: set[str] = set()
    copied_sessions: set[str] = set()
    existing_sessions: set[str] = set()
    missing_sessions: set[str] = set()

    report: Dict[str, Any] = {
        "phase": "POSITIVE_ARTIFACT_IMPORT",
        "source_roots": [str(root) for root in roots],
        "catalog_path": str(config.catalog_path),
        "sandbox_target_dir": str(config.sandbox_dir),
        "stats": {
            "roots_scanned": 0,
            "roots_missing": 0,
            "overview_files_found": 0,
            "overview_rows_scanned": 0,
            "overview_positive_rows": 0,
            "metadata_files_scanned": 0,
            "metadata_positive_rows": 0,
            "artifacts_processed": 0,
            "duplicates_skipped": 0,
            "catalog_entries_touched": 0,
            "builder_sessions_copied": 0,
            "builder_sessions_existing": 0,
            "builder_sessions_missing": 0,
            "import_failures": 0,
        },
        "entries": [],
        "failures": [],
    }

    workspace_root = _workspace_root().resolve()

    def _process_payload(payload: Dict[str, Any], *, source_root: Path, source_kind: str) -> None:
        identity = _artifact_identity(payload, source_root)
        if identity in seen_artifacts:
            report["stats"]["duplicates_skipped"] += 1
            return
        seen_artifacts.add(identity)
        report["stats"]["artifacts_processed"] += 1

        try:
            saved = upsert_from_saved_run(
                payload,
                target_category="p2_positive_observed",
                path=config.catalog_path,
            )
            entry = dict(saved)
            extra_tags = ["positive_import", "positive_return", f"import_{source_kind}"]
            if source_root.resolve() != workspace_root:
                extra_tags.append("legacy_import")
            entry["tags"] = sorted(set((entry.get("tags") or []) + extra_tags))

            meta = dict(entry.get("meta") or {})
            source_params = {}
            if isinstance(payload.get("params"), dict):
                source_params = dict(payload.get("params") or {})
            else:
                source_params = {
                    key[len("params_"):]: value
                    for key, value in payload.items()
                    if isinstance(key, str) and key.startswith("params_") and value not in (None, "")
                }
            meta.update(
                {
                    "import_root": str(source_root),
                    "import_source_kind": source_kind,
                    "import_min_return_pct": min_return_pct,
                    "positive_return_pct": _extract_artifact_return_pct(payload),
                    "source_params": _json_safe(source_params),
                    "source_strategy_name": payload.get("strategy") or payload.get("strategy_name"),
                    "source_symbol": payload.get("symbol"),
                    "source_timeframe": payload.get("timeframe"),
                }
            )
            entry["meta"] = _json_safe(meta)

            final_entry = upsert_entry(entry, path=config.catalog_path)
            touched_entries.add(str(final_entry.get("id") or ""))

            builder_session_id = str(meta.get("builder_session_id") or "").strip()
            if copy_builder_sessions and builder_session_id:
                copy_status = _copy_builder_session_dir(
                    source_root=source_root,
                    session_id=builder_session_id,
                    sandbox_target_dir=config.sandbox_dir,
                )
                if copy_status == "copied":
                    copied_sessions.add(builder_session_id)
                elif copy_status == "existing":
                    existing_sessions.add(builder_session_id)
                else:
                    missing_sessions.add(builder_session_id)

            report["entries"].append(
                {
                    "entry_id": final_entry.get("id"),
                    "catalog_category": final_entry.get("category"),
                    "run_id": meta.get("source_run_id"),
                    "strategy_name": final_entry.get("strategy_name"),
                    "symbol": final_entry.get("symbol"),
                    "timeframe": final_entry.get("timeframe"),
                    "return_pct": _extract_artifact_return_pct(payload),
                    "source_root": str(source_root),
                    "source_kind": source_kind,
                    "builder_session_id": builder_session_id or None,
                }
            )
        except Exception as exc:
            report["stats"]["import_failures"] += 1
            report["failures"].append(
                {
                    "source_root": str(source_root),
                    "source_kind": source_kind,
                    "run_id": payload.get("run_id"),
                    "path": payload.get("path"),
                    "error": str(exc),
                }
            )

    for raw_root in roots:
        report["stats"]["roots_scanned"] += 1
        root = raw_root.resolve()
        if not root.exists():
            report["stats"]["roots_missing"] += 1
            report["failures"].append(
                {
                    "source_root": str(raw_root),
                    "source_kind": "root",
                    "error": "source root does not exist",
                }
            )
            continue

        candidate_results_dirs: List[Path] = []
        for candidate in (get_results_root_dir(root), root / "backtest_results"):
            if (
                candidate.exists()
                and _looks_like_results_root(candidate)
                and candidate not in candidate_results_dirs
            ):
                candidate_results_dirs.append(candidate)

        candidate_saved_runs_dirs: List[Path] = []
        for candidate in (get_saved_runs_dir(root), root / "runs"):
            if candidate.exists() and candidate not in candidate_saved_runs_dirs:
                candidate_saved_runs_dirs.append(candidate)

        overview_path: Optional[Path] = None
        for candidate_results_dir in candidate_results_dirs:
            candidate_overview_path = candidate_results_dir / "_catalog" / "unified_overview.csv"
            if candidate_overview_path.exists():
                overview_path = candidate_overview_path
                break

        if overview_path is not None:
            report["stats"]["overview_files_found"] += 1
            try:
                with overview_path.open("r", encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    for row in reader:
                        report["stats"]["overview_rows_scanned"] += 1
                        payload = _normalize_artifact_payload(dict(row))
                        if _extract_artifact_return_pct(payload) <= min_return_pct:
                            continue
                        report["stats"]["overview_positive_rows"] += 1
                        _process_payload(payload, source_root=root, source_kind="unified_overview")
            except Exception as exc:
                report["stats"]["import_failures"] += 1
                report["failures"].append(
                    {
                        "source_root": str(root),
                        "source_kind": "unified_overview",
                        "path": str(overview_path),
                        "error": str(exc),
                    }
                )

        for base_dir in [*candidate_results_dirs, *candidate_saved_runs_dirs]:
            if not base_dir.exists():
                continue
            for metadata_path in base_dir.rglob("metadata.json"):
                report["stats"]["metadata_files_scanned"] += 1
                try:
                    payload = _normalize_artifact_payload(
                        json.loads(metadata_path.read_text(encoding="utf-8"))
                    )
                except Exception as exc:
                    report["stats"]["import_failures"] += 1
                    report["failures"].append(
                        {
                            "source_root": str(root),
                            "source_kind": "metadata_fallback",
                            "path": str(metadata_path),
                            "error": str(exc),
                        }
                    )
                    continue

                if _extract_artifact_return_pct(payload) <= min_return_pct:
                    continue

                report["stats"]["metadata_positive_rows"] += 1
                payload.setdefault("artifact_type", "saved_run")
                payload.setdefault("schema", "metadata_json")
                try:
                    relative_parent = metadata_path.parent.relative_to(root)
                    payload.setdefault("path", str(relative_parent))
                except ValueError:
                    payload.setdefault("path", str(metadata_path.parent))
                _process_payload(payload, source_root=root, source_kind="metadata_fallback")

    report["stats"]["catalog_entries_touched"] = len([entry_id for entry_id in touched_entries if entry_id])
    report["stats"]["builder_sessions_copied"] = len(copied_sessions)
    report["stats"]["builder_sessions_existing"] = len(existing_sessions)
    report["stats"]["builder_sessions_missing"] = len(missing_sessions)
    report["builder_sessions"] = {
        "copied": sorted(copied_sessions),
        "existing": sorted(existing_sessions),
        "missing": sorted(missing_sessions),
    }

    config.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = config.output_dir / report_filename
    report_path.write_text(
        json.dumps(_json_safe(report), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    report["report_path"] = str(report_path)

    logger.info(
        "Positive artifact import: %d entries touched, %d builder sessions copied",
        report["stats"]["catalog_entries_touched"],
        report["stats"]["builder_sessions_copied"],
    )
    return report


# ---------------------------------------------------------------------------
# CLI rapide
# ---------------------------------------------------------------------------

def main() -> None:
    """Point d'entrée CLI pour tester le scan."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Post-filter canonique des stratégies sandbox / imports positifs",
        prog="catalog.graduation",
    )
    parser.add_argument(
        "--sandbox-dir", "-d",
        default=str(SANDBOX_DIR),
        help="Chemin vers le répertoire sandbox",
    )
    parser.add_argument(
        "--min-return", type=float, default=0.0,
        help="Seuil min return %% (défaut: 0)",
    )
    parser.add_argument(
        "--min-score", type=float, default=40.0,
        help="Seuil min score continu (défaut: 40)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Exécute le pipeline complet canonique P1→P6",
    )
    parser.add_argument(
        "--sync-catalog",
        action="store_true",
        help="Synchronise les candidats vers config/strategy_catalog.json",
    )
    parser.add_argument(
        "--import-positive-artifacts",
        action="store_true",
        help="Importe tous les artefacts à return positif (legacy + courant) dans le strategy catalog",
    )
    parser.add_argument(
        "--artifact-root",
        action="append",
        default=[],
        help="Racine source à scanner pour les artefacts positifs (option répétable)",
    )
    parser.add_argument(
        "--no-copy-builder-sessions",
        action="store_true",
        help="N'importe pas les dossiers sandbox_strategies liés aux runs Builder positifs",
    )
    parser.add_argument(
        "--positive-import-full",
        action="store_true",
        help="Exécute le pipeline canonique P2→P5 sur les entrées `positive_import` déjà importées dans le strategy catalog",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = GraduationConfig(
        sandbox_dir=Path(args.sandbox_dir),
        sync_catalog=args.sync_catalog,
        repechage=RepechageThresholds(
            min_return_pct=args.min_return,
            min_score=args.min_score,
        ),
    )

    if args.import_positive_artifacts:
        roots = [Path(path) for path in args.artifact_root] if args.artifact_root else None
        report = import_positive_artifacts_to_catalog(
            config,
            source_roots=roots,
            min_return_pct=args.min_return,
            copy_builder_sessions=not args.no_copy_builder_sessions,
        )
        stats = report.get("stats") or {}
        print(f"\n{'='*70}")
        print("  IMPORT ARTEFACTS POSITIFS")
        print(f"{'='*70}")
        print(f"  Roots scannées:        {stats.get('roots_scanned', 0)}")
        print(f"  Rows overview+:        {stats.get('overview_positive_rows', 0)}")
        print(f"  Metadata+:             {stats.get('metadata_positive_rows', 0)}")
        print(f"  Duplicats ignorés:     {stats.get('duplicates_skipped', 0)}")
        print(f"  Entrées catalogue:     {stats.get('catalog_entries_touched', 0)}")
        print(f"  Sessions copiées:      {stats.get('builder_sessions_copied', 0)}")
        print(f"  Sessions déjà là:      {stats.get('builder_sessions_existing', 0)}")
        print(f"  Sessions manquantes:   {stats.get('builder_sessions_missing', 0)}")
        print(f"  Échecs import:         {stats.get('import_failures', 0)}")
        print(f"{'='*70}\n")
        print(f"  Rapport sauvegardé: {report.get('report_path')}")
        return

    if args.positive_import_full:
        result = run_positive_import_graduation(config)
        stats = result.get("stats") or {}
        print(f"\n{'='*70}")
        print("  GRADUATION ARTEFACTS POSITIFS")
        print(f"{'='*70}")
        print(f"  Candidats importés:   {stats.get('import_candidates', 0)}")
        print(f"  P2 Positifs:          {stats.get('p2_survivors', 0)}")
        print(f"  P3 Benchmarks:        {stats.get('p3_survivors', 0)}")
        print(f"  P4 Sensibilité:       {stats.get('p4_survivors', 0)}")
        print(f"  P5 Walk-Forward:      {stats.get('p5_survivors', 0)}")
        print(f"  Sync catalogue:      {stats.get('catalog_synced', 0)}")
        print(f"{'='*70}\n")
        print(f"  Rapport sauvegardé: {config.output_dir / 'positive_imports_graduation.json'}")
        return

    if args.full:
        result = run_full_graduation(config)
        stats = result["stats"]
        print(f"\n{'='*70}")
        print("  GRADUATION Pipeline Complet")
        print(f"{'='*70}")
        print(f"  P1 Inventaire:       {stats['p1_candidates']}")
        print(f"  P2 Positifs:         {stats['p2_survivors']}")
        print(f"  P3 Benchmarks:       {stats['p3_survivors']}")
        print(f"  P4 Sensibilité:      {stats['p4_survivors']}")
        print(f"  P5 Walk-Forward:     {stats['p5_survivors']}")
        print(f"  P6 Promotion:        {stats['p6_promoted']}")
        print(f"  Sync catalogue:      {stats.get('catalog_synced', 0)}")
        print(f"{'='*70}\n")
        print(f"  Rapport sauvegardé: {config.output_dir / 'graduation_full.json'}")
        return

    candidates = scan_sandbox(config)
    if args.sync_catalog:
        synced = sync_graduation_to_catalog(candidates, config)
        print(f"  Sync catalogue:    {len(synced)} entrée(s)")

    # Afficher résumé
    print(f"\n{'='*70}")
    print(f"  GRADUATION Phase 1 — Repêchage")
    print(f"{'='*70}")
    print(f"  Sessions scannées:   {len(list(config.sandbox_dir.glob('*/session_summary.json')))}")
    print(f"  Candidats retenus:   {len(candidates)}")
    print(f"{'='*70}\n")

    # Top 20
    print(f"  {'#':<4} {'Score':>7} {'Return%':>9} {'PF':>6} {'Trades':>7} {'Status':<15} {'Raisons'}")
    print(f"  {'-'*4} {'-'*7} {'-'*9} {'-'*6} {'-'*7} {'-'*15} {'-'*30}")

    for i, c in enumerate(candidates[:20], 1):
        print(
            f"  {i:<4} {c.best_score:>7.1f} {c.best_return_pct:>8.1f}% "
            f"{c.best_profit_factor:>6.2f} {c.best_trades:>7} "
            f"{c.origin_status:<15} {', '.join(c.inclusion_reasons)}"
        )

    if len(candidates) > 20:
        print(f"\n  ... et {len(candidates) - 20} autres candidats")

    # Sauvegarder
    report_path = save_graduation_report(candidates, config.output_dir, phase="P1_repechage")
    print(f"\n  Rapport sauvegardé: {report_path}")


# ---------------------------------------------------------------------------
# Phase 2 — Validation multi-contexte
# ---------------------------------------------------------------------------

def _load_strategy_from_file(strategy_path: Path):
    """Charge dynamiquement une stratégie depuis un fichier .py sandbox."""
    import importlib.util
    import sys

    module_name = f"grad_{strategy_path.stem}_{id(strategy_path)}"
    spec = importlib.util.spec_from_file_location(module_name, str(strategy_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {strategy_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Chercher la classe de stratégie (hérite de StrategyBase ou a generate_signals)
    strategy_cls = None
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and attr_name != "StrategyBase"
            and hasattr(attr, "generate_signals")
        ):
            strategy_cls = attr
            break

    if strategy_cls is None:
        raise RuntimeError(f"No strategy class found in {strategy_path}")

    return strategy_cls()


def _load_strategy_from_name(strategy_name: str):
    """Charge une stratégie native depuis le registre global."""
    from strategies.base import get_strategy

    normalized_name = str(strategy_name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized_name:
        raise RuntimeError("Missing strategy name")

    strategy_cls = get_strategy(normalized_name)
    return strategy_cls()


def _load_strategy_for_candidate(candidate: GraduationCandidate):
    """Résout une stratégie depuis un fichier sandbox ou le registre natif."""
    strategy_path = _resolved_strategy_path(candidate)
    if strategy_path.exists():
        strategy = _load_strategy_from_file(strategy_path)
    elif candidate.strategy_name:
        strategy = _load_strategy_from_name(candidate.strategy_name)
    else:
        raise RuntimeError("No strategy path or strategy name available")

    if not candidate.strategy_name:
        candidate.strategy_name = str(getattr(strategy, "name", "") or "").strip()

    params = dict(candidate.strategy_params or {})
    return strategy, params


def run_multi_context_validation(
    candidates: List[GraduationCandidate],
    config: Optional[GraduationConfig] = None,
    *,
    progress_callback: Optional[Callable[..., None]] = None,
) -> List[GraduationCandidate]:
    """Phase 3 — Validation benchmark multi-token / multi-timeframe."""
    if config is None:
        config = GraduationConfig()

    import warnings
    from pandas.errors import SettingWithCopyWarning

    from backtest.engine import BacktestEngine
    from data.loader import load_ohlcv

    engine = BacktestEngine(initial_capital=10000.0)
    context_plan = _resolve_validation_contexts(config)
    timeframes = context_plan["timeframes"]
    benchmarks = context_plan["benchmarks"]
    benchmark_contexts = context_plan["benchmark_contexts"]
    configured_contexts = list(context_plan["configured_contexts"])
    missing_contexts = list(context_plan["missing_contexts"])
    total_contexts = len(configured_contexts)
    survivors: List[GraduationCandidate] = []

    logger.info(
        "Phase 3: validating %d candidates on %d configured contexts across benchmarks=%s timeframes=%s",
        len(candidates), total_contexts, list(benchmarks.keys()), timeframes,
    )

    # Précharger les DataFrames
    dataframes: Dict[str, Any] = {}
    for key in configured_contexts:
        token, tf = key.split("_", 1)
        try:
            df = load_ohlcv(token, tf)
            if df is not None and len(df) > 100:
                dataframes[key] = df
                logger.debug("Loaded %s: %d bars", key, len(df))
            else:
                logger.warning("Skipping %s: insufficient data (%d bars)", key, len(df) if df is not None else 0)
        except Exception as e:
            logger.warning("Cannot load %s: %s", key, e)

    if not dataframes:
        logger.error("No data loaded — Phase 3 aborted")
        return candidates  # Retourner tels quels

    if progress_callback:
        progress_callback(
            phase="P3",
            event="phase_start",
            candidate=None,
            index=0,
            total=len(candidates),
            survivors=0,
            extra={
                "loaded_contexts": len(dataframes),
                "configured_contexts": total_contexts,
                "benchmarks": list(benchmarks.keys()),
            },
        )

    for index, candidate in enumerate(candidates, 1):
        candidate.candidate_id = _build_candidate_id(candidate)
        candidate.phase = "P3"
        candidate.configured_contexts = list(configured_contexts)
        candidate.loaded_contexts = sorted(dataframes.keys())
        candidate.missing_contexts = list(missing_contexts)
        candidate.tested_timeframes = list(timeframes)
        candidate.coverage_pct = context_plan["coverage_pct"]

        if progress_callback:
            progress_callback(
                phase="P3",
                event="candidate_start",
                candidate=candidate,
                index=index,
                total=len(candidates),
                survivors=len(survivors),
                extra={
                    "loaded_contexts": len(dataframes),
                    "configured_contexts": total_contexts,
                    "benchmarks": list(benchmarks.keys()),
                },
            )
        try:
            strategy, params = _load_strategy_for_candidate(candidate)
        except Exception as e:
            candidate.decision = "REJECTED"
            candidate.rejection_reason = f"load error: {e}"
            candidate.p3_verdict = "REJECTED"
            logger.debug("Cannot load %s: %s", candidate.session_id, e)
            if progress_callback:
                progress_callback(
                    phase="P3",
                    event="candidate_done",
                    candidate=candidate,
                    index=index,
                    total=len(candidates),
                    survivors=len(survivors),
                    extra={
                        "loaded_contexts": len(dataframes),
                        "configured_contexts": total_contexts,
                        "benchmarks": list(benchmarks.keys()),
                    },
                )
            continue

        # Backtester sur chaque contexte
        ctx_results: Dict[str, Dict[str, Any]] = {}
        passed_count = 0
        benchmark_results: Dict[str, Dict[str, Any]] = {}
        benchmarks_passed: List[str] = []

        for benchmark_name, benchmark in benchmarks.items():
            benchmark_keys = benchmark_contexts.get(benchmark_name, [])
            benchmark_loaded = [key for key in benchmark_keys if key in dataframes]
            benchmark_missing = [key for key in benchmark_keys if key not in dataframes]
            benchmark_passed_count = 0
            benchmark_context_results: Dict[str, Dict[str, Any]] = {}

            for key in benchmark_loaded:
                df = dataframes[key]
                token, tf = _split_context_key(key)
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", category=SettingWithCopyWarning)
                        result = engine.run(
                            df=df,
                            strategy=strategy,
                            params=params,
                            fast_metrics=True,
                            silent_mode=True,
                        )
                    m = result.metrics
                    ret = float(m.get("total_return_pct", 0) or 0)
                    dd = abs(float(m.get("max_drawdown_pct", 0) or 0))
                    pf = float(m.get("profit_factor", 0) or 0)
                    trades = int(m.get("total_trades", 0) or 0)
                    sharpe = float(m.get("sharpe_ratio", 0) or 0)

                    ctx_passed = bool(
                        ret > 0
                        and dd <= config.max_drawdown_abs
                        and trades >= config.min_trades_per_context
                        and pf >= config.min_profit_factor_per_context
                        and sharpe >= config.min_sharpe_per_context
                    )

                    context_result = {
                        "token": token,
                        "timeframe": tf,
                        "configured": True,
                        "loaded": True,
                        "missing": False,
                        "return_pct": round(ret, 2),
                        "max_drawdown_pct": round(dd, 2),
                        "profit_factor": round(pf, 4),
                        "sharpe_ratio": round(sharpe, 4),
                        "trades": trades,
                        "passed": ctx_passed,
                        "benchmark": benchmark_name,
                    }
                    ctx_results[key] = context_result
                    benchmark_context_results[key] = dict(context_result)
                    if ctx_passed:
                        passed_count += 1
                        benchmark_passed_count += 1
                except Exception as e:
                    error_result = {
                        "token": token,
                        "timeframe": tf,
                        "configured": True,
                        "loaded": True,
                        "missing": False,
                        "error": str(e),
                        "passed": False,
                        "benchmark": benchmark_name,
                    }
                    ctx_results[key] = error_result
                    benchmark_context_results[key] = dict(error_result)
                    logger.debug("Backtest error %s on %s: %s", candidate.session_id, key, e)

            for key in benchmark_missing:
                token, tf = _split_context_key(key)
                missing_result = {
                    "token": token,
                    "timeframe": tf,
                    "configured": True,
                    "loaded": False,
                    "missing": True,
                    "error": "missing_data",
                    "passed": False,
                    "benchmark": benchmark_name,
                }
                ctx_results[key] = missing_result
                benchmark_context_results[key] = dict(missing_result)

            benchmark_coverage_pct = round(
                len(benchmark_loaded) / max(len(benchmark_keys), 1) * 100.0,
                1,
            )
            benchmark_pass = bool(
                benchmark_loaded
                and benchmark_coverage_pct >= config.min_context_coverage_pct
                and benchmark_passed_count >= config.min_contexts_pass
            )
            benchmark_results[benchmark_name] = {
                "label": benchmark.get("label", benchmark_name),
                "tokens": list(benchmark.get("tokens", [])),
                "timeframes": list(timeframes),
                "configured_contexts": list(benchmark_keys),
                "configured_context_count": len(benchmark_keys),
                "loaded_contexts": list(benchmark_loaded),
                "loaded_context_count": len(benchmark_loaded),
                "missing_contexts": list(benchmark_missing),
                "missing_context_count": len(benchmark_missing),
                "passed_contexts": benchmark_passed_count,
                "passed_context_count": benchmark_passed_count,
                "coverage_pct": benchmark_coverage_pct,
                "pass_rate_pct": round(benchmark_passed_count / max(len(benchmark_loaded), 1) * 100.0, 1)
                if benchmark_loaded
                else 0.0,
                "passed": benchmark_pass,
                "contexts": benchmark_context_results,
            }
            if benchmark_pass:
                benchmarks_passed.append(benchmark_name)

        candidate.multi_ctx_results = {
            "contexts": ctx_results,
            "passed_count": passed_count,
            "total_contexts": len(configured_contexts),
            "loaded_contexts": len(dataframes),
            "missing_contexts": len(missing_contexts),
            "pass_rate": round(passed_count / max(len(configured_contexts), 1) * 100, 1),
        }
        candidate.benchmark_results = benchmark_results

        required_benchmark_name = (
            config.required_benchmark_name
            if config.required_benchmark_name in benchmarks
            else (next(iter(benchmarks.keys()), ""))
        )
        required_passed = required_benchmark_name in benchmarks_passed if required_benchmark_name else True
        consensus_passed = bool(required_passed and len(benchmarks_passed) >= config.min_benchmarks_pass)
        contradicted = bool(benchmarks_passed and not consensus_passed)
        candidate.benchmark_consensus = {
            "required_benchmark_name": required_benchmark_name,
            "required_passed": required_passed,
            "configured_benchmark_names": sorted(benchmarks.keys()),
            "benchmarks_passed": benchmarks_passed,
            "benchmarks_failed": sorted(name for name in benchmarks.keys() if name not in benchmarks_passed),
            "benchmarks_total": len(benchmarks),
            "n_passed": len(benchmarks_passed),
            "min_benchmarks_pass": config.min_benchmarks_pass,
            "consensus_passed": consensus_passed,
            "contradicted": contradicted,
        }

        if consensus_passed:
            candidate.p3_verdict = "PASSED"
            candidate.decision = "WATCHLIST"
            survivors.append(candidate)
            logger.debug(
                "P3 PASS: %s — benchmarks=%s",
                candidate.session_id, benchmarks_passed,
            )
        else:
            reasons = []
            if not required_passed and required_benchmark_name:
                reasons.append(f"required_benchmark_failed={required_benchmark_name}")
            reasons.append(
                f"benchmarks={len(benchmarks_passed)}/{len(benchmarks)}<{config.min_benchmarks_pass}"
            )
            if candidate.coverage_pct is not None and candidate.coverage_pct < config.min_context_coverage_pct:
                reasons.append(
                    f"coverage={candidate.coverage_pct:.1f}%<{config.min_context_coverage_pct}%"
                )
            candidate.p3_verdict = "REJECTED"
            candidate.decision = "REJECTED"
            candidate.rejection_reason = "; ".join(reasons)

        if progress_callback:
            progress_callback(
                phase="P3",
                event="candidate_done",
                candidate=candidate,
                index=index,
                total=len(candidates),
                survivors=len(survivors),
                extra={
                    "loaded_contexts": len(dataframes),
                    "configured_contexts": total_contexts,
                    "benchmarks_passed": benchmarks_passed,
                },
            )

    logger.info(
        "Phase 3 done: %d/%d survived",
        len(survivors), len(candidates),
    )

    if progress_callback:
        progress_callback(
            phase="P3",
            event="phase_end",
            candidate=None,
            index=len(candidates),
            total=len(candidates),
            survivors=len(survivors),
            extra={
                "loaded_contexts": len(dataframes),
                "configured_contexts": total_contexts,
                "benchmarks": list(benchmarks.keys()),
            },
        )

    return survivors


# ---------------------------------------------------------------------------
# Phase 3 — Sensibilité paramétrique
# ---------------------------------------------------------------------------

def _extract_numeric_params(strategy) -> Dict[str, float]:
    """Extrait les paramètres numériques depuis get_param_specs() ou defaults."""
    params: Dict[str, float] = {}

    specs = getattr(strategy, "parameter_specs", None)
    if not specs and hasattr(strategy, "get_param_specs"):
        try:
            specs = strategy.get_param_specs()
        except Exception:
            specs = None

    if isinstance(specs, dict):
        for name, spec in specs.items():
            optimize = True
            default = None
            if isinstance(spec, dict):
                default = spec.get("default")
                optimize = bool(spec.get("optimize", True))
            else:
                default = getattr(spec, "default", None)
                optimize = bool(getattr(spec, "optimize", True))

            if optimize and isinstance(default, (int, float)) and not isinstance(default, bool):
                params[name] = float(default)

    defaults = getattr(strategy, "default_params", None)
    if isinstance(defaults, dict):
        for name, value in defaults.items():
            if name in params:
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                params[name] = float(value)

    # Fallback : attributs numériques de l'instance
    if not params:
        for attr_name in dir(strategy):
            if attr_name.startswith("_"):
                continue
            try:
                val = getattr(strategy, attr_name)
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    params[attr_name] = float(val)
            except Exception:
                pass

    return params


def _generate_neighborhood(
    base_params: Dict[str, float],
    pct: float = 0.10,
    n_steps: int = 3,
    max_combinations: Optional[int] = None,
) -> List[Dict[str, float]]:
    """Génère des combinaisons dans le voisinage ±pct des paramètres de base."""
    import itertools

    param_ranges: Dict[str, List[float]] = {}
    for name, val in base_params.items():
        if val == 0:
            param_ranges[name] = [0.0]
            continue
        delta = abs(val * pct)
        step = (2 * delta) / max(n_steps - 1, 1)
        values = [val - delta + i * step for i in range(n_steps)]
        # Garder le type int si c'était un entier
        if val == int(val):
            values = [float(max(1, round(v))) for v in values]
            values = sorted(set(values))
        param_ranges[name] = values

    # Produit cartésien
    keys = list(param_ranges.keys())
    combos = list(itertools.product(*[param_ranges[k] for k in keys]))

    result = []
    for combo in combos:
        d = {k: v for k, v in zip(keys, combo)}
        # Rétablir les int
        for k, v in d.items():
            if base_params[k] == int(base_params[k]):
                d[k] = int(v)
        result.append(d)

    if max_combinations and len(result) > max_combinations:
        base_combo = {}
        for key, value in base_params.items():
            base_combo[key] = int(value) if value == int(value) else value

        base_index = None
        for idx, combo in enumerate(result):
            if combo == base_combo:
                base_index = idx
                break

        sampled_indices: List[int] = []
        if max_combinations == 1:
            sampled_indices = [base_index if base_index is not None else 0]
        else:
            for i in range(max_combinations):
                idx = round(i * (len(result) - 1) / (max_combinations - 1))
                if idx not in sampled_indices:
                    sampled_indices.append(idx)
            if base_index is not None and base_index not in sampled_indices:
                sampled_indices[-1] = base_index

        result = [result[idx] for idx in sorted(set(sampled_indices))]

    return result


def run_parameter_sensitivity(
    candidates: List[GraduationCandidate],
    config: Optional[GraduationConfig] = None,
    *,
    progress_callback: Optional[Callable[..., None]] = None,
) -> List[GraduationCandidate]:
    """
    Phase 4 — Sensibilité paramétrique.

    Pour chaque candidat, génère un voisinage ±10% autour des paramètres,
    backteste chaque combinaison, et mesure le % de combinaisons rentables.

    Rejette si < sweep_min_profitable_pct.
    """
    if config is None:
        config = GraduationConfig()

    import warnings
    from pandas.errors import SettingWithCopyWarning

    from backtest.engine import BacktestEngine
    from data.loader import load_ohlcv

    engine = BacktestEngine(initial_capital=10000.0)

    # Charger le contexte principal (premier token, premier TF)
    token = config.validation_tokens[0]
    tf = config.validation_timeframes[0]
    try:
        df = load_ohlcv(token, tf)
    except Exception as e:
        logger.error("Cannot load %s/%s for Phase 3: %s", token, tf, e)
        return candidates

    survivors: List[GraduationCandidate] = []

    logger.info("Phase 4: sensitivity test on %d candidates", len(candidates))

    if progress_callback:
        progress_callback(
            phase="P4",
            event="phase_start",
            candidate=None,
            index=0,
            total=len(candidates),
            survivors=0,
            extra={"token": token, "timeframe": tf},
        )

    for index, candidate in enumerate(candidates, 1):
        if progress_callback:
            progress_callback(
                phase="P4",
                event="candidate_start",
                candidate=candidate,
                index=index,
                total=len(candidates),
                survivors=len(survivors),
                extra={"token": token, "timeframe": tf},
            )
        try:
            strategy, candidate_params = _load_strategy_for_candidate(candidate)
        except Exception as e:
            candidate.decision = "REJECTED"
            candidate.rejection_reason = f"P4 load error: {e}"
            candidate.phase = "P4"
            candidate.p4_verdict = "REJECTED"
            if progress_callback:
                progress_callback(
                    phase="P4",
                    event="candidate_done",
                    candidate=candidate,
                    index=index,
                    total=len(candidates),
                    survivors=len(survivors),
                    extra={"token": token, "timeframe": tf},
                )
            continue

        base_params = _extract_numeric_params(strategy)
        for name, value in candidate_params.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                base_params[name] = float(value)
        if not base_params:
            # Pas de paramètres → on laisse passer (pas de sensibilité à tester)
            candidate.phase = "P4"
            candidate.sweep_robustness_pct = 100.0
            candidate.decision = "WATCHLIST"
            candidate.p4_verdict = "PASSED"
            survivors.append(candidate)
            logger.debug("P4 PASS (no params): %s", candidate.session_id)
            if progress_callback:
                progress_callback(
                    phase="P4",
                    event="candidate_done",
                    candidate=candidate,
                    index=index,
                    total=len(candidates),
                    survivors=len(survivors),
                    extra={"token": token, "timeframe": tf},
                )
            continue

        neighborhood = _generate_neighborhood(
            base_params,
            pct=config.sweep_neighborhood,
            n_steps=3,
            max_combinations=config.sweep_max_combinations,
        )

        profitable = 0
        total = 0

        for params in neighborhood:
            try:
                effective_params = dict(candidate_params)
                effective_params.update(params)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=SettingWithCopyWarning)
                    result = engine.run(
                        df=df,
                        strategy=strategy,
                        params=effective_params,
                        fast_metrics=True,
                        silent_mode=True,
                    )
                ret = result.metrics.get("total_return_pct", 0)
                total += 1
                if ret > 0:
                    profitable += 1
            except Exception:
                total += 1

        robustness = (profitable / max(total, 1)) * 100
        candidate.sweep_robustness_pct = round(robustness, 1)
        candidate.phase = "P4"

        if robustness >= config.sweep_min_profitable_pct:
            candidate.decision = "WATCHLIST"
            candidate.p4_verdict = "PASSED"
            survivors.append(candidate)
            logger.debug(
                "P4 PASS: %s — %d/%d profitable (%.1f%%)",
                candidate.session_id, profitable, total, robustness,
            )
        else:
            candidate.decision = "REJECTED"
            candidate.p4_verdict = "REJECTED"
            candidate.rejection_reason = f"sweep fragile {robustness:.0f}%<{config.sweep_min_profitable_pct}%"

        if progress_callback:
            progress_callback(
                phase="P4",
                event="candidate_done",
                candidate=candidate,
                index=index,
                total=len(candidates),
                survivors=len(survivors),
                extra={"token": token, "timeframe": tf},
            )

    logger.info("Phase 4 done: %d/%d survived", len(survivors), len(candidates))
    if progress_callback:
        progress_callback(
            phase="P4",
            event="phase_end",
            candidate=None,
            index=len(candidates),
            total=len(candidates),
            survivors=len(survivors),
            extra={"token": token, "timeframe": tf},
        )
    return survivors


# ---------------------------------------------------------------------------
# Phase 4 — Walk-Forward Validation
# ---------------------------------------------------------------------------

def run_wfa_validation(
    candidates: List[GraduationCandidate],
    config: Optional[GraduationConfig] = None,
    *,
    progress_callback: Optional[Callable[..., None]] = None,
) -> List[GraduationCandidate]:
    """
    Phase 5 — Walk-Forward Analysis.

    Pour chaque candidat, exécute un WFA (expanding window) sur le token principal.
    Rejette si stability_score < wfa_min_stability.
    """
    if config is None:
        config = GraduationConfig()

    import warnings
    from pandas.errors import SettingWithCopyWarning

    from backtest.walk_forward import WalkForwardConfig, run_walk_forward
    from data.loader import load_ohlcv

    token = config.validation_tokens[0]
    tf = config.validation_timeframes[0]

    try:
        df = load_ohlcv(token, tf)
    except Exception as e:
        logger.error("Cannot load %s/%s for Phase 4: %s", token, tf, e)
        return candidates

    wfa_cfg = WalkForwardConfig(
        n_folds=config.wfa_folds,
        train_ratio=0.8,
        expanding=True,
    )

    survivors: List[GraduationCandidate] = []

    logger.info("Phase 5: WFA on %d candidates (%d folds)", len(candidates), config.wfa_folds)

    if progress_callback:
        progress_callback(
            phase="P5",
            event="phase_start",
            candidate=None,
            index=0,
            total=len(candidates),
            survivors=0,
            extra={"token": token, "timeframe": tf, "folds": config.wfa_folds},
        )

    for index, candidate in enumerate(candidates, 1):
        if progress_callback:
            progress_callback(
                phase="P5",
                event="candidate_start",
                candidate=candidate,
                index=index,
                total=len(candidates),
                survivors=len(survivors),
                extra={"token": token, "timeframe": tf, "folds": config.wfa_folds},
            )
        try:
            strategy, params = _load_strategy_for_candidate(candidate)
        except Exception as e:
            candidate.decision = "REJECTED"
            candidate.rejection_reason = f"P5 load error: {e}"
            candidate.phase = "P5"
            candidate.p5_verdict = "REJECTED"
            if progress_callback:
                progress_callback(
                    phase="P5",
                    event="candidate_done",
                    candidate=candidate,
                    index=index,
                    total=len(candidates),
                    survivors=len(survivors),
                    extra={"token": token, "timeframe": tf, "folds": config.wfa_folds},
                )
            continue

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=SettingWithCopyWarning)
                summary = run_walk_forward(
                    df=df,
                    strategy_name=strategy,
                    params=params,
                    config=wfa_cfg,
                )

            valid_test_returns = [
                float(fold.test_metrics.get("total_return_pct", 0.0))
                for fold in summary.folds
                if fold.is_valid and fold.test_metrics is not None
            ]
            avg_test_return_pct = (
                sum(valid_test_returns) / len(valid_test_returns)
                if valid_test_returns else 0.0
            )

            stability = float(summary.confidence_score or 0.0)
            candidate.wfa_stability = round(stability, 3)
            candidate.wfa_avg_test_return_pct = round(avg_test_return_pct, 2)
            candidate.wfa_avg_test_sharpe = _safe_round(getattr(summary, "avg_test_sharpe", None), 3)
            candidate.wfa_overfitting_ratio = _safe_round(getattr(summary, "avg_overfitting_ratio", None), 3)
            candidate.wfa_is_robust = bool(getattr(summary, "is_robust", False))
            candidate.phase = "P5"

            if (
                stability >= config.wfa_min_stability
                and avg_test_return_pct > 0
                and (candidate.wfa_avg_test_sharpe is None or candidate.wfa_avg_test_sharpe >= config.wfa_min_test_sharpe)
                and (
                    candidate.wfa_overfitting_ratio is None
                    or candidate.wfa_overfitting_ratio <= config.wfa_max_overfitting_ratio
                )
            ):
                candidate.decision = "WATCHLIST"
                candidate.p5_verdict = "PASSED"
                survivors.append(candidate)
                logger.debug(
                    "P5 PASS: %s — stability=%.3f avg_test_return=%.2f%% robust=%s",
                    candidate.session_id, stability, avg_test_return_pct, summary.is_robust,
                )
            else:
                candidate.decision = "REJECTED"
                candidate.p5_verdict = "REJECTED"
                reasons = []
                if stability < config.wfa_min_stability:
                    reasons.append(f"WFA instable {stability:.2f}<{config.wfa_min_stability}")
                if avg_test_return_pct <= 0:
                    reasons.append(f"WFA avg_test_return={avg_test_return_pct:.2f}%<=0")
                if (
                    candidate.wfa_avg_test_sharpe is not None
                    and candidate.wfa_avg_test_sharpe < config.wfa_min_test_sharpe
                ):
                    reasons.append(
                        f"WFA avg_test_sharpe={candidate.wfa_avg_test_sharpe:.2f}<{config.wfa_min_test_sharpe}"
                    )
                if (
                    candidate.wfa_overfitting_ratio is not None
                    and candidate.wfa_overfitting_ratio > config.wfa_max_overfitting_ratio
                ):
                    reasons.append(
                        f"WFA overfitting={candidate.wfa_overfitting_ratio:.2f}>{config.wfa_max_overfitting_ratio}"
                    )
                candidate.rejection_reason = "; ".join(reasons)

        except Exception as e:
            candidate.decision = "REJECTED"
            candidate.p5_verdict = "REJECTED"
            candidate.rejection_reason = f"P5 WFA error: {e}"
            candidate.phase = "P5"
            logger.debug("WFA error %s: %s", candidate.session_id, e)

        if progress_callback:
            progress_callback(
                phase="P5",
                event="candidate_done",
                candidate=candidate,
                index=index,
                total=len(candidates),
                survivors=len(survivors),
                extra={"token": token, "timeframe": tf, "folds": config.wfa_folds},
            )

    logger.info("Phase 5 done: %d/%d survived", len(survivors), len(candidates))
    if progress_callback:
        progress_callback(
            phase="P5",
            event="phase_end",
            candidate=None,
            index=len(candidates),
            total=len(candidates),
            survivors=len(survivors),
            extra={"token": token, "timeframe": tf, "folds": config.wfa_folds},
        )
    return survivors


# ---------------------------------------------------------------------------
# Phase 6 — Promotion
# ---------------------------------------------------------------------------

def promote_to_strategies(
    candidates: List[GraduationCandidate],
    output_dir: Optional[Path] = None,
) -> List[GraduationCandidate]:
    """
    Phase 6 — Promotion finale.

    Copie les stratégies validées dans strategies/ avec un en-tête de traçabilité.
    """
    import re

    if output_dir is None:
        output_dir = _default_promotion_dir()

    output_dir.mkdir(parents=True, exist_ok=True)

    promoted: List[GraduationCandidate] = []

    logger.info("Phase 6: promoting %d candidates to %s", len(candidates), output_dir)

    for candidate in candidates:
        strategy_path = candidate.session_dir / f"strategy_v{candidate.best_iteration}.py"
        if not strategy_path.exists():
            strategy_path = candidate.session_dir / "strategy.py"

        if not strategy_path.exists():
            candidate.decision = "REJECTED"
            candidate.p6_verdict = "REJECTED"
            candidate.rejection_reason = "P6: no strategy file"
            candidate.phase = "P6"
            continue

        # Générer un nom propre
        safe_id = re.sub(r"[^a-zA-Z0-9_]", "_", candidate.session_id)[:60]
        target = output_dir / f"grad_{safe_id}.py"

        try:
            code = strategy_path.read_text(encoding="utf-8")

            # Ajouter en-tête de traçabilité
            header = (
                f'"""\n'
                f"GRADUATED STRATEGY — promoted by catalog.graduation\n"
                f"\n"
                f"  Session:    {candidate.session_id}\n"
                f"  Origin:     {candidate.origin_status}\n"
                f"  Best Score: {candidate.best_score:.1f}\n"
                f"  Best Return: {candidate.best_return_pct:.1f}%\n"
                f"  Contexts:   {candidate.multi_ctx_results.get('passed_count', '?')}/{candidate.multi_ctx_results.get('total_contexts', '?')}\n"
                f"  Sweep:      {candidate.sweep_robustness_pct}%\n"
                f"  WFA:        {candidate.wfa_stability}\n"
                f'"""\n\n'
            )

            target.write_text(header + code, encoding="utf-8")

            candidate.decision = "PROMOTED"
            candidate.p6_verdict = "PROMOTED"
            candidate.phase = "P6"
            candidate.strategy_file = str(target)
            promoted.append(candidate)

            logger.info("PROMOTED: %s → %s", candidate.session_id, target.name)

        except Exception as e:
            candidate.decision = "REJECTED"
            candidate.p6_verdict = "REJECTED"
            candidate.rejection_reason = f"P6 copy error: {e}"
            candidate.phase = "P6"

    logger.info("Phase 6 done: %d/%d promoted", len(promoted), len(candidates))
    return promoted


# ---------------------------------------------------------------------------
# Catalog sync
# ---------------------------------------------------------------------------

def _resolved_strategy_path(candidate: GraduationCandidate) -> Path:
    if candidate.strategy_file:
        candidate_path = Path(candidate.strategy_file)
        if candidate_path.is_absolute() and candidate_path.exists():
            return candidate_path
        session_relative = candidate.session_dir / candidate.strategy_file
        if session_relative.exists():
            return session_relative
        session_parent_relative = candidate.session_dir.parent / candidate.strategy_file
        if session_parent_relative.exists():
            return session_parent_relative
    strategy_path = candidate.session_dir / f"strategy_v{candidate.best_iteration}.py"
    if not strategy_path.exists():
        strategy_path = candidate.session_dir / "strategy.py"
    return strategy_path


def _candidate_catalog_category(
    candidate: GraduationCandidate,
    config: GraduationConfig,
) -> str:
    if candidate.decision == "PROMOTED" or candidate.p6_verdict == "PROMOTED":
        return "p6_paper_candidate"

    if candidate.p5_verdict == "PASSED":
        return "p5_wfa_candidate"

    if candidate.p4_verdict == "PASSED":
        return "p4_param_robust"

    consensus_passed = bool((candidate.benchmark_consensus or {}).get("consensus_passed"))
    if consensus_passed or candidate.p3_verdict == "PASSED":
        return "p3_benchmark_consensus"

    if candidate.p2_verdict == "PASSED" or candidate.best_return_pct > 0:
        return "p2_positive_observed"

    return "p1_builder_inbox"


def sync_graduation_to_catalog(
    candidates: List[GraduationCandidate],
    config: Optional[GraduationConfig] = None,
) -> List[Dict[str, Any]]:
    """
    Synchronise les candidats de graduation vers strategy_catalog.json.

    Mapping canonique:
      - P2 positifs observés -> p2_positive_observed
      - P3 benchmark consensus -> p3_benchmark_consensus
      - P4 robustesse paramétrique -> p4_param_robust
      - P5 walk-forward -> p5_wfa_candidate
      - P6 promotion finale -> p6_paper_candidate
    """
    if config is None:
        config = GraduationConfig()

    from catalog.strategy_catalog import (
        CATEGORY_ORDER,
        build_entry_id,
        compute_params_hash,
        get_entry,
        upsert_entry,
    )

    synced: List[Dict[str, Any]] = []

    for candidate in candidates:
        target_category = _candidate_catalog_category(candidate, config)
        strategy_name = "graduation_candidate"
        strategy_defaults: Dict[str, Any] = {}

        strategy_path = _resolved_strategy_path(candidate)
        if strategy_path.exists():
            try:
                strategy = _load_strategy_from_file(strategy_path)
                strategy_name = str(getattr(strategy, "name", "") or strategy_name).strip() or strategy_name
                defaults = getattr(strategy, "default_params", None)
                if isinstance(defaults, dict):
                    strategy_defaults = defaults
            except Exception:
                pass

        params_hash = compute_params_hash(
            {
                "session_id": candidate.session_id,
                "best_iteration": candidate.best_iteration,
                "defaults": strategy_defaults,
            }
        )
        entry_id = build_entry_id(strategy_name, "MULTI", "MULTI", params_hash)

        metrics_snapshot = {
            "best_return_pct": candidate.best_return_pct,
            "best_profit_factor": candidate.best_profit_factor,
            "best_score": candidate.best_score,
            "best_sharpe": candidate.best_sharpe,
            "best_trades": candidate.best_trades,
            "best_max_drawdown_pct": candidate.best_max_drawdown_pct,
            "best_win_rate_pct": candidate.best_win_rate_pct,
            "multi_context_passed": (candidate.multi_ctx_results or {}).get("passed_count"),
            "multi_context_total": (candidate.multi_ctx_results or {}).get("total_contexts"),
            "sweep_robustness_pct": candidate.sweep_robustness_pct,
            "wfa_stability": candidate.wfa_stability,
            "wfa_avg_test_return_pct": candidate.wfa_avg_test_return_pct,
        }

        tags = [
            "builder_out",
            "graduation",
            f"graduation_{candidate.phase.lower()}",
            f"graduation_{candidate.decision.lower()}",
        ]

        note_parts = [
            f"session_id: {candidate.session_id}",
            f"phase: {candidate.phase}",
            f"decision: {candidate.decision}",
        ]
        if candidate.rejection_reason:
            note_parts.append(f"reason: {candidate.rejection_reason}")
        elif candidate.objective:
            note_parts.append(candidate.objective[:220])

        entry = {
            "id": entry_id,
            "strategy_name": strategy_name,
            "symbol": "MULTI",
            "timeframe": "MULTI",
            "params_hash": params_hash,
            "category": target_category,
            "status": "active",
            "builder_state": "completed" if candidate.origin_status == "success" else "stopped",
            "source": "graduation",
            "tags": tags,
            "note": " | ".join(note_parts),
            "last_metrics_snapshot": _json_safe(metrics_snapshot),
            "meta": _json_safe(
                {
                    "session_id": candidate.session_id,
                    "session_dir": str(candidate.session_dir),
                    "strategy_file": candidate.strategy_file,
                    "best_iteration": candidate.best_iteration,
                    "origin_status": candidate.origin_status,
                    "objective": candidate.objective,
                    "candidate_id": candidate.candidate_id or candidate.session_id,
                    "source_mode": candidate.source_mode,
                    "benchmark_results": candidate.benchmark_results,
                    "benchmark_names": config.benchmark_names,
                    "benchmark_consensus": candidate.benchmark_consensus,
                    "configured_contexts": candidate.configured_contexts,
                    "loaded_contexts": candidate.loaded_contexts,
                    "missing_contexts": candidate.missing_contexts,
                    "tested_timeframes": candidate.tested_timeframes,
                    "coverage_pct": candidate.coverage_pct,
                    "validation_tokens": config.validation_tokens,
                    "validation_timeframes": config.validation_timeframes,
                    "decision": candidate.decision,
                    "phase": candidate.phase,
                    "p2_verdict": candidate.p2_verdict,
                    "p3_verdict": candidate.p3_verdict,
                    "p4_verdict": candidate.p4_verdict,
                    "p5_verdict": candidate.p5_verdict,
                    "p6_verdict": candidate.p6_verdict,
                    "promoted_strategy_path": candidate.strategy_file
                    if candidate.decision == "PROMOTED"
                    else None,
                }
            ),
        }

        existing = get_entry(entry_id, path=config.catalog_path)
        if existing:
            existing_category = existing.get("category")
            if existing_category in CATEGORY_ORDER and CATEGORY_ORDER.index(existing_category) > CATEGORY_ORDER.index(target_category):
                entry["category"] = existing_category
            existing_tags = existing.get("tags") or []
            entry["tags"] = sorted(set(existing_tags).union(entry["tags"]))
            existing_meta = existing.get("meta") or {}
            if isinstance(existing_meta, dict):
                merged_meta = dict(existing_meta)
                merged_meta.update(entry["meta"])
                entry["meta"] = merged_meta
            if existing.get("note"):
                entry["note"] = existing["note"]

        saved = upsert_entry(entry, path=config.catalog_path)
        candidate.catalog_category = saved.get("category")
        candidate.catalog_entry_id = saved.get("id")
        synced.append(saved)

    logger.info("Graduation sync: %d candidates synced to %s", len(synced), config.catalog_path)
    return synced


def sync_positive_import_candidates_to_catalog(
    candidates: List[GraduationCandidate],
    config: Optional[GraduationConfig] = None,
) -> List[Dict[str, Any]]:
    """Met à jour les entrées `positive_import` existantes avec l'avancement canonique P2→P6."""
    if config is None:
        config = GraduationConfig()

    from catalog.strategy_catalog import CATEGORY_ORDER, get_entry, upsert_entry

    synced: List[Dict[str, Any]] = []

    for candidate in candidates:
        if not candidate.catalog_entry_id:
            continue

        existing = get_entry(candidate.catalog_entry_id, path=config.catalog_path)
        if not existing:
            continue

        target_category = _candidate_catalog_category(candidate, config)
        existing_category = existing.get("category")
        if existing_category in CATEGORY_ORDER and CATEGORY_ORDER.index(existing_category) > CATEGORY_ORDER.index(target_category):
            target_category = existing_category

        metrics_snapshot = dict(existing.get("last_metrics_snapshot") or {})
        metrics_snapshot.update(
            _json_safe(
                {
                    "best_return_pct": candidate.best_return_pct,
                    "best_profit_factor": candidate.best_profit_factor,
                    "best_score": candidate.best_score,
                    "best_sharpe": candidate.best_sharpe,
                    "best_trades": candidate.best_trades,
                    "best_max_drawdown_pct": candidate.best_max_drawdown_pct,
                    "best_win_rate_pct": candidate.best_win_rate_pct,
                    "multi_context_passed": (candidate.multi_ctx_results or {}).get("passed_count"),
                    "multi_context_total": (candidate.multi_ctx_results or {}).get("total_contexts"),
                    "sweep_robustness_pct": candidate.sweep_robustness_pct,
                    "wfa_stability": candidate.wfa_stability,
                    "wfa_avg_test_return_pct": candidate.wfa_avg_test_return_pct,
                }
            )
        )

        tags = sorted(
            set(existing.get("tags") or []).union(
                {
                    "positive_import",
                    "positive_processed",
                    f"positive_{candidate.phase.lower()}",
                    f"positive_{candidate.decision.lower()}",
                }
            )
        )

        meta = dict(existing.get("meta") or {})
        meta.update(
            _json_safe(
                {
                    "positive_pipeline_phase": candidate.phase,
                    "positive_pipeline_decision": candidate.decision,
                    "positive_pipeline_rejection_reason": candidate.rejection_reason or None,
                    "positive_pipeline_candidate_id": candidate.candidate_id or candidate.session_id,
                    "positive_pipeline_source_mode": candidate.source_mode,
                    "positive_pipeline_strategy_name": candidate.strategy_name,
                    "positive_pipeline_source_kind": candidate.source_kind,
                    "positive_pipeline_source_run_id": candidate.source_run_id,
                    "positive_pipeline_benchmark_results": candidate.benchmark_results,
                    "positive_pipeline_benchmark_consensus": candidate.benchmark_consensus,
                    "positive_pipeline_configured_contexts": candidate.configured_contexts,
                    "positive_pipeline_loaded_contexts": candidate.loaded_contexts,
                    "positive_pipeline_missing_contexts": candidate.missing_contexts,
                    "positive_pipeline_tested_timeframes": candidate.tested_timeframes,
                    "positive_pipeline_coverage_pct": candidate.coverage_pct,
                    "positive_pipeline_p2_verdict": candidate.p2_verdict,
                    "positive_pipeline_p3_verdict": candidate.p3_verdict,
                    "positive_pipeline_p4_verdict": candidate.p4_verdict,
                    "positive_pipeline_p5_verdict": candidate.p5_verdict,
                    "positive_pipeline_p6_verdict": candidate.p6_verdict,
                    "positive_pipeline_tokens": config.validation_tokens,
                    "positive_pipeline_timeframes": config.validation_timeframes,
                    "positive_pipeline_passed_count": (candidate.multi_ctx_results or {}).get("passed_count"),
                    "positive_pipeline_total_contexts": (candidate.multi_ctx_results or {}).get("total_contexts"),
                }
            )
        )

        note = str(existing.get("note") or "").strip()
        if candidate.rejection_reason:
            suffix = f" | positive_pipeline: {candidate.rejection_reason}"
            if suffix not in note:
                note = f"{note}{suffix}" if note else suffix.lstrip(" |")

        entry = dict(existing)
        entry.update(
            {
                "category": target_category,
                "tags": tags,
                "note": note,
                "last_metrics_snapshot": metrics_snapshot,
                "meta": meta,
            }
        )

        saved = upsert_entry(entry, path=config.catalog_path)
        candidate.catalog_category = saved.get("category")
        candidate.catalog_entry_id = saved.get("id")
        synced.append(saved)

    logger.info("Positive import sync: %d candidates synced to %s", len(synced), config.catalog_path)
    return synced


def run_positive_import_graduation(
    config: Optional[GraduationConfig] = None,
) -> Dict[str, Any]:
    """
    Exécute le pipeline canonique P2→P5 sur les entrées `positive_import` du strategy catalog.
    """
    if config is None:
        config = GraduationConfig()

    stats: Dict[str, Any] = {}
    report_filename = "positive_imports_graduation.json"
    progress_path = config.output_dir / config.positive_progress_filename
    started_at = _utc_now_iso()
    current_phase = "P1"
    current_candidate: Optional[GraduationCandidate] = None

    def _write_progress(
        *,
        status: str,
        event: str,
        phase: str,
        candidate: Optional[GraduationCandidate],
        index: int,
        total: int,
        extra: Optional[Dict[str, Any]] = None,
        error: str = "",
    ) -> None:
        payload: Dict[str, Any] = {
            "pipeline": "positive_imports",
            "status": status,
            "event": event,
            "pid": os.getpid(),
            "started_at": started_at,
            "current_phase": phase,
            "current_index": index,
            "current_total": total,
            "stats": dict(stats),
            "report_path": str(config.output_dir / report_filename),
        }
        if candidate is not None:
            payload["current_candidate"] = _candidate_progress_payload(candidate)
        if extra:
            payload["extra"] = dict(extra)
        if error:
            payload["error"] = error
        _save_progress_state(config.output_dir, config.positive_progress_filename, payload)

    _write_progress(
        status="starting",
        event="bootstrap",
        phase=current_phase,
        candidate=None,
        index=0,
        total=0,
    )

    candidates: List[GraduationCandidate] = []
    all_candidates: List[GraduationCandidate] = []
    synced: List[Dict[str, Any]] = []

    try:
        candidates = scan_positive_import_candidates(config)
        stats["p1_candidates"] = len(candidates)
        stats["import_candidates"] = len(candidates)
        all_candidates = list(candidates)
        save_graduation_report(
            all_candidates,
            config.output_dir,
            phase="POSITIVE_IMPORTS",
            filename=report_filename,
            stats=stats,
        )
        _write_progress(
            status="running",
            event="scan_complete",
            phase="P1",
            candidate=None,
            index=0,
            total=len(candidates),
        )

        survivors = run_positive_observed_filter(candidates, source_mode="positive_import")
        stats["p2_survivors"] = len(survivors)
        current_phase = "P2"
        _write_progress(
            status="running",
            event="positive_observed_complete",
            phase="P2",
            candidate=None,
            index=len(survivors),
            total=len(candidates),
            extra={"survivors": len(survivors)},
        )
        save_graduation_report(
            all_candidates,
            config.output_dir,
            phase="POSITIVE_IMPORTS",
            filename=report_filename,
            stats=stats,
        )

        def _progress_callback(
            *,
            phase: str,
            event: str,
            candidate: Optional[GraduationCandidate],
            index: int,
            total: int,
            survivors: int,
            extra: Optional[Dict[str, Any]] = None,
        ) -> None:
            nonlocal current_phase, current_candidate
            current_phase = phase
            current_candidate = candidate

            processed_key = f"{phase.lower()}_processed"
            if event in {"candidate_done", "phase_end"}:
                stats[processed_key] = max(int(stats.get(processed_key, 0)), index)
            else:
                stats.setdefault(processed_key, max(index - 1, 0))

            if phase == "P3":
                stats["p3_survivors"] = survivors
            elif phase == "P4":
                stats["p4_survivors"] = survivors
            elif phase == "P5":
                stats["p5_survivors"] = survivors

            _write_progress(
                status="running",
                event=event,
                phase=phase,
                candidate=candidate,
                index=index,
                total=total,
                extra=extra,
            )

            if event in {"candidate_done", "phase_end"}:
                save_graduation_report(
                    all_candidates,
                    config.output_dir,
                    phase="POSITIVE_IMPORTS",
                    filename=report_filename,
                    stats=stats,
                )

        with _safe_engine_mode():
            survivors = run_multi_context_validation(
                survivors,
                config,
                progress_callback=_progress_callback,
            )
            stats["p3_survivors"] = len(survivors)

            survivors = run_parameter_sensitivity(
                survivors,
                config,
                progress_callback=_progress_callback,
            )
            stats["p4_survivors"] = len(survivors)

            survivors = run_wfa_validation(
                survivors,
                config,
                progress_callback=_progress_callback,
            )
            stats["p5_survivors"] = len(survivors)
        stats["p6_promoted"] = 0

        synced = sync_positive_import_candidates_to_catalog(all_candidates, config)
        stats["catalog_synced"] = len(synced)

        save_graduation_report(
            all_candidates,
            config.output_dir,
            phase="POSITIVE_IMPORTS",
            filename=report_filename,
            stats=stats,
        )
        _write_progress(
            status="completed",
            event="completed",
            phase=current_phase,
            candidate=current_candidate,
            index=stats.get("p5_processed", stats.get("p4_processed", stats.get("p3_processed", 0))),
            total=stats.get("import_candidates", 0),
        )
    except Exception as exc:
        save_graduation_report(
            all_candidates,
            config.output_dir,
            phase="POSITIVE_IMPORTS",
            filename=report_filename,
            stats=stats,
        )
        _write_progress(
            status="failed",
            event="failed",
            phase=current_phase,
            candidate=current_candidate,
            index=stats.get("p5_processed", stats.get("p4_processed", stats.get("p3_processed", 0))),
            total=stats.get("import_candidates", 0),
            error=str(exc),
        )
        raise

    logger.info(
        "Positive import graduation: P1=%d → P2=%d → P3=%d → P4=%d → P5=%d",
        stats["p1_candidates"],
        stats["p2_survivors"],
        stats["p3_survivors"],
        stats["p4_survivors"],
        stats["p5_survivors"],
    )

    return {
        "stats": stats,
        "all_candidates": all_candidates,
        "catalog_entries": synced,
        "progress_path": progress_path,
    }


# ---------------------------------------------------------------------------
# Pipeline complet
# ---------------------------------------------------------------------------

def run_full_graduation(
    config: Optional[GraduationConfig] = None,
) -> Dict[str, Any]:
    """
    Exécute le pipeline complet canonique P1 → P6.

    Returns:
        Dict avec stats par phase et liste finale de candidats promus.
    """
    if config is None:
        config = GraduationConfig()

    stats: Dict[str, Any] = {}

    # P1
    candidates = scan_sandbox(config)
    stats["p1_candidates"] = len(candidates)
    all_candidates = list(candidates)  # copie pour le rapport

    # P2
    survivors = run_positive_observed_filter(candidates, source_mode="sandbox")
    stats["p2_survivors"] = len(survivors)

    # P3
    survivors = run_multi_context_validation(survivors, config)
    stats["p3_survivors"] = len(survivors)

    # P4
    survivors = run_parameter_sensitivity(survivors, config)
    stats["p4_survivors"] = len(survivors)

    # P5
    survivors = run_wfa_validation(survivors, config)
    stats["p5_survivors"] = len(survivors)

    # P6
    promoted = promote_to_strategies(survivors, config.promotion_dir)
    stats["p6_promoted"] = len(promoted)

    synced = []
    if config.sync_catalog:
        synced = sync_graduation_to_catalog(all_candidates, config)
    stats["catalog_synced"] = len(synced)

    # Sauvegarder le rapport complet
    save_graduation_report(
        all_candidates,
        config.output_dir,
        phase="FULL",
        filename="graduation_full.json",
        stats=stats,
    )

    logger.info(
        "Full graduation: P1=%d → P2=%d → P3=%d → P4=%d → P5=%d → P6=%d",
        stats["p1_candidates"], stats["p2_survivors"],
        stats["p3_survivors"], stats["p4_survivors"], stats["p5_survivors"], stats["p6_promoted"],
    )

    return {
        "stats": stats,
        "promoted": promoted,
        "all_candidates": all_candidates,
        "catalog_entries": synced,
    }


if __name__ == "__main__":
    main()
