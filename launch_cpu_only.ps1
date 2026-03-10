# ============================================================================
# BACKTEST_CORE - Launcher CPU-ONLY
# ============================================================================
# Ce script PowerShell configure l'environnement CPU-only et lance le backtest.
# Les variables d'environnement sont chargées depuis .env automatiquement.
#
# Usage:
#   .\launch_cpu_only.ps1              # Lance le test de validation
#   .\launch_cpu_only.ps1 ui           # Lance l'interface Streamlit
#   .\launch_cpu_only.ps1 sweep        # Lance un sweep d'optimisation
# ============================================================================

param(
    [string]$Mode = "test"
)

Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "BACKTEST_CORE - CPU-ONLY MODE LAUNCHER" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

# Vérifier que .env existe
if (-not (Test-Path ".env")) {
    Write-Host "❌ ERREUR: Fichier .env non trouvé!" -ForegroundColor Red
    Write-Host "   Créez le fichier .env à la racine du projet." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

Write-Host "✅ Fichier .env trouvé" -ForegroundColor Green
Write-Host ""

# Installer python-dotenv si nécessaire
Write-Host "[1/3] Vérification des dépendances..." -ForegroundColor Yellow
python -c "import dotenv" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "   Installation de python-dotenv..." -ForegroundColor Yellow
    pip install python-dotenv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   ❌ Erreur installation python-dotenv" -ForegroundColor Red
        exit 1
    }
    Write-Host "   ✅ python-dotenv installé" -ForegroundColor Green
} else {
    Write-Host "   ✅ python-dotenv déjà installé" -ForegroundColor Green
}
Write-Host ""

# Lancer selon le mode
Write-Host "[2/3] Lancement du mode: $Mode" -ForegroundColor Yellow
Write-Host ""

switch ($Mode) {
    "test" {
        Write-Host ">>> Exécution du test de validation CPU-only..." -ForegroundColor Cyan
        Write-Host ""
        python test_cpu_only_mode.py
        $exitCode = $LASTEXITCODE
    }
    "ui" {
        Write-Host ">>> Lancement de l'interface Streamlit..." -ForegroundColor Cyan
        Write-Host ""
        streamlit run ui/main.py
        $exitCode = $LASTEXITCODE
    }
    "sweep" {
        Write-Host ">>> Lancement d'un sweep d'optimisation..." -ForegroundColor Cyan
        Write-Host ""
        python examples/sweep_30gb_ram_optimized.py
        $exitCode = $LASTEXITCODE
    }
    default {
        Write-Host "❌ Mode inconnu: $Mode" -ForegroundColor Red
        Write-Host ""
        Write-Host "Modes disponibles:" -ForegroundColor Yellow
        Write-Host "  test   - Test de validation CPU-only" -ForegroundColor White
        Write-Host "  ui     - Interface Streamlit" -ForegroundColor White
        Write-Host "  sweep  - Sweep d'optimisation" -ForegroundColor White
        Write-Host ""
        exit 1
    }
}

Write-Host ""
Write-Host "[3/3] Vérification VRAM finale..." -ForegroundColor Yellow
Write-Host ""

# Vérifier VRAM avec nvidia-smi
$nvidiaSmi = nvidia-smi --query-gpu=index,name,memory.used --format=csv,noheader,nounits 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "État VRAM des GPUs:" -ForegroundColor Cyan
    Write-Host ""
    $nvidiaSmi | ForEach-Object {
        $parts = $_ -split ","
        $gpuId = $parts[0].Trim()
        $gpuName = $parts[1].Trim()
        $vramUsed = [int]$parts[2].Trim()

        if ($vramUsed -eq 0) {
            Write-Host "  ✅ GPU $gpuId ($gpuName): ${vramUsed} MB VRAM utilisée" -ForegroundColor Green
        } elseif ($vramUsed -lt 100) {
            Write-Host "  ⚠️  GPU $gpuId ($gpuName): ${vramUsed} MB VRAM utilisée (résiduel)" -ForegroundColor Yellow
        } else {
            Write-Host "  ❌ GPU $gpuId ($gpuName): ${vramUsed} MB VRAM utilisée (conflit possible!)" -ForegroundColor Red
        }
    }
    Write-Host ""
} else {
    Write-Host "⚠️  nvidia-smi non disponible (vérification VRAM impossible)" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

exit $exitCode
