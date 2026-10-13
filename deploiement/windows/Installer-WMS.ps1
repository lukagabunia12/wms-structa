<#
    INSTALLATION COMPLETE DU WMS STRUCTA SUR LE SERVEUR.

    A lancer sur la machine qui servira de serveur, apres avoir copie le
    dossier du projet. Double-cliquez plutot sur Installer-WMS.bat a la racine :
    il demande les droits administrateur et appelle ce script.

    Ce que le script fait, dans cet ordre -- apres avoir reserve le dossier du
    projet aux administrateurs et au service, AVANT d'y ecrire le moindre
    secret :
      1. verifie Python (version, et qu'il sait creer un environnement)
      2. cree l'environnement .venv du projet
      3. installe les dependances -- hors ligne depuis paquets\ si ce dossier
         existe, depuis internet sinon
      4. prepare .env : cle secrete tiree au hasard, mode exploitation, nom de
         domaine (-Noms)
      5. verifie PostgreSQL, cree le role applicatif, la base et les droits
      6. inscrit la base dans .env
      7. applique le schema (migrate)
      8. reprend les donnees de reprise\ s'il y en a, sinon cree un compte
         administrateur
      9. fabrique le certificat HTTPS de CE poste et installe l'autorite dans
         le magasin de confiance de Windows
     10. ouvre le port HTTPS dans le pare-feu (profils Domaine et Prive)
     11. controle de pre-vol
     12. pose les taches planifiees (demarrage automatique, sauvegardes,
         menage des journaux), fait une premiere sauvegarde et demarre le WMS

    Rejouable : aucune etape ne detruit ce qui existe deja. Une base qui porte
    des tables n'est jamais ecrasee ; si .env designe deja une base en
    service, les etapes 5, 6 et 8 sont sautees sans rien toucher.

    Options utiles :
      -Noms wms.structa.fr        nom de domaine des telephones (certificat)
      -Sauvegardes D:\WMS-Sauvegardes      dossier des sauvegardes
      -CopieSauvegardes \\NAS\WMS         seconde destination, hors machine
      -Taches                     seulement reposer les taches et redemarrer
      -SansTaches                 poste de test : rien ne demarre tout seul

    Journal de l'installation : logs\installation.log
#>
param(
    [string]$Base = "wms",
    [string]$Utilisateur = "wms",
    [string]$Hote = "127.0.0.1",
    [string]$Port = "5432",
    [string]$PortHttps = "4443",
    [string]$Python = "",
    [string]$Noms = "",
    [string]$Sauvegardes = "",
    [string]$CopieSauvegardes = "",
    [string]$HeuresSauvegarde = "12:30,22:30",
    [int]$NettoyageTousLes = 7,
    [switch]$SansPareFeu,
    [switch]$SansPostgreSQL,
    [switch]$SansTaches,
    [switch]$SansDurcissement,
    [switch]$Taches,
    [switch]$Tunnel
)

$ErrorActionPreference = "Stop"
$Projet = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $Projet

# --- Journal ----------------------------------------------------------------
# Une installation qui echoue au milieu laisse une console qu'on ferme par
# reflexe. Le journal survit a la fermeture : c'est lui qu'on lit ensuite.
$null = New-Item -ItemType Directory -Force -Path "$Projet\logs"
$Journal = "$Projet\logs\installation.log"
function Noter {
    param([string]$Texte, [string]$Couleur = "Gray")
    Write-Host $Texte -ForegroundColor $Couleur
    Add-Content -Path $Journal -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Texte" -Encoding UTF8
}
function Etape { param([string]$Numero, [string]$Texte) Noter "" ; Noter "$Numero  $Texte" "Yellow" }

# Une erreur fatale (throw) s'affichait a l'ecran mais n'arrivait jamais au
# journal : la console fermee, plus rien ne disait ce qui avait arrete
# l'installation.
trap {
    Noter ""
    Noter "  ERREUR : $($_.Exception.Message)" "Red"
    Noter "  L'installation s'arrete ici. Journal : logs\installation.log" "Yellow"
    break
}

function Reserver-Dossier {
    <#
        Reserve le dossier du projet aux Administrateurs, a SYSTEM et au compte
        qui installe.

        Un dossier cree a la racine d'un disque herite d'un droit de
        MODIFICATION pour tous les utilisateurs authentifies : n'importe quel
        compte du serveur pouvait lire .env (mot de passe de la base, cle
        secrete) et la cle de l'autorite de certification -- ou deposer dans
        .venv un fichier que le service, qui tourne en SYSTEM, aurait execute.
        Fait AVANT les etapes qui ecrivent ces secrets (4, 6 et 9) : une
        installation interrompue au milieu ne doit pas les laisser lisibles.
    #>
    if ($SansDurcissement) {
        Noter "     Droits du dossier laisses tels quels (-SansDurcissement)." "Yellow"
        return
    }
    if (-not $Administrateur) {
        Noter "     Droits du dossier NON restreints : droits administrateur requis." "Yellow"
        return
    }
    $moi = ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
    & icacls $Projet /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*${moi}:(OI)(CI)F" /Q | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Noter "     Dossier du projet reserve aux Administrateurs, a SYSTEM et a $env:USERNAME." "Green"
    } else {
        Noter "     Droits du dossier NON modifies (icacls code $LASTEXITCODE). A faire a la main :" "Yellow"
        Noter "       icacls ""$Projet"" /inheritance:r /grant:r *S-1-5-32-544:(OI)(CI)F *S-1-5-18:(OI)(CI)F" "Yellow"
    }
}

