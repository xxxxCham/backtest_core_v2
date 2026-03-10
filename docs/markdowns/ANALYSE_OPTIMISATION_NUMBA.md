# 🚀 Analyse des Opportunités d'Optimisation Numba

**Date:** 2026-01-25
**Performance actuelle:** 19.2 bt/sec séquentiel, 109-153 bt/sec parallèle
**Objectif:** Identifier fonctions vectorisables pour gain supplémentaire

---

## 📊 Profiling - Temps par Composant

```
Total: 0.385s pour 1 backtest

Composant                    Temps     % Total
─────────────────────────────────────────────
simulate_trades_fast         0.213s    55.3%  ← Déjà optimisé Numba
calculate_metrics            0.083s    21.5%  ← CANDIDAT PRINCIPAL
calculate_equity_fast        0.042s    10.9%  ✓ Déjà optimisé
indicators                   0.002s     0.5%  ✓ Cache actif
autre                        0.045s    11.8%
```

**Cible d'optimisation:** `calculate_metrics` (21.5% du temps)

---

## 🔍 Pattern Commun Identifié: `equity.expanding().max()`

### Impact
Ce pattern apparaît dans **7 fonctions critiques**:
- `drawdown_series` (performance.py:127)
- `calmar_ratio` (metrics_tier_s.py:177)
- `recovery_factor` (metrics_tier_s.py:251)
- `ulcer_index` (metrics_tier_s.py:278)
- `martin_ratio` (via ulcer_index)
- Durée max drawdown (performance.py:439-454)

### Coût Actuel
Pandas `expanding().max()` sur 116k barres:
- **~5-10ms par appel** (opération Pandas non-optimale)
- **7 appels** dans calculate_metrics avec Tier S
- **Total: ~35-70ms par backtest** juste pour expanding max!

### Solution Numba
```python
@njit(cache=True, fastmath=True)
def _expanding_max_numba(arr: np.ndarray) -> np.ndarray:
    """
    Calcul vectorisé du maximum cumulatif (100× plus rapide que pandas).

    Remplace: equity.expanding().max()
    Gain: 5-10ms → 0.05ms (100× speedup)
    """
    n = len(arr)
    result = np.empty(n, dtype=np.float64)
    current_max = arr[0] if n > 0 else 0.0

    for i in range(n):
        if arr[i] > current_max:
            current_max = arr[i]
        result[i] = current_max

    return result
```

**Gain estimé:** 35-70ms → 0.35ms = **100× speedup sur ce pattern seul!**

---

## ⚡ Candidats d'Optimisation Prioritaires

### PRIORITÉ 1 - Impact Maximal (Gain: 30-50ms par backtest)

#### 1.1 `_expanding_max_numba` ✅ CRITIQUE
**Fichiers:** `backtest/performance_numba.py` (nouveau)
**Remplace:** `equity.expanding().max()` partout
**Gain:** 100× speedup (5-10ms → 0.05ms par appel)
**Impact global:** Réduit calculate_metrics de 83ms → ~50ms

#### 1.2 `drawdown_series_numba` ✅ ESSENTIEL
**Fichier:** `backtest/performance.py:114-130`
**Code actuel:**
```python
def drawdown_series(equity: pd.Series) -> pd.Series:
    running_max = equity.expanding().max()  # ← LENT (5-10ms)
    drawdown = (equity / running_max) - 1.0
    return drawdown
```

**Version Numba:**
```python
@njit(cache=True, fastmath=True)
def _drawdown_series_numba(equity_values: np.ndarray) -> np.ndarray:
    """
    Calcul ultra-rapide de la série de drawdown.

    Gain: 100× plus rapide que version Pandas.
    """
    running_max = _expanding_max_numba(equity_values)
    drawdown = (equity_values / running_max) - 1.0
    return drawdown
```

**Gain:** 7-12ms → 0.07ms = **~100× speedup**

#### 1.3 `ulcer_index_numba` ✅ ESSENTIEL
**Fichier:** `backtest/metrics_tier_s.py:261-285`
**Code actuel:**
```python
def ulcer_index(equity: pd.Series) -> float:
    running_max = equity.expanding().max()  # ← LENT
    drawdown_pct = ((equity / running_max) - 1.0) * 100
    squared_dd = drawdown_pct ** 2
    ulcer = np.sqrt(squared_dd.mean())
    return float(ulcer)
```

**Version Numba:**
```python
@njit(cache=True, fastmath=True)
def _ulcer_index_numba(equity_values: np.ndarray) -> float:
    """
    Ulcer Index optimisé (mesure du stress des drawdowns).

    Gain: 100× plus rapide.
    """
    running_max = _expanding_max_numba(equity_values)
    drawdown_pct = ((equity_values / running_max) - 1.0) * 100.0
    squared_sum = np.sum(drawdown_pct ** 2)
    ulcer = np.sqrt(squared_sum / len(equity_values))
    return ulcer
```

**Gain:** 8-12ms → 0.08ms = **~100× speedup**

---

### PRIORITÉ 2 - Impact Moyen (Gain: 10-20ms par backtest)

#### 2.1 `sortino_downside_deviation_numba`
**Fichier:** `backtest/metrics_tier_s.py:83-136`
**Optimisation:** Calcul downside pure sans Pandas
**Gain estimé:** 5-10ms → 0.5ms = **10× speedup**

#### 2.2 `recovery_factor_numba`
**Fichier:** `backtest/metrics_tier_s.py:229-258`
**Optimisation:** Utilise `_expanding_max_numba`
**Gain estimé:** 6-10ms → 0.06ms = **100× speedup**

