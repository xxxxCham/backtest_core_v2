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

for /f "usebackq delims=" %%i in (`"%PYTHON_BIN%" -c "from backtest.result_store import get_results_analysis_dir; print(get_results_analysis_dir())"`) do set "ANALYSIS_DIR=%%i"

if not defined ANALYSIS_DIR (
    echo Unable to resolve analysis directory.
    exit /b 1
)

echo [2/2] Open refreshed artifacts from "%ANALYSIS_DIR%"...
start "" "%ANALYSIS_DIR%\analysis_report.html"
start "" "%ANALYSIS_DIR%\analysis_report_filtered.html"
start "" "%ANALYSIS_DIR%\analysis_top_configs.csv"
