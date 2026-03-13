[CmdletBinding()]
param(
    [string]$SourceRoot = 'D:\models',
    [string]$RuntimeRoot = 'C:\AI\ollama\models',
    [string]$CatalogRoot = 'C:\AI\models',
    [string]$GgufRoot = 'K:\models',
    [string]$HfArchiveRoot = 'L:\models',
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:RunStartedAt = Get-Date
$script:Timestamp = $script:RunStartedAt.ToString('yyyyMMdd_HHmmss')
$script:ControlRoot = Split-Path -Parent $CatalogRoot
$script:ArchiveRoot = Join-Path $CatalogRoot '_archive'
$script:CatalogDir = Join-Path $CatalogRoot 'catalog'
$script:ScriptMirrorRoot = Join-Path $script:ControlRoot '_scripts'
$script:LogRoot = Join-Path $script:ControlRoot (Join-Path '_meta\logs' ("model_topology_$script:Timestamp"))
$script:RepoRoot = Split-Path -Parent $PSScriptRoot
$script:CatalogBuilder = Join-Path $PSScriptRoot 'build_c_model_catalog.py'
$script:PythonExe = if (Test-Path (Join-Path $script:RepoRoot '.venv\Scripts\python.exe')) {
    Join-Path $script:RepoRoot '.venv\Scripts\python.exe'
} else {
    'python'
}
$script:Results = New-Object System.Collections.Generic.List[object]
$script:HadFailure = $false

function Format-SizeGb {
    param([long]$Bytes)
    return [math]::Round(($Bytes / 1GB), 2)
}

function Get-SafeInt64 {
    param(
        $Value,
        [long]$Default = 0
    )

    if ($null -eq $Value) {
        return [int64]$Default
    }

    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) {
        return [int64]$Default
    }

    return [int64]$Value
}

function Get-PathStats {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{
            Exists = $false
            IsDirectory = $false
            Files = 0
            Bytes = [int64]0
        }
    }

    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer) {
        $files = @(Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue)
        $sum = [int64]0
        foreach ($file in $files) {
            $sum += [int64]$file.Length
        }
        return [ordered]@{
            Exists = $true
            IsDirectory = $true
            Files = @($files).Count
            Bytes = $sum
        }
    }

    return [ordered]@{
        Exists = $true
        IsDirectory = $false
        Files = 1
        Bytes = [int64]$item.Length
    }
}

function Ensure-Directory {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ($DryRun) {
        return
    }

    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Test-WriteAccess {
    param([Parameter(Mandatory = $true)][string]$Path)

    $probeDir = if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -Force
        if ($item.PSIsContainer) { $item.FullName } else { Split-Path -Parent $item.FullName }
    } else {
        $Path
    }

    if ($DryRun) {
        return [ordered]@{
            Path = $probeDir
            Status = 'skipped_dry_run'
            Error = $null
        }
    }

    $createdProbeDir = $false
    try {
        if (-not (Test-Path -LiteralPath $probeDir)) {
            New-Item -ItemType Directory -Path $probeDir -Force | Out-Null
            $createdProbeDir = $true
        }
        $probeFile = Join-Path $probeDir ('.write_probe_' + [guid]::NewGuid().ToString('N') + '.tmp')
        Set-Content -LiteralPath $probeFile -Value 'ok' -Encoding ascii
        Remove-Item -LiteralPath $probeFile -Force
        if ($createdProbeDir -and (Test-Path -LiteralPath $probeDir)) {
            Remove-Item -LiteralPath $probeDir -Force -Recurse
        }
        return [ordered]@{
            Path = $probeDir
            Status = 'ok'
            Error = $null
        }
    } catch {
        return [ordered]@{
            Path = $probeDir
            Status = 'failed'
            Error = $_.Exception.Message
        }
    }
}

function Add-Result {
    param([Parameter(Mandatory = $true)][hashtable]$Entry)
    $script:Results.Add([pscustomobject]$Entry)
}

