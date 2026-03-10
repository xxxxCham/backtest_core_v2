# ============================================
# Script PowerShell - Configuration Windows pour performances maximales
# Optimisé pour Ryzen 9950X (32 threads) + DDR5 60GB
# ============================================
# EXÉCUTER EN ADMINISTRATEUR:
#   powershell -ExecutionPolicy Bypass -File .\tools\scripts\configure_windows_perf.ps1
# ============================================

param(
    [switch]$Apply,
    [switch]$Revert,
    [switch]$CheckOnly
)

Write-Host ""
Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host "🚀 Configuration Windows pour Backtest Core" -ForegroundColor Cyan
Write-Host "=" * 60 -ForegroundColor Cyan

# Vérifier si admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host ""
    Write-Host "⚠️  Ce script nécessite des droits administrateur pour certaines options." -ForegroundColor Yellow
    Write-Host "    Relancez PowerShell en tant qu'Administrateur." -ForegroundColor Yellow
}

# ============================================
# 1. VÉRIFICATION CONFIGURATION ACTUELLE
# ============================================
Write-Host ""
Write-Host "📊 Configuration Actuelle" -ForegroundColor Green
Write-Host "-" * 40

# CPU
$cpu = Get-CimInstance -ClassName Win32_Processor
Write-Host "  CPU: $($cpu.Name)"
Write-Host "  Cores physiques: $($cpu.NumberOfCores)"
Write-Host "  Threads logiques: $($cpu.NumberOfLogicalProcessors)"

# RAM
$ram = Get-CimInstance -ClassName Win32_ComputerSystem
$ramGB = [math]::Round($ram.TotalPhysicalMemory / 1GB, 1)
Write-Host "  RAM: $ramGB GB"

# Plan d'alimentation
$powerPlan = powercfg /getactivescheme
Write-Host "  Plan actuel: $powerPlan"

# ============================================
# 2. PLAN D'ALIMENTATION HAUTE PERFORMANCE
# ============================================
Write-Host ""
Write-Host "⚡ Plan d'Alimentation" -ForegroundColor Green
Write-Host "-" * 40

$highPerfGUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
$currentPlan = (powercfg /getactivescheme) -replace ".*GUID du schéma d'alimentation : ([a-f0-9-]+).*", '$1'

if ($currentPlan -eq $highPerfGUID) {
    Write-Host "  ✅ Haute Performance déjà activé" -ForegroundColor Green
} else {
    Write-Host "  ⚠️ Plan actuel n'est pas Haute Performance" -ForegroundColor Yellow
    if ($Apply -and $isAdmin) {
        Write-Host "  → Activation Haute Performance..." -ForegroundColor Cyan
        powercfg /setactive $highPerfGUID
        Write-Host "  ✅ Haute Performance activé" -ForegroundColor Green
    } else {
        Write-Host "  → Pour activer: powercfg /setactive $highPerfGUID" -ForegroundColor Gray
    }
}

# ============================================
# 3. VARIABLES D'ENVIRONNEMENT
# ============================================
Write-Host ""
Write-Host "🔧 Variables d'Environnement" -ForegroundColor Green
Write-Host "-" * 40

$envVars = @{
    "BACKTEST_CPU_MULTIPLIER" = "2.0"
    "NUMBA_NUM_THREADS" = "$($cpu.NumberOfLogicalProcessors)"
    "NUMBA_CACHE_DIR" = ".numba_cache"
    "JOBLIB_MAX_NBYTES" = "500M"
    "JOBLIB_VERBOSE" = "0"
    "OMP_NUM_THREADS" = "$($cpu.NumberOfLogicalProcessors)"
    "MKL_NUM_THREADS" = "$($cpu.NumberOfLogicalProcessors)"
}

