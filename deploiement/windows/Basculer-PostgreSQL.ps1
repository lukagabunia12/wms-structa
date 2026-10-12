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

# Deja bascule ? Ce script commence par REVENIR sur SQLite pour exporter : sur
# un WMS qui tourne deja sur PostgreSQL, il exportait la vieille base SQLite,
# s'arretait sur "base non vide"... et laissait .env sur SQLite. Le WMS
# repartait alors sur des donnees d'il y a des semaines, sans rien dire.
& $Py outils\basculer_base.py en-service
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "  Le WMS tourne deja sur une base PostgreSQL en service : rien a basculer." -ForegroundColor Green
    Write-Host "  Rien n'a ete modifie. Quelle base est active : Quelle-Base.bat" -ForegroundColor Gray
    Write-Host ""
    exit 0
}

# Le WMS doit etre arrete : l'export est une photo de la base a un instant
# donne. Ce qui serait saisi ensuite resterait dans SQLite, perdu pour
# PostgreSQL sans que personne le voie.
& $Py outils\basculer_base.py wms-arrete
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  Arretez d'abord le WMS : fermez sa fenetre (sur le serveur :" -ForegroundColor Yellow
    Write-Host "  Arreter-WMS.bat), puis relancez. Rien n'a ete modifie." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

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
. "$PSScriptRoot\Base-PostgreSQL.ps1"
for ($essai = 1; $essai -le 3; $essai++) {
    # Saisie masquee : le mot de passe n'apparait ni a l'ecran, ni dans
    # l'historique de la console.
    $saisie = Read-Host "     Mot de passe a donner au compte applicatif '$Utilisateur'" -AsSecureString
    $MotDePasse = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($saisie))
    if ([string]::IsNullOrWhiteSpace($MotDePasse)) { throw "Mot de passe vide : abandon." }
    $refus = Tester-MotDePasseEnv $MotDePasse
    if (-not $refus) { break }
    Write-Host "     Ce mot de passe ne convient pas : $refus. Un autre ?" -ForegroundColor Yellow
    $MotDePasse = $null
}
if (-not $MotDePasse) { throw "Aucun mot de passe utilisable : abandon." }
$saisie = Read-Host "     Mot de passe du compte 'postgres' (installation)" -AsSecureString
$MotDePasseAdmin = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($saisie))

# La fonction commune a l'installateur : elle examine la base AVANT de toucher
# au role, et refuse d'ecraser une base qui porte des tables.
Preparer-BasePostgreSQL -Base $Base -Utilisateur $Utilisateur -MotDePasse $MotDePasse `
    -MotDePasseAdmin $MotDePasseAdmin -Hote $Hote -Port $Port
$MotDePasseAdmin = $null
Write-Host "4/7  Base '$Base' prete." -ForegroundColor Green

# --- 5. Bascule -------------------------------------------------------------
Write-Host "5/7  Bascule de .env sur PostgreSQL..." -ForegroundColor Yellow
# Par variable d'environnement, et non en argument : les arguments d'un
# processus sont lisibles par tout compte du poste.
$env:WMS_DB_PASSWORD = $MotDePasse
try {
    & $Py outils\basculer_base.py postgresql --base $Base --utilisateur $Utilisateur `
          --hote $Hote --port $Port
    if ($LASTEXITCODE -ne 0) { throw "La bascule de .env a echoue." }
}
finally {
    Remove-Item Env:\WMS_DB_PASSWORD -ErrorAction SilentlyContinue
    $MotDePasse = $null
}

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
Write-Host "   2. Sauvegarder : Sauvegarder-WMS.bat tout de suite, puis les sauvegardes" -ForegroundColor Cyan
Write-Host "      planifiees (docs\guide-serveur.md, section Sauvegardes)." -ForegroundColor Cyan
Write-Host "   3. Garder db.sqlite3 quelques semaines : c'est votre filet." -ForegroundColor Cyan
Write-Host ""
Write-Host "  Quelle base est active, a tout moment : Quelle-Base.bat" -ForegroundColor Gray
Write-Host ""
