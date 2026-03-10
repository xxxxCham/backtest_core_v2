# ============================================================================
# Script d'activation Numba/NumPy Threading (VALIDÉ)
# ============================================================================
# Usage: .\activate_numba_final.ps1 avant de lancer vos scripts Python
#
# Configuration testée et validée :
#   - Threading layer: OpenMP
#   - Threads: 32
#   - Throughput: 31,656 backtests/seconde
# ============================================================================

$env:NUMBA_NUM_THREADS = "32"
$env:NUMBA_THREADING_LAYER = "omp"
$env:OMP_NUM_THREADS = "32"
$env:MKL_NUM_THREADS = "32"
$env:OPENBLAS_NUM_THREADS = "32"
$env:NUMEXPR_MAX_THREADS = "32"

Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 69) -ForegroundColor Cyan
Write-Host "✓ Numba Threading ACTIVÉ" -ForegroundColor Green
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 69) -ForegroundColor Cyan

Write-Host "`nConfiguration:" -ForegroundColor Yellow
Write-Host "  Threading layer: OpenMP"
Write-Host "  Threads: 32"
Write-Host "  Performance attendue: 31,000+ backtests/seconde"

Write-Host "`nVariables d'environnement définies:" -ForegroundColor Yellow
Write-Host "  NUMBA_NUM_THREADS=$env:NUMBA_NUM_THREADS"
Write-Host "  NUMBA_THREADING_LAYER=$env:NUMBA_THREADING_LAYER"
Write-Host "  OMP_NUM_THREADS=$env:OMP_NUM_THREADS"
Write-Host "  MKL_NUM_THREADS=$env:MKL_NUM_THREADS"

Write-Host "`nValidation rapide..." -ForegroundColor Yellow
python -c "import os; os.environ.get('NUMBA_THREADING_LAYER') or exit(1); import numba; print(f'  ✓ Threading layer: {numba.config.THREADING_LAYER}'); print(f'  ✓ Threads: {numba.config.NUMBA_NUM_THREADS}')"

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✅ Configuration validée - Vous pouvez lancer vos scripts" -ForegroundColor Green
    Write-Host "`nExemple:" -ForegroundColor Cyan
    Write-Host "  python -m cli.__main__ --strategy bollinger_atr --sweep"
} else {
    Write-Host "`n⚠️  Erreur de validation - Vérifier l'installation de Numba" -ForegroundColor Red
}

Write-Host "`n" -NoNewline
Write-Host ("=" * 70) -ForegroundColor Cyan
