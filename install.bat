@echo off
setlocal
REM ============================================================
REM Backtest Core V2 - Script d'Installation Automatique (Windows)
REM ============================================================

set "ROOT_DIR=%~dp0"
set "VENV_DIR=%ROOT_DIR%.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

echo.
echo ========================================
echo  Backtest Core V2 - Installation
echo ========================================
echo.

if exist "%VENV_PY%" (
    echo [ETAPE 1/3] Environnement virtuel detecte: %VENV_PY%
) else (
    echo [ETAPE 1/3] Creation de l'environnement virtuel...
    where py >nul 2>&1
    if %errorlevel% equ 0 (
        py -3.12 -m venv "%VENV_DIR%"
    ) else (
        python -m venv "%VENV_DIR%"
    )
    if %errorlevel% neq 0 (
        echo [ERREUR] Creation de .venv echouee
        echo Verifiez que Python 3.12 est installe et accessible.
        pause
        exit /b 1
    )
)

if not exist "%VENV_PY%" (
    echo [ERREUR] Interpreteur virtuel introuvable: %VENV_PY%
    pause
    exit /b 1
)

echo.
echo [ETAPE 2/3] Mise a jour de pip...
"%VENV_PY%" -m pip install --upgrade pip --quiet
if %errorlevel% neq 0 (
    echo [ERREUR] Mise a jour de pip echouee
    pause
    exit /b 1
)

echo.
echo [ETAPE 3/3] Installation des dependances...
"%VENV_PY%" -m pip install -r "%ROOT_DIR%requirements.txt"
if %errorlevel% neq 0 (
    echo [ERREUR] Installation des dependances echouee
    pause
    exit /b 1
)

echo.
echo ========================================
echo  Installation REUSSIE!
echo ========================================
echo.
echo Pour lancer l'interface:
echo   1. Activer l'environnement: .venv\Scripts\activate
echo   2. Lancer Streamlit:        streamlit run ui\app.py
echo.
echo Documentation complete: README.md
echo.

echo [TEST] Verification des imports...
"%VENV_PY%" -c "import streamlit, pandas, numpy, plotly; print('[OK] Toutes les dependances sont installees!')"
if %errorlevel% neq 0 (
    echo [ATTENTION] Certains imports ont echoue, verifiez requirements.txt
)

echo.
pause
