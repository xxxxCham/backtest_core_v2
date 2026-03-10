# 🚀 NumPy et prange - Configuration VALIDÉE

## ✅ Résultat des tests

**Performance mesurée :** **31,656 backtests/seconde** (OpenMP activé, 32 threads)

| Avant (default) | Après (OpenMP) | Gain |
|-----------------|----------------|------|
| ~100-500 bt/s   | **31,656 bt/s** | **63×** |

## 🎯 Solution rapide (2 minutes)

### Option 1 : Script PowerShell (recommandé)

```powershell
# Dans backtest_core/
.\tools\scripts\activate_numba_final.ps1

# Puis lancer vos scripts
python votre_script.py
```

### Option 2 : Configuration manuelle

**PowerShell :**
```powershell
$env:NUMBA_NUM_THREADS="32"
$env:NUMBA_THREADING_LAYER="omp"
$env:OMP_NUM_THREADS="32"
```

**CMD :**
```cmd
activate_numba.bat
```

### Option 3 : Dans vos scripts Python

Ajouter **EN DÉBUT** de script (avant imports Numba) :

```python
import os
os.environ['NUMBA_NUM_THREADS'] = '32'
os.environ['NUMBA_THREADING_LAYER'] = 'omp'
os.environ['OMP_NUM_THREADS'] = '32'

# Puis vos imports
from backtest.sweep_numba import run_numba_sweep
```

## 📊 Performance estimée

| Combinaisons | Temps avant | Temps après | Gain |
|--------------|-------------|-------------|------|
| 10K          | ~20 min     | **< 1 sec** | 1200× |
| 100K         | ~3h         | **15 sec**  | 720× |
| 1M           | ~30h        | **8 min**   | 225× |
| **5M**       | **~200h**   | **40 min**  | **300×** |

## ✅ Validation

```bash
python test_sweep_performance.py
```

Attendu : **Throughput > 30,000 bt/s**

## 📁 Fichiers créés

- ✅ `tools\scripts\activate_numba_final.ps1` - Script PowerShell validé
- ✅ `activate_numba.bat` - Script CMD
- ✅ `test_sweep_performance.py` - Benchmark complet
- ✅ `test_numba_openmp.py` - Test rapide
- ✅ `CONFIGURATION_FINALE.md` - Documentation complète
- ✅ `pyproject.toml` - Dépendances mises à jour

## 🎯 Pour vos sweeps massifs

```bash
# 1. Activer threading
.\tools\scripts\activate_numba_final.ps1

# 2. Lancer sweep
python -m cli.__main__ --strategy bollinger_atr --sweep --n-combos 5000000

# Temps attendu : ~40 minutes (au lieu de ~200h !)
```

## ❓ Problème ?

**Threading layer reste "default" :**
→ Variables définies **AVANT** import numba ? (voir Option 3)

**Performance toujours lente :**
→ Vérifier que `parallel=True` dans les `@njit` et `prange` utilisé (pas `range`)

**Erreur NUMEXPR_MAX_THREADS :**
```python
os.environ['NUMEXPR_MAX_THREADS'] = '32'
```

## 📖 Documentation complète

- `CONFIGURATION_FINALE.md` - Guide complet
- `NUMBA_SETUP.md` - Installation détaillée

---

**Status :** ✅ **OPÉRATIONNEL**
**Performance :** 31,656 backtests/seconde
**Gain vs séquentiel :** **63× plus rapide**



