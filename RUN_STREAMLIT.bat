@echo off
setlocal

REM ============================================================================
REM BACKTEST CORE V2 - Lanceur unique Streamlit
REM Point d'entree unique pour l'application UI.
REM
REM OPTIONS:
REM   --clean         : Force le nettoyage des caches Python (__pycache__, .pyc)
REM   --clean-numba   : Force aussi la suppression du cache Numba (JIT recompile)
REM   --clean-all     : Equivalent a --clean + --clean-numba + cache Streamlit
REM ============================================================================

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM --- Lecture des flags de ligne de commande ---
set "FLAG_CLEAN=0"
set "FLAG_CLEAN_NUMBA=0"
set "FLAG_CLEAN_STREAMLIT=0"
for %%A in (%*) do (
    if /I "%%A"=="--clean"       set "FLAG_CLEAN=1"
    if /I "%%A"=="--clean-numba" set "FLAG_CLEAN_NUMBA=1"
    if /I "%%A"=="--clean-all"   set "FLAG_CLEAN=1" & set "FLAG_CLEAN_NUMBA=1" & set "FLAG_CLEAN_STREAMLIT=1"
)

if not defined BACKTEST_STREAMLIT_PORT (
    set "BACKTEST_STREAMLIT_PORT=8502"
)
if not defined BACKTEST_STREAMLIT_STALE_RUNTIME_CLAIM_TIMEOUT_SEC (
    set "BACKTEST_STREAMLIT_STALE_RUNTIME_CLAIM_TIMEOUT_SEC=120"
)
if not defined BACKTEST_STREAMLIT_RESTART_DELAY_SEC (
    set "BACKTEST_STREAMLIT_RESTART_DELAY_SEC=5"
)

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

taskkill /F /FI "WINDOWTITLE eq *streamlit*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq *Streamlit*" >nul 2>&1
ping -n 2 127.0.0.1 >nul

echo       [OK] Processus orphelins nettoyes
echo.

REM ============================================================================
REM ETAPE 2: Nettoyage des caches (conditionnel - uniquement si flag explicite)
REM          Raison: la suppression systematique penalise de 45-90s au demarrage
REM          Usage: RUN_STREAMLIT.bat --clean-all  (apres mise a jour sources)
REM ============================================================================
echo [2/5] Verification des caches...

if "%FLAG_CLEAN%"=="1" (
    echo       [--clean] Nettoyage du cache Python en cours...
    for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d" >nul 2>&1
    del /s /q *.pyc >nul 2>&1
    echo       [OK] Cache Python nettoye
) else (
    echo       [OK] Cache Python conserve ^(utilisez --clean pour forcer^)
)

if "%FLAG_CLEAN_NUMBA%"=="1" (
    if exist ".numba_cache" (
        echo       [--clean-numba] Suppression du cache Numba ^(JIT se recompile au 1er sweep^)...
        rmdir /s /q ".numba_cache" >nul 2>&1
        echo       [OK] Cache Numba supprime
    ) else (
        echo       [OK] Pas de cache Numba a supprimer
    )
) else (
    if exist ".numba_cache" (
        echo       [OK] Cache Numba conserve ^(utilisez --clean-numba pour forcer^)
    ) else (
        echo       [OK] Pas de cache Numba existant
    )
)

