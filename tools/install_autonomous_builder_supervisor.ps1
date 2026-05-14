param(
    [switch]$RunNow,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $RepoRoot "tools\run_autonomous_builder_supervisor.ps1"
$LoopRunner = Join-Path $RepoRoot "tools\run_autonomous_builder_supervisor_loop.ps1"
$TaskStartup = "BacktestCoreV2 Autonomous Builder Supervisor - Startup"
$TaskLogon = "BacktestCoreV2 Autonomous Builder Supervisor - Logon"
$TaskEvery30 = "BacktestCoreV2 Autonomous Builder Supervisor - 30min"
$LegacyTaskEvery15 = "BacktestCoreV2 Autonomous Builder Supervisor - 15min"
$RunKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$RunKeyName = "BacktestCoreV2AutonomousBuilderSupervisor"

function Invoke-Schtasks {
    param([string[]]$Arguments)
    & schtasks.exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks.exe failed with exit code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

function Invoke-SchtasksOptional {
    param([string[]]$Arguments)
    try {
        Invoke-Schtasks $Arguments
        return $true
    }
    catch {
        Write-Warning $_.Exception.Message
        return $false
    }
}

if ($Remove) {
    foreach ($taskName in @($TaskStartup, $TaskLogon, $TaskEvery30, $LegacyTaskEvery15)) {
        schtasks.exe /Query /TN $taskName *> $null
        if ($LASTEXITCODE -eq 0) {
            Invoke-Schtasks @("/Delete", "/TN", $taskName, "/F")
            Write-Host "Removed scheduled task: $taskName"
        }
    }
    if (Get-ItemProperty -Path $RunKeyPath -Name $RunKeyName -ErrorAction SilentlyContinue) {
        Remove-ItemProperty -Path $RunKeyPath -Name $RunKeyName
        Write-Host "Removed HKCU Run fallback: $RunKeyName"
    }
    exit 0
}

if (-not (Test-Path $Runner)) {
    throw "Runner not found: $Runner"
}
if (-not (Test-Path $LoopRunner)) {
    throw "Loop runner not found: $LoopRunner"
}

$TaskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Runner`""
$LoopCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$LoopRunner`""

schtasks.exe /Query /TN $LegacyTaskEvery15 *> $null
if ($LASTEXITCODE -eq 0) {
    Invoke-Schtasks @("/Delete", "/TN", $LegacyTaskEvery15, "/F")
    Write-Host "Removed legacy scheduled task: $LegacyTaskEvery15"
}

$startupInstalled = Invoke-SchtasksOptional @("/Create", "/F", "/TN", $TaskStartup, "/SC", "ONSTART", "/TR", $TaskCommand)
$logonInstalled = Invoke-SchtasksOptional @("/Create", "/F", "/TN", $TaskLogon, "/SC", "ONLOGON", "/TR", $TaskCommand)
$every30Installed = Invoke-SchtasksOptional @("/Create", "/F", "/TN", $TaskEvery30, "/SC", "MINUTE", "/MO", "30", "/TR", $TaskCommand)

if ($startupInstalled) {
    Write-Host "Installed scheduled task: $TaskStartup"
}
else {
    Write-Warning "Startup trigger not installed. Run this installer from an elevated PowerShell if you need execution before user logon."
}
if ($logonInstalled) {
    Write-Host "Installed scheduled task: $TaskLogon"
}
if ($every30Installed) {
    Write-Host "Installed scheduled task: $TaskEvery30"
}

if (-not $logonInstalled -or -not $every30Installed) {
    New-Item -Path $RunKeyPath -Force | Out-Null
    New-ItemProperty -Path $RunKeyPath -Name $RunKeyName -Value $LoopCommand -PropertyType String -Force | Out-Null
    Write-Warning "Task Scheduler refused at least one trigger. Installed HKCU Run fallback: $RunKeyName"
    Write-Host "Fallback command: $LoopCommand"
}

if ($RunNow) {
    if ($every30Installed) {
        Invoke-Schtasks @("/Run", "/TN", $TaskEvery30)
        Write-Host "Started scheduled task once: $TaskEvery30"
    }
    else {
        Start-Process -FilePath "powershell.exe" `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", $LoopRunner) `
            -WindowStyle Hidden
        Write-Host "Started fallback supervisor loop."
    }
}
