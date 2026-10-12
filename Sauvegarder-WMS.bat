@echo off
rem =====================================================================
rem  SAUVEGARDE LE WMS MAINTENANT -- la base (verifiee) et la configuration.
rem
rem  La meme sauvegarde que la tache planifiee, a lancer avant une mise a
rem  jour ou une operation delicate. Destination et copie : reglages
rem  WMS_SAUVEGARDE_DOSSIER et WMS_SAUVEGARDE_COPIE dans .env.
rem
rem  Demande les droits administrateur : sur le serveur, le dossier des
rem  sauvegardes leur est reserve.
rem =====================================================================
title WMS Structa - sauvegarde
cd /d "%~dp0"

rem Droits administrateur ? (fltmc, et non "net session" : celui-ci echoue
rem aussi quand le service Serveur est desactive, et la fenetre se
rem redemanderait alors l'elevation sans fin.)
rem "&&" et non "if not errorlevel 1" : un code de sortie negatif
rem (0x80070005, acces refuse) passerait ce test pour un succes.
fltmc >nul 2>&1 && goto :sauvegarder
echo  Demande des droits administrateur...
rem Le chemin par une variable : une apostrophe dans le nom d'un dossier
rem cassait la commande PowerShell, et la fenetre se fermait sans un mot.
set "WMS_SOI=%~f0"
powershell -NoProfile -Command "Start-Process -FilePath $env:WMS_SOI -Verb RunAs"
exit /b 0

:sauvegarder
set "DJANGO_LOG_CONSOLE=False"
".venv\Scripts\python.exe" manage.py sauvegarder
echo.
pause
