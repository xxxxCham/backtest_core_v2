# Configuration Numba/NumPy Threading

## Problème identifié

NumPy et `prange` (parallélisation Numba) ne sont **pas activés correctement** :

- ❌ **Threading layer = "default"** (au lieu de "tbb")
- ❌ **NUMBA_NUM_THREADS non défini** (32 threads disponibles mais non utilisés)
- ❌ **TBB non installé** (Thread Building Blocks pour meilleur scaling)

## Solution rapide (3 minutes)

### Option 1 : Script PowerShell (recommandé Windows)

```powershell
# Dans backtest_core/
.\tools\scripts\setup_numba_threading.ps1
```

Ce script :
1. Installe TBB et intel-openmp
2. Met à jour Numba
3. Configure les variables d'environnement
4. Valide l'installation

### Option 2 : Manuel

```bash
# 1. Installer dépendances
pip install --upgrade numba>=0.60.0 tbb intel-openmp

# 2. PowerShell : configurer variables (session actuelle)
$env:NUMBA_NUM_THREADS="32"
$env:NUMBA_THREADING_LAYER="tbb"
$env:OMP_NUM_THREADS="32"

# 2bis. CMD/Batch : utiliser le .bat
activate_numba.bat

# 3. Vérifier
python -c "import numba; print('Threading layer:', numba.config.THREADING_LAYER); print('Threads:', numba.config.NUMBA_NUM_THREADS)"
```

### Option 3 : Permanent (variables système Windows)

```powershell
# Définir dans variables utilisateur (permanent)
[System.Environment]::SetEnvironmentVariable('NUMBA_NUM_THREADS','32','User')
[System.Environment]::SetEnvironmentVariable('NUMBA_THREADING_LAYER','tbb','User')
[System.Environment]::SetEnvironmentVariable('OMP_NUM_THREADS','32','User')
[System.Environment]::SetEnvironmentVariable('MKL_NUM_THREADS','32','User')
```

## Validation

```python
import numba
import numpy as np

print('Numba version:', numba.__version__)
print('Threading layer:', numba.config.THREADING_LAYER)  # Doit afficher "tbb"
print('Threads:', numba.config.NUMBA_NUM_THREADS)        # Doit afficher 32

# Test prange
@numba.njit(parallel=True, fastmath=True)
def test_prange():
    total = 0.0
    for i in numba.prange(10000):
        total += i * 2.0
    return total

result = test_prange()
print('Test prange: OK' if result > 0 else 'ERREUR')
```

## Performance attendue (après configuration)

Avec TBB + variables correctement configurées :

| Combinaisons | Bars    | Avant (défaut) | Après (TBB) | Gain   |
|--------------|---------|----------------|-------------|--------|
| 10K          | 10K     | ~200 bt/s      | ~1000 bt/s  | **5×** |
| 100K         | 50K     | ~150 bt/s      | ~2000 bt/s  | **13×**|
| 1M           | 100K    | ~100 bt/s      | ~5000 bt/s  | **50×**|
| 5M           | 150K    | ~80 bt/s       | **8-15K bt/s** | **100-180×** |

**Estimation pour votre cas (5M combos, 150K bars) :**
- **Avant :** ~17h (5M / 80 bt/s)
- **Après :** **5-10 minutes** (5M / 8000-15000 bt/s)

## Fichiers créés

- `tools\scripts\setup_numba_threading.ps1` : Installation automatique (PowerShell)
- `activate_numba.bat` : Configuration rapide (CMD/Batch)
- `.env.numba` : Template variables d'environnement

## Troubleshooting

### TBB n'est pas détecté après installation

```bash
# Forcer réinstallation
pip uninstall numba tbb -y
pip install numba==0.60.0 tbb==2021.13.0 --no-cache-dir
```

### Threading layer reste "default"

```bash
# Vérifier chemin TBB
python -c "import numba.np.ufunc.parallel; print(numba.np.ufunc.parallel.threading_layer())"

# Si erreur : réinstaller en mode debug
pip install numba --upgrade --force-reinstall --no-binary :all:
```

### Performance pas améliorée

```bash
# Vérifier que parallel=True est bien utilisé
python -c "from backtest.sweep_numba import _sweep_bollinger_full; import inspect; print('parallel' in inspect.getsource(_sweep_bollinger_full))"

# Lancer avec profiling
NUMBA_WARNINGS=1 python votre_script.py
```

## Références

- [Numba Threading Layers](https://numba.readthedocs.io/en/stable/user/threading-layer.html)
- [TBB Documentation](https://github.com/oneapi-src/oneTBB)
- [NumPy Threading](https://numpy.org/doc/stable/user/threading.html)



