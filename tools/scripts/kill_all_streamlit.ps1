# Script pour tuer TOUS les processus sur ports 8501-8510
Write-Host "Nettoyage de tous les ports Streamlit..." -ForegroundColor Yellow

$portsKilled = 0

for ($port = 8501; $port -le 8510; $port++) {
    try {
        $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue

        foreach ($conn in $connections) {
            $processId = $conn.OwningProcess

            try {
                $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
                if ($process) {
                    Write-Host "  Port $port : Arret du processus $processId ($($process.ProcessName))..." -ForegroundColor Yellow
                    Stop-Process -Id $processId -Force
                    $portsKilled++
                    Write-Host "    OK" -ForegroundColor Green
                }
            } catch {
                Write-Host "    Processus $processId deja ferme" -ForegroundColor Gray
            }
        }
    } catch {
        # Port non occupe - OK
    }
}

if ($portsKilled -eq 0) {
    Write-Host "Aucun processus trouve sur les ports 8501-8510" -ForegroundColor Green
} else {
    Write-Host "$portsKilled processus arretes" -ForegroundColor Green
}

Write-Host "Nettoyage termine!" -ForegroundColor Cyan
Start-Sleep -Seconds 1
