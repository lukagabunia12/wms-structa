@echo off
rem =====================================================================
rem  ARRETE LE WMS SUR CE SERVEUR -- pour une mise a jour, une
rem  maintenance, une restauration.
rem
rem  Il ne repart PAS tout seul ensuite, meme au redemarrage de Windows :
rem  c'est Redemarrer-WMS.bat qui le remet en service.
rem =====================================================================
title WMS Structa - arret
cd /d "%~dp0"

rem Droits administrateur ? (fltmc, et non "net session" : celui-ci echoue
rem aussi quand le service Serveur est desactive, et la fenetre se
rem redemanderait alors l'elevation sans fin.)
rem "&&" et non "if not errorlevel 1" : un code de sortie negatif
rem (0x80070005, acces refuse) passerait ce test pour un succes.
fltmc >nul 2>&1 && goto :arreter
echo  Demande des droits administrateur...
rem Le chemin par une variable : une apostrophe dans le nom d'un dossier
rem cassait la commande PowerShell, et la fenetre se fermait sans un mot.
set "WMS_SOI=%~f0"
powershell -NoProfile -Command "Start-Process -FilePath $env:WMS_SOI -Verb RunAs"
exit /b 0

:arreter
".venv\Scripts\python.exe" outils\serveur_wms.py arreter
echo.
pause
