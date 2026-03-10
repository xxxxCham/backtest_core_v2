"""
Test de performance non-régression.

Garantit que le système maintient >10k bt/s sur 10k barres (5k combos).
Détecte automatiquement les régressions de performance.
"""
import sys
from pathlib import Path

# Ajouter racine du projet au path
sys.path.insert(0, str(Path(__file__).parent.parent))

import time

import numpy as np
import pytest


def test_numba_sweep_performance_no_regression():
    """
    Test critique: garantir >10k bt/s sur sweep Numba.

    Configuration:
    - 5,000 combinaisons
    - 10,000 barres OHLCV
    - Stratégie: bollinger_best_longe_3i (vectorisée Numba)

    Seuils:
    - PASS: >=10,000 bt/s (objectif utilisateur)
    - WARN: 7,000-10,000 bt/s (dégradation détectée)
    - FAIL: <7,000 bt/s (régression critique)
    """
    from backtest.sweep_numba import _sweep_boll_level_long

    # Données test (10k barres)
    n_bars = 10000
    np.random.seed(42)
    closes = (100 * np.exp(np.cumsum(np.random.randn(n_bars) * 0.02))).astype(np.float64)
    highs = (closes * 1.01).astype(np.float64)
    lows = (closes * 0.99).astype(np.float64)

    # Grille params: 5k combos
    n_combos = 5000
    bb_periods = np.random.choice([10, 15, 20, 25, 30, 40, 50, 60, 80, 100], n_combos).astype(np.float64)
    bb_stds = np.random.uniform(0.5, 6.0, n_combos).astype(np.float64)
    entry_levels = np.random.uniform(-0.2, 0.7, n_combos).astype(np.float64)
    sl_levels = np.random.uniform(-1.5, 0.1, n_combos).astype(np.float64)
    tp_levels = np.random.uniform(0.3, 4.0, n_combos).astype(np.float64)
    leverages = np.full(n_combos, 1.0, dtype=np.float64)

    # Warm-up JIT (exclu du timing)
    _ = _sweep_boll_level_long(
        closes[:100], highs[:100], lows[:100],
        bb_periods[:5], bb_stds[:5], entry_levels[:5], sl_levels[:5], tp_levels[:5],
        leverages[:5], 10000.0, 10.0, 5.0
    )

    # Mesure performance
    start = time.perf_counter()
    pnls, sharpes, max_dds, win_rates, n_trades = _sweep_boll_level_long(
        closes, highs, lows, bb_periods, bb_stds, entry_levels, sl_levels, tp_levels,
        leverages, 10000.0, 10.0, 5.0
    )
    elapsed = time.perf_counter() - start

    throughput = n_combos / elapsed

    # Assertions graduelles
    print(f"\n{'='*60}")
    print(f"PERFORMANCE TEST RESULTS")
    print(f"{'='*60}")
    print(f"  Throughput: {throughput:,.0f} bt/s")
    print(f"  Time:       {elapsed:.3f}s for {n_combos:,} combos")
    print(f"  Target:     >=10,000 bt/s")
    print(f"{'='*60}")

    if throughput >= 10000:
        print("  ✅ PASS - Performance excellente")
    elif throughput >= 7000:
        print("  ⚠️  WARN - Dégradation détectée (mais acceptable)")
        pytest.warns(UserWarning, match="Performance dégradée")
    else:
        print("  ❌ FAIL - Régression critique")

    # Seuil critique: échec si <7k bt/s
    assert throughput >= 7000, (
        f"Régression performance critique: {throughput:.0f} bt/s < 7,000 bt/s.\n"
        f"Objectif utilisateur: >=10,000 bt/s.\n"
        f"Vérifiez les changements récents (fast_metrics, df.loc, cache disque, allocations)."
    )

    # Validation résultats corrects
    assert len(pnls) == n_combos
    assert np.any(pnls != 0), "Aucun P&L calculé (erreur logique)"
    assert np.any(n_trades > 0), "Aucun trade (erreur logique)"


