@echo off
rem =====================================================================
rem  Quelle base le WMS utilise-t-il en ce moment ?
rem
rem  A double-cliquer en cas de doute : deux bases peuvent repondre, une
rem  seule contient le travail du jour.
rem =====================================================================
title WMS Structa - quelle base ?
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo  Lancez d'abord Demarrer-WMS.bat une fois.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" outils\basculer_base.py etat
echo.
echo  Pour basculer :
echo     .venv\Scripts\python.exe outils\basculer_base.py sqlite
echo     .venv\Scripts\python.exe outils\basculer_base.py postgresql
echo.
pause
