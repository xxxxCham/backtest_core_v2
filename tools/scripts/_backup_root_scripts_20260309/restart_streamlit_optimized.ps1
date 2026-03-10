#!/usr/bin/env pwsh
# ============================================================================
# REDÉMARRAGE STREAMLIT AVEC CONFIGURATION CPU OPTIMALE
# ============================================================================

Write-Host ""
Write-Host "🚀 Configuration CPU Optimale - Ryzen 9 9950X" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Charger les variables depuis .env
if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match '^\s*([^#=]+?)\s*=\s*(.+?)\s*$') {
            $name = $matches[1]
            $value = $matches[2]
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
            Write-Host "✓ $name = $value" -ForegroundColor Green
        }
    }
    Write-Host ""
} else {
    Write-Host "⚠️  Fichier .env introuvable, utilisation valeurs par défaut" -ForegroundColor Yellow
}

# Forcer les valeurs critiques
$env:NUMBA_NUM_THREADS = "16"
$env:NUMBA_THREADING_LAYER = "omp"
$env:BACKTEST_MAX_WORKERS = "24"
$env:JOBLIB_MAX_NBYTES = "500M"
$env:BACKTEST_BACKEND = "cpu"
$env:BACKTEST_WORKSPACE_VARIANT = "multillm_parallel"
if (-not $env:BACKTEST_STREAMLIT_PORT) {
    $env:BACKTEST_STREAMLIT_PORT = "8502"
}

Write-Host "🔧 Configuration CPU active:" -ForegroundColor Cyan
Write-Host "   • Workers: 24" -ForegroundColor White
Write-Host "   • Numba Threads: 16 (cores physiques)" -ForegroundColor White
Write-Host "   • Threading Layer: OpenMP" -ForegroundColor White
Write-Host "   • RAM Cache: 500M" -ForegroundColor White
Write-Host "   • Backend: CPU-only" -ForegroundColor White
Write-Host ""

Write-Host "📊 Performance attendue:" -ForegroundColor Cyan
Write-Host "   • CPU: 95-100% (optimal)" -ForegroundColor Green
Write-Host "   • Vitesse ProcessPool: 3,000-6,000 runs/s" -ForegroundColor Green
Write-Host "   • Vitesse Numba: 20,000-60,000 runs/s" -ForegroundColor Green
Write-Host ""

# Tuer les processus Streamlit existants
Write-Host "🔄 Arrêt des processus Streamlit existants..." -ForegroundColor Yellow
Get-Process -Name "streamlit" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

# Activer l'environnement virtuel
Write-Host "📦 Activation environnement virtuel..." -ForegroundColor Yellow
& ".venv\Scripts\Activate.ps1"

# Lancer Streamlit
Write-Host ""
Write-Host "🚀 Démarrage Streamlit Multi-LLM sur http://localhost:$env:BACKTEST_STREAMLIT_PORT" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "💡 Astuce: Utilisez une stratégie supportée par Numba pour performance maximale:" -ForegroundColor Cyan
Write-Host "   • bollinger_atr / bollinger_atr_v2 / bollinger_atr_v3" -ForegroundColor White
Write-Host "   • ema_cross" -ForegroundColor White
Write-Host "   • rsi_reversal" -ForegroundColor White
Write-Host ""
Write-Host "📝 Vérifiez les logs pour voir quel mode est sélectionné:" -ForegroundColor Cyan
Write-Host "   [EXECUTION PATH] 🚀 NUMBA SWEEP sélectionné" -ForegroundColor White
Write-Host "   [EXECUTION PATH] 🔄 PROCESSPOOL sélectionné" -ForegroundColor White
Write-Host ""

streamlit run ui\app.py --server.port $env:BACKTEST_STREAMLIT_PORT --server.headless true
