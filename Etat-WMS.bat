@echo off
rem =====================================================================
rem  ETAT DU WMS SUR CE SERVEUR, en un ecran : les taches planifiees,
rem  les ports, la sante de l'application, le certificat, les
rem  sauvegardes et la place libre.
rem =====================================================================
title WMS Structa - etat du serveur
cd /d "%~dp0"

rem Droits administrateur ? (fltmc, et non "net session" : celui-ci echoue
rem aussi quand le service Serveur est desactive, et la fenetre se
rem redemanderait alors l'elevation sans fin.)
rem "&&" et non "if not errorlevel 1" : un code de sortie negatif
rem (0x80070005, acces refuse) passerait ce test pour un succes.
fltmc >nul 2>&1 && goto :etat
echo  Demande des droits administrateur...
rem Le chemin par une variable : une apostrophe dans le nom d'un dossier
rem cassait la commande PowerShell, et la fenetre se fermait sans un mot.
set "WMS_SOI=%~f0"
powershell -NoProfile -Command "Start-Process -FilePath $env:WMS_SOI -Verb RunAs"
exit /b 0

:etat
".venv\Scripts\python.exe" outils\serveur_wms.py etat
echo.
pause
