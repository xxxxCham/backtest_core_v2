$src = 'D:\_sorted\Autres\mistral-22b-v0.2.Q4_K_M.gguf'
$destDir = 'K:\models\mistral\mistral-22b-v0.2-Q4_K_M'
$dest = Join-Path $destDir 'model.gguf'

if (-not (Test-Path $src)) { Write-Host 'Source absente'; exit 0 }
if (Test-Path $dest)        { Write-Host 'Dest existe deja'; exit 0 }

Write-Host '=== Verif K: avant move ===' -ForegroundColor Yellow
$k = Get-PSDrive K
Write-Host ('  K: free GB: ' + [math]::Round($k.Free/1GB,2))
$srcSize = [math]::Round((Get-Item $src).Length/1GB,2)
Write-Host ('  Src GB    : ' + $srcSize)

if (-not (Test-Path $destDir)) {
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
}

Write-Host ''
Write-Host '=== robocopy (resilient sur disconnect) ===' -ForegroundColor Cyan
# /MOV = move (delete src apres copy)
# /R:3 = retry 3 fois
# /W:5 = wait 5s entre retries
# /NFL /NDL /NJS /NJH = output minimal
robocopy 'D:\_sorted\Autres' $destDir 'mistral-22b-v0.2.Q4_K_M.gguf' /MOV /R:3 /W:5 /NFL /NDL
$rc = $LASTEXITCODE
Write-Host ('robocopy exit code: ' + $rc)

# robocopy: 0=ok no copy, 1=ok copied, 2-7=warnings, 8+=errors
if ($rc -lt 8) {
    Write-Host '=== Renommage final vers model.gguf ===' -ForegroundColor Cyan
    $movedFile = Join-Path $destDir 'mistral-22b-v0.2.Q4_K_M.gguf'
    if (Test-Path $movedFile) {
        Move-Item -Path $movedFile -Destination $dest -Force
        Write-Host '  OK' -ForegroundColor Green
    }
}

Write-Host ''
Write-Host '=== Etat final ===' -ForegroundColor Yellow
if (Test-Path $src)  { Write-Host ('  Source: PRESENTE -> ' + $src) -ForegroundColor Yellow }
else                  { Write-Host ('  Source: SUPPRIMEE') -ForegroundColor Green }
if (Test-Path $dest) {
    $destSize = [math]::Round((Get-Item $dest).Length/1GB,2)
    Write-Host ('  Dest  : ' + $dest + ' (' + $destSize + ' GB)') -ForegroundColor Green
}