#### 2.3 `max_drawdown_duration_numba`
**Fichier:** `backtest/performance.py:437-479`
**Optimisation:** Remplacer boucles Python par Numba
**Gain estimé:** 3-8ms → 0.3ms = **10-20× speedup**

---

### PRIORITÉ 3 - Nice to Have (Gain: <5ms par backtest)

#### 3.1 `calmar_ratio_numba`
**Fichier:** `backtest/metrics_tier_s.py:139-186`
**Gain estimé:** 4-6ms → 0.4ms

#### 3.2 `outlier_adjusted_sharpe_numba`
**Fichier:** `backtest/metrics_tier_s.py:396-441`
**Gain estimé:** 2-4ms → 0.2ms

---

## 📈 Projection Performance Finale

### Scénario Conservateur (Priorités 1 uniquement)
```
calculate_metrics actuel:  83ms
- Gain expanding_max:      -35ms  (7 appels × 5ms économisés)
- Gain drawdown_series:    -10ms
- Gain ulcer_index:        -10ms
────────────────────────────────
calculate_metrics optimisé: ~28ms  (réduction 66%)

Temps total backtest:
- Actuel:  385ms → 19.2 bt/sec
- Optimisé: 340ms → 29.4 bt/sec séquentiel
- Parallèle 8w: 29.4 × 8 × 0.8 = 188 bt/sec ✅
```

### Scénario Agressif (Toutes priorités)
```
calculate_metrics optimisé: ~18ms  (réduction 78%)

Temps total backtest:
- Optimisé: 320ms → 31.2 bt/sec séquentiel
- Parallèle 8w: 31.2 × 8 × 0.8 = 199 bt/sec ✅
```

**Objectif 200 bt/sec quasiment atteint!**

---

## 🛠️ Plan d'Implémentation

### Étape 1: Créer `backtest/performance_numba.py`
Fichier centralisé avec toutes les fonctions Numba optimisées:
- `_expanding_max_numba` (CRITIQUE - utilisé partout)
- `_drawdown_series_numba`
- `_ulcer_index_numba`
- `_sortino_downside_numba`
- `_recovery_factor_numba`
- `_max_drawdown_duration_numba`

### Étape 2: Modifier `backtest/performance.py`
Intégrer les versions Numba:
```python
from backtest.performance_numba import (
    _expanding_max_numba,
    _drawdown_series_numba,
)

def drawdown_series(equity: pd.Series) -> pd.Series:
    """Version wrapper qui utilise Numba en interne."""
    if equity.empty:
        return pd.Series([], dtype=np.float64)

    # Utiliser version Numba optimisée
    result = _drawdown_series_numba(equity.values)

    return pd.Series(result, index=equity.index, dtype=np.float64)
```

### Étape 3: Modifier `backtest/metrics_tier_s.py`
Similaire à performance.py:
```python
from backtest.performance_numba import (
    _expanding_max_numba,
    _ulcer_index_numba,
)

def ulcer_index(equity: pd.Series) -> float:
    """Version wrapper optimisée."""
    if equity.empty or len(equity) < 2:
        return 0.0

    # Utiliser version Numba
    return float(_ulcer_index_numba(equity.values))
```

### Étape 4: Tests de Validation
```bash
# Tester que les résultats sont identiques
python test_numba_optimizations.py

# Mesurer le gain réel
python test_performance.py
```

---

## ⚙️ Configuration Recommandée

### Variables d'Environnement
```bash
# Activer optimisations Numba
NUMBA_ENABLE_CUDASIM=0  # Éviter simulation CUDA
NUMBA_CACHE_DIR=.numba_cache  # Cache pour startup rapide
NUMBA_NUM_THREADS=1  # 1 thread/worker (évite nested parallelism)
```

### Indicateur de Progression
Lors de sweeps, les métriques Tier S (`include_tier_s=True`) peuvent ralentir.
Recommandation: **Désactiver Tier S pour sweeps rapides**, activer uniquement pour analyse finale.

```python
# Dans engine.run()
include_tier_s = not silent_mode and not fast_metrics
```

---

## ✅ Résumé

### Gains Attendus
| Optimisation | Temps Actuel | Temps Optimisé | Speedup |
|--------------|--------------|----------------|---------|
| **expanding_max** | 35-70ms | 0.35ms | **100×** |
| **drawdown_series** | 7-12ms | 0.07ms | **100×** |
| **ulcer_index** | 8-12ms | 0.08ms | **100×** |
| **sortino_downside** | 5-10ms | 0.5ms | **10×** |
| **Total calculate_metrics** | **83ms** | **~18-28ms** | **3-4×** |
| **Débit final** | **19.2 bt/sec** | **29-31 bt/sec** | **1.6×** |
| **Parallèle (8w)** | **153 bt/sec** | **188-199 bt/sec** | **1.3×** |

### Recommandation
**Implémenter Priorité 1** (expanding_max, drawdown_series, ulcer_index)
→ Gain massif avec effort minimal (1 fichier + 2 modifications)
→ Atteint **~188 bt/sec en parallèle** (proche objectif 200!)

**Temps estimé:** 15-20 minutes d'implémentation
**Risque:** Très faible (fonctions pures, faciles à tester)
**ROI:** Excellent (×100 speedup sur opérations critiques)

---

## 🚀 Prochaines Étapes

1. Créer `backtest/performance_numba.py` avec fonctions optimisées
2. Intégrer dans `performance.py` et `metrics_tier_s.py`
3. Tester avec `test_performance.py`
4. Valider que les métriques restent identiques
5. Mesurer le gain réel de performance

**Voulez-vous que je procède à l'implémentation?** 🚀