Noter ""
Noter "  ============================================================" "Cyan"
Noter "   WMS STRUCTA - installation du poste serveur" "Cyan"
Noter "  ============================================================" "Cyan"
Noter "   Projet : $Projet"
Noter "   Poste  : $env:COMPUTERNAME"
# Le compte est note volontairement : l'elevation en administrateur bascule
# parfois sur un AUTRE compte que celui ouvert, et un Python installe "pour moi
# seulement" devient alors invisible. Quand un poste se comporte differemment
# selon le fichier lance, c'est la premiere chose a comparer.
Noter "   Compte : $env:USERNAME"
if ($SansPostgreSQL) {
    Noter ""
    Noter "   MODE DE SECOURS : base SQLite, PostgreSQL n'est pas installe." "Yellow"
    Noter "   Tient pour un POC de quelques jours avec une poignee de caristes." "Yellow"
    Noter "   SQLite supporte mal plusieurs ecritures simultanees : a repasser" "Yellow"
    Noter "   sur PostgreSQL avant tout usage reel." "Yellow"
}
if ($Tunnel) {
    Noter ""
    Noter "   MODE TUNNEL : l'acces passera par cloudflared, pas par le reseau" "Cyan"
    Noter "   interne. Pare-feu et autorite de certification sont donc sautes." "Cyan"
}

$Administrateur = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $Administrateur) {
    Noter ""
    Noter "  Cette console n'a pas les droits administrateur." "Yellow"
    Noter "  L'installation continue, mais DEUX etapes seront sautees :" "Yellow"
    Noter "    - l'ouverture du port dans le pare-feu ;" "Yellow"
    Noter "    - l'inscription de l'autorite de certification." "Yellow"
    Noter "  Les telephones ne joindront pas le serveur tant que ces deux" "Yellow"
    Noter "  etapes n'auront pas ete faites. Fermez et relancez plutot" "Yellow"
    Noter "  Installer-WMS.bat, qui demande l'elevation." "Yellow"
}

Noter ""
Noter "  Droits du dossier du projet..." "Yellow"
Reserver-Dossier

