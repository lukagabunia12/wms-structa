@echo off
rem =====================================================================
rem  INSTALLE LE WMS STRUCTA SUR CE POSTE.
rem
rem  A lancer apres avoir copie le dossier du projet sur le poste qui
rem  servira de serveur. Se relance sans risque (mise a jour, taches) :
rem  une base en service n'est jamais touchee.
rem
rem  Sur le serveur, avec le nom que taperont les telephones :
rem    Installer-WMS.bat -Noms wms.structa.fr
rem  Seulement reposer les taches planifiees et redemarrer :
rem    Installer-WMS.bat -Taches
rem  Toutes les options : docs\guide-serveur.md, section 4.
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

rem Droits administrateur ? (fltmc, et non "net session" : celui-ci echoue
rem aussi quand le service Serveur est desactive, et la fenetre se
rem redemanderait alors l'elevation sans fin.)
rem "&&" et non "if not errorlevel 1" : un code de sortie negatif
rem (0x80070005, acces refuse) passerait ce test pour un succes.
fltmc >nul 2>&1 && goto :installer

echo.
echo  Demande des droits administrateur...
echo  Repondez Oui a la fenetre qui s'ouvre.
echo.
rem Les options doivent traverser l'elevation, guillemets compris :
rem  Installer-WMS.bat -Python "C:\Program Files\Python313\python.exe"
rem Glissees telles quelles dans la commande PowerShell, un guillemet la
rem coupait, et une parenthese -- "Program Files (x86)" -- fermait le bloc
rem if. Elles passent donc par des variables, lues par PowerShell. Et
rem l'elevation lance cmd.exe lui-meme, avec  /c ""fichier" options"  :
rem confiee au verbe "Executer en tant qu'administrateur" des .bat, une
rem ligne a quatre guillemets perdait les siens, et la fenetre se fermait.
set "WMS_SOI=%~f0"
set "WMS_OPTIONS=%*"
if not defined WMS_OPTIONS goto :elever
powershell -NoProfile -Command "Start-Process -FilePath $env:ComSpec -ArgumentList ('/c ' + [char]34 + [char]34 + $env:WMS_SOI + [char]34 + ' ' + $env:WMS_OPTIONS + [char]34) -Verb RunAs"
exit /b 0

:elever
powershell -NoProfile -Command "Start-Process -FilePath $env:WMS_SOI -Verb RunAs"
exit /b 0

:installer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploiement\windows\Installer-WMS.ps1" %*
echo.
pause
