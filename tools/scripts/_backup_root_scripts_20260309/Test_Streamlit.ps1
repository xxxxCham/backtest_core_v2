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
$env:BACKTEST_DATA_DIR = "D:\my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet"
$env:BACKTEST_WORKER_THREADS = "1"
Write-Host "  BACKTEST_DATA_DIR = $env:BACKTEST_DATA_DIR" -ForegroundColor Gray
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
