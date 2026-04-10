# Script PowerShell pour lancer Streamlit avec capture des erreurs
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Test de lancement Streamlit" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Set-Location $PSScriptRoot

# Activer venv
if (Test-Path ".venv\Scripts\Activate.ps1") {
    Write-Host "Activation de l'environnement virtuel..." -ForegroundColor Yellow
    & .\.venv\Scripts\Activate.ps1
    Write-Host "OK - Environnement active" -ForegroundColor Green
}

Write-Host ""
Write-Host "Variables d'environnement:" -ForegroundColor Yellow
$dataCandidates = @(
    "D:\.my_soft\gestionnaire_telechargement_multi-timeframe_clean\processed\parquet",
    "D:\my_soft\gestionnaire_telechargement_multi-timeframe_clean\processed\parquet",
    "D:\.my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet",
    "D:\my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet"
)
$resolvedDataDir = $dataCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($resolvedDataDir) {
    $env:BACKTEST_DATA_DIR = $resolvedDataDir
} else {
    Remove-Item Env:BACKTEST_DATA_DIR -ErrorAction SilentlyContinue
}
$env:BACKTEST_WORKER_THREADS = "1"
if ($env:BACKTEST_DATA_DIR) {
    Write-Host "  BACKTEST_DATA_DIR = $env:BACKTEST_DATA_DIR" -ForegroundColor Gray
} else {
    Write-Host "  BACKTEST_DATA_DIR = <auto-detection loader>" -ForegroundColor Gray
}
Write-Host "  BACKTEST_WORKER_THREADS = $env:BACKTEST_WORKER_THREADS" -ForegroundColor Gray

Write-Host ""
Write-Host "Lancement de Streamlit..." -ForegroundColor Yellow
Write-Host "URL: http://localhost:8501" -ForegroundColor Cyan
Write-Host ""

try {
    python -m streamlit run ui\app.py --server.port=8501 --browser.gatherUsageStats=false
    $exitCode = $LASTEXITCODE

    Write-Host ""
    if ($exitCode -eq 0) {
        Write-Host "Streamlit arrete normalement" -ForegroundColor Green
    } else {
        Write-Host "ERREUR: Streamlit arrete avec code $exitCode" -ForegroundColor Red
    }
} catch {
    Write-Host "ERREUR CRITIQUE: $_" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}

Write-Host ""
Write-Host "Appuyez sur une touche pour fermer..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
