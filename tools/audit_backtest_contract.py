"""MVP runner for strict backtest parameter audit."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.audit_contract import (
    dump_json,
    recompute_basic_metrics,
    reconcile_metrics,
)
from backtest.audit_sentinels import make_sentinel_ohlcv  # noqa: F401 - imports/registers sentinels
from backtest.engine import BacktestEngine
from utils.config import Config


@dataclass(frozen=True)
class AuditRun:
    strategy: str
    params: dict[str, Any]
    metrics: dict[str, Any]
    trades: pd.DataFrame
    equity: pd.Series
    meta: dict[str, Any]

    @property
    def audit(self) -> dict[str, Any]:
        return dict(self.meta.get("audit", {}) or {})

    @property
    def hashes(self) -> dict[str, str]:
        audit = self.audit
        return {
            "signals_hash": str(audit.get("signals_hash", "")),
            "trades_hash": str(audit.get("trades_hash", "")),
            "equity_hash": str(audit.get("equity_hash", "")),
            "metrics_hash": str(audit.get("metrics_hash", "")),
        }


def _metrics_dict(metrics: Any) -> dict[str, Any]:
    if hasattr(metrics, "to_dict"):
        return dict(metrics.to_dict())
    return dict(metrics or {})


def run_audited_once(
    *,
    strategy: str,
    df: pd.DataFrame,
    params: dict[str, Any] | None = None,
    seed: int = 42,
    capital: float = 10000.0,
    symbol: str = "AUDIT",
    timeframe: str = "1h",
) -> AuditRun:
    provided = dict(params or {})
    provided.setdefault("fees_bps", 0.0)
    provided.setdefault("slippage_bps", 0.0)
    config = Config(
        fees_bps=float(provided.get("fees_bps", 0.0)),
        slippage_bps=float(provided.get("slippage_bps", 0.0)),
    )
    engine = BacktestEngine(initial_capital=capital, config=config)
    result = engine.run(
        df=df.copy(deep=True),
        strategy=strategy,
        params=provided,
        symbol=symbol,
        timeframe=timeframe,
        seed=seed,
        audit_mode=True,
        strict_params=True,
        fast_metrics=True,
    )
    return AuditRun(
        strategy=strategy,
        params=provided,
        metrics=_metrics_dict(result.metrics),
        trades=result.trades.copy(deep=True),
        equity=result.equity.copy(deep=True),
        meta=dict(result.meta or {}),
    )


def compare_reproducibility(run_a: AuditRun, run_b: AuditRun) -> dict[str, Any]:
    comparisons = {
        key: {
            "run_a": run_a.hashes.get(key),
            "run_b": run_b.hashes.get(key),
            "passed": run_a.hashes.get(key) == run_b.hashes.get(key),
        }
        for key in ("signals_hash", "trades_hash", "equity_hash", "metrics_hash")
    }
    failures = [key for key, item in comparisons.items() if not item["passed"]]
    return {"passed": not failures, "failures": failures, "comparisons": comparisons}


def run_reproducibility_check(
    *,
    strategy: str,
    df: pd.DataFrame,
    params: dict[str, Any],
    seed: int = 42,
    capital: float = 10000.0,
) -> tuple[dict[str, Any], AuditRun, AuditRun]:
    run_a = run_audited_once(strategy=strategy, df=df, params=params, seed=seed, capital=capital)
    run_b = run_audited_once(strategy=strategy, df=df, params=params, seed=seed, capital=capital)
    return compare_reproducibility(run_a, run_b), run_a, run_b


def recompute_and_reconcile(run: AuditRun, *, capital: float = 10000.0) -> tuple[dict[str, Any], dict[str, Any]]:
    recomputed = recompute_basic_metrics(equity=run.equity, trades=run.trades, initial_capital=capital)
    reconciliation = reconcile_metrics(run.metrics, recomputed)
    return recomputed, reconciliation


def _hashes_changed(run_a: AuditRun, run_b: AuditRun) -> bool:
    return any(run_a.hashes.get(key) != run_b.hashes.get(key) for key in run_a.hashes)


def evaluate_sensitivity_pair(
    *,
    baseline: AuditRun,
    variant: AuditRun,
    required_exit_reason: str | None = None,
    allowed_sides: set[str] | None = None,
) -> dict[str, Any]:
    changed = _hashes_changed(baseline, variant)
    extra_passed = True
    details: dict[str, Any] = {"hashes_changed": changed}

    if required_exit_reason is not None:
        reasons = set(str(value) for value in variant.trades.get("exit_reason", pd.Series(dtype=str)).tolist())
        details["exit_reasons"] = sorted(reasons)
        extra_passed = extra_passed and required_exit_reason in reasons

    if allowed_sides is not None:
        sides = set(str(value) for value in variant.trades.get("side", pd.Series(dtype=str)).tolist())
        details["sides"] = sorted(sides)
        extra_passed = extra_passed and sides.issubset(allowed_sides)

    status = "affected" if changed and extra_passed else "no_effect"
    return {"status": status, **details, "baseline_hashes": baseline.hashes, "variant_hashes": variant.hashes}


def run_sensitivity_suite(*, seed: int = 42, capital: float = 10000.0) -> dict[str, Any]:
    report: dict[str, Any] = {}

    cases = [
        (
            "leverage",
            "always_long",
            "trend",
            {"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "warmup": 0, "k_sl": 50.0},
            {"leverage": 3, "fees_bps": 0, "slippage_bps": 0, "warmup": 0, "k_sl": 50.0},
            {},
        ),
        (
            "fees_bps",
            "fees_slippage",
            "flat",
            {"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "warmup": 0, "k_sl": 50.0},
            {"leverage": 1, "fees_bps": 1000, "slippage_bps": 0, "warmup": 0, "k_sl": 50.0},
            {},
        ),
        (
            "slippage_bps",
            "fees_slippage",
            "flat",
            {"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "warmup": 0, "k_sl": 50.0},
            {"leverage": 1, "fees_bps": 0, "slippage_bps": 500, "warmup": 0, "k_sl": 50.0},
            {},
        ),
        (
            "k_sl",
            "stop_near",
            "stop",
            {"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "k_sl": 50.0},
            {"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "k_sl": 0.1},
            {"required_exit_reason": "stop_loss"},
        ),
        (
            "take_profit_pct",
            "tp_near",
            "tp",
            {"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "k_sl": 50.0, "take_profit_pct": 999.0},
            {"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "k_sl": 50.0, "take_profit_pct": 0.1},
            {"required_exit_reason": "take_profit"},
        ),
        (
            "warmup",
            "always_long",
            "trend",
            {"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "warmup": 0, "k_sl": 50.0},
            {"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "warmup": 3, "k_sl": 50.0},
            {},
        ),
    ]

    for name, strategy, data_kind, baseline_params, variant_params, expectations in cases:
        try:
            df = make_sentinel_ohlcv(data_kind)
            baseline = run_audited_once(
                strategy=strategy,
                df=df,
                params=baseline_params,
                seed=seed,
                capital=capital,
            )
            variant = run_audited_once(
                strategy=strategy,
                df=df,
                params=variant_params,
                seed=seed,
                capital=capital,
            )
            report[name] = evaluate_sensitivity_pair(
                baseline=baseline,
                variant=variant,
                **expectations,
            )
        except Exception as exc:
            report[name] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    try:
        df = make_sentinel_ohlcv("flat")
        baseline = run_audited_once(
            strategy="fees_slippage",
            df=df,
            params={"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "direction": "long_short"},
            seed=seed,
            capital=capital,
        )
        long_only = run_audited_once(
            strategy="fees_slippage",
            df=df,
            params={"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "direction": "long_only"},
            seed=seed,
            capital=capital,
        )
        short_only = run_audited_once(
            strategy="fees_slippage",
            df=df,
            params={"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "direction": "short_only"},
            seed=seed,
            capital=capital,
        )
        long_report = evaluate_sensitivity_pair(
            baseline=baseline,
            variant=long_only,
            allowed_sides={"LONG"},
        )
        short_report = evaluate_sensitivity_pair(
            baseline=baseline,
            variant=short_only,
            allowed_sides={"SHORT"},
        )
        report["direction"] = {
            "status": "affected" if long_report["status"] == short_report["status"] == "affected" else "no_effect",
            "long_only": long_report,
            "short_only": short_report,
        }
    except Exception as exc:
        report["direction"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    return report


def run_mvp_audit(output_dir: Path, *, seed: int = 42, capital: float = 10000.0) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    repro_params = {"leverage": 1, "fees_bps": 0, "slippage_bps": 0, "warmup": 0, "k_sl": 50.0}
    reproducibility, run_a, _run_b = run_reproducibility_check(
        strategy="always_long",
        df=make_sentinel_ohlcv("trend"),
        params=repro_params,
        seed=seed,
        capital=capital,
    )
    effective_config = run_a.audit.get("effective_config", {})
    recomputed, reconciliation = recompute_and_reconcile(run_a, capital=capital)
    sensitivity = run_sensitivity_suite(seed=seed, capital=capital)

    dump_json(output_dir / "effective_config.json", effective_config)
    dump_json(output_dir / "reproducibility.json", reproducibility)
    dump_json(output_dir / "metrics_recomputed.json", recomputed)
    dump_json(output_dir / "metric_reconciliation.json", reconciliation)
    dump_json(output_dir / "sensitivity_report.json", sensitivity)

    failures: list[str] = []
    if not reproducibility["passed"]:
        failures.append("non_reproducible")
    if not reconciliation["passed"]:
        failures.append("metric_reconciliation_failed")
    for name, payload in sensitivity.items():
        if payload.get("status") != "affected":
            failures.append(f"sensitivity_{name}_{payload.get('status')}")

    report = {
        "verdict": "failed" if failures else "passed",
        "failures": failures,
        "effective_config_path": str(output_dir / "effective_config.json"),
        "reproducibility": {"passed": reproducibility["passed"]},
        "metric_reconciliation": {"passed": reconciliation["passed"]},
        "sensitivity": {name: payload.get("status") for name, payload in sensitivity.items()},
    }
    dump_json(output_dir / "audit_report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the MVP strict backtest audit.")
    parser.add_argument("--output", default="runs/audit/mvp_latest", help="Audit output directory.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--capital", type=float, default=10000.0)
    args = parser.parse_args(argv)

    report = run_mvp_audit(Path(args.output), seed=args.seed, capital=args.capital)
    dump_json(Path(args.output) / "audit_report.json", report)
    print(f"audit verdict: {report['verdict']}")
    if report["failures"]:
        print("failures:")
        for failure in report["failures"]:
            print(f"  - {failure}")
    return 0 if report["verdict"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
