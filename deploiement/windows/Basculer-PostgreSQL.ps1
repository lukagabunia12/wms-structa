<#
    BASCULE DEFINITIVE DU WMS SUR POSTGRESQL.

    A la difference de Repeter-PostgreSQL.ps1, qui monte une base d'ESSAI
    jetable et la recree a chaque passage, ce script prepare la base
    d'EXPLOITATION et ne detruit jamais rien : si la base existe deja et
    contient des tables, il s'arrete au lieu d'ecraser.

    Deroulement :
      1. retour temporaire sur SQLite, pour exporter depuis la source d'origine
      2. export des donnees (lecture seule)
      3. pilote PostgreSQL
      4. role applicatif et base d'exploitation
      5. bascule de .env
      6. schema (migrate) et reprise des donnees, comptages verifies
      7. controle d'exploitation : ecriture reelle, puis annulation

    Retour arriere a tout moment : Revenir-SQLite.bat
    (le fichier db.sqlite3 n'est jamais modifie par ce script)

    powershell -ExecutionPolicy Bypass -File deploiement\windows\Basculer-PostgreSQL.ps1
#>
param(
    [string]$Base = "wms",
    [string]$Utilisateur = "wms",
    [string]$Hote = "127.0.0.1",
    [string]$Port = "5432"
)

$ErrorActionPreference = "Stop"
$Projet = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $Projet
$Py = "$Projet\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "Lancez d'abord Demarrer-WMS.bat une fois, pour creer l'environnement." }

Write-Host ""
Write-Host "  Bascule du WMS sur PostgreSQL - base d'exploitation '$Base'" -ForegroundColor Cyan
Write-Host ""

. "$PSScriptRoot\Trouver-PostgreSQL.ps1"
$BinPg = Initialiser-PostgreSQL
if (-not $BinPg) { Message-PostgreSQLIntrouvable; exit 1 }
Write-Host "     Outils PostgreSQL : $BinPg" -ForegroundColor Gray

# Le service repond-il ? Sans ce controle, le script demandait DEUX mots de
# passe avant de tomber en "Creation du role impossible : mot de passe postgres
# incorrect ?" -- alors que la vraie cause etait un service arrete. On echoue
# ici, avant de faire saisir quoi que ce soit, et avec la bonne raison.
& pg_isready -h $Hote -p $Port -q
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  Le service PostgreSQL ne repond pas sur ${Hote}:${Port}." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Verifiez qu'il est demarre : touche Windows, tapez services.msc," -ForegroundColor Yellow
    Write-Host "  cherchez 'postgresql-x64-...' et demarrez-le." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}
Write-Host "     Service PostgreSQL : joignable sur ${Hote}:${Port}" -ForegroundColor Gray
Write-Host ""

# --- 1. Revenir sur SQLite pour exporter depuis la source d'origine ---------
# Sans cette etape, un .env deja bascule (apres une repetition) ferait exporter
# la base d'essai au lieu de db.sqlite3 : on reprendrait une copie d'une copie.
Write-Host "1/7  Retour temporaire sur SQLite (source de la reprise)..." -ForegroundColor Yellow
& $Py outils\basculer_base.py sqlite
if ($LASTEXITCODE -ne 0) { throw "Impossible de revenir sur SQLite." }

# --- 2. Export --------------------------------------------------------------
Write-Host "2/7  Export des donnees (lecture seule, db.sqlite3 non modifie)..." -ForegroundColor Yellow
if (Test-Path "reprise") { Remove-Item "reprise" -Recurse -Force }
& $Py manage.py reprise_sql exporter --vers reprise
if ($LASTEXITCODE -ne 0) { throw "L'export a echoue : rien n'a ete modifie." }

# --- 3. Pilote --------------------------------------------------------------
Write-Host "3/7  Pilote PostgreSQL..." -ForegroundColor Yellow
& $Py -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "Installation du pilote PostgreSQL impossible." }

# --- 4. Role et base d'exploitation -----------------------------------------
Write-Host "4/7  Role applicatif et base d'exploitation..." -ForegroundColor Yellow
$MotDePasse = Read-Host "     Mot de passe a donner au compte applicatif '$Utilisateur'"
if ([string]::IsNullOrWhiteSpace($MotDePasse)) { throw "Mot de passe vide : abandon." }
$MotDePasseAdmin = Read-Host "     Mot de passe du compte 'postgres' (installation)" -AsSecureString
$env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($MotDePasseAdmin))

# Rejouable : on ne recree pas un role existant, on remet son mot de passe.
$sql = @"
DO `$`$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$Utilisateur') THEN
    CREATE ROLE $Utilisateur WITH LOGIN PASSWORD '$MotDePasse';
  ELSE
    ALTER ROLE $Utilisateur WITH LOGIN PASSWORD '$MotDePasse';
  END IF;
END `$`$;
"@
$sql | & psql -h $Hote -p $Port -U postgres -v ON_ERROR_STOP=1 -q
if ($LASTEXITCODE -ne 0) { Remove-Item Env:\PGPASSWORD; throw "Creation du role impossible : mot de passe postgres incorrect ?" }

