param([switch]$DryRun)

# Reorganisation des modeles LLM - cible: K:\models structure par editeur
# Plan: SUPPRIMER les doublons de modeles deja presents sur K: ou Ollama,
# DEPLACER vers K: les modeles uniques.

$ErrorActionPreference = "Stop"
$script:movements = @()
$script:deletions = @()

function MoveModel {
    param(
        [string]$Src,
        [string]$DestDir,
        [string]$DestFile = "model.gguf",
        [bool]$DryRunMode = $false
    )
    if (-not (Test-Path $Src)) {
        Write-Host "  SKIP (introuvable) : $Src" -ForegroundColor DarkGray
        return
    }
    $size = [math]::Round((Get-Item $Src).Length / 1GB, 2)
    $finalDest = Join-Path $DestDir $DestFile
    # Cas: destination existe deja avec meme taille -> source = doublon, on supprime
    if (Test-Path $finalDest) {
        $destSize = [math]::Round((Get-Item $finalDest).Length / 1GB, 2)
        if ([math]::Abs($destSize - $size) -lt 0.01) {
            Write-Host "  DEDUP $Src ($size GB)" -ForegroundColor Yellow
            Write-Host "    deja sur K: en taille identique -> suppression source" -ForegroundColor DarkGray
            if (-not $DryRunMode) {
                try {
                    Remove-Item -Path $Src -Force -ErrorAction Stop
                    $script:deletions += [PSCustomObject]@{
                        Path = $Src; Reason = "Doublon, deja sur K:"; Size_GB = $size
                    }
                } catch {
                    Write-Host "    ECHEC suppression: $($_.Exception.Message)" -ForegroundColor Red
                }
            }
            return
        }
        Write-Host "  CONFLIT $Src ($size GB) - dest existe avec taille differente, skip" -ForegroundColor Yellow
        return
    }
    Write-Host "  MOVE $Src ($size GB)" -ForegroundColor Cyan
    Write-Host "    -> $finalDest" -ForegroundColor Gray
    if ($DryRunMode) { return }
    if (-not (Test-Path $DestDir)) {
        New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
    }
    try {
        Move-Item -Path $Src -Destination $finalDest -ErrorAction Stop
        $script:movements += [PSCustomObject]@{
            Src     = $Src
            Dest    = $finalDest
            Size_GB = $size
        }
        Write-Host "    OK" -ForegroundColor Green
    } catch {
        Write-Host "    ECHEC: $($_.Exception.Message)" -ForegroundColor Red
    }
}

function RemoveFileSafe {
    param(
        [string]$Path,
        [string]$Reason = "",
        [bool]$DryRunMode = $false
    )
    if (-not (Test-Path $Path)) { return }
    $size = [math]::Round((Get-Item $Path).Length / 1GB, 2)
    Write-Host "  DELETE $Path ($size GB)" -ForegroundColor Magenta
    if ($Reason) { Write-Host "    raison: $Reason" -ForegroundColor DarkGray }
    if ($DryRunMode) { return }
    try {
        Remove-Item -Path $Path -Force -ErrorAction Stop
        $script:deletions += [PSCustomObject]@{
            Path    = $Path
            Reason  = $Reason
            Size_GB = $size
        }
        Write-Host "    OK" -ForegroundColor Green
    } catch {
        Write-Host "    ECHEC (probablement fichier verrouille): $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "    A traiter manuellement en mode admin" -ForegroundColor Yellow
    }
}

$dr = $DryRun.IsPresent
if ($dr) { Write-Host "=== DRY RUN ===" -ForegroundColor Yellow }
else     { Write-Host "=== EXECUTION REELLE ===" -ForegroundColor Green }

Write-Host ""
Write-Host "--- 1. SUPPRESSIONS de doublons (deja presents sur K: ou Ollama) ---" -ForegroundColor White
RemoveFileSafe -DryRunMode $dr `
    -Path "D:\Executables\Llama_ccp_win\models\deepseek-coder-33b-instruct.Q4_K_M.gguf" `
    -Reason "Q5 superieur deja sur K:\models\deepseek\deepseek-coder-33b-instruct-Q5_K_M\"
RemoveFileSafe -DryRunMode $dr `
    -Path "D:\Executables\Llama_ccp_win\models\Qwen3-30B-A3B-Instruct-2507-Q5_K_M.gguf" `
    -Reason "Q4 deja sur K: + qwen3-30b-a3b:q4_k_m installe dans Ollama"
RemoveFileSafe -DryRunMode $dr `
    -Path "D:\Documents - Copie\DeepSeek-R1-Distill-Llama-70B-Q3_K_M.gguf" `
    -Reason "deepseek-r1:70b deja installe dans Ollama"
RemoveFileSafe -DryRunMode $dr `
    -Path "D:\_sorted\Autres\mistral-22b-v0.2.Q4_K_M__dup1.gguf" `
    -Reason "Doublon strict de mistral-22b-v0.2.Q4_K_M.gguf"

Write-Host ""
Write-Host "--- 2. DEPLACEMENTS de modeles uniques vers K: ---" -ForegroundColor White
MoveModel -DryRunMode $dr `
    -Src "D:\Executables\Llama_ccp_win\models\Llama-3-8B-Instruct-Gradient-1048k-Q4_K_M.gguf" `
    -DestDir "K:\models\meta\llama-3-8b-instruct-gradient-1048k-Q4_K_M"
MoveModel -DryRunMode $dr `
    -Src "D:\_sorted\Autres\mistral-22b-v0.2.Q4_K_M.gguf" `
    -DestDir "K:\models\mistral\mistral-22b-v0.2-Q4_K_M"

Write-Host ""
Write-Host "--- 3. Vider GGUF residuels dans D:\`$RECYCLE.BIN ---" -ForegroundColor White
Get-ChildItem -Path 'D:\$RECYCLE.BIN' -Recurse -Include '*.gguf' -ErrorAction SilentlyContinue -Force |
    ForEach-Object {
        Write-Host "  DELETE $($_.FullName) ($([math]::Round($_.Length/1MB,2)) MB)" -ForegroundColor Magenta
        if (-not $dr) { Remove-Item -Path $_.FullName -Force -ErrorAction SilentlyContinue }
    }

Write-Host ""
Write-Host "=== Recapitulatif ===" -ForegroundColor Green
$totalMoveGB = ($script:movements | Measure-Object -Property Size_GB -Sum).Sum
$totalDelGB  = ($script:deletions | Measure-Object -Property Size_GB -Sum).Sum
Write-Host "Mouvements effectues : $($script:movements.Count) ($totalMoveGB GB)"
Write-Host "Suppressions         : $($script:deletions.Count) ($totalDelGB GB)"
Write-Host "Espace libere sur D: : $([math]::Round($totalDelGB + $totalMoveGB, 2)) GB"

if ($script:movements.Count -gt 0) {
    Write-Host ""
    Write-Host "Mouvements:" -ForegroundColor Cyan
    $script:movements | Format-Table -AutoSize
}
if ($script:deletions.Count -gt 0) {
    Write-Host ""
    Write-Host "Suppressions:" -ForegroundColor Magenta
    $script:deletions | Format-Table -AutoSize
}

if (-not $dr) {
    $logPath = "D:\backtest_core_v2\tools\reorganize_models_log.json"
    @{
        movements  = $script:movements
        deletions  = $script:deletions
        timestamp  = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    } | ConvertTo-Json -Depth 4 | Out-File -FilePath $logPath -Encoding UTF8
    Write-Host "Log sauvegarde       : $logPath" -ForegroundColor Gray
}
