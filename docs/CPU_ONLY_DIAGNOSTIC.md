# Diagnostic CPU-Only Mode - Rapport de Cartographie

**Date**: 6 février 2026
**Objectif**: Rendre le mode CPU-only 100% propre (zéro init CUDA / zéro VRAM touchée)

## 📊 Cartographie des Touchpoints GPU/CUDA

### Résumé Exécutif

| Catégorie | Fichiers | Statut | Priorité |
|-----------|----------|--------|----------|
| **Imports conditionnels CuPy** | 26 fichiers | ⚠️ À protéger | HAUTE |
| **Détection GPU automatique** | 4 modules | ⚠️ À désactiver | HAUTE |
| **Imports implicites dans __init__** | 2 fichiers | ❌ CRITIQUE | CRITIQUE |
| **Cache Numba versionné** | `.numba_cache/` | ❌ À nettoyer | MOYENNE |
| **Scripts tools GPU** | 0 trouvés | ✅ OK | BASSE |

---

## 🔍 Analyse Détaillée

### 1. Configuration Actuelle

**Performance/gpu.py** (ligne 33-36):
```python
# Désactivation forcée du GPU : opération CPU-only (RAM)
GPU_DISABLED = True
HAS_CUPY = False
cp = None
```

✅ **Bon point**: Variable `GPU_DISABLED` déjà présente
❌ **Problème**: Pas respectée ailleurs dans le code

### 2. Imports CuPy (26 fichiers détectés)

#### CRITIQUE - Imports implicites dans __init__.py

**performance/__init__.py** (ligne 22):
```python
from performance.gpu import (
    GPUIndicatorCalculator,
    benchmark_gpu_cpu,
    get_gpu_info,
    gpu_available,
    to_cpu,
    to_gpu,
)
```

**Impact**: Importer `performance` déclenche automatiquement le chargement de `gpu.py`
**Solution**: Lazy import ou suppression de l'import automatique

#### Imports conditionnels (24 autres fichiers)

| Module | Type Import | Dangerosité | Note |
|--------|-------------|-------------|------|
| `performance/device_backend.py` | Lazy (L99, L182, L383, L391, L400, L421) | ✅ OK | Imports dans fonctions |
| `performance/benchmark.py` | Lazy (L358) | ✅ OK | Fonction isolée |
| `performance/hybrid_compute.py` | Lazy (L252, L353) | ✅ OK | Contexte isolé |
| `utils/gpu_utils.py` | Top-level (L28) | ⚠️ MOYEN | Mais avec `HAS_CUPY` guard |
| `utils/gpu_oom.py` | Dans docstrings (L83, L116, L133...) | ✅ OK | Exemples seulement |
| `utils/error_recovery.py` | Lazy (L328, L434) | ✅ OK | Fonction de fallback |
| `cli/commands.py` | Lazy (L1633) | ✅ OK | Commande check-gpu uniquement |
| `ui/helpers.py`, `ui/helpers_backup.py` | Lazy (L1131, L1141) | ✅ OK | Diagnostic UI |
| `ui/emergency_stop.py` | Lazy (L235) | ✅ OK | Cleanup emergency |

**Conclusion**: La plupart des imports sont **lazy** (dans fonctions), ce qui est bien. Le problème majeur est `performance/__init__.py`.

### 3. Détection GPU Automatique

#### device_backend.py (ligne 93-130)

```python
def _try_init_gpu(self) -> bool:
    """Tente d'initialiser le support GPU."""
    # Vérifier si désactivé par env var
    if os.environ.get("BACKTEST_DISABLE_GPU", "").lower() in ("1", "true", "yes"):
        logger.info("GPU désactivé par BACKTEST_DISABLE_GPU")
        self._setup_cpu()
        return False

    try:
        import cupy as cp
        # ...
```

✅ **Bon point**: Variable d'environnement `BACKTEST_DISABLE_GPU` déjà présente
❌ **Problème**: Appel de `_try_init_gpu()` dans `__init__()` même en mode CPU-only

#### GPUDeviceManager (performance/gpu.py, ligne 47-90)