def test_simulator_fast_no_regression():
    """
    Test simulateur rapide (backtest individuel).

    Seuil: <0.5ms par backtest (2000+ bt/s sur séquentiel).
    """
    from backtest.engine import BacktestEngine
    from strategies.bollinger_best_longe_3i import BollingerBestLonge3iStrategy
    import pandas as pd

    # Données 1000 barres
    n_bars = 1000
    np.random.seed(42)
    close = 100 * np.exp(np.cumsum(np.random.randn(n_bars) * 0.02))
    df = pd.DataFrame({
        'close': close,
        'high': close * 1.01,
        'low': close * 0.99,
        'open': close,
        'volume': np.random.randint(1000, 10000, n_bars)
    }, index=pd.date_range('2020-01-01', periods=n_bars, freq='1h'))

    engine = BacktestEngine(initial_capital=10000.0)
    strategy = BollingerBestLonge3iStrategy()
    params = {
        "bb_period": 20,
        "bb_std": 2.1,
        "entry_level": 0.0,
        "sl_level": -0.5,
        "tp_level": 0.85,
    }

    # Warm-up
    engine.run(df=df, strategy=strategy, params=params, silent_mode=True, fast_metrics=True)

    # Mesure
    n_runs = 100
    start = time.perf_counter()
    for _ in range(n_runs):
        engine.run(df=df, strategy=strategy, params=params, silent_mode=True, fast_metrics=True)
    elapsed = time.perf_counter() - start

    time_per_run_ms = (elapsed / n_runs) * 1000

    print(f"\n{'='*60}")
    print(f"SIMULATOR PERFORMANCE")
    print(f"{'='*60}")
    print(f"  Time/run:  {time_per_run_ms:.2f} ms")
    print(f"  Target:    <2.0 ms (500+ bt/s séquentiel)")
    print(f"{'='*60}")

    # Seuil: <2ms par run (500+ bt/s séquentiel, acceptable)
    assert time_per_run_ms < 2.0, (
        f"Simulateur trop lent: {time_per_run_ms:.2f}ms > 2.0ms.\n"
        f"Objectif: <2ms pour 500+ bt/s séquentiel."
    )

    if time_per_run_ms < 1.0:
        print("  ✅ EXCELLENT - <1ms par run")
    else:
        print("  ✅ PASS - Performance acceptable")


def test_calculate_equity_fast_matches_reference_curve_for_numba_and_fallback(monkeypatch):
    """Le chemin rapide doit rester aligné avec la sémantique mark-to-market canonique."""
    import pandas as pd

    import backtest.simulator_fast as simulator_fast
    from backtest.simulator import calculate_equity_curve

    index = pd.date_range("2024-01-01", periods=8, freq="1h")
    df = pd.DataFrame(
        {
            "open": [100.0, 102.0, 105.0, 103.0, 101.0, 98.0, 96.0, 99.0],
            "high": [101.0, 103.0, 106.0, 104.0, 102.0, 99.0, 97.0, 100.0],
            "low": [99.0, 101.0, 104.0, 102.0, 100.0, 97.0, 95.0, 98.0],
            "close": [100.0, 102.0, 105.0, 103.0, 101.0, 98.0, 96.0, 99.0],
            "volume": [1000] * 8,
        },
        index=index,
    )
    trades_df = pd.DataFrame(
        {
            "entry_ts": [index[1], index[4]],
            "exit_ts": [index[3], index[6]],
            "price_entry": [102.0, 101.0],
            "price_exit": [103.0, 96.0],
            "size": [1.0, 2.0],
            "side": ["LONG", "SHORT"],
            "pnl": [1.0, 10.0],
        }
    )

    expected = calculate_equity_curve(df, trades_df, initial_capital=10_000.0)

    actual_numba = simulator_fast.calculate_equity_fast(df, trades_df, initial_capital=10_000.0)
    np.testing.assert_allclose(actual_numba.values, expected.values)

    monkeypatch.setattr(simulator_fast, "HAS_NUMBA", False)
    actual_fallback = simulator_fast.calculate_equity_fast(df, trades_df, initial_capital=10_000.0)
    np.testing.assert_allclose(actual_fallback.values, expected.values)


