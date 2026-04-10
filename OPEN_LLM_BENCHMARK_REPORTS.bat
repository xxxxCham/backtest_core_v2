@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

call "%SCRIPT_DIR%OPEN_ANALYSIS_REPORTS.bat" --llm-benchmark