```python
def __init__(self):
    if GPUDeviceManager._initialized:
        return

    # ...
    if HAS_CUPY:
        self._detect_devices()
        self._select_best_device()
```

✅ **Bon point**: Guard `if HAS_CUPY` présent
❌ **Problème**: `GPUDeviceManager` instancié même si GPU_DISABLED

### 4. Chemins "Fast" (Numba CPU, pas GPU)

**backtest/execution_fast.py** et **backtest/simulator_fast.py**:

✅ **EXCELLENT**: Ces fichiers utilisent **Numba CPU uniquement** (`@njit`, pas de CUDA)
✅ **Pas de problème**: `HAS_NUMBA` détecte l'installation, mais reste CPU-only

```python
try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
```

### 5. Cache Numba

```bash
Test-Path .numba_cache
# Output: True
```

❌ **Problème**: Cache Numba versionné dans le repo
**Impact**: Pollution du repo, cache peut contenir des artefacts GPU
**Solution**: Ajouter à `.gitignore` et supprimer du suivi

### 6. Scripts Tools GPU

**Fichiers mentionnés dans la demande**: NON TROUVÉS
- `check_gpu.py`: ❌ N'existe pas
- `test_cpu_gpu_parallel.py`: ❌ N'existe pas
- `configure_ollama_multigpu.py`: ❌ N'existe pas

**Fichiers existants**:
- `tools/benchmark_system.py`: ✅ Présent, aucun import GPU direct

**Conclusion**: Scripts GPU tools mentionnés n'existent pas dans le repo actuel.

### 7. Variables d'Environnement Existantes

Aucun fichier `.env` trouvé, mais variables utilisées dans le code:

| Variable | Usage | Fichier |
|----------|-------|---------|
| `BACKTEST_DISABLE_GPU` | Désactive GPU | `device_backend.py` L95 |
| `BACKTEST_GPU_ID` | Force GPU spécifique | `gpu.py` L135 |
| `CUDA_VISIBLE_DEVICES` | Limite GPUs visibles | Commentaire `gpu.py` L57 |

---

## 🎯 Problèmes Identifiés (par priorité)

### CRITIQUE ❌

1. **Import implicite dans performance/__init__.py**
   - Fichier: `performance/__init__.py` ligne 22
   - Problème: `from performance.gpu import ...` exécuté à l'import du package
   - Impact: Charger `performance` = tenter de détecter GPU
   - Solution: Supprimer ou lazy import

### HAUTE ⚠️

2. **device_backend.py initialise GPU dans __init__()**
   - Fichier: `performance/device_backend.py` ligne 86
   - Problème: `_try_init_gpu()` appelé systématiquement
   - Impact: Tente import CuPy même si mode CPU-only souhaité
   - Solution: Vérifier variable backend AVANT import

3. **Pas de mécanisme BACKTEST_BACKEND centralisé**
   - Problème: Logique éparpillée (`GPU_DISABLED`, `BACKTEST_DISABLE_GPU`)
   - Impact: Incohérence, confusion, maintenance difficile
   - Solution: Variable unique `BACKTEST_BACKEND=cpu|gpu|auto`

4. **GPUDeviceManager instancié sans raison**
   - Fichier: `performance/gpu.py` ligne 74
   - Problème: Singleton créé même si `GPU_DISABLED=True`
   - Impact: Code mort, overhead minimal mais confus
   - Solution: Lazy singleton uniquement si backend=gpu

### MOYENNE 🟡

5. **Cache Numba versionné**
   - Fichier: `.numba_cache/`
   - Problème: Dossier dans le repo (test via `Test-Path`)
   - Impact: Pollution, cache peut contenir code GPU
   - Solution: `.gitignore` + `git rm --cached`

6. **Numba parallel=True sans contrôle workers**
   - Fichier: `backtest/sweep_numba.py` (mentionné dans AGENTS.md)
   - Problème: Threads Numba * workers ProcessPool = oversubscription
   - Impact: Saturation CPU, performances dégradées
   - Solution: `NUMBA_NUM_THREADS=1` dans workers, ou désactiver parallel

---

