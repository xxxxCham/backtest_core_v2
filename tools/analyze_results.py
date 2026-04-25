"""Module-ID: tools.analyze_results

Purpose: Refresh lightweight analysis artifacts from backtest_results.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.result_store import (
    get_results_analysis_dir,
    get_results_root_dir,
    get_workspace_results_analysis_dir,
)
from tools.generate_html_report import generate_html_report

SYSTEM_PARAM_KEYS = {
    "initial_capital",
    "fees_bps",
    "slippage_bps",
}
ANALYSIS_ARTIFACT_FILENAMES = (
    "analysis_report.html",
    "analysis_report_filtered.html",
    "analysis_top_configs.csv",
)
TOP_CONFIG_BASE_COLUMNS = [
    "rank",
    "strategy",
    "symbol",
    "timeframe",
    "run_id",
    "timestamp",
    "status",
    "mode",
    "pnl",
    "return_pct",
    "sharpe",
    "sortino",
    "profit_factor",
    "max_drawdown",
    "trades",
    "win_rate",
    "account_ruined",
    "duplicate_run_count",
    "duplicate_run_ids",
    "path",
]


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if key in SYSTEM_PARAM_KEYS:
            continue
        cleaned[str(key)] = value
    return cleaned


def _stable_param_value(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


def extract_all_results(results_dir: Path | None = None) -> list[dict[str, Any]]:
    results_dir = get_results_root_dir(results_dir)
    results: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()

    if not results_dir.exists():
        return results

    for metadata_path in sorted(results_dir.rglob("metadata.json")):
        if "_catalog" in metadata_path.parts:
            continue
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        run_id = str(payload.get("run_id") or metadata_path.parent.name).strip()
        if not run_id or run_id in seen_run_ids:
            continue
        seen_run_ids.add(run_id)

        metrics = dict(payload.get("metrics") or {})
        params = _clean_params(dict(payload.get("params") or {}))
        extra_metadata = dict(payload.get("extra_metadata") or {})

        results.append(
            {
                "run_id": run_id,
                "strategy": str(payload.get("strategy") or "").strip(),
                "symbol": str(payload.get("symbol") or "").strip(),
                "tf": str(payload.get("timeframe") or "").strip(),
                "timestamp": str(payload.get("timestamp") or "").strip(),
                "status": str(payload.get("status") or "").strip(),
                "mode": str(payload.get("mode") or "").strip(),
                "pnl": _as_float(metrics.get("total_pnl")),
                "return_pct": _as_float(metrics.get("total_return_pct")),
                "sharpe": _as_float(metrics.get("sharpe_ratio")),
                "sortino": _as_float(metrics.get("sortino_ratio")),
                "win_rate": _as_float(metrics.get("win_rate_pct")),
                "trades": _as_int(metrics.get("total_trades")),
                "profit_factor": _as_float(metrics.get("profit_factor")),
                "max_drawdown": _as_float(metrics.get("max_drawdown_pct")),
                "account_ruined": bool(metrics.get("account_ruined", False)),
                "period_start": str(payload.get("period_start") or "").strip(),
                "period_end": str(payload.get("period_end") or "").strip(),
                "builder_session_id": str(extra_metadata.get("builder_session_id") or "").strip(),
                "builder_iteration": _as_int(extra_metadata.get("builder_iteration"), default=0),
                "params": params,
                "path": str(metadata_path.parent),
            },
        )

    return sort_results(results)


def sort_results(results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        list(results),
        key=lambda item: (
            _as_float(item.get("return_pct")),
            _as_float(item.get("pnl")),
            _as_float(item.get("sharpe")),
            _as_float(item.get("profit_factor")),
            _as_int(item.get("trades")),
        ),
        reverse=True,
    )


def filter_current_results(
    results: Iterable[dict[str, Any]],
    *,
    profitable_only: bool = True,
    exclude_ruined: bool = True,
    min_trades: int = 1,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for result in results:
        if profitable_only and _as_float(result.get("return_pct")) <= 0:
            continue
        if exclude_ruined and bool(result.get("account_ruined")):
            continue
        if _as_int(result.get("trades")) < min_trades:
            continue
        filtered.append(dict(result))
    return sort_results(filtered)


def deduplicate_results(results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for result in results:
        params_items = tuple(
            sorted((str(key), _stable_param_value(value)) for key, value in (result.get("params") or {}).items()),
        )
        key = (
            result.get("strategy"),
            result.get("symbol"),
            result.get("tf"),
            result.get("period_start"),
            result.get("period_end"),
            params_items,
        )
        grouped.setdefault(key, []).append(dict(result))

    deduped: list[dict[str, Any]] = []
    for duplicates in grouped.values():
        best = sort_results(duplicates)[0]
        best["duplicate_run_count"] = len(duplicates)
        best["duplicate_run_ids"] = [item.get("run_id") for item in duplicates]
        deduped.append(best)
    return sort_results(deduped)


def export_top_configs(
    results: Iterable[dict[str, Any]],
    output_path: Path | None = None,
    *,
    top_n: int = 100,
) -> Path:
    if output_path is None:
        output_path = get_results_analysis_dir() / "analysis_top_configs.csv"
    else:
        output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ranked_results = sort_results(results)[: max(int(top_n), 0)]
    param_columns = sorted(
        {
            f"param_{key}"
            for result in ranked_results
            for key in (result.get("params") or {}).keys()
        },
    )
    rows: list[dict[str, Any]] = []
    for rank, result in enumerate(ranked_results, 1):
        row = {
            "rank": rank,
            "strategy": result.get("strategy"),
            "symbol": result.get("symbol"),
            "timeframe": result.get("tf"),
            "run_id": result.get("run_id"),
            "timestamp": result.get("timestamp"),
            "status": result.get("status"),
            "mode": result.get("mode"),
            "pnl": result.get("pnl"),
            "return_pct": result.get("return_pct"),
            "sharpe": result.get("sharpe"),
            "sortino": result.get("sortino"),
            "profit_factor": result.get("profit_factor"),
            "max_drawdown": result.get("max_drawdown"),
            "trades": result.get("trades"),
            "win_rate": result.get("win_rate"),
            "account_ruined": result.get("account_ruined"),
            "duplicate_run_count": result.get("duplicate_run_count", 1),
            "duplicate_run_ids": "|".join(result.get("duplicate_run_ids") or []),
            "path": result.get("path"),
        }
        for key, value in sorted((result.get("params") or {}).items()):
            row[f"param_{key}"] = value
        rows.append(row)

    df = pd.DataFrame(rows, columns=[*TOP_CONFIG_BASE_COLUMNS, *param_columns])
    df.to_csv(output_path, index=False, encoding="utf-8")
    return output_path


def _mirror_analysis_artifacts(source_dir: Path, mirror_dir: Path) -> list[str]:
    source_dir = Path(source_dir)
    mirror_dir = Path(mirror_dir)
    if source_dir.resolve() == mirror_dir.resolve():
        return []

    mirror_dir.mkdir(parents=True, exist_ok=True)
    mirrored_paths: list[str] = []
    for filename in ANALYSIS_ARTIFACT_FILENAMES:
        source_path = source_dir / filename
        if not source_path.exists():
            continue
        target_path = mirror_dir / filename
        shutil.copy2(source_path, target_path)
        mirrored_paths.append(str(target_path))
    return mirrored_paths


def refresh_analysis_artifacts(
    results_dir: Path | None = None,
    *,
    top_n: int = 100,
    output_dir: Path | None = None,
    workspace_output_dir: Path | None = None,
) -> dict[str, Any]:
    results_dir = get_results_root_dir(results_dir)
    output_dir = Path(output_dir) if output_dir is not None else get_results_analysis_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_results = extract_all_results(results_dir)
    all_results = deduplicate_results(raw_results)
    filtered_results = deduplicate_results(filter_current_results(raw_results))

    csv_path = export_top_configs(filtered_results, output_dir / "analysis_top_configs.csv", top_n=top_n)
    html_path = output_dir / "analysis_report.html"
    filtered_html_path = output_dir / "analysis_report_filtered.html"
    generate_html_report(
        all_results,
        html_path,
        title="Backtest Analysis Report",
        top_n=top_n,
        filters_description="All available backtest runs",
        csv_path=csv_path,
    )
    generate_html_report(
        filtered_results,
        filtered_html_path,
        title="Backtest Analysis Report - Filtered",
        top_n=top_n,
        filters_description="return_pct > 0, account_ruined = False, trades >= 1",
        csv_path=csv_path,
    )
    workspace_output_dir = (
        Path(workspace_output_dir) if workspace_output_dir is not None else get_workspace_results_analysis_dir()
    )
    mirrored_files = _mirror_analysis_artifacts(output_dir, workspace_output_dir)

    return {
        "total_results": len(all_results),
        "raw_results": len(raw_results),
        "filtered_results": len(filtered_results),
        "top_n": top_n,
        "csv_path": str(csv_path),
        "html_path": str(html_path),
        "filtered_html_path": str(filtered_html_path),
        "workspace_output_dir": str(workspace_output_dir),
        "mirrored_files": mirrored_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh analysis artifacts from the configured backtest results store",
    )
    parser.add_argument(
        "--results-dir",
        default="",
        help="Path to backtest results root (default: BACKTEST_RESULTS_DIR or backtest_results)",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Path for generated analysis artifacts (default: configured artifacts root/_analysis)",
    )
    parser.add_argument("--top", type=int, default=100, help="Number of ranked configs to export/render")
    args = parser.parse_args()

    results_dir = get_results_root_dir(args.results_dir or None)
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else None
    stats = refresh_analysis_artifacts(results_dir, top_n=args.top, output_dir=output_dir)
    print(
        f"Analysis refreshed: total={stats['total_results']} filtered={stats['filtered_results']} top={stats['top_n']}",
    )
    print(f"CSV: {stats['csv_path']}")
    print(f"HTML: {stats['html_path']}")
    print(f"Filtered HTML: {stats['filtered_html_path']}")
    if stats.get("mirrored_files"):
        print(f"Workspace mirror: {stats['workspace_output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
