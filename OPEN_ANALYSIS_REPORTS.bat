@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_BIN=.venv\Scripts\python.exe"
) else (
    set "PYTHON_BIN=python"
)

set "MODE=standard"
if /I "%~1"=="--llm-benchmark" set "MODE=llm_benchmark"
if /I "%~1"=="--llm" set "MODE=llm_benchmark"

if /I "%MODE%"=="llm_benchmark" goto :open_llm_benchmark

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
exit /b 0

:open_llm_benchmark
set "LLM_ANALYSIS_DIR=backtest_results\_analysis"
set "CAMPAIGN_JSON=%LLM_ANALYSIS_DIR%\llm_token_matrix_campaign_full.json"
set "RERUN_JSON=%LLM_ANALYSIS_DIR%\llm_token_matrix_parser_rerun.json"

if not exist "%CAMPAIGN_JSON%" if not exist "%RERUN_JSON%" (
    echo No LLM benchmark JSON artifacts found in "%LLM_ANALYSIS_DIR%".
    echo Expected at least one of:
    echo   %CAMPAIGN_JSON%
    echo   %RERUN_JSON%
    exit /b 1
)

echo [1/2] Refresh LLM benchmark HTML reports...
call :refresh_llm_html "%CAMPAIGN_JSON%"
if errorlevel 1 exit /b 1
call :refresh_llm_html "%RERUN_JSON%"
if errorlevel 1 exit /b 1

echo [2/2] Open LLM benchmark reports...
if exist "%LLM_ANALYSIS_DIR%\llm_token_matrix_campaign_full.html" (
    start "" "%LLM_ANALYSIS_DIR%\llm_token_matrix_campaign_full.html"
) else (
    echo Campaign HTML missing: "%LLM_ANALYSIS_DIR%\llm_token_matrix_campaign_full.html"
)
if exist "%LLM_ANALYSIS_DIR%\llm_token_matrix_parser_rerun.html" (
    start "" "%LLM_ANALYSIS_DIR%\llm_token_matrix_parser_rerun.html"
) else (
    echo Parser rerun HTML missing: "%LLM_ANALYSIS_DIR%\llm_token_matrix_parser_rerun.html"
)
exit /b 0

:refresh_llm_html
if not exist "%~1" exit /b 0

set "INPUT_JSON_ABS=%~f1"
for %%I in ("%INPUT_JSON_ABS%") do set "OUTPUT_HTML=%%~dpnI.html"

echo   - Build "%OUTPUT_HTML%" from "%INPUT_JSON_ABS%"
"%PYTHON_BIN%" -c "import json; from pathlib import Path; from tools.generate_html_report import generate_llm_benchmark_html_report; p = Path(r'%INPUT_JSON_ABS%'); payload = json.loads(p.read_text(encoding='utf-8')); payload['__source_path'] = str(p); generate_llm_benchmark_html_report(payload, p.with_suffix('.html'))"
if errorlevel 1 (
    echo Failed to generate HTML report from "%INPUT_JSON_ABS%".
    exit /b 1
)
exit /b 0
