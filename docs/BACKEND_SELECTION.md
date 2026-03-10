# Backend Selection: CPU / GPU / Auto

**Version**: 1.0
**Date**: 6 février 2026
**Statut**: Production Ready

---

## Vue d'ensemble

Le système de backtest supporte **3 modes de calcul** configurables via variable d'environnement :

| Mode | Description | Use Case |
|------|-------------|----------|
| **CPU** | CPU-only strict (défaut) | Production, serveurs sans GPU |
| **GPU** | GPU requis | Workstations avec RTX/Tesla |
| **AUTO** | Détection automatique | Développement, tests |

---

## Configuration

### Variable d'environnement

**Nom**: `BACKTEST_BACKEND`

**Valeurs**:
- `cpu` — **CPU-only** (défaut, recommandé)
- `gpu` — GPU requis, erreur si CUDA absent
- `auto` — GPU si disponible, sinon fallback CPU

### Exemples

#### Windows PowerShell

```powershell
# Mode CPU-only (recommandé pour production)
$env:BACKTEST_BACKEND = "cpu"
python run_backtest.py

# Mode GPU (workstation avec GPU)
$env:BACKTEST_BACKEND = "gpu"
python run_backtest.py

# Mode Auto (développement)
$env:BACKTEST_BACKEND = "auto"
streamlit run ui/app.py
```

#### Linux/macOS Bash

```bash
# Mode CPU-only
export BACKTEST_BACKEND=cpu
python run_backtest.py

# Mode GPU
export BACKTEST_BACKEND=gpu
python run_backtest.py
```

#### Fichier .env

```env
# Backend de calcul (cpu|gpu|auto)
BACKTEST_BACKEND=cpu
```

---

## Mode CPU-Only (Recommandé)

### Caractéristiques

✅ **Zéro dépendance GPU** — Pas de CuPy, CUDA, torch requis
✅ **Performance maximale** — Numba JIT + multi-threading
✅ **Stable** — Aucun problème de driver, VRAM, OOM
✅ **Portable** — Fonctionne partout (cloud, WSL, Docker)

### Quand l'utiliser

- **Production** : Serveurs cloud sans GPU
- **CI/CD** : Tests automatisés
- **Développement** : Machines portables
- **WSL** : Windows Subsystem for Linux

### Performance

Grâce à **Numba JIT + multi-core**, le mode CPU-only atteint :

| Opération | Performance |
|-----------|-------------|
| Sweep 1000 combos | **500-1000 bt/s** (32 threads) |
| Calcul indicateurs | **20-50ms** (50k barres) |
| Simulation trades | **5-10ms** (1000 trades) |

Voir `tools/benchmark_system.py` pour benchmarks détaillés.

---

## Mode GPU (Optionnel)

### Prérequis

- **GPU NVIDIA** avec CUDA 12.x
- **CuPy** installé : `pip install cupy-cuda12x`
- **Drivers NVIDIA** à jour

### Avantages

- Calculs matriciels massifs (>100k barres)
- Operations vectorisées sur GPU

### Limitations

- **Overhead GPU** : Transferts CPU↔GPU (1-5ms)
- **VRAM** : Limité par mémoire GPU
- **Drivers** : Instabilité possible (crash, OOM)

### Quand l'utiliser

- **Workstation** : RTX 3090/4090/5080
- **Multi-GPU** : 2+ GPUs avec sélection automatique
- **Datasets énormes** : >1M barres par sweep

---

## Mode Auto (Développement)

### Comportement

1. Tente d'initialiser CuPy
2. Si succès → Mode GPU
3. Si échec → Fallback CPU

### Utilité

- **Tests** : Valider code GPU sur workstation, CPU ailleurs
- **Développement** : Passer d'un env à l'autre sans config

### ⚠️ Avertissement

**Ne pas utiliser en production** — Comportement non déterministe

---

## Diagnostic

### Vérifier backend actif

