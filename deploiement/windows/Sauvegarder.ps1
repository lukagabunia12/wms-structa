<#
    Sauvegarde de la base WMS Structa, avec rotation.

    A planifier une fois par nuit :
        powershell -ExecutionPolicy Bypass -File deploiement\windows\Sauvegarder.ps1

    Une sauvegarde qu'on ne sait pas restaurer n'est pas une sauvegarde : le
    script verifie que le fichier produit n'est pas vide, et affiche la commande
    de restauration a chaque passage.
#>
param(
    [string]$Destination = "D:\Sauvegardes\WMS",
    [int]$JoursConserves = 30
)
$ErrorActionPreference = "Stop"
$Projet = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $Projet

# pg_dump n'est pas dans le PATH apres une installation standard sous Windows :
# une sauvegarde nocturne planifiee echouerait en silence tous les soirs.
. "$PSScriptRoot\Trouver-PostgreSQL.ps1"
$null = Initialiser-PostgreSQL
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$Horodatage = Get-Date -Format "yyyy-MM-dd_HHmm"

# Les reglages de connexion viennent de .env : une seule source de verite.
$env:PGPASSWORD = (Select-String -Path ".env" -Pattern '^DJANGO_DB_PASSWORD=(.*)$').Matches.Groups[1].Value
$Base = (Select-String -Path ".env" -Pattern '^DJANGO_DB_NAME=(.*)$').Matches.Groups[1].Value
$User = (Select-String -Path ".env" -Pattern '^DJANGO_DB_USER=(.*)$').Matches.Groups[1].Value
$Hote = (Select-String -Path ".env" -Pattern '^DJANGO_DB_HOST=(.*)$').Matches.Groups[1].Value

if ($Base) {
    if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) {
        Message-PostgreSQLIntrouvable
        throw "pg_dump introuvable : la base est sur PostgreSQL, la sauvegarde est impossible."
    }
    $Fichier = Join-Path $Destination "wms_$Horodatage.dump"
    # Format 'custom' (-Fc) : compresse, et restaurable table par table.
    & pg_dump -h $Hote -U $User -d $Base -Fc -f $Fichier
    if ($LASTEXITCODE -ne 0) { throw "pg_dump a echoue." }
} else {
    # Base SQLite : '.backup' copie a chaud, sans arreter le service.
    $Fichier = Join-Path $Destination "wms_$Horodatage.sqlite3"
    & sqlite3 "$Projet\db.sqlite3" ".backup '$Fichier'"
    if ($LASTEXITCODE -ne 0) { throw "La copie SQLite a echoue." }
}
Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue

$taille = (Get-Item $Fichier).Length
if ($taille -lt 10KB) { throw "Sauvegarde suspecte : $Fichier ne fait que $taille octets." }

Get-ChildItem $Destination -File |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$JoursConserves) } |
    Remove-Item -Force

Write-Host "Sauvegarde : $Fichier ($([math]::Round($taille/1MB,1)) Mo)"
Write-Host "Restauration : pg_restore -h $Hote -U $User -d $Base --clean --if-exists `"$Fichier`""