function Invoke-RobocopyDirectoryBlock {
    param([Parameter(Mandatory = $true)][hashtable]$Block)

    $sourceStats = Get-PathStats -Path $Block.Source
    $result = [ordered]@{
        Name = $Block.Name
        Category = $Block.Category
        Kind = 'directory'
        Source = $Block.Source
        Destination = $Block.Destination
        SourceFiles = $sourceStats.Files
        SourceBytes = $sourceStats.Bytes
        DestinationFiles = $null
        DestinationBytes = $null
        Status = 'pending'
        RobocopyExitCode = $null
        LogPath = $null
        Error = $null
    }

    if (-not $sourceStats.Exists) {
        $result.Status = 'failed_missing_source'
        $result.Error = 'Source path missing'
        $script:HadFailure = $true
        Add-Result -Entry $result
        return
    }

    try {
        if (-not $DryRun) {
            Ensure-Directory -Path (Split-Path -Parent $Block.Destination)
        }

        $args = @(
            $Block.Source,
            $Block.Destination,
            '/E',
            '/COPY:DAT',
            '/DCOPY:DAT',
            '/R:1',
            '/W:1',
            '/MT:16',
            '/NP'
        )

        if ($DryRun) {
            $args += @('/L', '/NFL', '/NDL', '/NJH', '/NJS')
        } else {
            $logPath = Join-Path $script:LogRoot ($Block.Name + '.robocopy.log')
            $args += @("/LOG:$logPath")
            $result.LogPath = $logPath
        }

        & robocopy @args
        $result.RobocopyExitCode = $LASTEXITCODE

        if ($result.RobocopyExitCode -lt 8) {
            $result.Status = if ($DryRun) { 'dry_run_ok' } else { 'ok' }
        } else {
            $result.Status = if ($DryRun) { 'dry_run_failed' } else { 'failed' }
            $script:HadFailure = $true
        }

        if (-not $DryRun -and (Test-Path -LiteralPath $Block.Destination)) {
            $destStats = Get-PathStats -Path $Block.Destination
            $result.DestinationFiles = $destStats.Files
            $result.DestinationBytes = $destStats.Bytes
        }
    } catch {
        $result.Status = if ($DryRun) { 'dry_run_exception' } else { 'failed_exception' }
        $result.Error = $_.Exception.Message
        $script:HadFailure = $true
    }

    Add-Result -Entry $result
}

function Invoke-FileBlock {
    param([Parameter(Mandatory = $true)][hashtable]$Block)

    $bytes = [int64]0
    foreach ($file in $Block.Files) {
        $bytes += [int64]$file.Length
    }

    $result = [ordered]@{
        Name = $Block.Name
        Category = $Block.Category
        Kind = 'files'
        Source = $Block.Source
        Destination = $Block.Destination
        SourceFiles = @($Block.Files).Count
        SourceBytes = $bytes
        DestinationFiles = $null
        DestinationBytes = $null
        Status = 'pending'
        RobocopyExitCode = $null
        LogPath = $null
        Error = $null
    }

    try {
        if ($DryRun) {
            $result.Status = 'dry_run_ok'
        } else {
            Ensure-Directory -Path $Block.Destination
            foreach ($file in $Block.Files) {
                Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $Block.Destination $file.Name) -Force
            }
            $destStats = Get-PathStats -Path $Block.Destination
            $result.DestinationFiles = $destStats.Files
            $result.DestinationBytes = $destStats.Bytes
            $logPath = Join-Path $script:LogRoot ($Block.Name + '.files.log')
            ($Block.Files | Select-Object -ExpandProperty FullName) | Set-Content -Path $logPath -Encoding UTF8
            $result.LogPath = $logPath
            $result.Status = 'ok'
        }
    } catch {
        $result.Status = if ($DryRun) { 'dry_run_exception' } else { 'failed_exception' }
        $result.Error = $_.Exception.Message
        $script:HadFailure = $true
    }

    Add-Result -Entry $result
}