if "%FLAG_CLEAN_STREAMLIT%"=="1" (
    if exist "%USERPROFILE%\.streamlit\cache" (
        echo       [--clean-all] Nettoyage du cache Streamlit...
        rmdir /s /q "%USERPROFILE%\.streamlit\cache" >nul 2>&1
        echo       [OK] Cache Streamlit nettoye
    )
) else (
    echo       [OK] Cache Streamlit conserve
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

REM --- Threading CPU (Numba / OpenMP / MKL) ---
set "NUMBA_NUM_THREADS=32"
set "NUMBA_THREADING_LAYER=omp"
set "NUMBA_CACHE_DIR=%CD%\.numba_cache"
set "OMP_NUM_THREADS=32"
set "MKL_NUM_THREADS=32"
set "OPENBLAS_NUM_THREADS=32"
set "NUMEXPR_MAX_THREADS=32"

REM --- GPU backtest: desactive pour les sweeps Streamlit multiprocess.
REM     NOTE: ce flag est AUSSI force a "0" dans ui/main.py (ligne ~20) et
REM     ui/helpers.py. Pour activer le GPU du moteur de backtest, ces deux
REM     fichiers Python doivent etre modifies en plus de cette variable.
set "BACKTEST_USE_GPU=0"
set "BACKTEST_GPU_QUEUE_ENABLED=0"

REM --- CUDA: laisser non defini pour les workers backtest CPU.
REM     ollama_manager.py injecte ses propres CUDA_VISIBLE_DEVICES dans le
REM     sous-processus Ollama; ne pas definir CUDA_VISIBLE_DEVICES ici evite
REM     d'heriter une valeur vide ambigue dans les workers CuPy/CUDA futurs.
REM set "CUDA_VISIBLE_DEVICES="
REM set "GPU_DEVICE_ORDINAL="
REM set "HIP_VISIBLE_DEVICES="

REM --- Chemins des resultats et artefacts (synchronises avec .env) ---
REM     Ces variables sont lues par cli/commands.py, tools/analyze_results.py,
REM     backtest/result_store.py, backtest/config_storage.py, etc.
REM     Sans elles, les workers ProcessPool enfants peuvent ecrire dans
REM     ./backtest_results local au lieu du store externe configure.
if not defined BACKTEST_RESULTS_DIR (
    set "BACKTEST_RESULTS_DIR=C:\Users\o3-Pro\Documents\backtest_results"
)
if not defined BACKTEST_ARTIFACTS_DIR (
    set "BACKTEST_ARTIFACTS_DIR=C:\Users\o3-Pro\Documents\backtest_results"
)

REM --- Modeles et catalogues ---
set "MODELS_JSON_PATH=C:\AI\models\catalog\models.json"
set "OLLAMA_MODELS=C:\AI\ollama\models"
set "MODEL_LIBRARY_ROOTS=K:\models;C:\AI\models\library"
set "HUGGINGFACE_ARCHIVE_ROOT=L:\models"

REM --- Ollama GPU (mode auto = Ollama decide seul de la repartition) ---
if not defined BACKTEST_OLLAMA_GPU_TARGET set "BACKTEST_OLLAMA_GPU_TARGET=auto"
if not defined BACKTEST_OLLAMA_PIN_LOCALHOST set "BACKTEST_OLLAMA_PIN_LOCALHOST=0"
if not defined BACKTEST_OLLAMA_RESTART_LOCAL_DAEMON set "BACKTEST_OLLAMA_RESTART_LOCAL_DAEMON=0"

REM --- Donnees OHLCV (auto-detection si non defini par .env) ---
if not defined BACKTEST_DATA_DIR (
    if exist "D:\.my_soft\gestionnaire_telechargement_multi-timeframe_clean\processed\parquet" (
        set "BACKTEST_DATA_DIR=D:\.my_soft\gestionnaire_telechargement_multi-timeframe_clean\processed\parquet"
    ) else if exist "D:\my_soft\gestionnaire_telechargement_multi-timeframe_clean\processed\parquet" (
        set "BACKTEST_DATA_DIR=D:\my_soft\gestionnaire_telechargement_multi-timeframe_clean\processed\parquet"
    ) else if exist "D:\.my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet" (
        set "BACKTEST_DATA_DIR=D:\.my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet"
    ) else if exist "D:\my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet" (
        set "BACKTEST_DATA_DIR=D:\my_soft\gestionnaire_telechargement_multi-timeframe\processed\parquet"
    )
)

echo       [OK] NUMBA_NUM_THREADS=32
echo       [OK] NUMBA_THREADING_LAYER=omp
echo       [OK] OMP_NUM_THREADS=32 / MKL=32 / OPENBLAS=32 / NUMEXPR=32
echo       [OK] GPU backtest desactive (Ollama GPU gere separement)
echo       [OK] OLLAMA GPU cible=%BACKTEST_OLLAMA_GPU_TARGET%
echo       [OK] OLLAMA pin localhost=%BACKTEST_OLLAMA_PIN_LOCALHOST%
echo       [OK] OLLAMA restart local daemon=%BACKTEST_OLLAMA_RESTART_LOCAL_DAEMON%
echo       [OK] MODELS_JSON_PATH=%MODELS_JSON_PATH%
echo       [OK] OLLAMA_MODELS=%OLLAMA_MODELS%
echo       [OK] BACKTEST_RESULTS_DIR=%BACKTEST_RESULTS_DIR%
echo       [OK] BACKTEST_ARTIFACTS_DIR=%BACKTEST_ARTIFACTS_DIR%
if defined BACKTEST_DATA_DIR (
    echo       [OK] BACKTEST_DATA_DIR=%BACKTEST_DATA_DIR%
) else (
    echo       [INFO] BACKTEST_DATA_DIR non force ^(auto-detection loader^)
)
echo       [OK] WATCHDOG relance sur sortie process seulement / delai=%BACKTEST_STREAMLIT_RESTART_DELAY_SEC%s
echo.

REM ============================================================================
REM ETAPE 5: Lancement de Streamlit
REM ============================================================================
echo [5/5] Lancement de Streamlit...
echo.
echo ========================================================================
echo                         PRET AU LANCEMENT
echo ========================================================================
echo   URL cible: http://localhost:%BACKTEST_STREAMLIT_PORT%
echo   Si ce port est occupe, le watchdog annoncera un port libre
echo   ou signalera qu'une instance existe deja.
echo   Performance: ~6,600 bt/s (sweep Numba optimise)
echo   Temps 1.7M combos: ~4-5 minutes
echo   Appuyez sur Ctrl+C pour arreter
echo   Flags disponibles: --clean  --clean-numba  --clean-all
echo ========================================================================
echo.

python tools\streamlit_watchdog.py ^
  --port %BACKTEST_STREAMLIT_PORT% ^
  --stale-runtime-claim-timeout-sec %BACKTEST_STREAMLIT_STALE_RUNTIME_CLAIM_TIMEOUT_SEC% ^
  --restart-delay-sec %BACKTEST_STREAMLIT_RESTART_DELAY_SEC%

echo.
echo ========================================================================
echo                       APPLICATION ARRETEE
echo ========================================================================
pause
