@echo off
rem =====================================================================
rem  PREPARE LE DOSSIER A COPIER SUR LE POSTE SERVEUR.
rem
rem  A lancer sur CE poste (celui qui a l'application aujourd'hui).
rem  Produit, a cote du projet, un dossier et une archive .zip qui ne
rem  contiennent que ce qui doit voyager : ni environnement Python, ni
rem  cle secrete, ni certificat, ni ancienne base.
rem
rem  Les donnees de l'entrepot sont exportees au passage : elles suivent
rem  dans le dossier reprise\.
rem =====================================================================
title WMS Structa - preparation de la copie
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  Environnement Python absent. Lancez d'abord Demarrer-WMS.bat une fois.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" outils\preparer_copie.py %*
echo.
pause
