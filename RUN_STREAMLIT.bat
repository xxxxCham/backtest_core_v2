@echo off
setlocal

REM ============================================================================
REM BACKTEST CORE MULTI-LLM - Lanceur Streamlit avec nettoyage automatique
REM ============================================================================

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

if not defined BACKTEST_STREAMLIT_PORT (
    set "BACKTEST_STREAMLIT_PORT=8502"
)
set "BACKTEST_WORKSPACE_VARIANT=multillm_parallel"

echo.
echo ========================================================================
echo       BACKTEST CORE MULTI-LLM - Demarrage Optimise
echo ========================================================================
echo.
echo [INFO] Repertoire: %CD%
echo.

REM ============================================================================
REM ETAPE 1: Nettoyage des processus Python orphelins
REM ============================================================================
echo [1/5] Nettoyage des processus Python orphelins...

REM Methode simple: tuer tous les processus streamlit existants
taskkill /F /FI "WINDOWTITLE eq *streamlit*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq *Streamlit*" >nul 2>&1

REM Attendre un peu
ping -n 2 127.0.0.1 >nul

echo       [OK] Processus orphelins nettoyes
echo.

REM ============================================================================
REM ETAPE 2: Nettoyage des caches
REM ============================================================================
echo [2/5] Nettoyage des caches...

REM Cache Python (.pyc, __pycache__) - CRITIQUE apres reboot
echo       Nettoyage du cache Python...
for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d" >nul 2>&1
del /s /q *.pyc >nul 2>&1
echo       [OK] Cache Python nettoye

if exist ".numba_cache" (
    echo       Suppression du cache Numba...
    rmdir /s /q ".numba_cache" >nul 2>&1
    echo       [OK] Cache Numba supprime
) else (
    echo       [OK] Pas de cache Numba
)

if exist "%USERPROFILE%\.streamlit\cache" (
    echo       Nettoyage du cache Streamlit...
    rmdir /s /q "%USERPROFILE%\.streamlit\cache" >nul 2>&1
    echo       [OK] Cache Streamlit nettoye
) else (
    echo       [OK] Pas de cache Streamlit
)
echo.

REM ============================================================================
REM ETAPE 3: Activation de l'environnement virtuel
REM ============================================================================
echo [3/5] Activation de l'environnement virtuel...

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
    echo       [OK] Environnement active
) else (
    echo       [WARN] .venv non trouve
)
echo.

REM ============================================================================
REM ETAPE 4: Configuration de l'environnement optimal
REM ============================================================================
echo [4/5] Configuration de l'environnement optimal...

set "NUMBA_NUM_THREADS=32"
set "NUMBA_THREADING_LAYER=omp"
set "NUMBA_CACHE_DIR=%CD%\.numba_cache"
set "OMP_NUM_THREADS=32"
set "MKL_NUM_THREADS=32"
set "OPENBLAS_NUM_THREADS=32"
set "NUMEXPR_MAX_THREADS=32"
set "BACKTEST_USE_GPU=0"

if not defined BACKTEST_DATA_DIR (
    if exist "D:\.my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet" (
        set "BACKTEST_DATA_DIR=D:\.my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet"
    ) else if exist "D:\my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet" (
        set "BACKTEST_DATA_DIR=D:\my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet"
    )
)

echo       [OK] NUMBA_NUM_THREADS=32
echo       [OK] NUMBA_THREADING_LAYER=omp
echo       [OK] OMP_NUM_THREADS=32
echo       [OK] MKL_NUM_THREADS=32
echo       [OK] OPENBLAS_NUM_THREADS=32
echo       [OK] NUMEXPR_MAX_THREADS=32
echo       [OK] Threading: OpenMP
echo       [OK] GPU desactive
if defined BACKTEST_DATA_DIR (
    echo       [OK] BACKTEST_DATA_DIR=%BACKTEST_DATA_DIR%
) else (
    echo       [INFO] BACKTEST_DATA_DIR non force (auto-detection loader)
)
echo.

REM ============================================================================
REM ETAPE 5: Lancement de Streamlit
REM ============================================================================
echo [5/5] Lancement de Streamlit...
echo.
echo ========================================================================
echo                         PRET AU LANCEMENT
echo ========================================================================
echo   URL: http://localhost:%BACKTEST_STREAMLIT_PORT%
echo   Performance: ~6,600 bt/s (sweep Numba optimise)
echo   Temps 1.7M combos: ~4-5 minutes
echo   Appuyez sur Ctrl+C pour arreter
echo ========================================================================
echo.

python -m streamlit run ui\app.py --server.port %BACKTEST_STREAMLIT_PORT% --server.maxUploadSize 500

echo.
echo ========================================================================
echo                       APPLICATION ARRETEE
echo ========================================================================
pause
