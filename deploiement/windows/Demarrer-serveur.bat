@echo off
rem =====================================================================
rem  WMS Structa - demarrage du service (serveur)
rem
rem  Lance par la tache planifiee "WMS Structa" au demarrage de Windows.
rem  Ne pas double-cliquer en exploitation : c'est la tache qui doit le
rem  lancer, pour que le WMS reparte tout seul apres une coupure.
rem =====================================================================
cd /d "%~dp0..\.."

if not exist ".venv\Scripts\python.exe" (
    echo  Environnement absent. Lancez d'abord Installer-Serveur.ps1
    exit /b 1
)

rem Migrations : le schema doit suivre le code avant que le premier poste
rem ne se connecte. Si elles echouent, on ne demarre pas du tout plutot
rem que de servir une application qui tombera a la premiere ecriture.
".venv\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 (
    echo  Migrations en echec : le service ne demarre pas.
    exit /b 1
)

rem Controle de pre-vol : cle secrete, DEBUG, base, compte administrateur.
".venv\Scripts\python.exe" outils\preparer_serveur.py
if errorlevel 1 (
    echo  Configuration incomplete : le service ne demarre pas.
    exit /b 1
)

rem Le WMS en HTTPS, exactement comme Demarrer-WMS.bat : waitress (8 fils,
rem large pour une vingtaine de postes et de telephones) sur la boucle
rem locale, et seul le port 8443, chiffre, ouvert au reseau. Il servait
rem auparavant le port 8000 en clair : plus de camera sur les telephones, et
rem les mots de passe en clair sur le Wi-Fi.
rem
rem Sans navigateur : c'est la tache planifiee qui le lance, sans ecran.
rem Si le serveur d'application tombe, le lanceur s'arrete avec lui (code 1) :
rem la tache planifiee peut alors relancer.
".venv\Scripts\python.exe" outils\demarrer_https.py --sans-navigateur
