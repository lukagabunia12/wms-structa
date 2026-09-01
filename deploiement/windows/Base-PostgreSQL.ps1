<#
    Preparation d'une base d'exploitation PostgreSQL pour le WMS.

    Ce fichier ne fait rien tout seul : il expose une fonction, appelee par
    Installer-WMS.ps1 (installation neuve) et par Basculer-PostgreSQL.ps1
    (reprise d'une base SQLite existante). Les deux avaient leur propre copie
    de ce code ; la moindre correction devait etre faite deux fois, et la
    seconde etait oubliee.

    Usage, en dot-source :
        . "$PSScriptRoot\Base-PostgreSQL.ps1"
        Preparer-BasePostgreSQL -Base wms -Utilisateur wms -Hote 127.0.0.1 `
            -Port 5432 -MotDePasse $mdp -MotDePasseAdmin $mdpAdmin
#>

function Echapper-SQL {
    <#
        Double les apostrophes pour une chaine litterale SQL.

        Sans cela, un mot de passe contenant une apostrophe -- ce que les
        politiques de mot de passe encouragent -- cassait la requete, et le
        script accusait le mot de passe du compte postgres.
    #>
    param([string]$Texte)
    return $Texte.Replace("'", "''")
}

function Tester-ServicePostgreSQL {
    <#
        Le service repond-il ? A verifier AVANT de faire saisir un mot de passe.

        Sans ce controle, un service arrete se manifestait par "mot de passe
        incorrect ?" apres deux saisies : le diagnostic partait dans la
        mauvaise direction pendant un quart d'heure.
    #>
    param([string]$Hote, [string]$Port)
    & pg_isready -h $Hote -p $Port -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "  Le service PostgreSQL ne repond pas sur ${Hote}:${Port}." -ForegroundColor Red
        Write-Host ""
        Write-Host "  Touche Windows, tapez services.msc, cherchez" -ForegroundColor Yellow
        Write-Host "  'postgresql-x64-...' et demarrez-le." -ForegroundColor Yellow
        Write-Host ""
        return $false
    }
    return $true
}

function Preparer-BasePostgreSQL {
    <#
        Cree le role applicatif et la base, puis attribue les droits.

        Rejouable : un role existant voit son mot de passe remis, une base
        existante et VIDE est reutilisee. Une base qui porte deja des tables
        n'est jamais ecrasee -- la fonction leve une erreur et laisse la
        decision a un humain.
    #>
    param(
        [Parameter(Mandatory)][string]$Base,
        [Parameter(Mandatory)][string]$Utilisateur,
        [Parameter(Mandatory)][string]$MotDePasse,
        [Parameter(Mandatory)][string]$MotDePasseAdmin,
        [string]$Hote = "127.0.0.1",
        [string]$Port = "5432",
        [string]$CompteAdmin = "postgres"
    )

    if ([string]::IsNullOrWhiteSpace($MotDePasse)) { throw "Mot de passe applicatif vide : abandon." }

    $mdp = Echapper-SQL $MotDePasse
    $env:PGPASSWORD = $MotDePasseAdmin
    try {
        # --- Role applicatif ---------------------------------------------------
        $sql = @"
DO `$`$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$Utilisateur') THEN
    CREATE ROLE $Utilisateur WITH LOGIN PASSWORD '$mdp';
  ELSE
    ALTER ROLE $Utilisateur WITH LOGIN PASSWORD '$mdp';
  END IF;
END `$`$;
"@
        $sql | & psql -h $Hote -p $Port -U $CompteAdmin -v ON_ERROR_STOP=1 -q
        if ($LASTEXITCODE -ne 0) {
            throw "Creation du role '$Utilisateur' impossible : mot de passe du compte '$CompteAdmin' incorrect ?"
        }

        # --- Base --------------------------------------------------------------
        # Les guillemets "$( )" ne sont pas cosmetiques : quand la base n'existe
        # pas, psql ne renvoie AUCUNE ligne et PowerShell recupere $null. Appeler
        # .Trim() dessus leve "You cannot call a method on a null-valued
        # expression" -- fatal sous ErrorActionPreference Stop, c'est-a-dire au
        # tout premier lancement, quand la base n'existe justement pas.
        $existe = "$(& psql -h $Hote -p $Port -U $CompteAdmin -tAc `
            "SELECT 1 FROM pg_database WHERE datname='$Base'")".Trim()

        if ($existe -eq "1") {
            $tables = "$(& psql -h $Hote -p $Port -U $CompteAdmin -d $Base -tAc `
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")".Trim()
            if ([string]::IsNullOrWhiteSpace($tables)) { $tables = "0" }
            if ([int]$tables -gt 0) {
                Write-Host ""
                Write-Host "  La base '$Base' existe deja et contient $tables table(s)." -ForegroundColor Red
                Write-Host "  Rien n'est ecrase : c'est a vous de decider." -ForegroundColor Red
                Write-Host ""
                Write-Host "  Si ces donnees sont a jeter :" -ForegroundColor Yellow
                Write-Host "     psql -U $CompteAdmin -c ""DROP DATABASE $Base;""" -ForegroundColor Yellow
                Write-Host "  Sinon, relancez en nommant une autre base :  -Base wms2" -ForegroundColor Yellow
                Write-Host ""
                throw "Base '$Base' non vide."
            }
            Write-Host "     Base '$Base' deja presente et vide : reutilisee." -ForegroundColor Gray
        } else {
            # Pas de LC_COLLATE force : 'fr_FR.UTF-8' n'existe pas sous Windows.
            & psql -h $Hote -p $Port -U $CompteAdmin -v ON_ERROR_STOP=1 -q `
                -c "CREATE DATABASE $Base WITH OWNER = $Utilisateur ENCODING = 'UTF8' TEMPLATE = template0;"
            if ($LASTEXITCODE -ne 0) { throw "Creation de la base '$Base' impossible." }
            Write-Host "     Base '$Base' creee." -ForegroundColor Gray
        }

        # --- Droits sur le schema ---------------------------------------------
        # Depuis PostgreSQL 15, le schema public n'est plus inscriptible par
        # tout le monde : sans ces trois ordres, migrate tombe beaucoup plus
        # loin en "permission denied for schema public", une erreur sans
        # rapport apparent avec sa cause.
        & psql -h $Hote -p $Port -U $CompteAdmin -d $Base -v ON_ERROR_STOP=1 -q `
            -c "ALTER SCHEMA public OWNER TO $Utilisateur; GRANT ALL ON SCHEMA public TO $Utilisateur; REVOKE ALL ON DATABASE $Base FROM PUBLIC;"
        if ($LASTEXITCODE -ne 0) { throw "Attribution des droits sur le schema public impossible." }
    }
    finally {
        # Toujours, meme sur erreur : le mot de passe administrateur ne doit pas
        # rester dans l'environnement de la console.
        Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    }

    Write-Host "     Droits attribues a '$Utilisateur' sur le schema public." -ForegroundColor Gray
}
