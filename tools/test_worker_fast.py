"""Test intégration rapide: worker fast path end-to-end."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

# Créer données test
np.random.seed(42)
n = 2000
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

# Test 1: Worker init + fast path
from backtest.worker import init_worker_with_dataframe, run_backtest_worker

print("=== Test Worker Fast Path ===")
init_worker_with_dataframe(
    df_or_path=df,
    strategy_key="ema_cross",
    symbol="BTCUSDT",
    timeframe="1h",
    initial_capital=10000,
    debug_enabled=False,
    thread_limit=1,
    fast_metrics=True,
)

from backtest.worker import _worker_sweep_ready as ready
print(f"Sweep ready: {ready}")
assert ready, "prepare_sweep devrait reussir"

# Test 2: Execution rapide
result = run_backtest_worker({"fast_period": 10, "slow_period": 30})
print(f"Result keys: {sorted(result.keys())}")
print(f"total_pnl: {result.get('total_pnl', 'MISSING')}")
print(f"sharpe: {result.get('sharpe', 'MISSING')}")
print(f"trades: {result.get('trades', 'MISSING')}")
assert "error" not in result, f"Erreur: {result.get('error')}"
assert "total_pnl" in result, "total_pnl manquant"
assert "sharpe" in result, "sharpe manquant"
assert "trades" in result, "trades manquant"
assert "params_dict" in result, "params_dict manquant"

# Test 3: Plusieurs combos
for combo in [
    {"fast_period": 5, "slow_period": 20},
    {"fast_period": 15, "slow_period": 50},
    {"fast_period": 8, "slow_period": 25},
]:
    r = run_backtest_worker(combo)
    assert "error" not in r, f"Erreur pour {combo}: {r.get('error')}"

print("=== TOUS LES TESTS OK ===")
