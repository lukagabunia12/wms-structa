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
rem  dans le dossier reprise\. LE WMS DOIT ETRE ARRETE sur ce poste (fermer
rem  sa fenetre) : l'export est la derniere ecriture, ce qui serait saisi
rem  ensuite ne partirait pas.
rem
rem  Options :
rem    Preparer-Copie.bat --avec-autorite
rem      emporte aussi l'autorite de certification : les telephones qui
rem      l'ont deja n'auront rien a reinstaller. La copie porte alors une
rem      cle sensible : cle USB chiffree, puis effacee apres installation.
rem    Preparer-Copie.bat --sans-donnees
rem      copie du code seul, sans aucune donnee : pour une MISE A JOUR du
rem      serveur (docs\guide-serveur.md), ou un serveur sur base vierge.
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
