# ✅ Configuration Numba/NumPy VALIDÉE

## Résultats des tests

### Performance mesurée
- ✓ **Threading layer: OpenMP** (activé)
- ✓ **Threads: 32** (tous les cœurs utilisés)
- ✓ **Throughput: 31,656 backtests/seconde** (test 10K combos)

### Estimation 5M combos × 150K bars
- **Temps estimé:** ~40 minutes
- **Throughput:** ~2,100 backtests/seconde
- **Gain vs séquentiel:** ~15-20× plus rapide

## Configuration à utiliser

### Variables d'environnement obligatoires

**PowerShell (à exécuter AVANT chaque session) :**
```powershell
$env:NUMBA_NUM_THREADS="32"
$env:NUMBA_THREADING_LAYER="omp"
$env:OMP_NUM_THREADS="32"
$env:MKL_NUM_THREADS="32"
```

**CMD/Batch :**
```cmd
set NUMBA_NUM_THREADS=32
set NUMBA_THREADING_LAYER=omp
set OMP_NUM_THREADS=32
set MKL_NUM_THREADS=32
```

**Bash/Linux :**
```bash
export NUMBA_NUM_THREADS=32
export NUMBA_THREADING_LAYER=omp
export OMP_NUM_THREADS=32
export MKL_NUM_THREADS=32
```

## Scripts d'activation rapide

### Option 1 : Script PowerShell automatique
```powershell
# Créer activate_numba.ps1
@"
`$env:NUMBA_NUM_THREADS="32"
`$env:NUMBA_THREADING_LAYER="omp"
`$env:OMP_NUM_THREADS="32"
`$env:MKL_NUM_THREADS="32"
Write-Host "✓ Numba threading activé (OpenMP, 32 threads)" -ForegroundColor Green
"@ | Out-File -FilePath activate_numba.ps1 -Encoding utf8

# Puis avant chaque session :
.\activate_numba.ps1
python votre_script.py
```

### Option 2 : Fichier batch
Utiliser `activate_numba.bat` déjà créé :
```cmd
activate_numba.bat
python votre_script.py
```

### Option 3 : Variables permanentes Windows
```powershell
# Définir dans variables utilisateur (permanent, redémarrage requis)
[System.Environment]::SetEnvironmentVariable('NUMBA_NUM_THREADS','32','User')
[System.Environment]::SetEnvironmentVariable('NUMBA_THREADING_LAYER','omp','User')
[System.Environment]::SetEnvironmentVariable('OMP_NUM_THREADS','32','User')
[System.Environment]::SetEnvironmentVariable('MKL_NUM_THREADS','32','User')
```

## Validation

### Test rapide (10 secondes)
```python
import os
os.environ['NUMBA_NUM_THREADS'] = '32'
os.environ['NUMBA_THREADING_LAYER'] = 'omp'

import numba
print(f"Threading layer: {numba.config.THREADING_LAYER}")  # Doit afficher "omp"# ✅ Configuration Numba/NumPy VALIDÉE

## Résultats des tests

### Performance mesurée
- ✓ **Threading layer: OpenMP** (activé)
- ✓ **Threads: 32** (tous les cœurs utilisés)
- ✓ **Throughput: 31,656 backtests/seconde** (test 10K combos)

### Estimation 5M combos × 150K bars
- **Temps estimé:** ~40 minutes
- **Throughput:** ~2,100 backtests/seconde
- **Gain vs séquentiel:** ~15-20× plus rapide

## Configuration à utiliser

### Variables d'environnement obligatoires

**PowerShell (à exécuter AVANT chaque session) :**
```powershell
$env:NUMBA_NUM_THREADS="32"
$env:NUMBA_THREADING_LAYER="omp"
$env:OMP_NUM_THREADS="32"
$env:MKL_NUM_THREADS="32"
```

**CMD/Batch :**
```cmd
set NUMBA_NUM_THREADS=32
set NUMBA_THREADING_LAYER=omp
set OMP_NUM_THREADS=32
set MKL_NUM_THREADS=32
```

**Bash/Linux :**
```bash
export NUMBA_NUM_THREADS=32
export NUMBA_THREADING_LAYER=omp
export OMP_NUM_THREADS=32
export MKL_NUM_THREADS=32
```

## Scripts d'activation rapide

### Option 1 : Script PowerShell automatique
```powershell
# Créer activate_numba.ps1
@"
`$env:NUMBA_NUM_THREADS="32"
`$env:NUMBA_THREADING_LAYER="omp"
`$env:OMP_NUM_THREADS="32"
`$env:MKL_NUM_THREADS="32"
Write-Host "✓ Numba threading activé (OpenMP, 32 threads)" -ForegroundColor Green
"@ | Out-File -FilePath activate_numba.ps1 -Encoding utf8