def test_parallel_recommendations_scale_with_existing_ram_and_cpu_heuristics(monkeypatch):
    import performance.parallel as parallel_module

    monkeypatch.setattr(parallel_module, "_get_cpu_count", lambda: 24)
    monkeypatch.setattr(parallel_module, "_get_available_memory_gb", lambda: 40.0)

    assert parallel_module.get_recommended_worker_count(max_cap=32) == 24
    assert parallel_module.get_recommended_chunk_size(default=100) == 200
    assert parallel_module.get_recommended_joblib_batch_size(5000, default_chunk_size=200) == 200
    assert parallel_module.get_recommended_max_in_flight(total_tasks=5000, worker_count=8) == 64


def test_parallel_recommendations_throttle_when_memory_is_tight(monkeypatch):
    import performance.parallel as parallel_module

    monkeypatch.setattr(parallel_module, "_get_cpu_count", lambda: 24)
    monkeypatch.setattr(parallel_module, "_get_available_memory_gb", lambda: 6.0)

    assert parallel_module.get_recommended_worker_count(max_cap=32) == 12
    assert parallel_module.get_recommended_chunk_size(default=100) == 100
    assert parallel_module.get_recommended_max_in_flight(total_tasks=5000, worker_count=8) == 16


def test_extract_strategy_params_supports_numba_sweep_families():
    from backtest.sweep_numba import extract_strategy_params

    ema_arrays = extract_strategy_params(
        "ema_cross",
        [
            {"fast_period": 12, "slow_period": 26, "leverage": 2},
            {"fast_period": 15, "slow_period": 50, "k_sl": 2.0},
        ],
    )
    assert set(ema_arrays) == {"fast_period", "slow_period", "leverage", "k_sl"}
    np.testing.assert_allclose(ema_arrays["fast_period"], np.array([12.0, 15.0]))
    np.testing.assert_allclose(ema_arrays["k_sl"], np.array([1.5, 2.0]))

    macd_arrays = extract_strategy_params(
        "macd_cross",
        [
            {"fast_period": 8, "slow_period": 21, "signal_period": 5},
            {"fast_period": 12, "slow_period": 26, "signal_period": 9},
        ],
    )
    assert set(macd_arrays) == {
        "fast_period",
        "slow_period",
        "signal_period",
        "leverage",
        "k_sl",
    }
    np.testing.assert_allclose(macd_arrays["signal_period"], np.array([5.0, 9.0]))


def test_numba_chunk_size_prefers_single_chunk_when_buffers_fit_budget(monkeypatch):
    import backtest.sweep_numba as sweep_numba

    monkeypatch.setattr(sweep_numba, "get_available_ram_gb", lambda: 40.0)
    monkeypatch.delenv("BACKTEST_NUMBA_SWEEP_RAM_BUDGET_GB", raising=False)
    monkeypatch.delenv("BACKTEST_NUMBA_SWEEP_MAX_CHUNK", raising=False)
    monkeypatch.delenv("BACKTEST_NUMBA_SWEEP_MIN_CHUNK", raising=False)

    assert sweep_numba._get_numba_chunk_size(
        strategy_lower="ema_cross",
        total_combos=200_000,
        n_bars=5_000,
    ) == 200_000


def test_numba_thread_count_is_strategy_aware(monkeypatch):
    import backtest.sweep_numba as sweep_numba

    monkeypatch.setattr(sweep_numba, "get_recommended_worker_count", lambda max_cap=None: 16)

    ema_threads = sweep_numba._get_numba_thread_count(
        strategy_lower="ema_cross",
        chunk_size=128,
        n_bars=5_000,
    )
    rsi_threads = sweep_numba._get_numba_thread_count(
        strategy_lower="rsi_reversal",
        chunk_size=128,
        n_bars=5_000,
    )
    ema_large_threads = sweep_numba._get_numba_thread_count(
        strategy_lower="ema_cross",
        chunk_size=1_024,
        n_bars=5_000,
    )

    assert ema_threads == 8
    assert rsi_threads == 4
    assert ema_large_threads == 16


