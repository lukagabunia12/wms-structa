@echo off
rem =====================================================================
rem  Repetition PostgreSQL SUR CE POSTE.
rem
rem  Eprouve le WMS sur une vraie base SQL, avec vos donnees, sans
rem  toucher au serveur ni a db.sqlite3 (l'export ne fait que lire).
rem  Retour arriere a tout moment : Revenir-SQLite.bat
rem
rem  PREALABLE, une fois : installer PostgreSQL depuis
rem  https://www.postgresql.org/download/windows/
rem    - noter le mot de passe du compte "postgres" demande a l'installation
rem    - cocher "Command Line Tools" (fournit psql et pg_dump)
rem
rem  Rien a ajouter au PATH : le script trouve le dossier bin tout seul.
rem  Une version precedente testait "where psql" et refusait de demarrer sur
rem  un poste ou PostgreSQL etait pourtant installe -- l'installeur Windows
rem  n'ajoute pas son dossier bin au PATH. Ce test a ete retire : la
rem  recherche et le message d'erreur sont dans Trouver-PostgreSQL.ps1.
rem =====================================================================
title WMS Structa - repetition PostgreSQL
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  Lancez d'abord Demarrer-WMS.bat une fois, pour creer l'environnement.
    echo.
    pause
    exit /b 1
)

powershell -ExecutionPolicy Bypass -File "deploiement\windows\Repeter-PostgreSQL.ps1"
echo.
pause
