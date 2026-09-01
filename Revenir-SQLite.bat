@echo off
rem =====================================================================
rem  Revenir a la base SQLite (fichier db.sqlite3).
rem
rem  Les reglages PostgreSQL ne sont pas perdus : ils restent en
rem  commentaire dans .env, prets a resservir.
rem =====================================================================
title WMS Structa - retour sur SQLite
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo  Lancez d'abord Demarrer-WMS.bat une fois.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" outils\basculer_base.py sqlite
".venv\Scripts\python.exe" outils\basculer_base.py etat
echo.
pause
