@echo off
rem =====================================================================
rem  INSTALLE LE WMS STRUCTA SUR CE POSTE.
rem
rem  A lancer UNE FOIS, apres avoir copie le dossier du projet sur le
rem  poste qui servira de serveur.
rem
rem  A installer AVANT, sur ce poste :
rem    - Python           https://www.python.org/downloads/windows/
rem                       (cocher "Add python.exe to PATH", et de preference
rem                        "Install for all users" : cette fenetre tourne en
rem                        administrateur, parfois sous un autre compte)
rem    - PostgreSQL       https://www.postgresql.org/download/windows/
rem                       (cocher "Command Line Tools")
rem
rem  Ce fichier demande les droits administrateur : ils sont necessaires
rem  pour ouvrir le port dans le pare-feu et inscrire l'autorite de
rem  certification. Sans eux, les telephones ne joindront pas le serveur.
rem
rem  DEUX OPTIONS DE SECOURS, a taper en ligne de commande :
rem
rem    Installer-WMS.bat -Tunnel
rem      quand le port 8443 n'est pas encore ouvert. L'acces passera par
rem      cloudflared : pare-feu et certificat local sont alors inutiles.
rem
rem    Installer-WMS.bat -SansPostgreSQL
rem      quand PostgreSQL ne peut pas etre installe. Le WMS tourne sur un
rem      fichier SQLite : cela tient pour un POC de quelques jours, pas
rem      pour un usage reel a plusieurs caristes.
rem
rem  Les deux se combinent :  Installer-WMS.bat -Tunnel -SansPostgreSQL
rem =====================================================================
title WMS Structa - installation du poste serveur
cd /d "%~dp0"

net session >nul 2>&1
if not errorlevel 1 goto :installer

echo.
echo  Demande des droits administrateur...
echo  Repondez Oui a la fenetre qui s'ouvre.
echo.
rem Les arguments doivent traverser l'elevation : sans -ArgumentList, un
rem  Installer-WMS.bat -Python "C:\..."  perdait son option en cours de route
rem et repartait dans la recherche automatique qui venait d'echouer.
if "%~1"=="" (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
) else (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
)
exit /b 0

:installer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploiement\windows\Installer-WMS.ps1" %*
echo.
pause
