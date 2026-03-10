# 🚀 Mode CPU-ONLY - Guide d'Utilisation

## 📋 Vue d'Ensemble

Ce guide explique comment utiliser le backtesting en **mode CPU-only strict**, libérant toute la VRAM (40 GB) pour vos LLMs Ollama.

**Architecture:**
- **CPU (32 cores):** Backtesting avec Numba JIT → 2000-3000 bt/sec
- **GPU 1 (RTX 5080 16GB):** 100% disponible pour Ollama
- **GPU 2 (RTX 2060 Super):** 100% disponible pour Ollama
- **RAM (64 GB DDR5):** Cache indicateurs (30+ GB utilisables)

---

## 🎯 Mise en Route (5 minutes)

### 1. Vérifier les fichiers créés

Assurez-vous que ces fichiers existent:

```powershell
# À la racine du projet
ls .env                          # ✅ Configuration CPU-only
ls test_cpu_only_mode.py        # ✅ Script de validation
ls launch_cpu_only.ps1           # ✅ Launcher PowerShell
```

### 2. Installer python-dotenv

```powershell
pip install python-dotenv
```

### 3. Lancer le test de validation

```powershell
# Option A: Via launcher PowerShell (recommandé)
.\launch_cpu_only.ps1 test

# Option B: Directement avec Python
python test_cpu_only_mode.py
```

**Résultat attendu:**
```
============================================================================
TEST CPU-ONLY MODE - VALIDATION
============================================================================

✅ Fichier .env chargé
✅ Toutes les variables d'environnement sont correctes
✅ indicators.registry importé sans activer GPU
✅ backtest.engine importé
✅ Numba JIT disponible (performance optimale)
✅ 10,000 candles générés
✅ Bollinger Bands calculé en 15.2ms (CPU-only)
✅ ATR calculé en 8.1ms (CPU-only)
✅ Cache hit confirmé: 0.45ms
✅ Backtest exécuté en 42.3ms
   - 23 trades
   - Sharpe: 1.45
   - P&L: $2,345.67
✅ Tous les tests CPU-only PASSED
```

### 4. Vérifier VRAM = 0 MB

Pendant que le test tourne, ouvrir un **autre terminal** et vérifier:

```powershell
nvidia-smi
```

**Résultat attendu:**
```
+-----------------------------------------------------------------------------+
| GPU  Name                  Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |
|===========================================================================|
|   0  NVIDIA GeForce RTX 5080       Off  | 00000000:01:00.0  On |                  N/A |
|  0%   45C    P8     0W / 320W |      0MiB / 16384MiB |      0%      Default |
+-------------------------------+----------------------+----------------------+
|   1  NVIDIA GeForce RTX 2060 Super Off  | 00000000:02:00.0 Off |                  N/A |
|  0%   42C    P8     0W / 175W |      0MiB /  8192MiB |      0%      Default |
+-----------------------------------------------------------------------------+
```

✅ **VRAM = 0 MiB pour Python** → Mode CPU-only validé!

---

## 💻 Utilisation Quotidienne

### Lancer l'interface Streamlit

```powershell
.\launch_cpu_only.ps1 ui
```

### Lancer un sweep d'optimisation

```powershell
.\launch_cpu_only.ps1 sweep
```

### Lancer vos propres scripts

```python
# mon_backtest.py
from dotenv import load_dotenv
load_dotenv()  # CRITICAL: Charger .env AVANT imports

from backtest.engine import BacktestEngine
from strategies.bollinger_atr_v3 import BollingerATRv3Strategy

# ... votre code normal
```

Puis lancer:
```powershell
python mon_backtest.py
```

---

## 🔧 Configuration Avancée

### Ajuster le cache indicateurs

Éditer `.env`:

```bash
# Réduire si problèmes RAM (64 GB → ~40 GB utilisé)
INDICATOR_CACHE_MAX_ENTRIES=50000  # Au lieu de 100000

# Activer cache disque hybride si RAM insuffisante
INDICATOR_CACHE_DISK_ENABLED=1
```

### Ajuster le nombre de workers

Éditer `.env`:

```bash
# Réduire si CPU overload (32 cores → 20 workers)
BACKTEST_MAX_WORKERS=20  # Au lieu de 28
```

### Configurer Numba (threads)

Numba permet de régler le nombre de threads et le backend de threading.
Recommandation: `tbb` pour de meilleures performances.

**PowerShell:**
```powershell
$env:NUMBA_NUM_THREADS="24"
$env:NUMBA_THREADING_LAYER="tbb"
python -m cli backtest -s ema_cross -d data/BTCUSDC_1h.parquet
```

