"""Benchmark RÉEL: multi-process avec run_sweep_iteration vs legacy."""

import os
import sys
import time

sys.path.insert(0, r"D:\backtest_core")
os.environ["INDICATOR_CACHE_ENABLED"] = "1"
os.environ["BACKTEST_DATA_DIR"] = r"D:\my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet"

from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd

DATA_PATH = r"D:\my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet\BTCUSDC_1h.parquet"


def main():
    # Charger et préparer les données
    df = pd.read_parquet(DATA_PATH)
    print(f"Barres: {len(df)}, Colonnes: {list(df.columns)}")

    # S'assurer que l'index est un DatetimeIndex
    if "timestamp" in df.columns:
        df.index = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.drop(columns=["timestamp"], errors="ignore")

    print(f"Index: {df.index[0]} -> {df.index[-1]}")

    # Générer grid EMA cross
    combos = [{"fast_period": f, "slow_period": s} for f in range(5, 21) for s in range(20, 51) if f < s]
    print(f"Combos total: {len(combos)}")

    # ═══════════════════════════════════════════════════════════════════
    # BENCHMARK 1: Single-thread comparatif (legacy vs fast)
    # ═══════════════════════════════════════════════════════════════════
    from backtest.engine import BacktestEngine

    n_test = min(100, len(combos))
    test_combos = combos[:n_test]

    # Legacy
    engine = BacktestEngine(initial_capital=10000)
    t0 = time.perf_counter()
    for c in test_combos:
        engine.run(df, "ema_cross", c, silent_mode=True, fast_metrics=True)
    t_legacy = time.perf_counter() - t0
    print(f"\n[SINGLE-THREAD] LEGACY: {n_test} runs en {t_legacy:.2f}s = {n_test / t_legacy:.0f} runs/s")

    # Fast
    engine2 = BacktestEngine(initial_capital=10000)
    engine2.prepare_sweep(df, "ema_cross", "1h")
    t0 = time.perf_counter()
    for c in test_combos:
        engine2.run_sweep_iteration(c)
    t_fast = time.perf_counter() - t0
    print(f"[SINGLE-THREAD] FAST:   {n_test} runs en {t_fast:.2f}s = {n_test / t_fast:.0f} runs/s")
    print(f"[SINGLE-THREAD] SPEEDUP: {t_legacy / t_fast:.1f}x")

    # ═══════════════════════════════════════════════════════════════════
    # BENCHMARK 2: Multi-process complet avec worker fast path
    # ═══════════════════════════════════════════════════════════════════
    from backtest.worker import init_worker_with_dataframe, run_backtest_worker

    n_workers = min(24, os.cpu_count() or 8)
    n_mp_test = min(500, len(combos))
    mp_combos = combos[:n_mp_test]

    print(f"\n[MULTI-PROCESS] {n_workers} workers, {n_mp_test} combos...")
    t0 = time.perf_counter()
    results = []
    with ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=init_worker_with_dataframe,
        initargs=(df, "ema_cross", "BTCUSDC", "1h", 10000, False, 1, True),
    ) as pool:
        futures = {pool.submit(run_backtest_worker, c): c for c in mp_combos}
        for f in as_completed(futures):
            results.append(f.result())
    t_mp = time.perf_counter() - t0

    errors = sum(1 for r in results if "error" in r)
    print(f"[MULTI-PROCESS] {n_mp_test} runs en {t_mp:.2f}s = {n_mp_test / t_mp:.0f} runs/s ({errors} erreurs)")

    # Extrapolation
    if t_mp > 0:
        rate = n_mp_test / t_mp
        for target in [10_000, 100_000, 500_000, 1_000_000, 5_000_000]:
            est_time = target / rate
            mins = est_time / 60
            print(f"  -> {target:>10,} combos: ~{mins:.1f} min ({est_time:.0f}s)")

    # Best result
    valid = [r for r in results if "error" not in r]
    if valid:
        best = max(valid, key=lambda r: r.get("total_pnl", -1e9))
        print(
            f"\nMeilleur: PnL=${best['total_pnl']:.2f}, sharpe={best['sharpe']:.4f}, "
            f"trades={best['trades']}, params={best['params_dict']}",
        )


if __name__ == "__main__":
    main()
