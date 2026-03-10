# 🔧 Fix: Crash ProcessPool - "BrokenProcessPool"

## 🎯 Problème

```
BrokenProcessPool: A child process terminated abruptly, the process pool is not usable anymore
```

### Cause

**Conflit threading** : ProcessPoolExecutor + NumPy/Numba threading élevé

- **ProcessPool** : 24-32 workers (processus séparés)
- **Numba/NumPy** : 32 threads **PAR worker**
- **Résultat** : 24-32 × 32 = **768-1024 threads** → **crash mémoire/CPU**

## ✅ Solutions

### Solution 1 : Réduire threading (IMMÉDIAT)

Utiliser le script qui désactive le threading multiple :

```powershell
# Lancer avec threading réduit
.\tools\scripts\launch_ui_processpool.ps1
```

Ce script configure :
- `NUMBA_NUM_THREADS=1` (au lieu de 32)
- `NUMBA_THREADING_LAYER=default` (au lieu de omp)
- Évite le conflit ProcessPool × threading

**Performance attendue** : ~200-500 bt/s (suffisant pour sweeps < 100K combos)

### Solution 2 : Utiliser le sweep Numba (OPTIMAL)

Le sweep Numba **remplace** ProcessPoolExecutor et évite le problème.

**⚠️ Le sweep Numba n'est PAS encore intégré dans l'UI !**

Pour l'utiliser temporairement via Python :

```python
import os
os.environ['NUMBA_NUM_THREADS'] = '32'
os.environ['NUMBA_THREADING_LAYER'] = 'omp'

import pandas as pd
from backtest.sweep_numba import run_numba_sweep

# Charger données
df = pd.read_parquet('data/...')

# Grille de paramètres
param_grid = [
    {'bb_period': 20, 'bb_std': 2.0, 'entry_z': 2.0, ...},
    # ...
]

# Exécuter sweep Numba
results = run_numba_sweep(
    df=df,
    strategy_key='bollinger_atr',
    param_grid=param_grid,
    initial_capital=10000.0,
    fees_bps=10.0,
    slippage_bps=5.0,
)

# results = liste de dicts avec total_pnl, sharpe_ratio, etc.
```

**Performance** : 31,000+ bt/s (100× plus rapide)

## 📊 Comparaison

| Mode              | Threads | Performance | Stabilité | Meilleur pour       |
|-------------------|---------|-------------|-----------|---------------------|
| ProcessPool (32t) | 32/worker | ❌ Crash    | ❌        | -                   |
| **ProcessPool (1t)** | **1/worker**  | **~300 bt/s** | **✅**    | **Sweeps < 100K**   |
| **Numba sweep**      | **32 total**  | **31K bt/s**  | **✅**    | **Sweeps > 100K**   |

## 🚀 TODO : Intégrer Numba sweep dans UI

Le sweep Numba existe (`backtest/sweep_numba.py`) mais n'est pas connecté à l'UI.

### Fichiers à modifier

1. **`ui/main.py`** (ligne ~1160)

Ajouter AVANT le bloc ProcessPoolExecutor :

```python
# ============================================================================
# SWEEP NUMBA (si supporté)
# ============================================================================
use_numba_sweep = False
NUMBA_MAX_COMBOS = 10_000_000  # Pas de limite pratique

try:
    from backtest.sweep_numba import is_numba_supported, run_numba_sweep

    if is_numba_supported(strategy_key) and total_runs > 100:  # > 100 combos
        use_numba_sweep = True
        logger.info(f"[NUMBA] Sweep activé: {total_runs:,} combos")
except ImportError as e:
    logger.warning(f"[NUMBA] Import failed: {e}")

if use_numba_sweep and total_runs > 1:
    # Convertir combo_iter en liste (Numba nécessite liste complète)
    param_grid = list(combo_iter)

    logger.info(f"[NUMBA] Lancement kernel: {len(param_grid):,} combos × {len(df):,} bars")

    try:
        # Exécuter sweep Numba
        numba_results = run_numba_sweep(
            df=df,
            strategy_key=strategy_key,
            param_grid=param_grid,
            initial_capital=params.get('initial_capital', 10000.0),
            fees_bps=params.get('fees_bps', 10.0),
            slippage_bps=params.get('slippage_bps', 5.0),
            return_arrays=False,  # Retourner liste de dicts
        )

        # Convertir résultats Numba au format attendu
        for res in numba_results:
            result_clean = {
                'total_pnl': res['total_pnl'],
                'sharpe_ratio': res['sharpe_ratio'],
                'max_drawdown': res['max_drawdown'],
                'win_rate': res['win_rate'],
                'total_trades': res['total_trades'],
                'params': res['params'],
            }
            results_list.append(result_clean)

            # Mise à jour monitor
            metrics = {k: v for k, v in res.items() if k != 'params'}
            sweep_monitor.update(params=res['params'], metrics=metrics)

        completed = len(numba_results)
        monitor.runs_completed = completed

        logger.info(f"[NUMBA] Sweep terminé: {completed:,} combos")

    except Exception as e:
        logger.error(f"[NUMBA] Erreur: {e}")
        use_numba_sweep = False  # Fallback ProcessPool
        completed = 0

# ============================================================================
# FALLBACK: ProcessPoolExecutor (si Numba non disponible/échoué)
# ============================================================================
if not use_numba_sweep and completed < total_runs and n_workers_effective > 1:
    logger.info(f"[PROCESSPOOL] Fallback: {total_runs:,} combos")
    # ... code ProcessPool existant ...
```

### Stratégies supportées (déjà implémentées)

- `bollinger_atr`, `bollinger_atr_v2`, `bollinger_atr_v3`
- `ema_cross`
- `rsi_reversal`
- `macd_cross`
- `bollinger_best_longe_3i`, `bollinger_best_short_3i`

## ⚡ Performance après intégration

| Combinaisons | Avant (ProcessPool 1t) | Après (Numba) | Gain  |
|--------------|------------------------|---------------|-------|
| 1K           | ~3s                    | **< 0.1s**    | 30×   |
| 10K          | ~30s                   | **0.3s**      | 100×  |
| 100K         | ~5 min                 | **3s**        | 100×  |
| 1M           | ~50 min                | **30s**       | 100×  |
| 5M           | **~250 min**           | **2-3 min**   | **100×** |

## 🔍 Diagnostic

Si le crash persiste avec `tools\scripts\launch_ui_processpool.ps1` :

```powershell
# Vérifier variables d'environnement
python -c "import os; print('NUMBA_NUM_THREADS:', os.environ.get('NUMBA_NUM_THREADS'))"

# Doit afficher: NUMBA_NUM_THREADS: 1
```

Si la valeur est toujours 32 :
1. Relancer le terminal PowerShell
2. Exécuter le script depuis le terminal fraîchement ouvert

---

**Date** : 2026-02-22
**Status** : Solution immédiate disponible (`tools\scripts\launch_ui_processpool.ps1`)
**TODO** : Intégrer sweep Numba dans UI (1-2h de travail)