function Invoke-CatalogBuild {
    param([Parameter(Mandatory = $true)][string]$LegacyJson,
          [Parameter(Mandatory = $true)][string]$OutputJson)

    $result = [ordered]@{
        Name = 'build_catalog'
        Category = 'catalog'
        Kind = 'command'
        Source = $LegacyJson
        Destination = $OutputJson
        SourceFiles = 1
        SourceBytes = (Get-PathStats -Path $LegacyJson).Bytes
        DestinationFiles = $null
        DestinationBytes = $null
        Status = 'pending'
        RobocopyExitCode = $null
        LogPath = $null
        Error = $null
    }

    if ($DryRun) {
        $result.Status = 'dry_run_planned'
        Add-Result -Entry $result
        return
    }

    try {
        Ensure-Directory -Path (Split-Path -Parent $OutputJson)
        $logPath = Join-Path $script:LogRoot 'build_catalog.log'
        Push-Location $script:RepoRoot
        try {
            & $script:PythonExe $script:CatalogBuilder `
                --legacy-json $LegacyJson `
                --output-json $OutputJson `
                --catalog-root $CatalogRoot `
                --ollama-root $RuntimeRoot `
                --gguf-root $GgufRoot `
                --hf-root $HfArchiveRoot 2>&1 | Tee-Object -FilePath $logPath
            $exitCode = $LASTEXITCODE
        } finally {
            Pop-Location
        }

        $result.LogPath = $logPath
        $result.RobocopyExitCode = $exitCode
        if ($exitCode -eq 0 -and (Test-Path -LiteralPath $OutputJson)) {
            $destStats = Get-PathStats -Path $OutputJson
            $result.DestinationFiles = $destStats.Files
            $result.DestinationBytes = $destStats.Bytes
            $result.Status = 'ok'
        } else {
            $result.Status = 'failed'
            $result.Error = "Catalog builder exit code: $exitCode"
            $script:HadFailure = $true
        }
    } catch {
        $result.Status = 'failed_exception'
        $result.Error = $_.Exception.Message
        $script:HadFailure = $true
    }

    Add-Result -Entry $result
}

function Invoke-ProgramResolutionCheck {
    param([Parameter(Mandatory = $true)][string]$CatalogJson)

    $result = [ordered]@{
        Name = 'program_resolution_check'
        Category = 'verification'
        Kind = 'command'
        Source = $CatalogJson
        Destination = $RuntimeRoot
        SourceFiles = 1
        SourceBytes = (Get-PathStats -Path $CatalogJson).Bytes
        DestinationFiles = $null
        DestinationBytes = $null
        Status = 'pending'
        RobocopyExitCode = $null
        LogPath = $null
        Error = $null
    }

    if ($DryRun) {
        $result.Status = 'dry_run_planned'
        Add-Result -Entry $result
        return
    }

    try {
        $logPath = Join-Path $script:LogRoot 'program_resolution_check.log'
        $snippet = @"
import json
from utils.model_loader import get_models_json_path, get_ollama_models_root, get_model_by_id
payload = {
    "models_json_path": str(get_models_json_path()),
    "ollama_models_root": str(get_ollama_models_root()),
    "qwen3_coder": bool(get_model_by_id("qwen3-coder:30b")),
    "deepseek_coder_v2_lite_hf": bool(get_model_by_id("deepseek-coder-v2-lite-hf")),
    "fin_llama_hf": bool(get_model_by_id("fin-llama-33b-hf")),
}
print(json.dumps(payload, indent=2))
"@
        Push-Location $script:RepoRoot
        try {
            $env:MODELS_JSON_PATH = $CatalogJson
            $env:OLLAMA_MODELS = $RuntimeRoot
            $env:MODEL_LIBRARY_ROOTS = "$GgufRoot;$HfArchiveRoot"
            $env:HUGGINGFACE_ARCHIVE_ROOT = $HfArchiveRoot
            $snippet | & $script:PythonExe - 2>&1 | Tee-Object -FilePath $logPath
            $exitCode = $LASTEXITCODE
        } finally {
            Pop-Location
        }

        $result.LogPath = $logPath
        $result.RobocopyExitCode = $exitCode
        if ($exitCode -eq 0) {
            $result.Status = 'ok'
        } else {
            $result.Status = 'failed'
            $result.Error = "Resolution check exit code: $exitCode"
            $script:HadFailure = $true
        }
    } catch {
        $result.Status = 'failed_exception'
        $result.Error = $_.Exception.Message
        $script:HadFailure = $true
    }

    Add-Result -Entry $result
}

