"""Benchmark: legacy engine.run() vs run_sweep_iteration()."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _build_synthetic_ohlcv(n: int = 4000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 30000 + np.cumsum(rng.normal(0, 50, n))
    high = close + np.abs(rng.normal(0, 30, n))
    low = close - np.abs(rng.normal(0, 30, n))
    opn = close + rng.normal(0, 10, n)
    vol = rng.integers(100, 10000, n).astype(float)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {"open": opn, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def main() -> int:
    os.environ["INDICATOR_CACHE_ENABLED"] = "1"
    sys.path.insert(0, str(ROOT))

    from backtest.engine import BacktestEngine

    df = _build_synthetic_ohlcv()
    print(f"Barres: {len(df)}")

    combos = [{"fast_period": f, "slow_period": s} for f in range(5, 21) for s in range(20, 51)]
    n_combos = min(300, len(combos))
    combos_test = combos[:n_combos]
    print(f"Combos a tester: {n_combos}")

    engine = BacktestEngine(initial_capital=10000)
    t0 = time.perf_counter()
    last_legacy_result = None
    for combo in combos_test:
        last_legacy_result = engine.run(df, "ema_cross", combo, silent_mode=True, fast_metrics=True)
    legacy_time = time.perf_counter() - t0
    print(f"LEGACY: {n_combos} runs en {legacy_time:.3f}s = {n_combos / legacy_time:.0f} runs/s")

    engine_fast = BacktestEngine(initial_capital=10000)
    engine_fast.prepare_sweep(df, "ema_cross", "1h")

    t0 = time.perf_counter()
    last_fast_result = None
    for combo in combos_test:
        last_fast_result = engine_fast.run_sweep_iteration(combo)
    fast_time = time.perf_counter() - t0
    print(f"FAST:   {n_combos} runs en {fast_time:.3f}s = {n_combos / fast_time:.0f} runs/s")
    print(f"SPEEDUP: {legacy_time / fast_time:.1f}x")

    hits = engine_fast._indicator_cache_hits
    misses = engine_fast._indicator_cache_misses
    total = hits + misses
    print(
        f"Cache indicateurs: {hits} hits / {misses} misses ({100 * hits / total:.0f}% hit rate)"
        if total
        else "No cache data",
    )

    final_result = last_fast_result or last_legacy_result or {}
    pnl = final_result.get("total_pnl", 0)
    sharpe = final_result.get("sharpe_ratio", 0)
    trades = final_result.get("total_trades", 0)
    print(f"Dernier resultat: total_pnl={pnl:.2f}, sharpe={sharpe:.4f}, trades={trades}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
