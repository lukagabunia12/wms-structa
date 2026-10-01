@echo off
rem =====================================================================
rem  DEMARRE LE WMS STRUCTA. Un seul lanceur, toujours en HTTPS.
rem
rem  Dans l'ordre :
rem    1. au premier lancement : l'environnement Python et les dependances ;
rem    2. le fichier .env : cle secrete, mode exploitation ;
rem    3. la base de donnees : migrations ;
rem    4. les bibliotheques du scanner, une seule fois ;
rem    5. le port 8443 dans le pare-feu, une seule fois ;
rem    6. le certificat HTTPS : cree s'il manque, refait si l'adresse du PC
rem       a change ou s'il arrive en fin de validite ;
rem    7. le serveur : https://<adresse du PC>:8443, et le navigateur s'ouvre.
rem
rem  Pourquoi toujours HTTPS : hors HTTPS, les telephones refusent l'acces a
rem  la camera, et le scan des QR codes ne marche pas. L'ancien
rem  Demarrer-WMS-HTTPS.bat est fusionne ici.
rem
rem  La premiere fois : clic droit > Executer en tant qu'administrateur.
rem  C'est ce qui ouvre le port 8443 et inscrit l'autorite dans Windows.
rem  Ensuite, un double-clic suffit.
rem
rem  Premiere fois sur un telephone : installer l'autorite
rem  certificats\ac-structa.crt, voir docs\guide-https.md.
rem
rem  Pour arreter le WMS : fermer cette fenetre.
rem =====================================================================
title WMS Structa - serveur (ne pas fermer)
cd /d "%~dp0"

rem --- Environnement Python ------------------------------------------------
if exist ".venv\Scripts\python.exe" goto :dependances
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo  Python n'est pas detecte sur ce poste.
    echo  Installe-le depuis https://www.python.org puis coche "Add Python to PATH".
    echo.
    pause
    exit /b 1
)
echo.
echo  Premiere installation en cours, patiente une minute...
echo.
python -m venv .venv
if errorlevel 1 (
    echo.
    echo  L'environnement Python n'a pas pu etre cree. Rien n'est demarre.
    pause
    exit /b 1
)

rem --- Dependances -----------------------------------------------------------
rem Verifiees a chaque lancement, et pas seulement le premier : une
rem installation interrompue laissait un .venv sans Django, et le lanceur
rem echouait plus loin avec un message qui ne disait pas pourquoi.
:dependances
".venv\Scripts\python.exe" -c "import django, rest_framework, corsheaders, waitress, cryptography, dotenv" >nul 2>&1
if not errorlevel 1 goto :configuration
echo  Installation des dependances...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet >nul 2>&1
rem Hors ligne si le dossier paquets\ est la : le poste serveur n'a pas
rem toujours internet. S'il ne convient pas a cette version de Python, on
rem repasse par internet.
set HORS_LIGNE=
if exist "paquets\*.whl" set HORS_LIGNE=--no-index --find-links paquets
".venv\Scripts\python.exe" -m pip install %HORS_LIGNE% -r requirements.txt
if not errorlevel 1 goto :configuration
if not defined HORS_LIGNE goto :dependances_ko
echo  Paquets hors ligne non adaptes a ce poste : installation depuis internet...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if not errorlevel 1 goto :configuration
:dependances_ko
echo.
echo  Les dependances n'ont pas pu s'installer. Ce poste a-t-il acces a internet ?
echo  Rien n'est demarre.
pause
exit /b 1

:configuration
rem --- Cle secrete -----------------------------------------------------------
rem Elle signe les sessions et les jetons. Laissee a sa valeur d'exemple, publiee
rem dans le depot, n'importe qui peut forger une session d'administrateur.
rem On la genere a la premiere installation ET on la repare si elle est restee
rem a l'exemple (cas d'un .env copie a la main avant l'existence de ce script).
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

rem --- Pare-feu : le port 8443, une seule fois -------------------------------
rem Profils Domaine et Prive seulement : jamais sur un reseau public. Sans
rem droits administrateur, on continue : le serveur demarre, seul le pare-feu
rem bloquera les autres postes.
netsh advfirewall firewall show rule name="WMS Structa HTTPS" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="WMS Structa HTTPS" dir=in action=allow ^
        protocol=TCP localport=8443 profile=domain,private >nul 2>&1
    if errorlevel 1 (
        echo  Note : port 8443 non ouvert dans le pare-feu, droits administrateur requis.
        echo  Relancez ce fichier par clic droit, Executer en tant qu'administrateur.
    )
)

rem --- Le serveur, en HTTPS --------------------------------------------------
rem Certificat cree ou refait au besoin, serveur d'application sur la boucle
rem locale, terminaison TLS sur le port 8443, adresses a donner aux
rem telephones, navigateur ouvert sur le WMS. Si le WMS tourne deja, il le
rem dit et ouvre simplement le navigateur.
".venv\Scripts\python.exe" outils\demarrer_https.py %*
echo.
pause
exit /b 0