$Py = "$Projet\.venv\Scripts\python.exe"
if ($Taches) {
    if (-not (Test-Path $Py)) {
        Noter "  -Taches suppose une installation deja faite (.venv absent)." "Red"
        exit 1
    }
    if (-not $Administrateur) {
        Noter "  -Taches demande les droits administrateur : passez par Installer-WMS.bat." "Red"
        exit 1
    }
    Noter "   MODE -Taches : seulement le controle de pre-vol, les taches planifiees" "Cyan"
    Noter "   et le redemarrage. Rien d'autre n'est touche." "Cyan"
} else {

# --- 1. Python ---------------------------------------------------------------
Etape "1/12" "Recherche de Python..."

. "$PSScriptRoot\Trouver-Python.ps1"
# Surtout pas `$python` : PowerShell ignore la casse, ce serait le parametre
# -Python, type [string]. L'objet rendu y serait converti en texte, et l'etape
# conclurait "Python trop ancien" avec des champs vides (vu sur SRV-WMS).
$interp = Initialiser-Python -Impose $Python
if (-not $interp) {
    Message-PythonIntrouvable
    Add-Content -Path $Journal -Encoding UTF8 `
        -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  Python introuvable : installation interrompue."
    exit 1
}
if ($interp.Majeur -lt 3 -or ($interp.Majeur -eq 3 -and $interp.Mineur -lt 10)) {
    Noter ""
    Noter "  Python $($interp.Version) est trop ancien : Django 5.2 exige 3.10 au minimum." "Red"
    Noter ""
    # Tout ce qu'il faut pour trancher sans revenir poser de questions : est-ce
    # un vieux Python reellement installe, ou une lecture de version ratee ?
    Noter "  Interpreteur retenu : $($interp.Exe) $($interp.Arguments)" "Gray"
    Noter "  Il a repondu        : [$($interp.Brut -replace '\r?\n', ' / ')]" "Gray"
    Noter "  Lu comme            : majeur=$($interp.Majeur) mineur=$($interp.Mineur)" "Gray"
    Noter ""
    Noter "  Si vous avez installe Python 3.10 ou plus recent, ce n'est pas celui-la" "Yellow"
    Noter "  qui a ete trouve. Double-cliquez Trouver-Python.bat : il liste tous les" "Yellow"
    Noter "  interpreteurs du poste. Puis designez le bon :" "Yellow"
    Noter "     Installer-WMS.bat -Python ""C:\chemin\vers\python.exe""" "Cyan"
    Noter ""
    Noter "  Sinon, installez une version recente :" "Cyan"
    Noter "     https://www.python.org/downloads/windows/" "Cyan"
    Noter ""
    exit 1
}
Noter "     Python $($interp.Version) : $($interp.Exe) $($interp.Arguments)" "Green"

# --- 2. Environnement du projet ---------------------------------------------
Etape "2/12" "Environnement Python du projet..."
if (-not (Test-Path $Py)) {
    & $interp.Exe @($interp.Arguments) "-m" "venv" ".venv"
    if (-not (Test-Path $Py)) {
        Noter ""
        Noter "  La creation de .venv a echoue." "Red"
        Noter "  Interpreteur utilise : $($interp.Exe)" "Yellow"
        Noter "  Cause la plus frequente : un Python installe 'pour moi seulement'" "Yellow"
        Noter "  alors que cette fenetre tourne sous un autre compte administrateur." "Yellow"
        Noter "  Reinstallez Python en 'Install for all users', ou passez son chemin :" "Yellow"
        Noter "     Installer-WMS.bat -Python ""C:\chemin\vers\python.exe""" "Cyan"
        exit 1
    }
    Noter "     .venv cree." "Green"
} else {
    Noter "     .venv deja present : reutilise." "Green"
}

# --- 3. Dependances ---------------------------------------------------------
Etape "3/12" "Dependances Python..."
$Paquets = "$Projet\paquets"
$horsLigne = (Test-Path $Paquets) -and
             ((Get-ChildItem $Paquets -Filter *.whl -ErrorAction SilentlyContinue).Count -gt 0)

if ($horsLigne) {
    # Les roues Python portent la version de l'interpreteur dans leur nom.
    # Un dossier prepare pour 3.12 ne s'installe pas sur 3.14 : pip repond
    # "no matching distribution", message qui laisse croire a un dossier vide.
    $marque = "$Paquets\version.txt"
    if (Test-Path $marque) {
        $attendue = (Get-Content $marque -First 1).Trim()
        if ($attendue -and $attendue -ne $interp.Version) {
            Noter ""
            Noter "  Le dossier paquets\ a ete prepare pour Python $attendue," "Red"
            Noter "  ce poste a Python $($interp.Version). Les deux doivent concorder." "Red"
            Noter ""
            Noter "  Deux issues :" "Yellow"
            Noter "   - installer Python $attendue sur ce poste ; ou" "Yellow"
            Noter "   - refaire le dossier paquets\ sur un poste en Python $($interp.Version)" "Yellow"
            Noter "     avec Preparer-Paquets.bat (a la racine du projet)." "Yellow"
            Noter ""
            exit 1
        }
    }
    Noter "     Installation hors ligne depuis paquets\ (aucun acces internet requis)."
    # Sous ErrorActionPreference Stop, Windows PowerShell 5.1 change en erreur
    # FATALE la premiere ligne qu'un programme ecrit sur stderr des qu'on la
    # redirige : un simple avertissement de pip arretait l'installation.
    $avant = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Py -m pip install --no-index --find-links "$Paquets" --upgrade pip --quiet 2>$null
    $ErrorActionPreference = $avant
    & $Py -m pip install --no-index --find-links "$Paquets" -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) {
        Noter ""
        Noter "  L'installation hors ligne a echoue." "Red"
        Noter "  Le dossier paquets\ est incomplet ou prepare pour un autre Python." "Yellow"
        Noter "  Refaites-le : Preparer-Paquets.bat (a la racine du projet)" "Yellow"
        exit 1
    }
} else {
    Noter "     Aucun dossier paquets\ : installation depuis internet."
    & $Py -m pip install --upgrade pip --quiet
    & $Py -m pip install -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) {
        Noter ""
        Noter "  L'installation depuis internet a echoue." "Red"
        Noter "  Ce poste n'a peut-etre pas acces a PyPI (reseau filtre)." "Yellow"
        Noter "  Preparez alors le dossier paquets\ sur un poste qui a internet :" "Yellow"
        Noter "     Preparer-Paquets.bat (a la racine du projet)" "Yellow"
        Noter "  puis recopiez-le ici et relancez." "Yellow"
        exit 1
    }
}
Noter "     Dependances installees." "Green"

# --- 4. Configuration -------------------------------------------------------
Etape "4/12" "Fichier .env (cle secrete, mode exploitation, nom de domaine)..."
& $Py outils\preparer_env.py
if ($LASTEXITCODE -ne 0) { throw "La preparation de .env a echoue." }
# Sans nom de domaine, le certificat ne couvre que les adresses IP : un
# telephone qui ouvre https://wms.structa.fr afficherait une alerte. Demande
# seulement s'il n'est ni passe en option, ni deja dans .env.
$nomDejaRegle = Select-String -Path "$Projet\.env" -Pattern '^WMS_NOMS=.+' -Quiet -ErrorAction SilentlyContinue
if (-not $Noms -and -not $nomDejaRegle -and -not $Tunnel) {
    Noter ""
    Noter "  Nom que taperont les telephones (ex. wms.structa.fr), s'il existe dans" "Cyan"
    Noter "  le DNS interne. Entree si les telephones utilisent l'adresse IP." "Cyan"
    $Noms = (Read-Host "     Nom de domaine").Trim()
}
# Le port des telephones (4443 sur le serveur de STRUCTA) : lu par le
# lanceur, le service, l'etat et l'arret.
& $Py outils\preparer_env.py --poser "WMS_PORT_HTTPS=$PortHttps"
if ($LASTEXITCODE -ne 0) { throw "Le port HTTPS n'a pas pu etre inscrit dans .env." }
# Les bibliotheques du scanner (lecture des QR, etiquettes) ne sont pas dans
# le depot GitHub : sans elles, les telephones les chargeraient depuis
# internet a chaque ouverture. Non bloquant.
if (-not (Test-Path "$Projet\wms\static\app\vendor\html5-qrcode.min.js")) {
    & $Py manage.py telecharger_libs
    if ($LASTEXITCODE -ne 0) {
        Noter "     Bibliotheques du scanner NON telechargees (acces internet ?). Plus tard :" "Yellow"
        Noter "       .venv\Scripts\python.exe manage.py telecharger_libs" "Yellow"
    }
}
if ($Noms) {
    # Le nom que les telephones taperont (wms.structa.fr) : le certificat le
    # couvrira, et Django l'acceptera. A poser AVANT le certificat (etape 9).
    & $Py outils\preparer_env.py --poser "WMS_NOMS=$Noms"
    if ($LASTEXITCODE -ne 0) { throw "Le nom de domaine n'a pas pu etre inscrit dans .env." }
}

# Une base deja en service (reinstallation, ajout du certificat ou des taches
# sur un serveur qui tourne) : on n'y touche plus -- ni role, ni mot de passe,
# ni reprise de donnees.
$BaseEnService = $false
if (-not $SansPostgreSQL) {
    & $Py outils\basculer_base.py en-service
    $BaseEnService = ($LASTEXITCODE -eq 0)
}

# Un poste qui a tourne sur SQLite (-SansPostgreSQL, quelques jours de POC) et
# qu'on installe maintenant sur PostgreSQL : la suite repartirait du dossier
# reprise\ du jour de la copie, ou d'une base vierge, et les jours de travail
# restes dans db.sqlite3 disparaitraient sans un mot.
if (-not $SansPostgreSQL -and -not $BaseEnService) {
    & $Py outils\basculer_base.py sqlite-occupee
    if ($LASTEXITCODE -eq 0) {
        Noter ""
        Noter "  Ce poste travaille sur SQLite, et sa base contient des donnees (ci-dessus)." "Red"
        Noter "  - Si ce serveur a vraiment travaille sur SQLite (installe avec" "Yellow"
        Noter "    -SansPostgreSQL) : Basculer-PostgreSQL.bat emporte ces donnees sur" "Yellow"
        Noter "    PostgreSQL, puis relancez Installer-WMS.bat." "Yellow"
        Noter "  - Si db.sqlite3 vient d'une copie du dossier faite a la main, il est" "Yellow"
        Noter "    perime (la date le dit) : renommez-le db.sqlite3.ancien, et passez" "Yellow"
        Noter "    plutot par Preparer-Copie.bat sur le poste d'origine." "Yellow"
        Noter "  Les donnees n'ont pas ete touchees." "Yellow"
        exit 1
    }
}

# --- 5. PostgreSQL ----------------------------------------------------------
Etape "5/12" "PostgreSQL : service, role applicatif et base..."
if ($SansPostgreSQL) {
    Noter "     Saute : la base sera le fichier SQLite db.sqlite3." "Yellow"
} elseif ($BaseEnService) {
    Noter "     Saute : .env designe deja une base en service. Rien n'est touche." "Green"
} else {
. "$PSScriptRoot\Trouver-PostgreSQL.ps1"
. "$PSScriptRoot\Base-PostgreSQL.ps1"

$BinPg = Initialiser-PostgreSQL
if (-not $BinPg) {
    Message-PostgreSQLIntrouvable
    Noter ""
    Noter "  PostgreSQL doit etre installe AVANT de relancer ce script." "Yellow"
    Noter "  Telechargement : https://www.postgresql.org/download/windows/" "Cyan"
    Noter "  Cochez 'Command Line Tools' pendant l'installation." "Cyan"
    Noter ""
    Noter "  S'IL FAUT DEMARRER SANS ATTENDRE (POC de quelques jours) :" "Yellow"
    Noter "     Installer-WMS.bat -SansPostgreSQL" "Cyan"
    Noter "  Le WMS tournera alors sur un fichier SQLite. C'est un secours, pas" "Yellow"
    Noter "  une cible : SQLite tient mal plusieurs caristes qui rangent ensemble." "Yellow"
    Noter ""
    exit 1
}
Noter "     Outils PostgreSQL : $BinPg"
if (-not (Tester-ServicePostgreSQL -Hote $Hote -Port $Port)) { exit 1 }
Noter "     Service joignable sur ${Hote}:${Port}."

Noter ""
Noter "  Deux mots de passe sont demandes :" "Cyan"
Noter "   - celui a DONNER au compte applicatif '$Utilisateur' (vous le choisissez) ;" "Cyan"
Noter "   - celui du compte 'postgres', choisi pendant l'installation de PostgreSQL." "Cyan"
Noter "  Ni l'un ni l'autre ne sera affiche ni ecrit dans le journal." "Cyan"
Noter ""
for ($essai = 1; $essai -le 3; $essai++) {
    $MdpSecure = Read-Host "     Mot de passe a donner au compte '$Utilisateur'" -AsSecureString
    $MdpApp = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($MdpSecure))
    if ([string]::IsNullOrWhiteSpace($MdpApp)) { throw "Mot de passe vide : abandon." }
    $refus = Tester-MotDePasseEnv $MdpApp
    if (-not $refus) { break }
    Noter "     Ce mot de passe ne peut pas etre ecrit dans .env : $refus. Un autre ?" "Yellow"
    $MdpApp = $null
}
if (-not $MdpApp) { throw "Aucun mot de passe utilisable : abandon." }
$MdpAdminSecure = Read-Host "     Mot de passe du compte 'postgres'" -AsSecureString
$MdpAdmin = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($MdpAdminSecure))

Preparer-BasePostgreSQL -Base $Base -Utilisateur $Utilisateur -MotDePasse $MdpApp `
    -MotDePasseAdmin $MdpAdmin -Hote $Hote -Port $Port
$MdpAdmin = $null
Noter "     Base '$Base' prete." "Green"
}

# --- 6. Inscription dans .env -----------------------------------------------
Etape "6/12" "Inscription de la base dans .env..."
if ($SansPostgreSQL) {
    Noter "     Saute : .env reste sur SQLite." "Yellow"
} elseif ($BaseEnService) {
    Noter "     Saute : base deja inscrite." "Green"
} else {
# Par variable d'environnement, et non en argument de ligne de commande : les
# arguments d'un processus sont lisibles par tout compte du poste.
$env:WMS_DB_PASSWORD = $MdpApp
try {
    & $Py outils\basculer_base.py postgresql --base $Base --utilisateur $Utilisateur `
          --hote $Hote --port $Port
    if ($LASTEXITCODE -ne 0) { throw "L'inscription de la base dans .env a echoue." }
}
finally {
    Remove-Item Env:\WMS_DB_PASSWORD -ErrorAction SilentlyContinue
    $MdpApp = $null
}
}

# --- 7. Schema --------------------------------------------------------------
Etape "7/12" "Application du schema (migrate)..."
& $Py manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw "Les migrations ont echoue : voir le message ci-dessus." }
Noter "     Schema a jour." "Green"

# --- 8. Donnees et compte administrateur ------------------------------------
Etape "8/12" "Donnees..."
if ($BaseEnService) {
    Noter "     Saute : la base en service garde ses donnees." "Green"
} elseif (Test-Path "$Projet\reprise\donnees.json") {
    Noter "     Reprise des donnees du dossier reprise\..."
    & $Py manage.py reprise_sql importer --depuis reprise
    if ($LASTEXITCODE -ne 0) {
        Noter ""
        Noter "  La reprise a ete refusee : la base est vide, rien n'est casse." "Red"
        Noter "  Creez un compte a la main, puis reprenez plus tard :" "Yellow"
        Noter "     .venv\Scripts\python.exe manage.py createsuperuser" "Yellow"
        exit 1
    }
    Noter "     Donnees reprises. Les comptes viennent avec." "Green"
    Noter "     La copie apportee (cle USB, archive .zip) contient toute la base :" "Yellow"
    Noter "     effacez-la maintenant que l'import est fait." "Yellow"
} else {
    Noter "     Aucun dossier reprise\ : base vierge."
    Noter ""
    Noter "  Creation du compte administrateur (nom, courriel, mot de passe)." "Cyan"
    Noter ""
    & $Py manage.py createsuperuser
    if ($LASTEXITCODE -ne 0) {
        Noter "  Compte non cree. A faire avant la mise en service :" "Yellow"
        Noter "     .venv\Scripts\python.exe manage.py createsuperuser" "Yellow"
    }
}

# --- 9. Certificat HTTPS ----------------------------------------------------
Etape "9/12" "Certificat HTTPS de ce poste..."
# Le certificat porte les adresses IP du poste : celui de l'ancien PC ne vaut
# rien ici. On le fabrique donc sur place, jamais on ne le recopie.
$certificatOk = $true
if ($Tunnel) {
    Noter "     Saute : Cloudflare fournit un certificat reconnu par les telephones." "Cyan"
    $certificatOk = $false
} else {
    # --si-besoin : sur une reinstallation, le certificat existant est refait
    # (signe par la meme autorite) s'il ne couvre pas un nom ou une adresse
    # d'aujourd'hui -- un nouveau -Noms, une nouvelle adresse IP.
    & $Py outils\certificat_https.py --si-besoin
    if ($LASTEXITCODE -ne 0) {
        # Non bloquant, delibere : sans certificat il reste l'acces par tunnel.
        # Faire echouer toute l'installation ici priverait d'un serveur qui,
        # par ailleurs, fonctionne.
        $certificatOk = $false
        Noter "     Certificat NON fabrique. L'acces par le reseau interne sera" "Yellow"
        Noter "     indisponible ; l'acces par tunnel reste possible." "Yellow"
    }
}

if ($certificatOk -and $Administrateur) {
    & certutil -addstore -f Root "$Projet\certificats\ac-structa.crt" | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Noter "     Autorite inscrite dans le magasin de confiance de Windows." "Green"
    } else {
        Noter "     Autorite NON inscrite : Edge et Chrome avertiront sur ce poste." "Yellow"
    }
} elseif ($certificatOk) {
    Noter "     Autorite non inscrite (droits administrateur requis)." "Yellow"
    Noter "     A faire dans une invite administrateur :" "Yellow"
    Noter "       certutil -addstore -f Root certificats\ac-structa.crt" "Yellow"
}

# --- 10. Pare-feu -----------------------------------------------------------
Etape "10/12" "Pare-feu : port $PortHttps en entree..."
if ($Tunnel) {
    Noter "     Saute : le tunnel ouvre une connexion SORTANTE, rien a autoriser" "Cyan"
    Noter "     en entree." "Cyan"
} elseif ($SansPareFeu) {
    Noter "     Saute (-SansPareFeu)."
} elseif (-not $Administrateur) {
    Noter "     Saute : droits administrateur requis." "Yellow"
    Noter "     A faire dans une invite administrateur :" "Yellow"
    Noter "       netsh advfirewall firewall add rule name=""WMS Structa HTTPS"" dir=in action=allow protocol=TCP localport=$PortHttps profile=domain,private" "Yellow"
} else {
    $regle = "WMS Structa HTTPS"
    Get-NetFirewallRule -DisplayName $regle -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    # Domaine et Prive seulement. Jamais Public : sur un reseau ouvert, le WMS
    # n'a rien a ecouter.
    New-NetFirewallRule -DisplayName $regle -Direction Inbound -Protocol TCP `
        -LocalPort $PortHttps -Action Allow -Profile Domain,Private | Out-Null
    Noter "     Port $PortHttps ouvert (profils Domaine et Prive)." "Green"
    Noter "     Sur un poste du domaine, une strategie de groupe peut annuler cette"
    Noter "     regle. Si les telephones n'aboutissent pas, c'est la premiere piste."
    # Le profil Public n'est pas couvert, volontairement. Mais un serveur hors
    # domaine dont la carte reseau est classee Public bloquerait les
    # telephones, alors que tout annonce un port ouvert.
    $publics = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue |
                 Where-Object { "$($_.NetworkCategory)" -eq "Public" })
    if ($publics.Count -gt 0) {
        Noter "     ATTENTION : le reseau '$($publics[0].Name)' est classe Public : la regle" "Yellow"
        Noter "     ne s'y applique pas, les telephones seront bloques. A classer en Prive" "Yellow"
        Noter "     (service informatique), ou dans une invite PowerShell administrateur :" "Yellow"
        Noter "       Set-NetConnectionProfile -InterfaceIndex $($publics[0].InterfaceIndex) -NetworkCategory Private" "Yellow"
    }
}

}   # fin du mode installation complete (-Taches saute jusqu'ici)

