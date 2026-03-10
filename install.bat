@echo off
REM ============================================================
REM Backtest Core - Script d'Installation Automatique (Windows)
REM ============================================================
REM NOTE: Utilise le script PowerShell fix_venv_windows.ps1 pour une installation robuste

echo.
echo ========================================
echo  Backtest Core - Installation
echo ========================================
echo.
echo Lancement du script PowerShell automatise...
echo.

REM Lancer le script PowerShell de réparation
powershell -ExecutionPolicy Bypass -File "%~dp0fix_venv_windows.ps1"

if %errorlevel% neq 0 (
    echo.
    echo [ERREUR] L'installation a echoue
    echo Consultez les messages ci-dessus pour plus de details
    pause
    exit /b 1
)

echo.
echo ========================================
echo  Installation terminee avec succes !
echo ========================================

REM Installer les dépendances
echo.
echo [ETAPE 3/3] Installation des dependances...
echo [INFO] Mise a jour de pip...
python -m pip install --upgrade pip --quiet

echo [INFO] Installation de requirements.txt...
pip install -r requirements.txt
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
echo Documentation complete: INSTALL.md
echo.

REM Test rapide
echo [TEST] Verification des imports...
python -c "import streamlit, pandas, numpy, plotly; print('[OK] Toutes les dependances sont installees!')"
if %errorlevel% neq 0 (
    echo [ATTENTION] Certains imports ont echoue, verifiez requirements.txt
)

echo.
pause
