"""
Test ultra-ciblé pour identifier le bottleneck restant (360→450 bt/s)
"""

import time

import pandas as pd

from backtest.engine import BacktestEngine
from strategies import get_strategy
from utils.config import Config

# Données
data_path = r"D:\my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet\BTCUSDC_30m.parquet"
df = pd.read_parquet(data_path)
df.index = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
df = df.head(1000)

# Config
config = Config()
config.initial_capital = 10000.0
strategy_class = get_strategy("ema_cross")
strategy = strategy_class()
engine = BacktestEngine(config=config)

# WARMUP
engine.run(df=df, strategy=strategy, params={"fast_period": 10, "slow_period": 21}, silent_mode=True, fast_metrics=True)

print("=" * 80)
print("🎯 BENCHMARK: Recherche du bottleneck 360→450 bt/s")
print("=" * 80)

# Test 1: Performance brute (baseline)
print("\n1️⃣ BASELINE (fast_metrics=True)")
start = time.perf_counter()
for i in range(100):
    engine.run(df=df, strategy=strategy, params={"fast_period": 10+i%10, "slow_period": 21+i%10}, silent_mode=True, fast_metrics=True)
elapsed_fast = time.perf_counter() - start
print(f"   {100/elapsed_fast:.1f} bt/s")

# Test 2: Sans fast_metrics (pour mesurer le gain)
print("\n2️⃣ SANS FAST_METRICS (daily_resample)")
start = time.perf_counter()
for i in range(100):
    engine.run(df=df, strategy=strategy, params={"fast_period": 10+i%10, "slow_period": 21+i%10}, silent_mode=True, fast_metrics=False)
elapsed_slow = time.perf_counter() - start
print(f"   {100/elapsed_slow:.1f} bt/s")
print(f"   Speedup fast_metrics: {elapsed_slow/elapsed_fast:.1f}x")

# Test 3: Taille dataset impact
print("\n3️⃣ IMPACT TAILLE DATASET")
for n_bars in [250, 500, 1000, 2000]:
    df_test = df.head(n_bars)
    start = time.perf_counter()
    for i in range(50):
        engine.run(df=df_test, strategy=strategy, params={"fast_period": 10+i%10, "slow_period": 21+i%10}, silent_mode=True, fast_metrics=True)
    elapsed = time.perf_counter() - start
    print(f"   {n_bars:4d} barres: {50/elapsed:6.1f} bt/s (temps/bt: {elapsed/50*1000:.1f}ms)")

# Test 4: Params variations impact
print("\n4️⃣ VARIATION PARAMÈTRES vs FIXES")
start = time.perf_counter()
for i in range(100):
    engine.run(df=df, strategy=strategy, params={"fast_period": 10, "slow_period": 21}, silent_mode=True, fast_metrics=True)
elapsed_fixed = time.perf_counter() - start

start = time.perf_counter()
for i in range(100):
    engine.run(df=df, strategy=strategy, params={"fast_period": 10+i%10, "slow_period": 21+i%10}, silent_mode=True, fast_metrics=True)
elapsed_varied = time.perf_counter() - start

print(f"   Params fixes:   {100/elapsed_fixed:.1f} bt/s")
print(f"   Params variés:  {100/elapsed_varied:.1f} bt/s")
print(f"   Overhead:       {(elapsed_varied/elapsed_fixed-1)*100:.1f}%")

# Test 5: Stratégies simples vs complexes
print("\n5️⃣ COMPARAISON STRATÉGIES")

strategies_to_test = [
    ("ema_cross", {"fast_period": 10, "slow_period": 21}),
    ("rsi_reversal", {"rsi_period": 14, "oversold": 30, "overbought": 70}),
]

for strat_name, params in strategies_to_test:
    try:
        strat_class = get_strategy(strat_name)
        strat = strat_class()
        engine_test = BacktestEngine(config=config)
        # Warmup
        engine_test.run(df=df, strategy=strat, params=params, silent_mode=True, fast_metrics=True)
        # Test
        start = time.perf_counter()
        for _ in range(50):
            engine_test.run(df=df, strategy=strat, params=params, silent_mode=True, fast_metrics=True)
        elapsed = time.perf_counter() - start
        print(f"   {strat_name:20s}: {50/elapsed:6.1f} bt/s")
    except Exception as e:
        print(f"   {strat_name:20s}: ERREUR ({e})")

# Test 6: Mesure overhead engine vs simulation pure
print("\n6️⃣ OVERHEAD BACKTEST ENGINE")
from backtest.simulator_fast import simulate_trades_fast
from indicators.registry import calculate_indicator

# Pré-calculer indicateurs
ema_fast = calculate_indicator("ema", df, {"period": 10})
ema_slow = calculate_indicator("ema", df, {"period": 21})
indicators = {"ema": {"fast": ema_fast, "slow": ema_slow}}
signals = strategy.generate_signals(df, indicators, {"fast_period": 10, "slow_period": 21})

# Test simulation pure
start = time.perf_counter()
for _ in range(100):
    trades_df = simulate_trades_fast(
        df=df,
        signals=signals,
        initial_capital=10000.0,
        strategy=strategy,
        params={"fast_period": 10, "slow_period": 21}
    )
elapsed_sim = time.perf_counter() - start
print(f"   Simulation seule:     {100/elapsed_sim:6.1f} ops/s")
print(f"   Backtest complet:     {100/elapsed_fast:6.1f} bt/s")
print(f"   Overhead engine:      {(elapsed_fast/elapsed_sim-1)*100:.1f}%")

print("\n" + "=" * 80)
print("📊 CONCLUSION")
print("=" * 80)
print(f"Performance actuelle:  {100/elapsed_fast:.1f} bt/s")
print("Objectif:             450 bt/s")
print(f"Gap restant:          {450 - 100/elapsed_fast:.1f} bt/s ({(450/(100/elapsed_fast)-1)*100:.1f}%)")
