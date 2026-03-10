"""
Script de profiling simple et direct pour identifier la régression 450→60 bt/s
"""

import cProfile
import pstats
import time
from io import StringIO

import pandas as pd

from backtest.engine import BacktestEngine
from strategies import get_strategy
from utils.config import Config

# Charger données
print("=" * 80)
print("🔍 ANALYSE PERFORMANCE SIMPLE")
print("=" * 80)

data_path = r"D:\my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet\BTCUSDC_30m.parquet"
df = pd.read_parquet(data_path)
df.index = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
df = df.head(1000)  # 1000 barres

print(f"\nDonnées: {len(df)} barres")
print(f"Période: {df.index[0]} → {df.index[-1]}")

# Config
config = Config()
config.initial_capital = 10000.0
config.fees_bps = 10
config.slippage_bps = 5

# Stratégie
strategy_class = get_strategy("ema_cross")
strategy = strategy_class()  # Instancier la stratégie

# Test 1: WARMUP NUMBA
print("\n" + "=" * 80)
print("TEST 1: WARMUP NUMBA")
print("=" * 80)

engine = BacktestEngine(config=config)
start = time.perf_counter()
result = engine.run(
    df=df,
    strategy=strategy,
    params={"fast_period": 10, "slow_period": 21},
    silent_mode=True,
    fast_metrics=False
)
warmup_time = time.perf_counter() - start
print(f"Temps warmup: {warmup_time:.3f}s")

# Test 2: PERFORMANCE PURE (après warmup)
print("\n" + "=" * 80)
print("TEST 2: PERFORMANCE PURE (10 backtests)")
print("=" * 80)

n_tests = 10
start = time.perf_counter()
for i in range(n_tests):
    result = engine.run(
        df=df,
        strategy=strategy,
        params={"fast_period": 10 + i, "slow_period": 21 + i},
        silent_mode=True,
        fast_metrics=True  # ACTIVÉ pour test
    )
elapsed = time.perf_counter() - start

bt_per_sec = n_tests / elapsed
bars_per_sec = (n_tests * len(df)) / elapsed

print("\n📊 RÉSULTATS:")
print(f"   Temps total: {elapsed:.2f}s")
print(f"   Temps moyen/backtest: {elapsed/n_tests*1000:.1f}ms")
print(f"   Backtests/sec: {bt_per_sec:.1f}")
print(f"   Barres/sec: {bars_per_sec:.0f}")

# Comparer avec objectif
target_bt_per_sec = 450
degradation_pct = ((target_bt_per_sec - bt_per_sec) / target_bt_per_sec) * 100

print(f"\n🎯 OBJECTIF: {target_bt_per_sec} bt/s")
if bt_per_sec < target_bt_per_sec:
    print(f"❌ DÉGRADATION: -{degradation_pct:.1f}%")
else:
    print("✅ OBJECTIF ATTEINT!")

# Test 3: PROFILING DÉTAILLÉ
print("\n" + "=" * 80)
print("TEST 3: PROFILING DÉTAILLÉ")
print("=" * 80)

profiler = cProfile.Profile()
profiler.enable()

for i in range(10):
    result = engine.run(
        df=df,
        strategy=strategy,
        params={"fast_period": 10 + i, "slow_period": 21 + i},
        silent_mode=True,
        fast_metrics=False
    )

profiler.disable()

# Analyse
s = StringIO()
ps = pstats.Stats(profiler, stream=s)
ps.strip_dirs()
ps.sort_stats('cumulative')
ps.print_stats(30)

print(s.getvalue())

# Test 4: FAST METRICS vs FULL METRICS
print("\n" + "=" * 80)
print("TEST 4: FAST METRICS vs FULL METRICS")
print("=" * 80)

# Full metrics
start = time.perf_counter()
for i in range(10):
    result = engine.run(
        df=df,
        strategy=strategy,
        params={"fast_period": 10 + i, "slow_period": 21 + i},
        silent_mode=True,
        fast_metrics=False
    )
elapsed_full = time.perf_counter() - start