```powershell
# Afficher backend configuré
python -c "from utils.backend_config import get_backend; print(get_backend())"

# Vérifier si GPU activé
python -c "from utils.backend_config import is_gpu_enabled; print(is_gpu_enabled())"
```

### Vérifier imports

```powershell
# Tester que CPU-only ne charge pas CuPy
$env:BACKTEST_BACKEND = "cpu"
python -c "import performance; import sys; print('cupy' in sys.modules)"
# Output attendu: False
```

### Tests automatisés

```powershell
# Lancer tests CPU-only
pytest tests/test_backend_cpu_only.py -v

# Vérifier mode CPU complet
pytest tests/test_backend_cpu_only.py::TestCPUOnlyMode -v
```

---

## Migration depuis l'ancien système

### Variables d'environnement obsolètes

| Ancienne | Nouvelle | Migration |
|----------|----------|-----------|
| `BACKTEST_DISABLE_GPU=1` | `BACKTEST_BACKEND=cpu` | Utiliser nouvelle |
| `GPU_DISABLED=True` | `BACKTEST_BACKEND=cpu` | Supprimer |
| Aucune var | Auto GPU | ⚠️ Définir `cpu` |

### Code Python

**Avant** (deprecated):

```python
from performance import gpu_available

if gpu_available():
    # ...
```

**Après** (recommandé):

```python
from utils.backend_config import is_gpu_enabled

if is_gpu_enabled():
    from performance.gpu import gpu_available
    if gpu_available():
        # ...
```

---

## Troubleshooting

### "CuPy non installé" en mode GPU

**Cause** : CuPy absent

**Solution** :

```powershell
pip install cupy-cuda12x
```

### "GPU non détecté" alors que hardware présent

**Cause** : Driver NVIDIA absent ou obsolète

**Solution** :

1. Installer/mettre à jour drivers : https://www.nvidia.com/drivers
2. Vérifier CUDA : `nvidia-smi`
3. Tester CuPy : `python -c "import cupy; print(cupy.__version__)"`

### Mode CPU lent malgré multi-core

**Cause** : Variable `NUMBA_NUM_THREADS` non configurée

**Solution** :

```powershell
# Configurer threads Numba (= nombre cores physiques)
$env:NUMBA_NUM_THREADS = "16"
```

Voir `tools/benchmark_system.py` pour recommandations.

### "Import performance déclenche CuPy"

**Cause** : Bug (corrigé)

**Vérification** :

```powershell
pytest tests/test_backend_cpu_only.py::test_performance_import_does_not_trigger_gpu_detection
```

---

## Performance Tuning

### CPU-Only

**Variables d'environnement** :

```powershell
# Threads Numba (= cores physiques)
$env:NUMBA_NUM_THREADS = "16"

# Threads BLAS (1 si multiprocessing actif)
$env:OMP_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"

# Cache Numba
$env:NUMBA_CACHE_DIR = ".numba_cache"

# Workers parallèles (sweep)
$env:BACKTEST_PARALLEL_WORKERS = "32"
```

**Benchmark** :

```powershell
python tools/benchmark_system.py --benchmark numba
```

### GPU

**Variables d'environnement** :

```powershell
# Forcer GPU spécifique
$env:BACKTEST_GPU_ID = "0"

# Limiter GPUs visibles (CUDA)
$env:CUDA_VISIBLE_DEVICES = "0,1"

# Backend GPU
$env:BACKTEST_BACKEND = "gpu"
```

**Benchmark** :

```powershell
python cli check-gpu --benchmark
```

---

## Références

- **Diagnostic complet** : `docs/CPU_ONLY_DIAGNOSTIC.md`
- **Tests** : `tests/test_backend_cpu_only.py`
- **Code** : `utils/backend_config.py`, `performance/device_backend.py`
- **Benchmark** : `tools/benchmark_system.py`

---

**Auteurs** : Claude (GitHub Copilot)
**Dernière mise à jour** : 6 février 2026