# --- 11. Controle de pre-vol ------------------------------------------------
Etape "11/12" "Controle de pre-vol..."
& $Py outils\preparer_serveur.py
$prevol = $LASTEXITCODE

# --- 12. Taches planifiees et demarrage -------------------------------------
Etape "12/12" "Taches planifiees : demarrage automatique, sauvegardes, menage..."
$service = $false
if ($SansTaches) {
    Noter "     Saute (-SansTaches) : le WMS ne demarrera pas tout seul." "Yellow"
} elseif (-not $Administrateur) {
    Noter "     Saute : droits administrateur requis. Relancez Installer-WMS.bat -Taches." "Yellow"
} elseif ($prevol -ne 0) {
    Noter "     Saute : le controle de pre-vol signale un point bloquant (ci-dessus)." "Red"
    Noter "     Corrigez-le, puis :  Installer-WMS.bat -Taches" "Yellow"
} else {
    # Destination des sauvegardes : demandee si elle n'est ni passee en option,
    # ni deja reglee dans .env.
    $dejaRegle = Select-String -Path "$Projet\.env" -Pattern '^WMS_SAUVEGARDE_DOSSIER=.+' -Quiet -ErrorAction SilentlyContinue
    if (-not $Sauvegardes -and -not $dejaRegle) {
        $defaut = [System.IO.Path]::Combine([System.IO.Path]::GetPathRoot($Projet), "WMS-Sauvegardes")
        Noter ""
        Noter "  Ou ecrire les sauvegardes ? Un autre disque que celui du systeme est" "Cyan"
        Noter "  preferable. Entree pour garder la proposition." "Cyan"
        $saisie = Read-Host "     Dossier des sauvegardes [$defaut]"
        $Sauvegardes = $(if ($saisie) { $saisie.Trim() } else { $defaut })
    }
    # Cree par la premiere sauvegarde, le dossier est reserve aux
    # administrateurs. S'il existe deja, ses droits ne sont pas touches -- il
    # peut servir a autre chose : le dire, plutot que de le croire protege.
    if ($Sauvegardes -and -not $Sauvegardes.StartsWith('\\') -and
            (Test-Path -LiteralPath $Sauvegardes) -and
            -not (Get-ChildItem -LiteralPath $Sauvegardes -Filter 'wms_*' -ErrorAction SilentlyContinue)) {
        Noter "     Le dossier $Sauvegardes existe deja : ses droits sont conserves. Il" "Yellow"
        Noter "     contiendra la cle secrete et toute la base : verifiez qu'il n'est" "Yellow"
        Noter "     lisible que par les administrateurs (Proprietes > Securite)." "Yellow"
    }
    $dejaCopie = Select-String -Path "$Projet\.env" -Pattern '^WMS_SAUVEGARDE_COPIE=.+' -Quiet -ErrorAction SilentlyContinue
    if (-not $CopieSauvegardes -and -not $dejaCopie) {
        Noter ""
        Noter "  Une seconde copie HORS de cette machine (partage reseau \\serveur\partage," "Cyan"
        Noter "  disque externe) protege contre la perte du disque. Le partage doit" "Cyan"
        Noter "  autoriser l'ecriture au compte de la machine ($env:COMPUTERNAME`$)." "Cyan"
        $CopieSauvegardes = (Read-Host "     Seconde destination (Entree : aucune pour l'instant)").Trim()
    }

    # Pas de chaine vide passee a python : Windows PowerShell 5.1 la supprime
    # de la ligne de commande, et l'option suivante perdrait son argument.
    $argsTaches = @("outils\serveur_wms.py", "taches", "--essayer")
    # Heures et frequence : passees seulement si elles ont ete donnees. Sinon
    # serveur_wms.py reprend celles d'avant, gardees dans .env -- une mise a
    # jour ne doit pas remettre en silence les horaires par defaut, ni le
    # compte dedie a la sauvegarde.
    if ($PSBoundParameters.ContainsKey('HeuresSauvegarde')) {
        $argsTaches += @("--heures", $HeuresSauvegarde)
    }
    if ($PSBoundParameters.ContainsKey('NettoyageTousLes')) {
        $argsTaches += @("--nettoyage-tous-les", "$NettoyageTousLes")
    }
    if ($Sauvegardes) { $argsTaches += @("--sauvegardes", $Sauvegardes) }
    if ($CopieSauvegardes) { $argsTaches += @("--copie", $CopieSauvegardes) }
    # En mode tunnel, le WMS se lance par Demarrer-WMS-Tunnel.bat, dans une
    # fenetre : seules la sauvegarde et le menage sont planifies.
    if ($Tunnel) { $argsTaches += "--sans-service" }
    & $Py @argsTaches
    if ($LASTEXITCODE -ne 0) {
        Noter "     La premiere sauvegarde n'a pas abouti : voir le message ci-dessus." "Yellow"
        Noter "     Le WMS demarre quand meme ; corrigez, puis Sauvegarder-WMS.bat." "Yellow"
    }
    if (-not $Tunnel) {
        & $Py outils\serveur_wms.py demarrer
        $service = ($LASTEXITCODE -eq 0)
    }
}

