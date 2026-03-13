#!/usr/bin/env pwsh
<#
.SYNOPSIS
Gère les dossiers du workspace VS Code (ajouter/retirer)

.EXAMPLE
.\manage_workspaces.ps1 add data_updater
.\manage_workspaces.ps1 remove data_updater
.\manage_workspaces.ps1 status
.\manage_workspaces.ps1 setup-all
#>

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("add", "remove", "show", "status", "setup-all", "hide", "unhide")]
    [string]$Action,
    
    [Parameter(Mandatory=$false)]
    [ValidateSet("data_updater", "models_data")]
    [string]$Folder
)

$workspacePath = "d:\backtest_core_v2\backtest_core_v2.code-workspace"
$projectRoot = "d:\backtest_core_v2"

function Load-Workspace {
    $json = Get-Content $workspacePath | ConvertFrom-Json
    return $json
}

function Save-Workspace($workspace) {
    $workspace | ConvertTo-Json -Depth 10 | Set-Content $workspacePath
    Write-Host "✓ Workspace sauvegardé" -ForegroundColor Green
}

function Show-Folders {
    $workspace = Load-Workspace
    Write-Host "`n📁 Dossiers du workspace :`n" -ForegroundColor Cyan
    $workspace.folders | ForEach-Object {
        $visible = if ($_.hidden -eq $true) { "❌ (caché)" } else { "✓ (visible)" }
        Write-Host "  $($_.name) : $($_.path) $visible"
    }
    Write-Host ""
}

function Add-Folder($folderName) {
    $workspace = Load-Workspace
    
    # Check s'il existe déjà
    if ($workspace.folders | Where-Object { $_.name -eq $folderName }) {
        Write-Host "⚠ Dossier '$folderName' déjà présent" -ForegroundColor Yellow
        return
    }
    
    $paths = @{
        "data_updater" = "D:\.my_soft\gestionnaire_telechargement_multi-timeframe_clean"
        "models_data" = "K:\models"
    }
    
    if ($null -eq $paths[$folderName]) {
        Write-Host "❌ Dossier inconnu: $folderName" -ForegroundColor Red
        return
    }
    
    $newFolder = @{
        path = $paths[$folderName]
        name = $folderName
        hidden = $false
    }
    
    $workspace.folders += $newFolder
    Save-Workspace $workspace
    Write-Host "✓ Dossier '$folderName' ajouté et rendu visible" -ForegroundColor Green
    Show-Folders
}

function Remove-Folder($folderName) {
    $workspace = Load-Workspace
    
    if ($folderName -eq "backtest_core") {
        Write-Host "❌ Impossible de supprimer le dossier principal 'backtest_core'" -ForegroundColor Red
        return
    }
    
    $originalCount = $workspace.folders.Count
    $workspace.folders = $workspace.folders | Where-Object { $_.name -ne $folderName }
    
    if ($workspace.folders.Count -eq $originalCount) {
        Write-Host "⚠ Dossier '$folderName' non trouvé" -ForegroundColor Yellow
        return
    }
    
    Save-Workspace $workspace
    Write-Host "✓ Dossier '$folderName' supprimé" -ForegroundColor Green
    Show-Folders
}

function Hide-Folder($folderName) {
    $workspace = Load-Workspace
    
    $folder = $workspace.folders | Where-Object { $_.name -eq $folderName } | Select-Object -First 1
    if ($null -eq $folder) {
        Write-Host "❌ Dossier '$folderName' non trouvé" -ForegroundColor Red
        return
    }
    
    $folder.hidden = $true
    Save-Workspace $workspace
    Write-Host "✓ Dossier '$folderName' caché" -ForegroundColor Green
    Show-Folders
}

function Unhide-Folder($folderName) {
    $workspace = Load-Workspace
    
    $folder = $workspace.folders | Where-Object { $_.name -eq $folderName } | Select-Object -First 1
    if ($null -eq $folder) {
        Write-Host "❌ Dossier '$folderName' non trouvé" -ForegroundColor Red
        return
    }
    
    $folder.hidden = $false
    Save-Workspace $workspace
    Write-Host "✓ Dossier '$folderName' rendu visible" -ForegroundColor Green
    Show-Folders
}

function Setup-All {
    Write-Host "`n🔧 Configuration complète des environnements...`n" -ForegroundColor Cyan
    
    # Setup backtest_core
    $backtest_venv = "$projectRoot\.venv"
    if (Test-Path $backtest_venv) {
        Write-Host "✓ .venv backtest_core existe" -ForegroundColor Green
    } else {
        Write-Host "⚠ .venv backtest_core manquant - création recommandée" -ForegroundColor Yellow
    }
    
    # Setup data_updater
    $data_updater_venv = "D:\.my_soft\gestionnaire_telechargement_multi-timeframe_clean\.venv"
    if (Test-Path $data_updater_venv) {
        Write-Host "✓ .venv data_updater existe" -ForegroundColor Green
    } else {
        Write-Host "⚠ .venv data_updater manquant - création recommandée" -ForegroundColor Yellow
    }
    
    Write-Host "`n📝 Pour créer les venvs manquants :`n" -ForegroundColor Cyan
    Write-Host "  # Backtest core"
    Write-Host "  cd $projectRoot"
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\pip install -r requirements.txt`n"
    Write-Host "  # Data updater"
    Write-Host "  cd D:\.my_soft\gestionnaire_telechargement_multi-timeframe_clean"
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\pip install -r requirements.txt`n"
}

# Main
switch ($Action) {
    "add" {
        if ($null -eq $Folder) {
            Write-Host "❌ Spécifie le dossier: data_updater ou models_data" -ForegroundColor Red
            exit 1
        }
        Add-Folder $Folder
    }
    "remove" {
        if ($null -eq $Folder) {
            Write-Host "❌ Spécifie le dossier: data_updater ou models_data" -ForegroundColor Red
            exit 1
        }
        Remove-Folder $Folder
    }
    "show" {
        Show-Folders
    }
    "status" {
        Show-Folders
    }
    "hide" {
        if ($null -eq $Folder) {
            Write-Host "❌ Spécifie le dossier: data_updater ou models_data" -ForegroundColor Red
            exit 1
        }
        Hide-Folder $Folder
    }
    "unhide" {
        if ($null -eq $Folder) {
            Write-Host "❌ Spécifie le dossier: data_updater ou models_data" -ForegroundColor Red
            exit 1
        }
        Unhide-Folder $Folder
    }
    "setup-all" {
        Setup-All
    }
}

Write-Host ""