foreach ($var in $envVars.GetEnumerator()) {
    $currentVal = [Environment]::GetEnvironmentVariable($var.Key, "User")
    if ($currentVal -eq $var.Value) {
        Write-Host "  ✅ $($var.Key) = $($var.Value)" -ForegroundColor Green
    } elseif ($currentVal) {
        Write-Host "  ⚠️ $($var.Key) = $currentVal (recommandé: $($var.Value))" -ForegroundColor Yellow
    } else {
        Write-Host "  ❌ $($var.Key) non défini (recommandé: $($var.Value))" -ForegroundColor Red
        if ($Apply) {
            [Environment]::SetEnvironmentVariable($var.Key, $var.Value, "User")
            Write-Host "     → Défini à $($var.Value)" -ForegroundColor Cyan
        }
    }
}

# ============================================
# 4. PRIORITÉ PROCESSUS PYTHON (Session)
# ============================================
Write-Host ""
Write-Host "🎯 Priorité Processus" -ForegroundColor Green
Write-Host "-" * 40

$pythonProcesses = Get-Process python -ErrorAction SilentlyContinue
if ($pythonProcesses) {
    foreach ($proc in $pythonProcesses) {
        Write-Host "  Python PID $($proc.Id): Priorité = $($proc.PriorityClass)"
        if ($Apply) {
            try {
                $proc.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::High
                Write-Host "    → Priorité élevée à High" -ForegroundColor Cyan
            } catch {
                Write-Host "    → Erreur: $_" -ForegroundColor Red
            }
        }
    }
} else {
    Write-Host "  Aucun processus Python en cours"
}

# ============================================
# 5. FICHIER .ENV
# ============================================
Write-Host ""
Write-Host "📝 Fichier .env" -ForegroundColor Green
Write-Host "-" * 40

$envFile = ".\.env"
if (Test-Path $envFile) {
    Write-Host "  ✅ Fichier .env présent" -ForegroundColor Green

    # Vérifier les variables clés
    $envContent = Get-Content $envFile -Raw
    $keyVars = @("BACKTEST_CPU_MULTIPLIER", "NUMBA_NUM_THREADS", "JOBLIB_MAX_NBYTES")
    foreach ($var in $keyVars) {
        if ($envContent -match "$var=") {
            Write-Host "  ✅ $var configuré dans .env" -ForegroundColor Green
        } else {
            Write-Host "  ⚠️ $var manquant dans .env" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "  ❌ Fichier .env non trouvé" -ForegroundColor Red
}

# ============================================
# 6. RÉSUMÉ ET COMMANDES
# ============================================
Write-Host ""
Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host "📋 RÉSUMÉ DES ACTIONS" -ForegroundColor Cyan
Write-Host "=" * 60 -ForegroundColor Cyan

if (-not $Apply) {
    Write-Host ""
    Write-Host "Pour appliquer les optimisations:" -ForegroundColor Yellow
    Write-Host "  .\tools\scripts\configure_windows_perf.ps1 -Apply" -ForegroundColor White
    Write-Host ""
    Write-Host "Commandes manuelles (Administrateur):" -ForegroundColor Yellow
    Write-Host "  # Activer Haute Performance" -ForegroundColor Gray
    Write-Host "  powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c" -ForegroundColor White
    Write-Host ""
    Write-Host "  # Définir variables d'environnement" -ForegroundColor Gray
    Write-Host '  [Environment]::SetEnvironmentVariable("NUMBA_NUM_THREADS", "32", "User")' -ForegroundColor White
    Write-Host ""
    Write-Host "  # Priorité haute pour Python actuel" -ForegroundColor Gray
    Write-Host '  (Get-Process python).PriorityClass = "High"' -ForegroundColor White
} else {
    Write-Host ""
    Write-Host "✅ Optimisations appliquées!" -ForegroundColor Green
    Write-Host ""
    Write-Host "⚠️  Redémarrez votre terminal pour que les variables" -ForegroundColor Yellow
    Write-Host "   d'environnement prennent effet." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=" * 60 -ForegroundColor Cyan