Noter ""
Noter "  ============================================================" "Cyan"
if ($prevol -eq 0) {
    Noter "   INSTALLATION TERMINEE." "Green"
} else {
    Noter "   INSTALLATION INCOMPLETE : voir les points BLOC ci-dessus." "Red"
}
Noter "  ============================================================" "Cyan"
Noter ""
if ($Tunnel) {
    Noter "  Pour demarrer le WMS :  Demarrer-WMS-Tunnel.bat" "Cyan"
    Noter ""
    Noter "  Une adresse https publique s'affichera, avec son QR code : les"
    Noter "  caristes scannent l'ecran. Elle change a chaque demarrage, et la"
    Noter "  fenetre du tunnel doit rester ouverte."
    Noter ""
    Noter "  Rien a installer sur les telephones : le certificat vient de"
    Noter "  Cloudflare, ils le reconnaissent deja."
    Noter ""
    Noter "  Des que le port $PortHttps sera ouvert, repasser sur l'acces interne :" "Yellow"
    Noter "     Installer-WMS.bat        (sans -Tunnel, pour le certificat et le pare-feu)" "Yellow"
    Noter "     Demarrer-WMS.bat" "Yellow"
} else {
    if ($service) {
        Noter "  Le WMS est EN SERVICE, et redemarre seul avec Windows." "Green"
        Noter "  Etat-WMS.bat : tout l'etat du serveur. Arreter-WMS.bat / Redemarrer-WMS.bat" "Cyan"
        Noter "  pour une mise a jour. Sauvegarder-WMS.bat : une sauvegarde tout de suite." "Cyan"
    } else {
        Noter "  Pour demarrer le WMS :  Redemarrer-WMS.bat (service), ou Demarrer-WMS.bat" "Cyan"
        Noter "  dans une fenetre a laisser ouverte." "Cyan"
    }
    Noter ""
    if ($Noms) {
        foreach ($n in ($Noms -split ',')) {
            if ($n.Trim()) { Noter "  Adresse pour les telephones : https://$($n.Trim()):$PortHttps" "Cyan" }
        }
    }
    $adresses = Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" }
    foreach ($a in $adresses) {
        Noter "  Adresse possible pour les telephones : https://$($a.IPAddress):$PortHttps" "Cyan"
    }
    Noter ""
    Noter "  Sur chaque telephone, une seule fois : installer l'autorite"
    Noter "  certificats\ac-structa.crt (iPhone : le profil ac-structa.mobileconfig,"
    Noter "  puis Reglages > General > Informations > Reglages de confiance)."
    Noter ""
    Noter "  Si le port n'est pas encore ouvert, l'acces de secours est :" "Yellow"
    Noter "     Demarrer-WMS-Tunnel.bat" "Yellow"
    Noter ""
}
Noter "  Journal de cette installation : logs\installation.log"
Noter ""
exit $prevol
