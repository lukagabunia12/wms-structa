@echo off
rem =====================================================================
rem  DEMARRE LE WMS EN HTTPS SUR LE RESEAU INTERNE.
rem
rem  Pourquoi HTTPS : les navigateurs mobiles refusent l'acces a la camera
rem  hors HTTPS. Sans certificat, le scan des QR codes est indisponible sur
rem  les telephones.
rem
rem  Au premier lancement, un certificat est fabrique automatiquement.
rem  Installez ensuite l'autorite certificats\ac-structa.crt sur chaque
rem  telephone (une seule fois) : voir docs\guide-https.md.
rem =====================================================================
title WMS Structa - HTTPS reseau interne
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  Lancez d'abord Demarrer-WMS.bat une fois, pour creer l'environnement.
    echo.
    pause
    exit /b 1
)

rem Le module de fabrication des certificats. Present des l'installation ;
rem ce rattrapage ne sert qu'a un environnement monte a la main.
".venv\Scripts\python.exe" -c "import cryptography" 2>nul
if errorlevel 1 (
    echo  Installation du module de certificats...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo.
        echo  Installation impossible - ce poste a-t-il acces a internet ?
        pause
        exit /b 1
    )
)

rem Ouverture du port 8443, sur les profils Domaine et Prive seulement :
rem jamais sur un reseau public. Sans droits administrateur, on continue :
rem le serveur demarre, seul le pare-feu bloquera les autres postes.
netsh advfirewall firewall show rule name="WMS Structa HTTPS" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="WMS Structa HTTPS" dir=in action=allow ^
        protocol=TCP localport=8443 profile=domain,private >nul 2>&1
    if errorlevel 1 (
        echo  Note : port non ouvert dans le pare-feu ^(droits administrateur requis^).
        echo  Relancez ce fichier par clic droit ^> Executer en tant qu'administrateur.
    )
)

".venv\Scripts\python.exe" outils\demarrer_https.py
echo.
pause