# Aucun DROP DATABASE ici. Une base d'exploitation ne se recree pas a l'aveugle :
# si elle porte deja des tables, c'est a un humain de decider ce qu'on en fait.
# Les guillemets "$( )" autour du resultat ne sont pas cosmetiques : quand la
# base n'existe pas, psql ne renvoie AUCUNE ligne et PowerShell recupere $null.
# Appeler .Trim() dessus leve "You cannot call a method on a null-valued
# expression", et sous $ErrorActionPreference = 'Stop' cela tuait le script --
# au premier lancement, c'est-a-dire exactement quand la base n'existe pas.
$existe = "$(& psql -h $Hote -p $Port -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$Base'")".Trim()
if ($existe -eq "1") {
    $tables = "$(& psql -h $Hote -p $Port -U postgres -d $Base -tAc `
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")".Trim()
    if ([string]::IsNullOrWhiteSpace($tables)) { $tables = "0" }
    if ([int]$tables -gt 0) {
        Remove-Item Env:\PGPASSWORD
        Write-Host ""
        Write-Host "  La base '$Base' existe deja et contient $tables table(s)." -ForegroundColor Red
        Write-Host "  Ce script n'ecrase jamais une base d'exploitation." -ForegroundColor Red
        Write-Host ""
        Write-Host "  Si ces donnees sont a jeter, supprimez la base a la main :" -ForegroundColor Yellow
        Write-Host "     psql -U postgres -c ""DROP DATABASE $Base;""" -ForegroundColor Yellow
        Write-Host "  Sinon, relancez avec un autre nom :" -ForegroundColor Yellow
        Write-Host "     ...\Basculer-PostgreSQL.ps1 -Base wms2" -ForegroundColor Yellow
        Write-Host ""
        exit 1
    }
    Write-Host "     Base '$Base' deja presente et vide : reutilisee." -ForegroundColor Gray
} else {
    # Pas de LC_COLLATE force : 'fr_FR.UTF-8' n'existe pas sous Windows.
    & psql -h $Hote -p $Port -U postgres -v ON_ERROR_STOP=1 -q `
        -c "CREATE DATABASE $Base WITH OWNER = $Utilisateur ENCODING = 'UTF8' TEMPLATE = template0;"
    if ($LASTEXITCODE -ne 0) { Remove-Item Env:\PGPASSWORD; throw "Creation de la base impossible." }
}
& psql -h $Hote -p $Port -U postgres -d $Base -v ON_ERROR_STOP=1 -q `
    -c "ALTER SCHEMA public OWNER TO $Utilisateur; GRANT ALL ON SCHEMA public TO $Utilisateur; REVOKE ALL ON DATABASE $Base FROM PUBLIC;"
# Sans ce controle, un GRANT en echec passait inapercu : le script annoncait
# "Base prete" et enchainait sur migrate, qui tombait beaucoup plus loin en
# "permission denied for schema public" -- une erreur sans rapport apparent
# avec sa cause.
$droits = $LASTEXITCODE
Remove-Item Env:\PGPASSWORD
if ($droits -ne 0) { throw "Attribution des droits sur le schema public impossible." }
Write-Host "4/7  Base '$Base' prete." -ForegroundColor Green

# --- 5. Bascule -------------------------------------------------------------
Write-Host "5/7  Bascule de .env sur PostgreSQL..." -ForegroundColor Yellow
& $Py outils\basculer_base.py postgresql --base $Base --utilisateur $Utilisateur `
      --mot-de-passe $MotDePasse --hote $Hote --port $Port
if ($LASTEXITCODE -ne 0) { throw "La bascule de .env a echoue." }

# --- 6. Schema et reprise ---------------------------------------------------
Write-Host "6/7  Schema et reprise des donnees..." -ForegroundColor Yellow
& $Py manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw "Les migrations ont echoue." }
& $Py manage.py reprise_sql importer --depuis reprise
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  La reprise a ete refusee : rien n'a ete ecrit dans PostgreSQL." -ForegroundColor Red
    Write-Host "  Revenez a SQLite :  Revenir-SQLite.bat" -ForegroundColor Red
    exit 1
}

# --- 7. Controle d'exploitation ---------------------------------------------
Write-Host "7/7  Controle d'exploitation..." -ForegroundColor Yellow
& $Py outils\verifier_bascule.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "  La base repond mais n'est pas exploitable. Revenez a SQLite :" -ForegroundColor Red
    Write-Host "     Revenir-SQLite.bat" -ForegroundColor Red
    exit 1
}
& $Py outils\preparer_serveur.py

Write-Host ""
Write-Host "  BASCULE TERMINEE. Le WMS tourne desormais sur PostgreSQL." -ForegroundColor Green
Write-Host ""
Write-Host "  A faire maintenant :" -ForegroundColor Cyan
Write-Host "   1. Demarrer-WMS.bat, puis eprouver : connexion, creation d'un rack," -ForegroundColor Cyan
Write-Host "      scan d'un emplacement, impression d'une bande, journal." -ForegroundColor Cyan
Write-Host "   2. Planifier la sauvegarde : deploiement\windows\Sauvegarder.ps1" -ForegroundColor Cyan
Write-Host "      (elle bascule seule sur pg_dump, elle lit .env)" -ForegroundColor Cyan
Write-Host "   3. Garder db.sqlite3 quelques semaines : c'est votre filet." -ForegroundColor Cyan
Write-Host ""
Write-Host "  Quelle base est active, a tout moment : Quelle-Base.bat" -ForegroundColor Gray
Write-Host ""