function Invoke-OllamaManifestNormalization {
    param([Parameter(Mandatory = $true)][string]$RuntimeRoot)

    $manifestRoot = Join-Path $RuntimeRoot 'manifests'
    $blobRoot = Join-Path $RuntimeRoot 'blobs'
    $sourceStats = Get-PathStats -Path $manifestRoot
    $result = [ordered]@{
        Name = 'normalize_ollama_manifest_from_refs'
        Category = 'runtime'
        Kind = 'command'
        Source = $manifestRoot
        Destination = $manifestRoot
        SourceFiles = $sourceStats.Files
        SourceBytes = $sourceStats.Bytes
        DestinationFiles = $null
        DestinationBytes = $null
        Status = 'pending'
        RobocopyExitCode = $null
        LogPath = $null
        Error = $null
    }

    if (-not $sourceStats.Exists) {
        $result.Status = 'failed_missing_source'
        $result.Error = 'Manifest root missing'
        $script:HadFailure = $true
        Add-Result -Entry $result
        return
    }

    try {
        $changedFiles = New-Object System.Collections.Generic.List[string]
        $escapedBlobRoot = $blobRoot.Replace('\', '\\')
        foreach ($file in Get-ChildItem -LiteralPath $manifestRoot -Recurse -File -Force) {
            $raw = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8
            $updated = [regex]::Replace(
                $raw,
                '"from"\s*:\s*"[^"]*?(sha256-[0-9a-f]+)"',
                ('"from":"' + $escapedBlobRoot + '\\$1"')
            )

            if ($updated -ne $raw) {
                $changedFiles.Add($file.FullName) | Out-Null
                if (-not $DryRun) {
                    Set-Content -LiteralPath $file.FullName -Value $updated -Encoding UTF8
                }
            }
        }

        $result.DestinationFiles = $changedFiles.Count
        $result.DestinationBytes = (Get-PathStats -Path $manifestRoot).Bytes
        if ($DryRun) {
            $result.Status = if ($changedFiles.Count -gt 0) { 'dry_run_pending_cleanup' } else { 'dry_run_ok' }
        } else {
            $logPath = Join-Path $script:LogRoot 'normalize_ollama_manifest_from_refs.log'
            if ($changedFiles.Count -gt 0) {
                $changedFiles | Set-Content -Path $logPath -Encoding UTF8
                $result.LogPath = $logPath
            }
            $result.Status = 'ok'
        }
    } catch {
        $result.Status = if ($DryRun) { 'dry_run_exception' } else { 'failed_exception' }
        $result.Error = $_.Exception.Message
        $script:HadFailure = $true
    }

    Add-Result -Entry $result
}

function Invoke-OllamaManifestLegacyRefCheck {
    param([Parameter(Mandatory = $true)][string]$RuntimeRoot)

    $manifestRoot = Join-Path $RuntimeRoot 'manifests'
    $sourceStats = Get-PathStats -Path $manifestRoot
    $result = [ordered]@{
        Name = 'verify_ollama_manifest_legacy_refs'
        Category = 'verification'
        Kind = 'command'
        Source = $manifestRoot
        Destination = $manifestRoot
        SourceFiles = $sourceStats.Files
        SourceBytes = $sourceStats.Bytes
        DestinationFiles = $null
        DestinationBytes = $null
        Status = 'pending'
        RobocopyExitCode = $null
        LogPath = $null
        Error = $null
    }

    if (-not $sourceStats.Exists) {
        $result.Status = 'failed_missing_source'
        $result.Error = 'Manifest root missing'
        $script:HadFailure = $true
        Add-Result -Entry $result
        return
    }

    try {
        $legacyHits = New-Object System.Collections.Generic.List[string]
        foreach ($file in Get-ChildItem -LiteralPath $manifestRoot -Recurse -File -Force) {
            $raw = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8
            if (
                $raw.Contains('D:\models') -or
                $raw.Contains('models_via_ollamaGUI') -or
                $raw.Contains('/Users/') -or
                $raw.Contains('/usr/share/')
            ) {
                $legacyHits.Add($file.FullName) | Out-Null
            }
        }

        $result.DestinationFiles = $legacyHits.Count
        $result.DestinationBytes = (Get-PathStats -Path $manifestRoot).Bytes
        if ($DryRun) {
            $result.Status = if ($legacyHits.Count -gt 0) { 'dry_run_pending_cleanup' } else { 'dry_run_ok' }
        } elseif ($legacyHits.Count -gt 0) {
            $logPath = Join-Path $script:LogRoot 'verify_ollama_manifest_legacy_refs.log'
            $legacyHits | Set-Content -Path $logPath -Encoding UTF8
            $result.LogPath = $logPath
            $result.Status = 'failed'
            $result.Error = "Legacy manifest references remaining: $($legacyHits.Count)"
            $script:HadFailure = $true
        } else {
            $result.Status = 'ok'
        }
    } catch {
        $result.Status = if ($DryRun) { 'dry_run_exception' } else { 'failed_exception' }
        $result.Error = $_.Exception.Message
        $script:HadFailure = $true
    }

    Add-Result -Entry $result
}

$excludedHf = @(
    [ordered]@{
        Source = (Join-Path $SourceRoot 'huggingface\llama2-13b-fp16')
        Reason = 'Duplicate archive already present on L:\models\meta\llama-2-13b-fp16'
    }
)

$directoryBlocks = @(
    [ordered]@{
        Name = 'copy_ollama_store'
        Category = 'runtime'
        Source = (Join-Path $SourceRoot 'ollama')
        Destination = $RuntimeRoot
    },
    [ordered]@{
        Name = 'copy_hf_llama_3_1_8b_instruct'
        Category = 'hf_archive'
        Source = (Join-Path $SourceRoot 'huggingface\llama-3.1-8b-instruct')
        Destination = (Join-Path $HfArchiveRoot 'meta\llama-3.1-8b-instruct')
    },
    [ordered]@{
        Name = 'copy_hf_fin_llama_33b'
        Category = 'hf_archive'
        Source = (Join-Path $SourceRoot 'huggingface\fin-llama-33b')
        Destination = (Join-Path $HfArchiveRoot 'finance\fin-llama-33b')
    },
    [ordered]@{
        Name = 'copy_hf_nemotron_3_nano_30b'
        Category = 'hf_archive'
        Source = (Join-Path $SourceRoot 'huggingface\nemotron-3-nano-30b')
        Destination = (Join-Path $HfArchiveRoot 'nvidia\nemotron-3-nano-30b')
    },
    [ordered]@{
        Name = 'copy_d_models_scripts'
        Category = 'archive'
        Source = (Join-Path $SourceRoot 'scripts')
        Destination = (Join-Path $script:ArchiveRoot 'd_models_scripts')
    },
    [ordered]@{
        Name = 'copy_d_models_hidden_vscode'
        Category = 'archive'
        Source = (Join-Path $SourceRoot '.vscode')
        Destination = (Join-Path $script:ArchiveRoot 'd_models_hidden\.vscode')
    },
    [ordered]@{
        Name = 'copy_d_models_hidden_pytest_cache'
        Category = 'archive'
        Source = (Join-Path $SourceRoot '.pytest_cache')
        Destination = (Join-Path $script:ArchiveRoot 'd_models_hidden\.pytest_cache')
    },
    [ordered]@{
        Name = 'copy_models_via_ollamaGUI'
        Category = 'archive'
        Source = (Join-Path $SourceRoot 'models_via_ollamaGUI')
        Destination = (Join-Path $script:ArchiveRoot 'models_via_ollamaGUI')
    }
)

$rootFileItems = @(Get-ChildItem -LiteralPath $SourceRoot -File -Force)
$fileBlocks = @()
if (@($rootFileItems).Count -gt 0) {
    $fileBlocks += [ordered]@{
        Name = 'copy_d_models_root_files'
        Category = 'archive'
        Source = $SourceRoot
        Destination = (Join-Path $script:ArchiveRoot 'd_models_root_files')
        Files = $rootFileItems
    }
}

$fileBlocks += [ordered]@{
    Name = 'copy_legacy_models_json'
    Category = 'catalog'
    Source = (Join-Path $SourceRoot 'models.json')
    Destination = $script:CatalogDir
    Files = @(Get-Item -LiteralPath (Join-Path $SourceRoot 'models.json'))
}

$precheckItems = @()
foreach ($block in $directoryBlocks) {
    $sourceStats = Get-PathStats -Path $block.Source
    $destStats = Get-PathStats -Path $block.Destination
    $requiredBytes = if ($sourceStats.Bytes -gt $destStats.Bytes) { [int64]($sourceStats.Bytes - $destStats.Bytes) } else { [int64]0 }
    $precheckItems += [pscustomobject]@{
        Name = $block.Name
        Category = $block.Category
        Source = $block.Source
        Destination = $block.Destination
        Files = $sourceStats.Files
        Bytes = $sourceStats.Bytes
        ExistingDestinationBytes = $destStats.Bytes
        RequiredBytes = $requiredBytes
        Exists = $sourceStats.Exists
    }
}
foreach ($block in $fileBlocks) {
    $bytes = [int64]0
    foreach ($file in $block.Files) {
        $bytes += [int64]$file.Length
    }
    $destStats = Get-PathStats -Path $block.Destination
    $requiredBytes = if ($bytes -gt $destStats.Bytes) { [int64]($bytes - $destStats.Bytes) } else { [int64]0 }
    $precheckItems += [pscustomobject]@{
        Name = $block.Name
        Category = $block.Category
        Source = $block.Source
        Destination = $block.Destination
        Files = @($block.Files).Count
        Bytes = $bytes
        ExistingDestinationBytes = $destStats.Bytes
        RequiredBytes = $requiredBytes
        Exists = $true
    }
}

$cRequiredBytes = ($precheckItems | Where-Object { $_.Destination -like 'C:\*' } | Measure-Object -Property RequiredBytes -Sum).Sum
$lRequiredBytes = ($precheckItems | Where-Object { $_.Destination -like 'L:\*' } | Measure-Object -Property RequiredBytes -Sum).Sum
if ($null -eq $cRequiredBytes) { $cRequiredBytes = [int64]0 }
if ($null -eq $lRequiredBytes) { $lRequiredBytes = [int64]0 }


$cFreeBytes = (Get-PSDrive -Name C).Free
$lFreeBytes = (Get-PSDrive -Name L).Free
$kFreeBytes = (Get-PSDrive -Name K).Free
$dFreeBytes = (Get-PSDrive -Name D).Free

$writeChecks = @(
    (Test-WriteAccess -Path $RuntimeRoot),
    (Test-WriteAccess -Path $CatalogRoot),
    (Test-WriteAccess -Path $HfArchiveRoot)
)

$missingSources = @($precheckItems | Where-Object { -not $_.Exists })
if (@($missingSources).Count -gt 0) {
    $script:HadFailure = $true
}
if ($cRequiredBytes -gt $cFreeBytes) {
    $script:HadFailure = $true
}
if ($lRequiredBytes -gt $lFreeBytes) {
    $script:HadFailure = $true
}
if (@($writeChecks | Where-Object { $_.Status -eq 'failed' }).Count -gt 0) {
    $script:HadFailure = $true
}

$precheckSummary = [ordered]@{
    started_at = $script:RunStartedAt.ToString('s')
    dry_run = [bool]$DryRun
    source_root = $SourceRoot
    runtime_root = $RuntimeRoot
    catalog_root = $CatalogRoot
    gguf_root = $GgufRoot
    hf_archive_root = $HfArchiveRoot
    drive_free_gb = [ordered]@{
        C = (Format-SizeGb -Bytes $cFreeBytes)
        D = (Format-SizeGb -Bytes $dFreeBytes)
        K = (Format-SizeGb -Bytes $kFreeBytes)
        L = (Format-SizeGb -Bytes $lFreeBytes)
    }
    required_copy_gb = [ordered]@{
        to_c = (Format-SizeGb -Bytes $cRequiredBytes)
        to_l = (Format-SizeGb -Bytes $lRequiredBytes)
    }
    projected_remaining_gb = [ordered]@{
        C = (Format-SizeGb -Bytes ($cFreeBytes - $cRequiredBytes))
        L = (Format-SizeGb -Bytes ($lFreeBytes - $lRequiredBytes))
    }
    write_checks = $writeChecks
    excluded_hf_sources = $excludedHf
    missing_sources = $missingSources
}

Write-Host "=== Precheck ==="
$precheckSummary | ConvertTo-Json -Depth 6
Write-Host "=== Planned blocks ==="
$precheckItems |
    Select-Object Name, Category, Source, Destination, Files, @{Name = 'SizeGB'; Expression = { Format-SizeGb -Bytes .Bytes } }, @{Name = 'RequiredGB'; Expression = { Format-SizeGb -Bytes .RequiredBytes } }, Exists |
    Format-Table -AutoSize

if ((@($missingSources).Count -gt 0) -or ($cRequiredBytes -gt $cFreeBytes) -or ($lRequiredBytes -gt $lFreeBytes) -or (@($writeChecks | Where-Object { $_.Status -eq 'failed' }).Count -gt 0)) {
    Write-Error 'Precheck failed. Aborting before copy operations.'
    exit 2
}

if (-not $DryRun) {
    Ensure-Directory -Path $script:LogRoot
    Ensure-Directory -Path $script:ScriptMirrorRoot
    Ensure-Directory -Path $script:CatalogDir

    $excludedPath = Join-Path $script:LogRoot 'excluded_hf_sources.txt'
    ($excludedHf | ForEach-Object { "{0}`t{1}" -f $_.Source, $_.Reason }) | Set-Content -Path $excludedPath -Encoding UTF8

    Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $script:ScriptMirrorRoot (Split-Path -Leaf $PSCommandPath)) -Force
    Copy-Item -LiteralPath $script:CatalogBuilder -Destination (Join-Path $script:ScriptMirrorRoot (Split-Path -Leaf $script:CatalogBuilder)) -Force
}

