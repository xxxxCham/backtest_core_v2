param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python.exe"
}

$Script = Join-Path $RepoRoot "tools\autonomous_builder_supervisor.py"
$Config = Join-Path $RepoRoot "config\autonomous_builder_supervisor.json"
Set-Location $RepoRoot

$ArgsList = @($Script, "loop", "--config", $Config)
if ($DryRun) {
    $ArgsList += "--dry-run"
}

& $Python @ArgsList
exit $LASTEXITCODE
