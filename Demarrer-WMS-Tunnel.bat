@echo off
rem =====================================================================
rem  DEMARRE LE WMS ET LE PUBLIE PAR UN TUNNEL CLOUDFLARE.
rem
rem  SOLUTION D'ATTENTE, tant que l'acces par le reseau interne n'est pas
rem  ouvert (port 8443 en entree). A remplacer par Demarrer-WMS.bat, qui
rem  sert le WMS en HTTPS sur le reseau interne, des que le port est ouvert.
rem
rem  Ce qu'il faut savoir :
rem   - l'adresse produite est PUBLIQUE. Toute personne qui la connait
rem     atteint la page de connexion : seul le mot de passe des comptes
rem     protege alors les donnees de l'entrepot ;
rem   - elle CHANGE a chaque lancement ;
rem   - elle passe par un service tiers, hors du reseau de STRUCTA.
rem
rem  En echange, aucune permission a demander : cloudflared ouvre une
rem  connexion SORTANTE, comme un navigateur. Et le certificat HTTPS est
rem  reconnu par tous les telephones : plus d'autorite a installer sur
rem  chaque appareil, la camera fonctionne aussitot.
rem
rem  Une page avec le QR code de l'adresse s'ouvre : les caristes scannent
rem  l'ecran au lieu de recopier une adresse aleatoire.
rem =====================================================================
title WMS Structa - acces par tunnel (temporaire)
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  Environnement Python absent. Lancez d'abord Demarrer-WMS.bat une fois.
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" outils\demarrer_tunnel.py %*
echo.
pause