foreach ($block in $directoryBlocks) {
    Invoke-RobocopyDirectoryBlock -Block $block
}
foreach ($block in $fileBlocks) {
    Invoke-FileBlock -Block $block
}

Invoke-OllamaManifestNormalization -RuntimeRoot $RuntimeRoot
$catalogJson = Join-Path $script:CatalogDir 'models.json'
Invoke-CatalogBuild -LegacyJson (Join-Path $SourceRoot 'models.json') -OutputJson $catalogJson
Invoke-ProgramResolutionCheck -CatalogJson $catalogJson
Invoke-OllamaManifestLegacyRefCheck -RuntimeRoot $RuntimeRoot

$verificationChecks = @(
    [ordered]@{ Name = 'c_archive_root'; Path = $script:ArchiveRoot },
    [ordered]@{ Name = 'c_catalog_dir'; Path = $script:CatalogDir },
    [ordered]@{ Name = 'c_ollama_blobs'; Path = (Join-Path $RuntimeRoot 'blobs') },
    [ordered]@{ Name = 'c_ollama_manifests'; Path = (Join-Path $RuntimeRoot 'manifests') },
    [ordered]@{ Name = 'c_catalog_models_json'; Path = $catalogJson },
    [ordered]@{ Name = 'l_hf_deepseek_coder_v2_lite'; Path = (Join-Path $HfArchiveRoot 'deepseek\deepseek-coder-v2-lite-instruct') },
    [ordered]@{ Name = 'l_hf_llama2_13b_fp16'; Path = (Join-Path $HfArchiveRoot 'meta\llama-2-13b-fp16') },
    [ordered]@{ Name = 'l_hf_llama_3_1_8b_instruct'; Path = (Join-Path $HfArchiveRoot 'meta\llama-3.1-8b-instruct') },
    [ordered]@{ Name = 'l_hf_fin_llama_33b'; Path = (Join-Path $HfArchiveRoot 'finance\fin-llama-33b') },
    [ordered]@{ Name = 'l_hf_nemotron_3_nano_30b'; Path = (Join-Path $HfArchiveRoot 'nvidia\nemotron-3-nano-30b') },
    [ordered]@{ Name = 'k_gguf_root'; Path = $GgufRoot }
)

