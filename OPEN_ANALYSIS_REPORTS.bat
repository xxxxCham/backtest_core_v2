@echo off
setlocal

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_BIN=.venv\Scripts\python.exe"
) else (
    set "PYTHON_BIN=python"
)

echo [1/2] Refresh analysis reports...
"%PYTHON_BIN%" -m tools.analyze_results --top 100
if errorlevel 1 (
    echo Refresh failed.
    exit /b 1
)

echo [2/2] Open refreshed artifacts...
start "" "analysis_report.html"
start "" "analysis_report_filtered.html"
start "" "analysis_top_configs.csv"