## 🚀 Solutions Proposées

### Étape B - Backend Selection (Patch minimal)

**1. Créer utils/backend_config.py** (nouveau fichier)

```python
"""Configuration centralisée du backend de calcul."""
import os
from enum import Enum

class BackendType(Enum):
    CPU = "cpu"
    GPU = "gpu"
    AUTO = "auto"

_BACKEND = None

def get_backend() -> BackendType:
    """Retourne le backend configuré."""
    global _BACKEND
    if _BACKEND is None:
        env = os.environ.get("BACKTEST_BACKEND", "cpu").lower()
        if env == "gpu":
            _BACKEND = BackendType.GPU
        elif env == "auto":
            _BACKEND = BackendType.AUTO
        else:
            _BACKEND = BackendType.CPU
    return _BACKEND

def is_gpu_enabled() -> bool:
    """True si GPU peut être utilisé."""
    backend = get_backend()
    if backend == BackendType.CPU:
        return False
    return True  # AUTO ou GPU
```

**2. Modifier performance/__init__.py** (suppression imports GPU)

```python
# AVANT (ligne 22-29):
from performance.gpu import (
    GPUIndicatorCalculator,
    benchmark_gpu_cpu,
    get_gpu_info,
    gpu_available,
    to_cpu,
    to_gpu,
)

# APRÈS:
# Imports GPU supprimés (lazy import uniquement)
# Utiliser: from performance.gpu import gpu_available
```

**3. Modifier performance/device_backend.py** (lazy GPU)

```python
# AVANT (ligne 86):
def __init__(self):
    if self._initialized:
        return
    # ...
    self._try_init_gpu()
    self._initialized = True

# APRÈS:
def __init__(self):
    if self._initialized:
        return
    # ...
    from utils.backend_config import is_gpu_enabled
    if is_gpu_enabled():
        self._try_init_gpu()
    else:
        self._setup_cpu()
    self._initialized = True
```

**4. Modifier performance/gpu.py** (lazy singleton)

```python
# AVANT (ligne 250):
_gpu_manager: Optional[GPUDeviceManager] = None

# APRÈS:
_gpu_manager: Optional[GPUDeviceManager] = None

def get_gpu_manager() -> Optional[GPUDeviceManager]:
    """Lazy singleton GPU manager."""
    global _gpu_manager
    if _gpu_manager is None and HAS_CUPY:
        from utils.backend_config import is_gpu_enabled
        if is_gpu_enabled():
            _gpu_manager = GPUDeviceManager()
    return _gpu_manager
```

**5. Ajouter à .gitignore**

```
# Numba cache
.numba_cache/
__pycache__/
*.pyc

# Old venvs
.venv_old/
```

**6. Nettoyer cache Numba**

```powershell
git rm -r --cached .numba_cache/
```

**7. Contrôler Numba dans workers**