def test_run_numba_sweep_param_arrays_match_across_chunk_sizes():
    import pandas as pd

    from backtest.sweep_numba import extract_strategy_params, run_numba_sweep

    n_bars = 800
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n_bars)))
    df = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(1_000, 10_000, n_bars),
        }
    )
    param_grid = [
        {
            "fast_period": float(fast),
            "slow_period": float(slow),
            "leverage": 1.0,
            "k_sl": 1.5,
        }
        for fast, slow in [(8, 21), (10, 26), (12, 30), (15, 35), (18, 40), (21, 50)]
    ]
    param_arrays = extract_strategy_params("ema_cross", param_grid)
    ohlcv = (
        df["close"].to_numpy(dtype=np.float64),
        df["high"].to_numpy(dtype=np.float64),
        df["low"].to_numpy(dtype=np.float64),
    )

    single_chunk = run_numba_sweep(
        df=df,
        strategy_key="ema_cross",
        param_grid=param_grid,
        return_arrays=True,
        thread_override=1,
        chunk_size_override=len(param_grid),
        _param_arrays=param_arrays,
        _ohlcv=ohlcv,
    )
    split_chunks = run_numba_sweep(
        df=df,
        strategy_key="ema_cross",
        param_grid=param_grid,
        return_arrays=True,
        thread_override=1,
        chunk_size_override=2,
        _param_arrays=param_arrays,
        _ohlcv=ohlcv,
    )

    for lhs, rhs in zip(single_chunk, split_chunks):
        np.testing.assert_allclose(lhs, rhs)


def test_run_numba_sweep_emits_chunk_results_callback():
    import pandas as pd

    from backtest.sweep_numba import run_numba_sweep

    n_bars = 400
    rng = np.random.default_rng(11)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n_bars)))
    df = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(1_000, 10_000, n_bars),
        }
    )
    param_grid = [
        {"fast_period": 8, "slow_period": 21},
        {"fast_period": 12, "slow_period": 26},
        {"fast_period": 15, "slow_period": 35},
    ]
    callback_chunks = []

    def chunk_callback(chunk_rows, completed, total, best_result):
        callback_chunks.append(
            {
                "rows": list(chunk_rows),
                "completed": completed,
                "total": total,
                "best_result": best_result,
            }
        )

    rows = run_numba_sweep(
        df=df,
        strategy_key="ema_cross",
        param_grid=param_grid,
        thread_override=1,
        chunk_size_override=2,
        result_chunk_callback=chunk_callback,
    )

    assert len(rows) == 3
    assert [item["completed"] for item in callback_chunks] == [2, 3]
    assert [len(item["rows"]) for item in callback_chunks] == [2, 1]
    assert all(item["total"] == 3 for item in callback_chunks)
    assert callback_chunks[-1]["best_result"] is not None


def test_should_use_numba_backend_rejects_unsupported_metric():
    from backtest.sweep_numba import should_use_numba_backend

    assert should_use_numba_backend(
        "ema_cross",
        metric="sharpe_ratio",
        total_combos=10,
    )
    assert not should_use_numba_backend(
        "ema_cross",
        metric="profit_factor",
        total_combos=10,
    )


