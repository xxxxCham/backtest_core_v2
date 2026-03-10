# Script pour vérifier l'état du sweep en cours
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "DIAGNOSTIC SWEEP EN COURS" -ForegroundColor Cyan
Write-Host "============================================`n" -ForegroundColor Cyan

# 1. Processus Python actifs
Write-Host "[1] Processus Python actifs:" -ForegroundColor Yellow
Get-Process | Where-Object {$_.ProcessName -like "*python*"} |
    Select-Object Id, ProcessName,
        @{Name="CPU(s)";Expression={[math]::Round($_.CPU,1)}},
        @{Name="RAM(MB)";Expression={[math]::Round($_.WorkingSet64/1MB,0)}},
        @{Name="Threads";Expression={$_.Threads.Count}} |
    Format-Table -AutoSize

# 2. Utilisation CPU globale
Write-Host "`n[2] Utilisation CPU:" -ForegroundColor Yellow
$cpu = Get-WmiObject Win32_Processor | Measure-Object -Property LoadPercentage -Average | Select-Object -ExpandProperty Average
Write-Host "  CPU global: $cpu%" -ForegroundColor $(if($cpu -gt 80){"Red"}else{"Green"})

# 3. RAM disponible
Write-Host "`n[3] Mémoire:" -ForegroundColor Yellow
$mem = Get-WmiObject Win32_OperatingSystem
$totalGB = [math]::Round($mem.TotalVisibleMemorySize/1MB,1)
$freeGB = [math]::Round($mem.FreePhysicalMemory/1MB,1)
$usedGB = $totalGB - $freeGB
Write-Host "  Total: $totalGB GB"
Write-Host "  Utilisée: $usedGB GB"
Write-Host "  Libre: $freeGB GB" -ForegroundColor $(if($freeGB -lt 5){"Red"}else{"Green"})

# 4. Fichiers de log récents
Write-Host "`n[4] Logs récents (dernières 2 minutes):" -ForegroundColor Yellow
$recentLogs = Get-ChildItem -Path . -Filter "*.log" -File -ErrorAction SilentlyContinue |
    Where-Object {$_.LastWriteTime -gt (Get-Date).AddMinutes(-2)} |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 3

if ($recentLogs) {
    $recentLogs | ForEach-Object {
        Write-Host "  - $($_.Name) (modifié il y a $([math]::Round(((Get-Date) - $_.LastWriteTime).TotalSeconds,0))s)" -ForegroundColor Green
    }
} else {
    Write-Host "  Aucun log récent trouvé" -ForegroundColor Gray
}

Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host "Temps estimé pour 1.7M combos: 2-5 minutes" -ForegroundColor Cyan
Write-Host "Si > 10 min, le sweep est probablement bloqué" -ForegroundColor Yellow
Write-Host "============================================`n" -ForegroundColor Cyan
