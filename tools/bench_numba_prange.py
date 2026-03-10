"""
Benchmark Numba prange vs ProcessPool vs Single-thread Python
sur données RÉELLES BTCUSDC_1h (62 448 barres).

Objectif : Répondre à "est-ce que prange est pertinent ?"
en comparant les 3 approches sur le même dataset.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

# ── Charger les données réelles ──────────────────────────────────────────
DATA_PATH = r"D:\my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet\BTCUSDC_1h.parquet"

print("=" * 72)
print("BENCHMARK : Numba prange vs ProcessPool vs Single-thread Python")
print("=" * 72)

df = pd.read_parquet(DATA_PATH)
print(f"\n📊 Dataset : {DATA_PATH}")
print(f"   Barres  : {len(df):,}")
print(f"   Colonnes: {list(df.columns)}")
print(f"   Période : {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")

# ── Générer une grille EMA Cross réaliste ────────────────────────────────
param_grid = []
for fast in range(5, 25):          # 20 valeurs
    for slow in range(20, 60):     # 40 valeurs
        if slow > fast + 3:
            for lev in [1, 2, 3]:  # 3 valeurs
                param_grid.append({
                    'fast_period': fast,
                    'slow_period': slow,
                    'leverage': lev,
                    'k_sl': 1.5,
                })

total_combos = len(param_grid)
print(f"\n🎯 Grille EMA Cross : {total_combos:,} combinaisons")
print(f"   fast_period : 5-24  (20 valeurs)")
print(f"   slow_period : 20-59 (40 valeurs, filtre slow > fast+3)")
print(f"   leverage    : 1-3   (3 valeurs)")

# ══════════════════════════════════════════════════════════════════════════
# TEST 1 : Single-thread Python (run_sweep_iteration)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 72)
print("TEST 1 : Single-thread Python (run_sweep_iteration)")
print("─" * 72)

from backtest.engine import BacktestEngine

engine = BacktestEngine()
engine.prepare_sweep(df, "ema_cross", "1h")

N_PYTHON = min(200, total_combos)
subset = param_grid[:N_PYTHON]

t0 = time.perf_counter()
for p in subset:
    engine.run_sweep_iteration(p)
t1 = time.perf_counter()

python_speed = N_PYTHON / (t1 - t0)
python_extrap = total_combos / python_speed
print(f"   ✅ {N_PYTHON} runs en {t1-t0:.2f}s = {python_speed:.0f} runs/s")
print(f"   📈 Extrapolation {total_combos:,} combos : {python_extrap:.0f}s ({python_extrap/60:.1f} min)")

# ══════════════════════════════════════════════════════════════════════════
# TEST 2 : Numba prange (sweep_numba.py)
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 72)
print("TEST 2 : Numba prange (sweep_numba.py)")
print("─" * 72)

try:
    from backtest.sweep_numba import run_numba_sweep

    # Warmup JIT (première compilation)
    print("   ⏳ Compilation JIT (1ère exécution, ~2-5s)...")
    warmup_grid = param_grid[:10]
    t_jit_start = time.perf_counter()
    run_numba_sweep(df, "ema_cross", warmup_grid, 10000, 10, 5)
    t_jit = time.perf_counter() - t_jit_start
    print(f"   ✅ JIT compilé en {t_jit:.2f}s")

    # Benchmark vrai sur TOUTE la grille
    print(f"\n   🚀 Lancement sur {total_combos:,} combos...")
    t0 = time.perf_counter()
    results = run_numba_sweep(df, "ema_cross", param_grid, 10000, 10, 5)
    t1 = time.perf_counter()

    numba_time = t1 - t0
    numba_speed = total_combos / numba_time
    print(f"\n   ✅ {total_combos:,} runs en {numba_time:.2f}s = {numba_speed:,.0f} runs/s")

    # Vérifier résultats
    pnls = [r['total_pnl'] for r in results]
    best_idx = np.argmax(pnls)
    best = results[best_idx]
    print(f"   🏆 Meilleur PnL : ${best['total_pnl']:,.2f} | Sharpe: {best['sharpe_ratio']:.2f}")
    print(f"      Params: {best['params']}")
    print(f"      Trades: {best['total_trades']} | Win Rate: {best['win_rate']:.1f}% | MaxDD: {best['max_drawdown']:.1f}%")

except ImportError as e:
    print(f"   ❌ Numba non disponible : {e}")
    numba_speed = 0
except Exception as e:
    print(f"   ❌ Erreur : {e}")
    import traceback; traceback.print_exc()
    numba_speed = 0

# ══════════════════════════════════════════════════════════════════════════
# TEST 3 : Numba prange - Bollinger ATR
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 72)
print("TEST 3 : Numba prange - Bollinger ATR")
print("─" * 72)

bollinger_grid = []
for bb_p in range(10, 50, 2):        # 20 valeurs
    for bb_s in np.arange(1.0, 4.0, 0.25):  # 12 valeurs
        for entry_z in np.arange(0.5, 3.5, 0.5):  # 6 valeurs
            for lev in [1, 2, 3]:
                bollinger_grid.append({
                    'bb_period': bb_p,
                    'bb_std': float(bb_s),
                    'entry_z': float(entry_z),
                    'leverage': lev,
                    'k_sl': 1.5,
                })

print(f"   🎯 Grille Bollinger : {len(bollinger_grid):,} combinaisons")

try:
    # Warmup
    run_numba_sweep(df, "bollinger_atr", bollinger_grid[:10], 10000, 10, 5)

    t0 = time.perf_counter()
    results_b = run_numba_sweep(df, "bollinger_atr", bollinger_grid, 10000, 10, 5)
    t1 = time.perf_counter()

    boll_time = t1 - t0
    boll_speed = len(bollinger_grid) / boll_time
    print(f"\n   ✅ {len(bollinger_grid):,} runs en {boll_time:.2f}s = {boll_speed:,.0f} runs/s")

    pnls_b = [r['total_pnl'] for r in results_b]
    best_b = results_b[np.argmax(pnls_b)]
    print(f"   🏆 Meilleur PnL : ${best_b['total_pnl']:,.2f} | Sharpe: {best_b['sharpe_ratio']:.2f}")
    print(f"      Params: {best_b['params']}")
except Exception as e:
    print(f"   ❌ Erreur : {e}")
    boll_speed = 0

# ══════════════════════════════════════════════════════════════════════════
# TEST 4 : Numba prange - RSI Reversal
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "─" * 72)
print("TEST 4 : Numba prange - RSI Reversal")
print("─" * 72)

rsi_grid = []
for rsi_p in range(5, 30):              # 25 valeurs
    for ob in range(60, 95, 5):          # 7 valeurs
        for os_ in range(5, 40, 5):      # 7 valeurs
            for lev in [1, 2, 3]:
                rsi_grid.append({
                    'rsi_period': rsi_p,
                    'overbought': ob,
                    'oversold': os_,
                    'leverage': lev,
                    'k_sl': 1.5,
                })

print(f"   🎯 Grille RSI : {len(rsi_grid):,} combinaisons")

try:
    run_numba_sweep(df, "rsi_reversal", rsi_grid[:10], 10000, 10, 5)

    t0 = time.perf_counter()
    results_r = run_numba_sweep(df, "rsi_reversal", rsi_grid, 10000, 10, 5)
    t1 = time.perf_counter()

    rsi_time = t1 - t0
    rsi_speed = len(rsi_grid) / rsi_time
    print(f"\n   ✅ {len(rsi_grid):,} runs en {rsi_time:.2f}s = {rsi_speed:,.0f} runs/s")

    pnls_r = [r['total_pnl'] for r in results_r]
    best_r = results_r[np.argmax(pnls_r)]
    print(f"   🏆 Meilleur PnL : ${best_r['total_pnl']:,.2f} | Sharpe: {best_r['sharpe_ratio']:.2f}")
    print(f"      Params: {best_r['params']}")
except Exception as e:
    print(f"   ❌ Erreur : {e}")
    rsi_speed = 0

# ══════════════════════════════════════════════════════════════════════════
# RÉSUMÉ COMPARATIF
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("RÉSUMÉ COMPARATIF - 62 448 barres BTCUSDC_1h")
print("=" * 72)

print(f"\n{'Méthode':<35} {'Vitesse':>12}  {'×Gain':>8}  {'5M combos':>12}")
print("─" * 72)

ref = 36  # ProcessPool mesuré précédemment

methods = [
    ("ProcessPool 24 workers", 36),
    ("Single-thread Python (fast)", python_speed),
]
if numba_speed > 0:
    methods.append(("Numba prange EMA Cross", numba_speed))
if boll_speed > 0:
    methods.append(("Numba prange Bollinger", boll_speed))
if rsi_speed > 0:
    methods.append(("Numba prange RSI", rsi_speed))

for name, speed in methods:
    gain = speed / ref
    time_5m = 5_000_000 / speed / 60 if speed > 0 else float('inf')
    print(f"  {name:<33} {speed:>10,.0f}/s  {gain:>7.1f}×  {time_5m:>10.1f} min")

print(f"\n💡 CONCLUSION :")
if numba_speed > 0:
    ratio = numba_speed / ref
    print(f"   prange est {ratio:.0f}× plus rapide que ProcessPool")
    print(f"   sur 62 448 barres avec {total_combos:,} combos EMA Cross")
    if numba_speed > 1000:
        print(f"   ✅ prange est PERTINENT et RECOMMANDÉ pour ce cas de figure")
    else:
        print(f"   ⚠️  Gain modeste — à évaluer selon le volume de combos")
