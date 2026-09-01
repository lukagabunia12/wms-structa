@echo off
title WMS Structa
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo  Python n'est pas detecte sur ce poste.
    echo  Installe-le depuis https://www.python.org puis coche "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  Premiere installation en cours, patiente une minute...
    echo.
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

rem --- Cle secrete -----------------------------------------------------------
rem Elle signe les sessions et les jetons. Laissee a sa valeur d'exemple, publiee
rem dans le depot, n'importe qui peut forger une session d'administrateur.
rem On la genere a la premiere installation ET on la repare si elle est restee
rem a l'exemple (cas d'un .env copie a la main avant l'existence de ce script).
rem L'ancienne version generait la cle en batch : dans un bloc `if (...)`, %CLE%
rem est remplace AVANT que la boucle ne l'affecte, la cle ecrite etait donc vide.
rem Un petit script Python fait le travail, et repare aussi DJANGO_DEBUG.
".venv\Scripts\python.exe" outils\preparer_env.py

rem --- Base de donnees -------------------------------------------------------
rem `makemigrations` n'est PAS lance ici : sur un poste d'exploitation, il
rem fabriquerait a la volee une migration absente du depot, differente de celle
rem des autres postes. Les migrations se preparent cote developpement et se
rem committent ; ici on se contente de les appliquer.
echo.
echo  Preparation de la base de donnees...
".venv\Scripts\python.exe" manage.py migrate
if errorlevel 1 (
    echo.
    echo  La base n'a pas pu etre preparee. Rien n'est demarre.
    pause
    exit /b 1
)

rem --- Bibliotheques du scanner ----------------------------------------------
rem Telechargees une seule fois : ensuite, scan camera et etiquettes QR
rem fonctionnent meme sans internet.
if not exist "wms\static\app\vendor\qrcode.min.js" (
    echo  Telechargement des bibliotheques du scanner...
    ".venv\Scripts\python.exe" manage.py telecharger_libs
)

set IP=
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do set IP=%%a
if defined IP set IP=%IP:~1%

echo.
echo  Demarrage du serveur WMS...
rem Waitress est un vrai serveur d'application (multi-thread, stable sur Windows).
rem `runserver` est l'outil de developpement de Django : conserve en secours pour
rem que le poste demarre meme si waitress n'est pas installe.
if exist ".venv\Scripts\waitress-serve.exe" (
    start "WMS Structa - serveur (ne pas fermer)" ".venv\Scripts\waitress-serve.exe" --listen=0.0.0.0:8000 --threads=8 config.wsgi:application
) else (
    start "WMS Structa - serveur (ne pas fermer)" ".venv\Scripts\python.exe" manage.py runserver 0.0.0.0:8000
)
timeout /t 4 >nul
start "" "http://127.0.0.1:8000/"

echo.
echo  ================================================================
echo   Sur CE PC          : http://127.0.0.1:8000/
echo   Sur ton TELEPHONE  : http://%IP%:8000/   (meme Wi-Fi que le PC)
echo  ================================================================
echo.
echo  Si Windows demande d'autoriser Python sur le reseau, clique "Autoriser".
echo  Pour arreter le WMS, ferme la fenetre "serveur".
echo.
pause
exit /b 0