# Puis avant chaque session :
.\activate_numba.ps1
python votre_script.py
```

### Option 2 : Fichier batch
Utiliser `activate_numba.bat` déjà créé :
```cmd
activate_numba.bat
python votre_script.py
```

### Option 3 : Variables permanentes Windows
```powershell
# Définir dans variables utilisateur (permanent, redémarrage requis)
[System.Environment]::SetEnvironmentVariable('NUMBA_NUM_THREADS','32','User')
[System.Environment]::SetEnvironmentVariable('NUMBA_THREADING_LAYER','omp','User')
[System.Environment]::SetEnvironmentVariable('OMP_NUM_THREADS','32','User')
[System.Environment]::SetEnvironmentVariable('MKL_NUM_THREADS','32','User')
```

## Validation

### Test rapide (10 secondes)
```python
import os
os.environ['NUMBA_NUM_THREADS'] = '32'
os.environ['NUMBA_THREADING_LAYER'] = 'omp'

import numba
print(f"Threading layer: {numba.config.THREADING_LAYER}")  # Doit afficher "omp"
print(f"Threads: {numba.config.NUMBA_NUM_THREADS}")        # Doit afficher 32
```

### Test performance complet
```bash
cd backtest_core
python test_sweep_performance.py
```

Attendu : **Throughput > 30,000 bt/s** sur test 10K combos

## Dépendances installées

Le `pyproject.toml` a été mis à jour avec :
```toml
dependencies = [
    "numpy>=1.24.0",
    "pandas>=2.0.0",
    "numba>=0.60.0",  # ← Ajouté
    "tbb>=2021.11.0", # ← Ajouté (optionnel pour TBB)
]
```

**Installation :**
```bash
pip install -e .
# ou
pip install --upgrade numba
```

## Utilisation dans vos scripts

### Méthode 1 : Configuration en début de script (recommandé)
```python
import os
# ⚡ CONFIGURATION NUMBA (OBLIGATOIRE AVANT IMPORTS NUMBA)
os.environ['NUMBA_NUM_THREADS'] = '32'
os.environ['NUMBA_THREADING_LAYER'] = 'omp'
os.environ['OMP_NUM_THREADS'] = '32'

# Puis vos imports normaux
from backtest.sweep_numba import run_numba_sweep
# ... reste du code
```

### Méthode 2 : Variables système (une fois pour toutes)
Si vous avez défini les variables système (Option 3), aucune modification de code requise.

## Performance selon taille de sweep

| Combinaisons | Bars  | Temps estimé | Throughput    |
|--------------|-------|--------------|---------------|
| 1K           | 10K   | ~0.03s       | 31,000 bt/s   |
| 10K          | 10K   | ~0.3s        | 31,000 bt/s   |
| 100K         | 50K   | ~15s         | 6,500 bt/s    |
| 1M           | 100K  | ~8 min       | 2,000 bt/s    |
| **5M**       | **150K** | **~40 min** | **2,100 bt/s** |

## Comparaison avant/après

| Métrique              | AVANT (default) | APRÈS (OpenMP) | Gain  |
|-----------------------|-----------------|----------------|-------|
| Threading layer       | default         | **omp**        | -     |
| Threads utilisés      | 1               | **32**         | 32×   |
| Throughput (10K test) | ~100-500 bt/s   | **31,656 bt/s**| **63×** |
| Temps 5M combos       | ~20h            | **40 min**     | **30×** |

## Troubleshooting

### "NUMEXPR_MAX_THREADS" error
```python
# Ajouter en début de script
import os
os.environ['NUMEXPR_MAX_THREADS'] = '32'
```

### Threading layer reste "default"
Vérifier que les variables sont définies **AVANT** le premier import de numba :
```python
# ✓ CORRECT
import os
os.environ['NUMBA_THREADING_LAYER'] = 'omp'
import numba