$verificationResults = foreach ($check in $verificationChecks) {
    $stats = Get-PathStats -Path $check.Path
    [pscustomobject]@{
        Name = $check.Name
        Path = $check.Path
        Exists = $stats.Exists
        Files = $stats.Files
        SizeGB = (Format-SizeGb -Bytes $stats.Bytes)
    }
}

$missingVerification = @($verificationResults | Where-Object { -not $_.Exists })
if ((-not $DryRun) -and @($missingVerification).Count -gt 0) {
    $script:HadFailure = $true
}

$endedAt = Get-Date
$globalStatus = if ($script:HadFailure) {
    if ($DryRun) { 'dry_run_failed' } else { 'failed' }
} else {
    if ($DryRun) {
        if (@($missingVerification).Count -gt 0) { 'dry_run_pending_changes' } else { 'dry_run_ok' }
    } else {
        'ok'
    }
}
$report = [ordered]@{
    started_at = $script:RunStartedAt.ToString('s')
    ended_at = $endedAt.ToString('s')
    duration_seconds = [math]::Round((New-TimeSpan -Start $script:RunStartedAt -End $endedAt).TotalSeconds, 2)
    dry_run = [bool]$DryRun
    global_status = $globalStatus
    precheck = $precheckSummary
    block_results = $script:Results
    verification = $verificationResults
    verification_missing = $missingVerification
}

Write-Host "=== Verification ==="
$verificationResults | Format-Table -AutoSize
Write-Host "=== Final summary ==="
$script:Results |
    Select-Object Name, Category, Kind, Status, RobocopyExitCode, @{Name = 'SourceGB'; Expression = { Format-SizeGb -Bytes (Get-SafeInt64 -Value $_.SourceBytes) } }, @{Name = 'DestGB'; Expression = { Format-SizeGb -Bytes (Get-SafeInt64 -Value $_.DestinationBytes) } }, LogPath |
    Format-Table -AutoSize
$report | ConvertTo-Json -Depth 8

if (-not $DryRun) {
    $reportPath = Join-Path $script:LogRoot 'migration_report.json'
    $summaryPath = Join-Path $script:LogRoot 'migration_summary.csv'
    $report | ConvertTo-Json -Depth 8 | Set-Content -Path $reportPath -Encoding UTF8
    $script:Results | Export-Csv -Path $summaryPath -NoTypeInformation -Encoding UTF8
}

if ($script:HadFailure) {
    exit 1
}

exit 0


