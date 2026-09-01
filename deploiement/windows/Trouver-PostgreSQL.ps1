<#
    Localise les outils en ligne de commande de PostgreSQL (psql, pg_dump).

    Pourquoi ce fichier existe : l'installeur PostgreSQL pour Windows n'ajoute
    PAS son dossier "bin" au PATH. Un simple `Get-Command psql` echoue donc sur
    un poste ou PostgreSQL est parfaitement installe et en service -- et le
    message "psql est introuvable" envoie alors chercher un probleme
    d'installation qui n'existe pas. C'est le piege rencontre en exploitation :
    le diagnostic accusait l'installation, la cause etait le PATH.

    Usage, en dot-source depuis un autre script :
        . "$PSScriptRoot\Trouver-PostgreSQL.ps1"
        $bin = Initialiser-PostgreSQL     # chemin du dossier bin, ou $null
#>

function Combiner-Chemin {
    # [System.IO.Path]::Combine est une operation de chaine pure. `Join-Path`,
    # lui, passe par le fournisseur de lecteurs de PowerShell et echoue en
    # "Cannot find drive" sur un poste sans disque D: -- erreur benigne qui
    # devient FATALE sous $ErrorActionPreference = 'Stop', celui des scripts
    # appelants. Une recherche d'emplacements possibles ne doit jamais tuer le
    # script qui la demande.
    param([string]$Gauche, [string]$Droite)
    return [System.IO.Path]::Combine($Gauche, $Droite)
}

function Dossiers-PostgreSQL {
    # Ceinture et bretelles : meme protegee par Combiner-Chemin, la recherche
    # touche des disques et des dossiers qui peuvent ne pas exister.
    $ErrorActionPreference = 'SilentlyContinue'

    # Emplacements possibles, du plus courant au plus rare.
    $racines = @()
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432,
                        'C:\Program Files', 'D:\Program Files')) {
        if ($base) { $racines += (Combiner-Chemin $base 'PostgreSQL') }
    }
    $racines += 'C:\PostgreSQL'

    $trouves = @()
    foreach ($racine in ($racines | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $racine)) { continue }
        $versions = Get-ChildItem -LiteralPath $racine -Directory
        foreach ($version in $versions) {
            $bin = Combiner-Chemin $version.FullName 'bin'
            if (Test-Path -LiteralPath (Combiner-Chemin $bin 'psql.exe')) {
                # Numero MAJEUR seulement : sur "9.6" -> 9, sur "17.2" -> 17.
                # Retirer tous les non-chiffres donnerait 96 et 172, et ferait
                # preferer PostgreSQL 9.6 a PostgreSQL 17.
                $numero = 0
                if ($version.Name -match '^(\d+)') { $numero = [int]$matches[1] }
                $trouves += [pscustomobject]@{ Bin = $bin; Version = $numero }
            }
        }
    }
    # La plus recente d'abord : sur un poste qui a vu passer deux installations,
    # c'est celle dont le service tourne.
    $trouves | Sort-Object Version -Descending | ForEach-Object { $_.Bin } | Select-Object -Unique
}

function Initialiser-PostgreSQL {
    # Deja dans le PATH (ajout manuel, Chocolatey, autre distribution) : on s'en
    # tient a celui-la, c'est le choix explicite de l'administrateur du poste.
    $commande = Get-Command psql.exe -ErrorAction SilentlyContinue
    if ($commande) { return (Split-Path $commande.Source -Parent) }

    $bin = @(Dossiers-PostgreSQL)
    if ($bin.Count -eq 0) { return $null }

    # Ajout au PATH de CETTE session de PowerShell seulement : la machine n'est
    # pas modifiee, rien a defaire si la repetition est abandonnee.
    $env:PATH = "$($bin[0]);$env:PATH"
    return $bin[0]
}

function Message-PostgreSQLIntrouvable {
    Write-Host ""
    Write-Host "  Les outils en ligne de commande de PostgreSQL sont introuvables." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Cherches dans le PATH, puis dans :" -ForegroundColor Gray
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, 'C:\Program Files')) {
        if ($base) { Write-Host "     $base\PostgreSQL\<version>\bin\psql.exe" -ForegroundColor Gray }
    }
    Write-Host ""
    Write-Host "  Deux causes possibles :" -ForegroundColor Yellow
    Write-Host "   1. PostgreSQL n'est pas installe." -ForegroundColor Yellow
    Write-Host "      https://www.postgresql.org/download/windows/" -ForegroundColor Yellow
    Write-Host "   2. Il est installe, mais sans 'Command Line Tools'. Relancez" -ForegroundColor Yellow
    Write-Host "      l'installeur et cochez cette case : c'est elle qui fournit" -ForegroundColor Yellow
    Write-Host "      psql et pg_dump." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Pour voir ce qui est reellement installe, dans PowerShell :" -ForegroundColor Cyan
    Write-Host "     Get-ChildItem 'C:\Program Files\PostgreSQL' -Recurse -Filter psql.exe" -ForegroundColor Cyan
    Write-Host ""
}