Dans `backtest/worker.py` (ou fichier d'init workers):

```python
def init_worker_with_dataframe(...):
    # Limiter Numba à 1 thread dans workers
    os.environ["NUMBA_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    # ...
```

---

## ✅ Tests de Non-Régression Proposés

### Test 1: Mode CPU strict

```python
# tests/test_backend_cpu_only.py
import os
import sys
import pytest

def test_cpu_only_does_not_import_torch_cuda():
    """Vérifie que mode CPU-only ne touche pas torch/cuda."""
    os.environ["BACKTEST_BACKEND"] = "cpu"

    # Import principal
    import performance

    # Vérifications
    assert "torch" not in sys.modules
    assert "cupy" not in sys.modules
    assert "numba.cuda" not in sys.modules

def test_cpu_only_backend_selection():
    """Vérifie sélection backend CPU."""
    os.environ["BACKTEST_BACKEND"] = "cpu"

    from utils.backend_config import get_backend, BackendType
    assert get_backend() == BackendType.CPU

def test_device_backend_respects_cpu_mode():
    """Vérifie device_backend reste CPU."""
    os.environ["BACKTEST_BACKEND"] = "cpu"

    from performance.device_backend import ArrayBackend
    backend = ArrayBackend()

    assert backend.device_type.value == "cpu"
    assert not backend.gpu_available
```

### Test 2: Mode GPU optionnel

```python
def test_gpu_mode_requires_explicit_flag():
    """GPU activé uniquement si BACKTEST_BACKEND=gpu."""
    os.environ["BACKTEST_BACKEND"] = "gpu"

    from utils.backend_config import is_gpu_enabled
    assert is_gpu_enabled()

@pytest.mark.skipif(not HAS_CUPY, reason="CuPy non installé")
def test_gpu_mode_validates_cuda():
    """Mode GPU doit valider CUDA disponible."""
    os.environ["BACKTEST_BACKEND"] = "gpu"

    from performance.device_backend import ArrayBackend
    backend = ArrayBackend()

    # Si CUDA absent, doit fallback CPU ou raise
    assert backend.device_type.value in ("cpu", "gpu")
```

---

## 📈 Impact Performance Estimé

| Modification | Overhead CPU-only | Gain |
|--------------|-------------------|------|
| Supprimer import GPU dans __init__ | **0ms** | ✅ Pas d'init CuPy |
| Backend config (1 read env var) | **<0.1ms** | ✅ Négligeable |
| Lazy GPU manager | **0ms** | ✅ Pas d'instanciation |
| Numba 1 thread dans workers | **0ms** | ✅ Évite oversubscription |

**Conclusion**: **ZÉRO overhead** dans le chemin CPU-only.

---

## 🎯 Checklist d'Acceptation

- [ ] `BACKTEST_BACKEND=cpu` ne charge jamais CuPy
- [ ] `sys.modules` ne contient ni `torch` ni `cupy` après import
- [ ] Tests unitaires passent (nouveaux tests ajoutés)
- [ ] `.numba_cache/` retiré du suivi git
- [ ] Documentation backend selection ajoutée
- [ ] Performance CPU-only inchangée (benchmark avant/après)
- [ ] Mode GPU reste fonctionnel (BACKTEST_BACKEND=gpu|auto)

---

## 📝 Documentation Utilisateur

**Nouveau fichier**: `docs/BACKEND_SELECTION.md`

```markdown
# Backend Selection: CPU / GPU / Auto

## Configuration

Variable d'environnement: `BACKTEST_BACKEND`

| Valeur | Comportement |
|--------|--------------|
| `cpu` | **CPU-only strict** (défaut) - Aucun GPU utilisé |
| `gpu` | **GPU requis** - Erreur si CUDA absent |
| `auto` | **Détection auto** - GPU si disponible, sinon CPU |

## Exemples

### Mode CPU-only (recommandé)
```powershell
$env:BACKTEST_BACKEND = "cpu"
python run_backtest.py
```

### Mode GPU
```powershell
$env:BACKTEST_BACKEND = "gpu"
python run_backtest.py
```

### Mode Auto (legacy)
```powershell
$env:BACKTEST_BACKEND = "auto"
python run_backtest.py
```

## Diagnostic

```powershell
# Vérifier backend actif
python -c "from utils.backend_config import get_backend; print(get_backend())"
```
```

---

## 🔬 Validation Finale

**Commandes de test**:

```powershell
# 1. Mode CPU strict
$env:BACKTEST_BACKEND = "cpu"
python -c "import performance; import sys; assert 'cupy' not in sys.modules"

# 2. Lancer tests
pytest tests/test_backend_cpu_only.py -v

# 3. Benchmark avant/après
python tools/benchmark_system.py

# 4. Vérifier .gitignore
git status .numba_cache/  # Doit être ignoré
```

---

## 📊 Métriques de Succès

| Critère | Objectif | Validation |
|---------|----------|------------|
| Init CUDA en mode CPU | **0 appels** | `assert 'cupy' not in sys.modules` |
| VRAM touchée | **0 bytes** | nvidia-smi avant/après |
| Overhead CPU-only | **<1ms** | Benchmark diff |
| Tests passent | **100%** | pytest --tb=short |
| Code modifié | **<200 lignes** | git diff --stat |

---

**Signature**: Claude (GitHub Copilot)
**Date**: 6 février 2026