# Fast metrics
start = time.perf_counter()
for i in range(10):
    result = engine.run(
        df=df,
        strategy=strategy,
        params={"fast_period": 10 + i, "slow_period": 21 + i},
        silent_mode=True,
        fast_metrics=True
    )
elapsed_fast = time.perf_counter() - start

print(f"Full metrics: {10/elapsed_full:.1f} bt/s")
print(f"Fast metrics: {10/elapsed_fast:.1f} bt/s")
print(f"Speedup: {elapsed_full/elapsed_fast:.1f}x")

# Test 5: BREAKDOWN PAR COMPOSANT
print("\n" + "=" * 80)
print("TEST 5: BREAKDOWN PAR COMPOSANT")
print("=" * 80)

# Test indicateurs seuls
print("\n📊 Test INDICATEURS...")
from indicators.registry import calculate_indicator

start = time.perf_counter()
for _ in range(10):
    ema_fast = calculate_indicator("ema", df, period=10)
    ema_slow = calculate_indicator("ema", df, period=21)
elapsed_indicators = time.perf_counter() - start
print(f"   Temps: {elapsed_indicators:.3f}s ({10/elapsed_indicators:.0f} runs/s)")

# Test stratégie seule (signals)
print("\n📊 Test STRATÉGIE (signals)...")
ema_fast = calculate_indicator("ema", df, period=10)
ema_slow = calculate_indicator("ema", df, period=21)
indicators = {"ema": {"fast": ema_fast, "slow": ema_slow}}

start = time.perf_counter()
for _ in range(10):
    signals = strategy.generate_signals(df, indicators, {"fast_period": 10, "slow_period": 21})
elapsed_signals = time.perf_counter() - start
print(f"   Temps: {elapsed_signals:.3f}s ({10/elapsed_signals:.0f} runs/s)")

# Test simulateur seul
print("\n📊 Test SIMULATEUR...")
from backtest.simulator_fast import simulate_trades_fast

signals = strategy.generate_signals(df, indicators, {"fast_period": 10, "slow_period": 21})

start = time.perf_counter()
for _ in range(10):
    trades_df = simulate_trades_fast(
        df=df,
        signals=signals,
        initial_capital=10000.0,
        strategy=strategy,
        params={"fast_period": 10, "slow_period": 21}
    )
elapsed_simulator = time.perf_counter() - start
print(f"   Temps: {elapsed_simulator:.3f}s ({10/elapsed_simulator:.0f} runs/s)")

# Test métriques seules
print("\n📊 Test MÉTRIQUES...")
from backtest.performance import calculate_metrics

trades_df = simulate_trades_fast(
    df=df,
    signals=signals,
    initial_capital=10000.0,
    strategy=strategy,
    params={"fast_period": 10, "slow_period": 21}
)

start = time.perf_counter()
for _ in range(10):
    metrics = calculate_metrics(
        trades_df=trades_df,
        df=df,
        initial_capital=10000.0,
        fast_metrics=False
    )
elapsed_metrics = time.perf_counter() - start
print(f"   Temps: {elapsed_metrics:.3f}s ({10/elapsed_metrics:.0f} runs/s)")

# Résumé du breakdown
print("\n" + "=" * 80)
print("RÉSUMÉ BREAKDOWN:")
print("=" * 80)
total_components = elapsed_indicators + elapsed_signals + elapsed_simulator + elapsed_metrics
print(f"Indicateurs:  {elapsed_indicators:.3f}s ({elapsed_indicators/total_components*100:.1f}%)")
print(f"Stratégie:    {elapsed_signals:.3f}s ({elapsed_signals/total_components*100:.1f}%)")
print(f"Simulateur:   {elapsed_simulator:.3f}s ({elapsed_simulator/total_components*100:.1f}%)")
print(f"Métriques:    {elapsed_metrics:.3f}s ({elapsed_metrics/total_components*100:.1f}%)")
print(f"Total:        {total_components:.3f}s")
print(f"Overhead:     {(elapsed_full - total_components)/elapsed_full*100:.1f}%")

print("\n" + "=" * 80)
print("✅ PROFILING TERMINÉ")
print("=" * 80)