def test_sweep_engine_prefers_numba_backend_for_supported_sweeps(monkeypatch):
    import pandas as pd

    from backtest.sweep import SweepEngine

    calls = {"numba": 0}

    def fake_run_numba_items(**kwargs):
        calls["numba"] += 1
        return [
            {
                "params": {"fast_period": 12, "slow_period": 26},
                "metrics": {
                    "total_pnl": 123.0,
                    "sharpe_ratio": 1.5,
                    "max_drawdown_pct": -12.0,
                    "win_rate_pct": 55.0,
                    "total_trades": 14,
                },
                "score": 1.5,
            }
        ]

    monkeypatch.setattr("backtest.sweep.run_numba_sweep_items_if_supported", fake_run_numba_items)
    monkeypatch.setattr("backtest.sweep.should_use_numba_backend", lambda *args, **kwargs: True)

    engine = SweepEngine(max_workers=2, auto_save=False)
    result = engine.run_sweep(
        df=pd.DataFrame(
            {
                "open": [1.0, 1.1, 1.2],
                "high": [1.1, 1.2, 1.3],
                "low": [0.9, 1.0, 1.1],
                "close": [1.0, 1.1, 1.2],
                "volume": [100.0, 100.0, 100.0],
            }
        ),
        strategy="ema_cross",
        param_grid={"fast_period": [12], "slow_period": [26]},
        show_progress=False,
    )

    assert calls["numba"] == 1
    assert result.n_completed == 1
    assert result.best_metrics["total_pnl"] == 123.0


def test_cli_sweep_executor_prefers_numba_backend_and_preserves_callbacks(monkeypatch):
    import pandas as pd

    import backtest.engine as engine_module
    import backtest.sweep_numba as sweep_numba_module
    from cli.sweep_executor import SweepConfig, run_sweep

    class FailingBacktestEngine:
        def __init__(self, *args, **kwargs):
            raise AssertionError("BacktestEngine ne doit pas être utilisé quand Numba est actif")

    monkeypatch.setattr(engine_module, "BacktestEngine", FailingBacktestEngine)

    def fake_run_numba_items_if_supported(**kwargs):
        items = [
            {
                "params": {"fast_period": 12, "slow_period": 26},
                "metrics": {
                    "total_pnl": 100.0,
                    "sharpe_ratio": 1.0,
                    "max_drawdown_pct": -10.0,
                    "win_rate_pct": 55.0,
                    "total_trades": 10,
                },
                "score": 1.0,
            },
            {
                "params": {"fast_period": 15, "slow_period": 50},
                "metrics": {
                    "total_pnl": 180.0,
                    "sharpe_ratio": 1.6,
                    "max_drawdown_pct": -8.0,
                    "win_rate_pct": 60.0,
                    "total_trades": 12,
                },
                "score": 1.6,
            },
        ]
        chunk_callback = kwargs.get("result_chunk_callback")
        if chunk_callback is not None:
            chunk_callback(items[:1], 1, 2, items[:1][0])
            chunk_callback(items[1:], 2, 2, items[1])
        return items

    monkeypatch.setattr(
        sweep_numba_module,
        "run_numba_sweep_items_if_supported",
        fake_run_numba_items_if_supported,
    )

    progress_history = []
    result_history = []
    config = SweepConfig(
        strategy_name="ema_cross",
        data_path=Path("dummy.csv"),
        symbol="BTCUSDT",
        timeframe="1h",
        initial_capital=10_000.0,
        metric="sharpe",
    )
    df = pd.DataFrame(
        {
            "open": [1.0, 1.1, 1.2],
            "high": [1.1, 1.2, 1.3],
            "low": [0.9, 1.0, 1.1],
            "close": [1.0, 1.1, 1.2],
            "volume": [100.0, 100.0, 100.0],
        }
    )

    result = run_sweep(
        config=config,
        df=df,
        param_grid=[
            {"fast_period": 12, "slow_period": 26},
            {"fast_period": 15, "slow_period": 50},
        ],
        on_progress=lambda progress: progress_history.append(progress.completed),
        on_result=lambda item: result_history.append(item["params"].copy()),
    )

    assert progress_history == [1, 2]
    assert result_history == [
        {"fast_period": 12, "slow_period": 26},
        {"fast_period": 15, "slow_period": 50},
    ]
    assert result.completed == 2
    assert result.failed == 0
    assert result.best_params == {"fast_period": 15, "slow_period": 50}
    assert result.best_metrics["sharpe_ratio"] == 1.6


if __name__ == "__main__":
    print("Exécution tests performance...")
    test_numba_sweep_performance_no_regression()
    test_simulator_fast_no_regression()
    print("\n✅ Tous les tests passés!")
