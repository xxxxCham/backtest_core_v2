$f1 = 'D:\_sorted\Autres\mistral-22b-v0.2.Q4_K_M.gguf'
$f2 = 'D:\_sorted\Autres\mistral-22b-v0.2.Q4_K_M__dup1.gguf'

Write-Host '=== Attributs fichiers ===' -ForegroundColor Yellow
foreach ($f in @($f1, $f2)) {
    $item = Get-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue
    if ($item) {
        Write-Host ('  ' + $item.Name)
        Write-Host ('    Attributes : ' + $item.Attributes)
        Write-Host ('    Length     : ' + [math]::Round($item.Length/1GB,2) + ' GB')
        Write-Host ('    LastWrite  : ' + $item.LastWriteTime)
    }
}

Write-Host ''
Write-Host '=== Defender threats actifs ===' -ForegroundColor Yellow
Get-MpThreat -ErrorAction SilentlyContinue | Format-Table -AutoSize
Get-MpThreatDetection -ErrorAction SilentlyContinue | Where-Object { $_.Resources -match 'mistral' } | Format-Table -AutoSize

Write-Host ''
Write-Host '=== Defender history (mistral) ===' -ForegroundColor Yellow
Get-WinEvent -LogName 'Microsoft-Windows-Windows Defender/Operational' -MaxEvents 50 -ErrorAction SilentlyContinue |
    Where-Object { $_.Message -match 'mistral' } |
    Select-Object -First 5 TimeCreated, Id, @{N='Msg';E={($_.Message -split [Environment]::NewLine)[0]}} |
    Format-Table -AutoSize -Wrap

Write-Host ''
Write-Host '=== Tentative cmd /c del ===' -ForegroundColor Yellow
& cmd /c del /F /Q $f2 2>&1
if (Test-Path $f2) { Write-Host '  toujours present' -ForegroundColor Red }
else                { Write-Host '  SUPPRIME' -ForegroundColor Green }