**Bash:**
```bash
export NUMBA_NUM_THREADS=24
export NUMBA_THREADING_LAYER=tbb
python -m cli backtest -s ema_cross -d data/BTCUSDC_1h.parquet
```

### Activer logs debug

Éditer `.env`:

```bash
# Pour troubleshooting
LOG_LEVEL=DEBUG
```

---

## 📊 Performance Attendue

### Single Backtest
- **Stratégie simple (EMA cross):** 10-20ms
- **Stratégie complexe (Bollinger ATR v3):** 30-50ms
- **Avec cache hit:** <5ms

### Sweep 2.4M Combinaisons
- **Sans cache:** ~13 heures ❌
- **Avec cache optimal (100K entries):** 30-45 minutes ✅
- **Throughput:** 2000-3000 bt/sec

### Utilisation Ressources
- **RAM:** 35-50 GB / 64 GB (selon cache)
- **CPU:** 90-95% (28 workers)
- **VRAM:** 0 MB (backtesting) + 40 GB (Ollama)

---

## 🐛 Troubleshooting

### Problème: VRAM > 0 MB après test

**Cause:** Import GPU accidentel malgré `.env`

**Solution:**
```powershell
# Vérifier variables d'environnement
python -c "import os; print('BACKTEST_DISABLE_GPU =', os.getenv('BACKTEST_DISABLE_GPU'))"

# Devrait afficher: BACKTEST_DISABLE_GPU = 1
```

Si `None` ou `0`:
1. Vérifier que `.env` existe: `ls .env`
2. Vérifier que `python-dotenv` est installé: `pip list | grep dotenv`
3. Vérifier que votre script charge `.env` AVANT imports

### Problème: Performance dégradée (<500 bt/sec)

**Cause:** Numba non installé ou cache désactivé

**Solution:**
```powershell
# Installer Numba
pip install numba

# Vérifier cache activé dans .env
grep INDICATOR_CACHE_ENABLED .env
# Devrait afficher: INDICATOR_CACHE_ENABLED=1
```

### Problème: RAM saturée (>60 GB)

**Cause:** Cache trop gros ou fuite mémoire

**Solution:**
```bash
# Réduire cache dans .env
INDICATOR_CACHE_MAX_ENTRIES=50000  # Au lieu de 100000
BACKTEST_MAX_WORKERS=20            # Au lieu de 28
```

### Problème: Import errors "Module not found"

**Cause:** Dépendances manquantes

**Solution:**
```powershell
# Installer toutes les dépendances
pip install -r requirements.txt

# Vérifier packages critiques
pip install numba pandas numpy python-dotenv streamlit
```

---

## 📈 Monitoring en Temps Réel

### Terminal 1: Backtesting
```powershell
.\launch_cpu_only.ps1 sweep
```

### Terminal 2: VRAM Monitoring
```powershell
# Rafraîchir toutes les secondes
nvidia-smi -l 1
```

### Terminal 3: RAM/CPU Monitoring
```powershell
# PowerShell
while ($true) {
    $ram = [math]::Round((Get-Counter '\Memory\Available MBytes').CounterSamples.CookedValue / 1024, 1)
    $cpu = [math]::Round((Get-Counter '\Processor(_Total)\% Processor Time').CounterSamples.CookedValue, 1)
    Write-Host "RAM libre: $ram GB | CPU: $cpu%" -ForegroundColor Cyan
    Start-Sleep -Seconds 2
}
```

---

## ✅ Checklist Quotidienne

Avant de lancer un backtest/sweep:

- [ ] `.env` existe et contient `BACKTEST_DISABLE_GPU=1`
- [ ] `python-dotenv` installé: `pip list | grep dotenv`
- [ ] VRAM = 0 MB au repos: `nvidia-smi`
- [ ] Test validation PASSED: `.\launch_cpu_only.ps1 test`
- [ ] RAM disponible > 30 GB
- [ ] Ollama LLMs peuvent démarrer sans OOM

---

## 🎯 Support

En cas de problème:

1. Lancer le test de validation: `python test_cpu_only_mode.py`
2. Vérifier les logs dans la console
3. Vérifier `nvidia-smi` pour VRAM
4. Consulter ce guide section Troubleshooting

---

**Mode CPU-only configuré avec succès! 🚀**

Vos backtests utilisent maintenant 100% CPU (Numba JIT) et 0% GPU,
libérant toute la VRAM (40 GB) pour vos LLMs Ollama.
