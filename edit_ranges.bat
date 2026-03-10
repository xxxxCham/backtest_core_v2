@echo off
REM Script pour lancer l'éditeur de plages de paramètres
REM Usage: edit_ranges.bat

echo.
echo ========================================
echo   Editeur de Plages - Backtest Core
echo ========================================
echo.

REM Vérifier l'environnement virtuel
if not exist ".venv\Scripts\activate.bat" (
    echo [ERREUR] Environnement virtuel non trouve
    echo Executez d'abord: install.bat
    pause
    exit /b 1
)

echo [1/3] Activation environnement virtuel...
call .venv\Scripts\activate.bat

echo [2/3] Verification Streamlit...
python -c "import streamlit" 2>nul
if errorlevel 1 (
    echo [ERREUR] Streamlit non installe
    echo Installation en cours...
    pip install streamlit
)

echo [3/3] Lancement editeur...
echo.
echo ========================================
echo Interface disponible sur:
echo http://localhost:8502
echo ========================================
echo.
echo Appuyez sur Ctrl+C pour arreter
echo.

streamlit run ui\pages\range_editor_page.py --server.port=8502

pause
