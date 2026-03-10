# Vérifier les détails du process 18352
$proc = Get-Process -Id 18352 -ErrorAction SilentlyContinue

if ($proc) {
    Write-Host "`n=== PROCESS $($proc.Id) ===" -ForegroundColor Cyan
    Write-Host "Name: $($proc.ProcessName)"
    Write-Host "Start: $($proc.StartTime)"
    Write-Host "Runtime: $([math]::Round(((Get-Date) - $proc.StartTime).TotalMinutes,1)) minutes"
    Write-Host "CPU Time: $([math]::Round($proc.CPU,0)) seconds"
    Write-Host "Threads: $($proc.Threads.Count)"
    Write-Host "RAM: $([math]::Round($proc.WorkingSet64/1MB,0)) MB"

    # Essayer de trouver la ligne de commande
    $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId = $($proc.Id)").CommandLine
    Write-Host "`nCommand:"
    Write-Host $cmd -ForegroundColor Yellow
} else {
    Write-Host "Process 18352 non trouvé (peut-être terminé)" -ForegroundColor Red
}
