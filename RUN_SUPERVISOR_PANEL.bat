@echo off
setlocal
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" tools\supervisor_control_panel.py
) else (
    python tools\supervisor_control_panel.py
)
