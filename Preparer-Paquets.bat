@echo off
rem =====================================================================
rem  CONSTITUE LE DOSSIER paquets\ : TOUTES LES DEPENDANCES, EN LOCAL.
rem
rem  A lancer sur CE poste, qui a acces a internet. Le dossier produit
rem  part avec la copie : le poste serveur s'installe alors sans reseau.
rem
rem  A refaire si requirements.txt change, ou si le poste serveur n'a pas
rem  la meme version de Python que celui-ci.
rem =====================================================================
title WMS Structa - dependances hors ligne
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  Environnement Python absent. Lancez d'abord Demarrer-WMS.bat une fois.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" outils\preparer_paquets.py %*
echo.
pause
