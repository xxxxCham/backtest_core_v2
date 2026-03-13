"""
Module-ID: tools.analyze_results

Purpose: Refresh lightweight analysis artifacts from backtest_results.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from tools.generate_html_report import generate_html_report

SYSTEM_PARAM_KEYS = {
    "initial_capital",
    "fees_bps",
    "slippage_bps",
}


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


def _clean_params(params: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for key, value in (params or {}).items():
        if key in SYSTEM_PARAM_KEYS:
            continue
        cleaned[str(key)] = value
    return cleaned


def extract_all_results(results_dir: Path = Path("backtest_results")) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
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
            }
        )

    return sort_results(results)


def sort_results(results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
    results: Iterable[Dict[str, Any]],
    *,
    profitable_only: bool = True,
    exclude_ruined: bool = True,
    min_trades: int = 1,
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for result in results:
        if profitable_only and _as_float(result.get("return_pct")) <= 0:
            continue
        if exclude_ruined and bool(result.get("account_ruined")):
            continue
        if _as_int(result.get("trades")) < min_trades:
            continue
        filtered.append(dict(result))
    return sort_results(filtered)


def deduplicate_results(results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[Any, ...], List[Dict[str, Any]]] = {}
    for result in results:
        params_items = tuple(sorted((result.get("params") or {}).items()))
        key = (
            result.get("strategy"),
            result.get("symbol"),
            result.get("tf"),
            result.get("period_start"),
            result.get("period_end"),
            params_items,
        )
        grouped.setdefault(key, []).append(dict(result))

    deduped: List[Dict[str, Any]] = []
    for duplicates in grouped.values():
        best = sort_results(duplicates)[0]
        best["duplicate_run_count"] = len(duplicates)
        best["duplicate_run_ids"] = [item.get("run_id") for item in duplicates]
        deduped.append(best)
    return sort_results(deduped)


def export_top_configs(
    results: Iterable[Dict[str, Any]],
    output_path: Path = Path("analysis_top_configs.csv"),
    *,
    top_n: int = 100,
) -> Path:
    rows: List[Dict[str, Any]] = []
    for rank, result in enumerate(sort_results(results)[:top_n], 1):
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

    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False, encoding="utf-8")
    return output_path


def refresh_analysis_artifacts(
    results_dir: Path = Path("backtest_results"),
    *,
    top_n: int = 100,
) -> Dict[str, Any]:
    raw_results = extract_all_results(results_dir)
    all_results = deduplicate_results(raw_results)
    filtered_results = deduplicate_results(filter_current_results(raw_results))

    csv_path = export_top_configs(filtered_results, top_n=top_n)
    generate_html_report(
        all_results,
        Path("analysis_report.html"),
        title="Backtest Analysis Report",
        top_n=top_n,
        filters_description="All available backtest runs",
        csv_path=csv_path,
    )
    generate_html_report(
        filtered_results,
        Path("analysis_report_filtered.html"),
        title="Backtest Analysis Report - Filtered",
        top_n=top_n,
        filters_description="return_pct > 0, account_ruined = False, trades >= 1",
        csv_path=csv_path,
    )

    return {
        "total_results": len(all_results),
        "raw_results": len(raw_results),
        "filtered_results": len(filtered_results),
        "top_n": top_n,
        "csv_path": str(csv_path),
        "html_path": str(Path("analysis_report.html")),
        "filtered_html_path": str(Path("analysis_report_filtered.html")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh analysis artifacts from backtest_results")
    parser.add_argument("--results-dir", default="backtest_results", help="Path to backtest results root")
    parser.add_argument("--top", type=int, default=100, help="Number of ranked configs to export/render")
    args = parser.parse_args()

    stats = refresh_analysis_artifacts(Path(args.results_dir), top_n=args.top)
    print(
        "Analysis refreshed: "
        f"total={stats['total_results']} "
        f"filtered={stats['filtered_results']} "
        f"top={stats['top_n']}"
    )
    print(f"CSV: {stats['csv_path']}")
    print(f"HTML: {stats['html_path']}")
    print(f"Filtered HTML: {stats['filtered_html_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
