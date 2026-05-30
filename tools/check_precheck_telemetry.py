"""Verifie la presence de la telemetrie precheck (precheck_truncated, ...)
dans les session_summary.json recents.

Utile pour confirmer que ma modif a bien ete prise en compte apres un
redemarrage de Streamlit. Si "with_truncation_telemetry" == 0 sur des sessions
recentes, c'est que le module tourne avec l'ancien code en memoire.

Usage:
    python tools/check_precheck_telemetry.py [--since 2026-05-25T19:54]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backtest.result_store import get_builder_sessions_dir  # noqa: E402


NEW_PRECHECK_KEYS = {"precheck_truncated", "precheck_max_bars", "full_dataset_bars"}


def parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="ISO datetime (ex: 2026-05-25T19:54). Defaults: scan all.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Override builder sessions directory.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Max sessions to display in detail (default 25).",
    )
    args = parser.parse_args()

    root = args.root or get_builder_sessions_dir()
    cutoff = parse_since(args.since)

    rows: list[dict] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        try:
            ts = datetime.strptime(d.name[:15], "%Y%m%d_%H%M%S")
        except ValueError:
            continue
        if cutoff and ts < cutoff:
            continue
        summary = d / "session_summary.json"
        if not summary.exists() or summary.stat().st_size == 0:
            continue
        try:
            data = json.loads(summary.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        iters = data.get("iterations") or []
        new_telemetry_iters = 0
        no_trade_iters = 0
        truncated_iters = 0
        max_bars_seen = 0
        for it in iters:
            pf = (it.get("phase_feedback") or {}).get("precheck") or {}
            if NEW_PRECHECK_KEYS & set(pf.keys()):
                new_telemetry_iters += 1
                if pf.get("precheck_truncated"):
                    truncated_iters += 1
                if pf.get("precheck_max_bars"):
                    max_bars_seen = max(max_bars_seen, int(pf.get("precheck_max_bars") or 0))
            if pf.get("no_trade_signal_profile"):
                no_trade_iters += 1
            # Also check via metrics-side propagation
            metrics = (
                it.get("backtest_result", {}).get("metrics")
                if isinstance(it.get("backtest_result"), dict)
                else {}
            )
            if isinstance(metrics, dict) and "precheck_truncated" in metrics:
                new_telemetry_iters = max(new_telemetry_iters, 1)

        rows.append(
            {
                "started": ts,
                "name": d.name,
                "n_iter": len(iters),
                "new_telemetry_iters": new_telemetry_iters,
                "truncated_iters": truncated_iters,
                "no_trade_iters": no_trade_iters,
                "max_bars_seen": max_bars_seen,
            },
        )

    rows.sort(key=lambda r: r["started"], reverse=True)

    if not rows:
        print(f"Aucune session trouvee dans {root}")
        return 1

    total = len(rows)
    with_new = sum(1 for r in rows if r["new_telemetry_iters"] > 0)
    with_truncated = sum(1 for r in rows if r["truncated_iters"] > 0)
    with_no_trade = sum(1 for r in rows if r["no_trade_iters"] > 0)

    print(f"Scan: {root}")
    if cutoff:
        print(f"Filter: started >= {cutoff.isoformat()}")
    print()
    print(f"Total sessions analysees     : {total}")
    print(f"Sessions avec NEW telemetrie : {with_new} ({100*with_new/total:.0f}%)")
    print(f"Sessions avec truncation     : {with_truncated} ({100*with_truncated/total:.0f}%)")
    print(f"Sessions avec no_trade skip  : {with_no_trade} ({100*with_no_trade/total:.0f}%)")
    print()
    print(f"{'Started':<19} {'Iter':>4} {'New':>4} {'Trun':>5} {'NoTr':>5} {'MaxBars':>8}  Name")
    print("-" * 95)
    for r in rows[: args.limit]:
        print(
            f"{r['started'].strftime('%Y-%m-%d %H:%M:%S'):<19} "
            f"{r['n_iter']:>4} "
            f"{r['new_telemetry_iters']:>4} "
            f"{r['truncated_iters']:>5} "
            f"{r['no_trade_iters']:>5} "
            f"{r['max_bars_seen']:>8}  "
            f"{r['name'][:40]}",
        )

    if with_new == 0:
        print()
        print("DIAGNOSTIC: aucune session ne contient la nouvelle telemetrie.")
        print("Cause probable: Streamlit utilise une copie du module chargee avant")
        print("la modification. Redemarrer Streamlit pour activer le levier 1.")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
