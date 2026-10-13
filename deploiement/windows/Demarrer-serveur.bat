@echo off
rem =====================================================================
rem  WMS Structa - demarrage en service (serveur)
rem
rem  Lance par la tache planifiee "WMS Structa\Service" : au demarrage de
rem  Windows, sans session ouverte, puis toutes les deux minutes. S'il
rem  tourne deja, rien ne se passe ; s'il est tombe, il repart.
rem
rem  Ne pas double-cliquer en exploitation : Redemarrer-WMS.bat, a la
rem  racine, passe par la tache. Arreter-WMS.bat l'arrete pour de bon.
rem
rem  Toute la sortie part dans logs\service.log (au-dela de 5 Mo, il est
rem  renomme en service.log.1 ; trois anciens sont gardes).
rem =====================================================================
setlocal
cd /d "%~dp0..\.."
if not exist "logs" mkdir "logs"

if not exist ".venv\Scripts\python.exe" (
    echo %date% %time% Environnement absent : lancez d'abord Installer-WMS.bat.>> "logs\service.log"
    exit /b 1
)

rem Deja en marche (lance par cette tache, ou a la main) : rien a faire, et
rem rien a ecrire -- la verification revient toutes les deux minutes.
".venv\Scripts\python.exe" -c "import socket,sys; sys.path.insert(0,'outils'); import certificat_https as C; s=socket.socket(); s.settimeout(2); sys.exit(0 if s.connect_ex(('127.0.0.1',C.port_https())) == 0 else 1)"
if not errorlevel 1 exit /b 0

rem --- Rotation du journal de service --------------------------------------
if exist "logs\service.log" for %%F in ("logs\service.log") do if %%~zF GTR 5000000 (
    if exist "logs\service.log.3" del /q "logs\service.log.3"
    if exist "logs\service.log.2" move /y "logs\service.log.2" "logs\service.log.3" >nul
    if exist "logs\service.log.1" move /y "logs\service.log.1" "logs\service.log.2" >nul
    move /y "logs\service.log" "logs\service.log.1" >nul
)

call :demarrer >> "logs\service.log" 2>&1
exit /b %errorlevel%

:demarrer
echo.
echo ===== %date% %time% : demarrage du WMS par la tache planifiee =====
rem Accents lisibles dans le journal, et les avertissements de Django dans
rem wms.log seulement (pas en double ici).
set "PYTHONIOENCODING=utf-8"
set "DJANGO_LOG_CONSOLE=False"

rem Migrations : le schema doit suivre le code avant que le premier poste ne
rem se connecte. Au demarrage de Windows, PostgreSQL peut ne pas etre encore
rem pret : l'echec n'est pas grave, la tache reessaie dans deux minutes.
".venv\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 (
    echo  Migrations en echec ^(base pas encore prete ?^) : nouvel essai dans deux minutes.
    exit /b 1
)

rem Controle de pre-vol : cle secrete, DEBUG, base, compte administrateur.
".venv\Scripts\python.exe" outils\preparer_serveur.py
if errorlevel 1 (
    echo  Configuration incomplete : le service ne demarre pas. Voir ci-dessus.
    exit /b 1
)

rem Le WMS en HTTPS, comme Demarrer-WMS.bat : waitress sur la boucle locale,
rem seul le port HTTPS (WMS_PORT_HTTPS) ouvert au reseau. Si le serveur d'application tombe,
rem le lanceur s'arrete avec lui ; la tache le relance au passage suivant.
".venv\Scripts\python.exe" outils\demarrer_https.py --service
exit /b %errorlevel%
