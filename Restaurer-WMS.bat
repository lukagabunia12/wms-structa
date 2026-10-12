@echo off
rem =====================================================================
rem  RESTAURE LA BASE DU WMS depuis une sauvegarde.
rem
rem  Dans l'ordre :
rem    1. Arreter-WMS.bat      (la restauration refuse de tourner sinon)
rem    2. Restaurer-WMS.bat    (ce fichier : choisir la sauvegarde, confirmer)
rem    3. Redemarrer-WMS.bat
rem
rem  La base actuelle est sauvegardee d'abord (le "filet") : une
rem  restauration choisie par erreur se defait de la meme facon, en
rem  restaurant le filet. Le rechargement se fait en une seule
rem  transaction : un incident en cours de route ne change rien.
rem  Detail : docs\guide-serveur.md, "Restaurer".
rem =====================================================================
title WMS Structa - restauration
cd /d "%~dp0"

rem Droits administrateur ? (fltmc, et non "net session" : celui-ci echoue
rem aussi quand le service Serveur est desactive, et la fenetre se
rem redemanderait alors l'elevation sans fin.)
rem "&&" et non "if not errorlevel 1" : un code de sortie negatif
rem (0x80070005, acces refuse) passerait ce test pour un succes.
fltmc >nul 2>&1 && goto :restaurer
echo  Demande des droits administrateur...
rem Le chemin par une variable : une apostrophe dans le nom d'un dossier
rem cassait la commande PowerShell, et la fenetre se fermait sans un mot.
set "WMS_SOI=%~f0"
powershell -NoProfile -Command "Start-Process -FilePath $env:WMS_SOI -Verb RunAs"
exit /b 0

:restaurer
set "DJANGO_LOG_CONSOLE=False"
".venv\Scripts\python.exe" manage.py restaurer
echo.
set "JEU="
set /p "JEU=Sauvegarde a restaurer (premiere colonne, ou chemin du fichier ; Entree pour abandonner) : "
if not defined JEU goto :abandon
rem Un chemin colle par "Copier en tant que chemin d'acces" arrive entre
rem guillemets : ils sont retires, le chemin est remis entre guillemets plus bas.
set "JEU=%JEU:"=%"
if not defined JEU goto :abandon
".venv\Scripts\python.exe" manage.py restaurer "%JEU%"
echo.
pause
exit /b 0

:abandon
echo  Abandon : rien n'a ete modifie.
echo.
pause
