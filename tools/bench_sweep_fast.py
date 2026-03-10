"""Benchmark: legacy engine.run() vs run_sweep_iteration()"""
import time
import os
import sys

os.environ["INDICATOR_CACHE_ENABLED"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from backtest.engine import BacktestEngine

# Générer données synthétiques OHLCV (4000 barres ~ 6 mois en 1h)
np.random.seed(42)
n = 4000
close = 30000 + np.cumsum(np.random.randn(n) * 50)
high = close + np.abs(np.random.randn(n) * 30)
low = close - np.abs(np.random.randn(n) * 30)
opn = close + np.random.randn(n) * 10
vol = np.random.randint(100, 10000, n).astype(float)

idx = pd.date_range("2024-01-01", periods=n, freq="h")
df = pd.DataFrame(
    {"open": opn, "high": high, "low": low, "close": close, "volume": vol},
    index=idx,
)
print(f"Barres: {len(df)}")

combos = [
    {"fast_period": f, "slow_period": s}
    for f in range(5, 21)
    for s in range(20, 51)
]
n_combos = min(300, len(combos))
combos_test = combos[:n_combos]
print(f"Combos a tester: {n_combos}")

# === BENCHMARK LEGACY ===
engine = BacktestEngine(initial_capital=10000)
t0 = time.perf_counter()
for c in combos_test:
    r = engine.run(df, "ema_cross", c, silent_mode=True, fast_metrics=True)
t1 = time.perf_counter()
legacy_time = t1 - t0
print(f"LEGACY: {n_combos} runs en {legacy_time:.3f}s = {n_combos / legacy_time:.0f} runs/s")

# === BENCHMARK FAST ===
engine2 = BacktestEngine(initial_capital=10000)
engine2.prepare_sweep(df, "ema_cross", "1h")

t0 = time.perf_counter()
for c in combos_test:
    r = engine2.run_sweep_iteration(c)
t1 = time.perf_counter()
fast_time = t1 - t0
print(f"FAST:   {n_combos} runs en {fast_time:.3f}s = {n_combos / fast_time:.0f} runs/s")
print(f"SPEEDUP: {legacy_time / fast_time:.1f}x")
hits = engine2._indicator_cache_hits
misses = engine2._indicator_cache_misses
total = hits + misses
print(f"Cache indicateurs: {hits} hits / {misses} misses ({100*hits/total:.0f}% hit rate)" if total else "No cache data")
pnl = r.get("total_pnl", 0)
sharpe = r.get("sharpe_ratio", 0)
trades = r.get("total_trades", 0)
print(f"Dernier resultat: total_pnl={pnl:.2f}, sharpe={sharpe:.4f}, trades={trades}")
