"""Test intégration rapide: worker fast path end-to-end."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backtest.worker as worker


def _build_dataframe(n: int = 2000) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 30000 + np.cumsum(rng.normal(0, 50, n))
    return pd.DataFrame(
        {
            "open": close + rng.normal(0, 10, n),
            "high": close + np.abs(rng.normal(0, 30, n)),
            "low": close - np.abs(rng.normal(0, 30, n)),
            "close": close,
            "volume": rng.integers(100, 10000, n).astype(float),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="h"),
    )


def main() -> int:
    print("=== Test Worker Fast Path ===")
    worker.init_worker_with_dataframe(
        df_or_path=_build_dataframe(),
        strategy_key="ema_cross",
        symbol="BTCUSDT",
        timeframe="1h",
        initial_capital=10000,
        debug_enabled=False,
        thread_limit=1,
        fast_metrics=True,
    )
    print(f"Sweep ready: {worker._worker_sweep_ready}")
    assert worker._worker_sweep_ready, "prepare_sweep devrait reussir"

    combos = [
        {"fast_period": 10, "slow_period": 30},
        {"fast_period": 5, "slow_period": 20},
        {"fast_period": 15, "slow_period": 50},
        {"fast_period": 8, "slow_period": 25},
    ]
    result = worker.run_backtest_worker(combos[0])
    print(f"Result keys: {sorted(result.keys())}")
    print(f"total_pnl: {result.get('total_pnl', 'MISSING')}")
    print(f"sharpe: {result.get('sharpe', 'MISSING')}")
    print(f"trades: {result.get('trades', 'MISSING')}")
    assert "error" not in result, f"Erreur: {result.get('error')}"
    assert {"params_dict", "sharpe", "total_pnl", "trades"}.issubset(result)

    for combo in combos[1:]:
        current = worker.run_backtest_worker(combo)
        assert "error" not in current, f"Erreur pour {combo}: {current.get('error')}"

    print("=== TOUS LES TESTS OK ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