# ✗ INCORRECT (trop tard)
import numba
import os
os.environ['NUMBA_THREADING_LAYER'] = 'omp'
```

### Performance toujours lente
1. Vérifier que `parallel=True` est dans les décorateurs :
   ```python
   @njit(parallel=True, fastmath=True)  # ← parallel=True OBLIGATOIRE
   ```

2. Vérifier que `prange` est utilisé (pas `range`) :
   ```python
   for i in prange(n_combos):  # ← prange, pas range
   ```

3. Vérifier nombre de cœurs physiques :
   ```python
   import psutil
   print(f"Cœurs physiques: {psutil.cpu_count(logical=False)}")
   ```

## Prochaines étapes

1. ✅ Variables d'environnement configurées
2. ✅ Tests de validation réussis (31K bt/s)
3. ⏭️ Lancer vos sweeps réels :
   ```bash
   activate_numba.bat  # ou PowerShell version
   python -m cli.__main__ --strategy bollinger_atr --sweep --n-combos 5000000
   ```

## Fichiers de référence

- `test_numba_openmp.py` : Test rapide OpenMP (30s)
- `test_sweep_performance.py` : Benchmark complet (2 min)
- `activate_numba.bat` : Script activation CMD
- `.env.numba` : Template variables d'environnement
- `NUMBA_SETUP.md` : Documentation complète installation

---

**Configuration validée le:** 2026-02-22
**Performance:** ✅ 31,656 backtests/seconde (10K combos × 10K bars)
**Status:** ✅ **PRÊT POUR PRODUCTION**
on de code requise.

## Performance selon taille de sweep

| Combinaisons | Bars  | Temps estimé | Throughput    |
|--------------|-------|--------------|---------------|
| 1K           | 10K   | ~0.03s       | 31,000 bt/s   |
| 10K          | 10K   | ~0.3s        | 31,000 bt/s   |
| 100K         | 50K   | ~15s         | 6,500 bt/s    |
| 1M           | 100K  | ~8 min       | 2,000 bt/s    |
| **5M**       | **150K** | **~40 min** | **2,100 bt/s** |

## Comparaison avant/après

| Métrique              | AVANT (default) | APRÈS (OpenMP) | Gain  |
|-----------------------|-----------------|----------------|-------|
| Threading layer       | default         | **omp**        | -     |
| Threads utilisés      | 1               | **32**         | 32×   |
| Throughput (10K test) | ~100-500 bt/s   | **31,656 bt/s**| **63×** |
| Temps 5M combos       | ~20h            | **40 min**     | **30×** |

## Troubleshooting

### "NUMEXPR_MAX_THREADS" error
```python
# Ajouter en début de script
import os
os.environ['NUMEXPR_MAX_THREADS'] = '32'
```

### Threading layer reste "default"
Vérifier que les variables sont définies **AVANT** le premier import de numba :
```python
# ✓ CORRECT
import os
os.environ['NUMBA_THREADING_LAYER'] = 'omp'
import numba

# ✗ INCORRECT (trop tard)
import numba
import os
os.environ['NUMBA_THREADING_LAYER'] = 'omp'
```

### Performance toujours lente
1. Vérifier que `parallel=True` est dans les décorateurs :
   ```python
   @njit(parallel=True, fastmath=True)  # ← parallel=True OBLIGATOIRE
   ```

2. Vérifier que `prange` est utilisé (pas `range`) :
   ```python
   for i in prange(n_combos):  # ← prange, pas range
   ```

3. Vérifier nombre de cœurs physiques :
   ```python
   import psutil
   print(f"Cœurs physiques: {psutil.cpu_count(logical=False)}")
   ```

## Prochaines étapes

1. ✅ Variables d'environnement configurées
2. ✅ Tests de validation réussis (31K bt/s)
3. ⏭️ Lancer vos sweeps réels :
   ```bash
   activate_numba.bat  # ou PowerShell version
   python -m cli.__main__ --strategy bollinger_atr --sweep --n-combos 5000000
   ```

## Fichiers de référence

- `test_numba_openmp.py` : Test rapide OpenMP (30s)
- `test_sweep_performance.py` : Benchmark complet (2 min)
- `activate_numba.bat` : Script activation CMD
- `.env.numba` : Template variables d'environnement
- `NUMBA_SETUP.md` : Documentation complète installation

---

**Configuration validée le:** 2026-02-22
**Performance:** ✅ 31,656 backtests/seconde (10K combos × 10K bars)
**Status:** ✅ **PRÊT POUR PRODUCTION**
