@echo off
rem =====================================================================
rem  BASCULE DEFINITIVE DU WMS SUR POSTGRESQL.
rem
rem  Prepare la base d'EXPLOITATION (wms), pas la base d'essai.
rem  N'ecrase jamais une base existante qui contient des tables.
rem  Le fichier db.sqlite3 n'est pas modifie : il reste votre filet.
rem
rem  Retour arriere a tout moment : Revenir-SQLite.bat
rem =====================================================================
title WMS Structa - bascule sur PostgreSQL
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  Lancez d'abord Demarrer-WMS.bat une fois, pour creer l'environnement.
    echo.
    pause
    exit /b 1
)

echo.
echo  Cette operation fait passer le WMS sur PostgreSQL, pour de bon.
echo  Assurez-vous que le serveur WMS est ARRETE avant de continuer.
echo.
pause

powershell -ExecutionPolicy Bypass -File "deploiement\windows\Basculer-PostgreSQL.ps1"
echo.
pause
