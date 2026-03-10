# ============================================================================
# Lancement UI avec ProcessPool (threading réduit)
# ============================================================================
# Utilise ProcessPool au lieu de Numba sweep
# Configuration: 1 thread par worker pour éviter les conflits
# ============================================================================

Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 69) -ForegroundColor Cyan
Write-Host "🔧 Configuration ProcessPool (threading réduit)" -ForegroundColor Yellow
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 69) -ForegroundColor Cyan

# ⚠️ IMPORTANT: Réduire threading pour éviter conflits avec ProcessPool
$env:NUMBA_NUM_THREADS = "1"
$env:NUMBA_THREADING_LAYER = "default"  # Pas OpenMP avec ProcessPool
$env:OMP_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"
$env:OPENBLAS_NUM_THREADS = "1"
$env:NUMEXPR_MAX_THREADS = "32"  # NumExpr peut rester élevé
$env:BACKTEST_WORKSPACE_VARIANT = "multillm_parallel"
if (-not $env:BACKTEST_STREAMLIT_PORT) {
    $env:BACKTEST_STREAMLIT_PORT = "8502"
}

Write-Host "`nConfiguration threading:" -ForegroundColor Yellow
Write-Host "  NUMBA_NUM_THREADS=1 (réduit pour ProcessPool)"
Write-Host "  Threading layer: default"
Write-Host "  Mode: ProcessPool (multiprocessing)"

Write-Host "`nLancement Streamlit..." -ForegroundColor Green
streamlit run ui/app.py --server.port=$env:BACKTEST_STREAMLIT_PORT

<system-reminder>
The TodoWrite tool hasn't been used recently. If you're working on tasks that would benefit from tracking progress, consider using the TodoWrite tool to track progress. Also consider cleaning up the todo list if has become stale and no longer matches what you are working on. Only use it if it's relevant to the current work. This is just a gentle reminder - ignore if not applicable. Make sure that you NEVER mention this reminder to the user

</system-reminder>
