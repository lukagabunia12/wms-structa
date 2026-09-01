<#
    Repetition du passage sur PostgreSQL, DEPUIS VOTRE POSTE.

    Le but : eprouver l'application sur une vraie base SQL, avec vos vraies
    donnees, sans toucher au serveur ni a votre base SQLite. Vous pouvez revenir
    en arriere a tout moment avec :

        .venv\Scripts\python.exe outils\basculer_base.py sqlite

    PREALABLE, a faire une fois a la main :
      Installer PostgreSQL depuis https://www.postgresql.org/download/windows/
      - noter le mot de passe du compte 'postgres' demande a l'installation ;
      - cocher 'Command Line Tools' (c'est ce qui fournit psql et pg_dump).
    Le dossier bin est localise automatiquement : rien a ajouter au PATH.

    Puis, dans une console PowerShell depuis le dossier du projet :

        powershell -ExecutionPolicy Bypass -File deploiement\windows\Repeter-PostgreSQL.ps1
#>
param(
    [string]$Base = "wms_essai",
    [string]$Utilisateur = "wms",
    [string]$Hote = "127.0.0.1",
    [string]$Port = "5432"
)

$ErrorActionPreference = "Stop"
$Projet = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $Projet
$Py = "$Projet\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "Lancez d'abord Demarrer-WMS.bat une fois, pour creer l'environnement." }

# Une base d'ESSAI, distincte de celle du futur serveur : cette repetition doit
# pouvoir etre jetee et recommencee sans consequence.
Write-Host ""
Write-Host "  Repetition PostgreSQL en local - base d'essai '$Base'" -ForegroundColor Cyan
Write-Host ""

# L'installeur PostgreSQL pour Windows n'ajoute pas son dossier "bin" au PATH.
# Chercher psql nous-memes evite d'annoncer a tort qu'il n'est pas installe --
# ce que faisait la version precedente, sur un poste ou il l'etait parfaitement.
. "$PSScriptRoot\Trouver-PostgreSQL.ps1"
$BinPg = Initialiser-PostgreSQL
if (-not $BinPg) { Message-PostgreSQLIntrouvable; exit 1 }
Write-Host "     Outils PostgreSQL : $BinPg" -ForegroundColor Gray
Write-Host ""

# --- 1. Export DEPUIS SQLite, avant toute bascule ---------------------------
Write-Host "1/6  Export des donnees actuelles (lecture seule)..." -ForegroundColor Yellow
& $Py manage.py reprise_sql exporter --vers reprise
if ($LASTEXITCODE -ne 0) { throw "L'export a echoue : rien n'a ete modifie." }

# --- 2. Pilote --------------------------------------------------------------
Write-Host "2/6  Installation du pilote PostgreSQL..." -ForegroundColor Yellow
& $Py -m pip install -r requirements.txt --quiet

# --- 3. Role et base --------------------------------------------------------
Write-Host "3/6  Creation du role et de la base d'essai..." -ForegroundColor Yellow
$MotDePasse = Read-Host "     Mot de passe a donner au compte applicatif '$Utilisateur'"
$MotDePasseAdmin = Read-Host "     Mot de passe du compte 'postgres' (installation)" -AsSecureString
$env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($MotDePasseAdmin))

# Rejouable : on ne recree pas un role qui existe deja, on remet son mot de passe.
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
if ($LASTEXITCODE -ne 0) { throw "Creation du role impossible : mot de passe postgres incorrect ?" }

# Base repartie de zero a chaque repetition : c'est tout l'interet d'un essai.
& psql -h $Hote -p $Port -U postgres -q -c "DROP DATABASE IF EXISTS $Base;"
& psql -h $Hote -p $Port -U postgres -v ON_ERROR_STOP=1 -q `
    -c "CREATE DATABASE $Base WITH OWNER = $Utilisateur ENCODING = 'UTF8' TEMPLATE = template0;"
if ($LASTEXITCODE -ne 0) { throw "Creation de la base impossible." }
& psql -h $Hote -p $Port -U postgres -d $Base -v ON_ERROR_STOP=1 -q `
    -c "ALTER SCHEMA public OWNER TO $Utilisateur; GRANT ALL ON SCHEMA public TO $Utilisateur;"
# Un GRANT en echec faisait echouer migrate bien plus loin, en
# "permission denied for schema public" : on s'arrete ici, a la cause.
$droits = $LASTEXITCODE
Remove-Item Env:\PGPASSWORD
if ($droits -ne 0) { throw "Attribution des droits sur le schema public impossible." }
Write-Host "3/6  Base '$Base' prete." -ForegroundColor Green

# --- 4. Bascule -------------------------------------------------------------
Write-Host "4/6  Bascule de .env sur PostgreSQL..." -ForegroundColor Yellow
& $Py outils\basculer_base.py postgresql --base $Base --utilisateur $Utilisateur `
      --mot-de-passe $MotDePasse --hote $Hote --port $Port
if ($LASTEXITCODE -ne 0) { throw "La bascule a echoue." }

# --- 5. Schema et reprise ---------------------------------------------------
Write-Host "5/6  Creation du schema et reprise des donnees..." -ForegroundColor Yellow
& $Py manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw "Les migrations ont echoue." }
& $Py manage.py reprise_sql importer --depuis reprise
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  La reprise a ete refusee : rien n'a ete ecrit dans PostgreSQL." -ForegroundColor Red
    Write-Host "  Revenez a SQLite :  .venv\Scripts\python.exe outils\basculer_base.py sqlite" -ForegroundColor Red
    exit 1
}

# --- 6. Verdict -------------------------------------------------------------
Write-Host "6/6  Etat apres reprise :" -ForegroundColor Yellow
& $Py outils\basculer_base.py etat
& $Py outils\preparer_serveur.py

Write-Host ""
Write-Host "  Repetition terminee. Lancez maintenant Demarrer-WMS.bat :" -ForegroundColor Green
Write-Host "  l'application tourne desormais sur PostgreSQL, avec vos donnees." -ForegroundColor Green
Write-Host ""
Write-Host "  A eprouver : connexion, scan d'un emplacement, rangement d'une cabine," -ForegroundColor Cyan
Write-Host "  creation d'un rack, impression d'une bande, et le journal." -ForegroundColor Cyan
Write-Host ""
Write-Host "  Pour revenir a SQLite :" -ForegroundColor Cyan
Write-Host "     .venv\Scripts\python.exe outils\basculer_base.py sqlite" -ForegroundColor Cyan
Write-Host ""
