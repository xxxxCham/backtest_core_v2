# Script de vérification de l'environnement Backtest Core
# Date: 4 février 2026

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Vérification de l'environnement" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Python système
Write-Host "1. Python système:" -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "   ✅ $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "   ❌ Python non trouvé dans PATH" -ForegroundColor Red
    exit 1
}

# 2. Environnement virtuel
Write-Host "`n2. Environnement virtuel:" -ForegroundColor Yellow
$venvPath = if (Test-Path ".venv_new\Scripts\python.exe") {
    ".venv_new"
} elseif (Test-Path ".venv\Scripts\python.exe") {
    ".venv"
} else {
    $null
}

if ($venvPath) {
    Write-Host "   ✅ Trouvé: $venvPath" -ForegroundColor Green
    $venvPython = Join-Path $venvPath "Scripts\python.exe"
    $venvVersion = & $venvPython --version 2>&1
    Write-Host "   ✅ $venvVersion" -ForegroundColor Green
} else {
    Write-Host "   ❌ Aucun environnement virtuel trouvé" -ForegroundColor Red
    Write-Host "   💡 Exécutez: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

# 3. Packages critiques
Write-Host "`n3. Packages critiques:" -ForegroundColor Yellow
$criticalPackages = @("streamlit", "pandas", "numpy", "numba", "plotly", "optuna")
$venvPip = Join-Path $venvPath "Scripts\pip.exe"
$installedPackages = & $venvPip list 2>&1 | Out-String

$allInstalled = $true
foreach ($pkg in $criticalPackages) {
    if ($installedPackages -match $pkg) {
        $version = ($installedPackages -split "`n" | Select-String $pkg) -replace '\s+', ' '
        Write-Host "   ✅ $version" -ForegroundColor Green
    } else {
        Write-Host "   ❌ $pkg non installé" -ForegroundColor Red
        $allInstalled = $false
    }
}

if (-not $allInstalled) {
    Write-Host "`n   💡 Installez les packages manquants:" -ForegroundColor Yellow
    Write-Host "   pip install -r requirements.txt" -ForegroundColor Cyan
    exit 1
}

# 4. Modules du projet
Write-Host "`n4. Modules du projet:" -ForegroundColor Yellow
$modules = @("agents", "backtest", "strategies", "indicators", "ui", "utils", "performance")
$venvPython = Join-Path $venvPath "Scripts\python.exe"

foreach ($module in $modules) {
    $testCmd = "import $module; print('OK')"
    $result = & $venvPython -c $testCmd 2>&1
    if ($result -match "OK") {
        Write-Host "   ✅ $module" -ForegroundColor Green
    } else {
        Write-Host "   ❌ $module (erreur d'import)" -ForegroundColor Red
        Write-Host "      $result" -ForegroundColor DarkRed
    }
}

# 5. Fichiers de configuration
Write-Host "`n5. Fichiers de configuration:" -ForegroundColor Yellow
$configFiles = @(
    "requirements.txt",
    "requirements-performance.txt",
    "config/indicator_ranges.toml",
    "ui/app.py",
    "run_streamlit.bat"
)

foreach ($file in $configFiles) {
    if (Test-Path $file) {
        Write-Host "   ✅ $file" -ForegroundColor Green
    } else {
        Write-Host "   ❌ $file manquant" -ForegroundColor Red
    }
}

# 6. GPU (optionnel)
Write-Host "`n6. Support GPU (optionnel):" -ForegroundColor Yellow
$cudaTest = & $venvPython -c "try: import cupy; print('CuPy:', cupy.__version__); print('GPU OK')
except: print('CuPy non installé (mode CPU-only)')" 2>&1

if ($cudaTest -match "GPU OK") {
    Write-Host "   ✅ $cudaTest" -ForegroundColor Green
} else {
    Write-Host "   ℹ️  Mode CPU uniquement (normal)" -ForegroundColor Cyan
}

# Résumé
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "✅ ENVIRONNEMENT PRÊT!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Pour lancer l'interface:" -ForegroundColor Yellow
Write-Host "  .\run_streamlit.bat" -ForegroundColor Cyan
Write-Host ""
Write-Host "Environnement utilisé: $venvPath" -ForegroundColor Gray
