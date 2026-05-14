# A LANCER EN MODE ADMINISTRATEUR
# Exclut K:\ et L:\ du scan Defender pour eviter les deconnexions disque
# pendant les moves de gros fichiers GGUF.

#Requires -RunAsAdministrator

$ErrorActionPreference = "Continue"

Write-Host "=== Diagnostic K: ===" -ForegroundColor Yellow
$kInfo = Get-PSDrive K -ErrorAction SilentlyContinue
if ($kInfo) {
    Write-Host "  K: free GB: $([math]::Round($kInfo.Free/1GB,2))"
} else {
    Write-Host "  K: NON ACCESSIBLE" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Etat Defender avant ===" -ForegroundColor Yellow
$prefBefore = Get-MpPreference
Write-Host "  Real-time monitoring: $(-not $prefBefore.DisableRealtimeMonitoring)"
Write-Host "  Exclusions actuelles:"
$prefBefore.ExclusionPath | ForEach-Object { Write-Host "    - $_" }

Write-Host ""
Write-Host "=== Ajout exclusions Defender ===" -ForegroundColor Cyan
$pathsToExclude = @(
    'K:\models',
    'L:\models',
    'C:\AI\ollama\models',
    'C:\AI\models'
)
foreach ($p in $pathsToExclude) {
    Add-MpPreference -ExclusionPath $p -ErrorAction SilentlyContinue
    Write-Host "  + $p" -ForegroundColor Green
}
# Exclure aussi l'extension .gguf (les blobs Ollama sans extension restent scannes)
Add-MpPreference -ExclusionExtension 'gguf' -ErrorAction SilentlyContinue
Add-MpPreference -ExclusionExtension 'safetensors' -ErrorAction SilentlyContinue
Write-Host "  + extensions .gguf, .safetensors" -ForegroundColor Green

Write-Host ""
Write-Host "=== Etat Defender apres ===" -ForegroundColor Yellow
$prefAfter = Get-MpPreference
Write-Host "  Exclusions paths:"
$prefAfter.ExclusionPath | ForEach-Object { Write-Host "    - $_" }
Write-Host "  Exclusions extensions:"
$prefAfter.ExclusionExtension | ForEach-Object { Write-Host "    - $_" }

Write-Host ""
Write-Host "=== Bonus : retirer attribut readonly + acl du fichier verrouille ===" -ForegroundColor Cyan
$lockedFile = 'D:\_sorted\Autres\mistral-22b-v0.2.Q4_K_M__dup1.gguf'
if (Test-Path $lockedFile) {
    takeown /F $lockedFile 2>&1 | Out-Host
    icacls $lockedFile /grant "${env:USERNAME}:(F)" /T 2>&1 | Out-Host
    Write-Host "  Tentative de suppression..."
    Remove-Item -Path $lockedFile -Force -ErrorAction SilentlyContinue
    if (Test-Path $lockedFile) {
        Write-Host "  ECHEC - fichier toujours verrouille (autre process le tient)" -ForegroundColor Red
    } else {
        Write-Host "  OK - supprime" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "=== Termine ===" -ForegroundColor Green
Write-Host "Vous pouvez maintenant relancer:"
Write-Host '  powershell -ExecutionPolicy Bypass -File "D:\backtest_core_v2\tools\reorganize_models.ps1"' -ForegroundColor Cyan
