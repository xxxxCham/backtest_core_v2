@echo off
setlocal

REM Alias de lancement principal (compatibilite)
REM Ce script delegue au lanceur maintenu RUN_STREAMLIT.bat.

call "%~dp0RUN_STREAMLIT.bat"

endlocal
