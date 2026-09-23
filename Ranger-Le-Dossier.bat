@echo off
rem =====================================================================
rem  RANGE LE DOSSIER DU PROJET.
rem
rem  Deplace dans un dossier d'archive date ce qui a servi et ne sert plus :
rem  anciennes versions de documents, captures de recette, paquet serveur
rem  perime, roues Python remplacees. RIEN N'EST SUPPRIME : tout reste
rem  lisible dans l'archive, et se ramene d'un glisser.
rem
rem  Seuls les dossiers __pycache__ sont effaces : Python les refabrique.
rem
rem  Premier lancement : il MONTRE ce qu'il ferait, sans rien deplacer.
rem =====================================================================
title WMS Structa - rangement du dossier
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  Environnement Python absent. Lancez d'abord Demarrer-WMS.bat une fois.
    echo.
    pause
    exit /b 1
)

echo.
echo  --- Ce qui serait range (rien n'est deplace pour l'instant) ---
".venv\Scripts\python.exe" outils\ranger_le_dossier.py
echo.
set /p REPONSE=  Ranger pour de bon ? (O/N) :
if /i not "%REPONSE%"=="O" (
    echo.
    echo  Rien n'a ete deplace.
    echo.
    pause
    exit /b 0
)
".venv\Scripts\python.exe" outils\ranger_le_dossier.py --ranger
echo.
pause
