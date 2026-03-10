# ============================================================================
# Configuration Numba Threading pour backtest_core
# ============================================================================
# Active TBB (Thread Building Blocks) et optimise le threading Numba/NumPy
# Usage: .\setup_numba_threading.ps1

Write-Host "=== Configuration Numba/NumPy Threading ===" -ForegroundColor Cyan

# 1. Installer TBB (Intel Threading Building Blocks)
Write-Host "`n[1/4] Installation TBB..." -ForegroundColor Yellow
pip install tbb intel-openmp

# 2. Vérifier/installer Numba avec TBB
Write-Host "`n[2/4] Mise à jour Numba..." -ForegroundColor Yellow
pip install --upgrade "numba>=0.60.0"

# 3. Configurer variables d'environnement (session PowerShell actuelle)
Write-Host "`n[3/4] Configuration variables d'environnement..." -ForegroundColor Yellow

# Nombre de threads = nombre de cœurs logiques
$numCores = (Get-WmiObject Win32_Processor).NumberOfLogicalProcessors
Write-Host "  Cœurs logiques détectés: $numCores"

$env:NUMBA_NUM_THREADS = "$numCores"
$env:NUMBA_THREADING_LAYER = "tbb"
$env:NUMBA_CACHE_DIR = "$PWD\.numba_cache"
$env:OMP_NUM_THREADS = "$numCores"
$env:MKL_NUM_THREADS = "$numCores"
$env:OPENBLAS_NUM_THREADS = "$numCores"

Write-Host "  NUMBA_NUM_THREADS=$env:NUMBA_NUM_THREADS" -ForegroundColor Green
Write-Host "  NUMBA_THREADING_LAYER=$env:NUMBA_THREADING_LAYER" -ForegroundColor Green

# 4. Test de validation
Write-Host "`n[4/4] Test de validation..." -ForegroundColor Yellow

python -c @"
import numba
import numpy as np
import os

print('✓ Numba version:', numba.__version__)
print('✓ NumPy version:', np.__version__)
print('✓ Threading layer:', numba.config.THREADING_LAYER)
print('✓ Threads configurés:', numba.config.NUMBA_NUM_THREADS)
print('✓ Cache dir:', os.environ.get('NUMBA_CACHE_DIR', 'default'))

# Test prange
@numba.njit(parallel=True, fastmath=True)
def test_prange():
    total = 0.0
    for i in numba.prange(1000):
        total += i * 2.0
    return total

result = test_prange()
print('✓ Test prange: OK (result={:.0f})'.format(result))
"@

Write-Host "`n=== Configuration terminée ===" -ForegroundColor Green
Write-Host "`nPour rendre permanent (optionnel):" -ForegroundColor Cyan
Write-Host "  1. Variables utilisateur Windows:" -ForegroundColor Yellow
Write-Host "     [System.Environment]::SetEnvironmentVariable('NUMBA_NUM_THREADS','$numCores','User')"
Write-Host "     [System.Environment]::SetEnvironmentVariable('NUMBA_THREADING_LAYER','tbb','User')"
Write-Host "`n  2. Ou créer un fichier .env dans backtest_core/" -ForegroundColor Yellow
