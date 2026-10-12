@echo off
rem =====================================================================
rem  (RE)MET LE WMS EN SERVICE SUR CE SERVEUR, par la tache planifiee
rem  "WMS Structa\Service" -- apres Arreter-WMS.bat ou une mise a jour.
rem
rem  Les migrations de la base sont appliquees au passage. S'il tourne
rem  deja, rien ne change : pour le relancer, Arreter-WMS.bat d'abord.
rem =====================================================================
title WMS Structa - demarrage
cd /d "%~dp0"

rem Droits administrateur ? (fltmc, et non "net session" : celui-ci echoue
rem aussi quand le service Serveur est desactive, et la fenetre se
rem redemanderait alors l'elevation sans fin.)
rem "&&" et non "if not errorlevel 1" : un code de sortie negatif
rem (0x80070005, acces refuse) passerait ce test pour un succes.
fltmc >nul 2>&1 && goto :demarrer
echo  Demande des droits administrateur...
rem Le chemin par une variable : une apostrophe dans le nom d'un dossier
rem cassait la commande PowerShell, et la fenetre se fermait sans un mot.
set "WMS_SOI=%~f0"
powershell -NoProfile -Command "Start-Process -FilePath $env:WMS_SOI -Verb RunAs"
exit /b 0

:demarrer
".venv\Scripts\python.exe" outils\serveur_wms.py demarrer
echo.
pause
