<#
    INSTALLATION COMPLETE DU WMS STRUCTA SUR UN POSTE NEUF.

    A lancer UNE FOIS sur le PC qui servira de serveur, apres avoir copie le
    dossier du projet. Double-cliquez plutot sur Installer-WMS.bat a la racine :
    il demande les droits administrateur et appelle ce script.

    Ce que le script fait, dans cet ordre :
      1. verifie Python (version, et qu'il sait creer un environnement)
      2. cree l'environnement .venv du projet
      3. installe les dependances -- hors ligne depuis paquets\ si ce dossier
         existe, depuis internet sinon
      4. prepare .env : cle secrete tiree au hasard, mode exploitation
      5. verifie PostgreSQL, cree le role applicatif, la base et les droits
      6. inscrit la base dans .env
      7. applique le schema (migrate)
      8. reprend les donnees de reprise\ s'il y en a, sinon cree un compte
         administrateur
      9. fabrique le certificat HTTPS de CE poste et installe l'autorite dans
         le magasin de confiance de Windows
     10. ouvre le port HTTPS dans le pare-feu (profils Domaine et Prive)
     11. controle de pre-vol, puis affiche l'adresse a donner aux telephones

    Rejouable : aucune etape ne detruit ce qui existe deja. Une base qui porte
    des tables n'est jamais ecrasee.

    Journal de l'installation : logs\installation.log
#>
param(
    [string]$Base = "wms",
    [string]$Utilisateur = "wms",
    [string]$Hote = "127.0.0.1",
    [string]$Port = "5432",
    [string]$PortHttps = "8443",
    [string]$Python = "",
    [switch]$SansPareFeu,
    [switch]$SansPostgreSQL,
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

# --- 1. Python ---------------------------------------------------------------
Etape "1/11" "Recherche de Python..."

. "$PSScriptRoot\Trouver-Python.ps1"
$python = Initialiser-Python -Impose $Python
if (-not $python) {
    Message-PythonIntrouvable
    Add-Content -Path $Journal -Encoding UTF8 `
        -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  Python introuvable : installation interrompue."
    exit 1
}
if ($python.Majeur -lt 3 -or ($python.Majeur -eq 3 -and $python.Mineur -lt 10)) {
    Noter ""
    Noter "  Python $($python.Version) est trop ancien : Django 5.2 exige 3.10 au minimum." "Red"
    Noter ""
    # Tout ce qu'il faut pour trancher sans revenir poser de questions : est-ce
    # un vieux Python reellement installe, ou une lecture de version ratee ?
    Noter "  Interpreteur retenu : $($python.Exe) $($python.Arguments)" "Gray"
    Noter "  Il a repondu        : [$($python.Brut -replace '\r?\n', ' / ')]" "Gray"
    Noter "  Lu comme            : majeur=$($python.Majeur) mineur=$($python.Mineur)" "Gray"
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
Noter "     Python $($python.Version) : $($python.Exe) $($python.Arguments)" "Green"

# --- 2. Environnement du projet ---------------------------------------------
Etape "2/11" "Environnement Python du projet..."
$Py = "$Projet\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    & $python.Exe @($python.Arguments) "-m" "venv" ".venv"
    if (-not (Test-Path $Py)) {
        Noter ""
        Noter "  La creation de .venv a echoue." "Red"
        Noter "  Interpreteur utilise : $($python.Exe)" "Yellow"
        Noter "  Cause la plus frequente : un Python installe 'pour moi seulement'" "Yellow"
        Noter "  alors que cette fenetre tourne sous un autre compte administrateur." "Yellow"
        Noter "  Reinstallez Python en 'Install for all users', ou passez son chemin :" "Yellow"
        Noter "     Installer-WMS.bat -Python \"C:\\chemin\\vers\\python.exe\"" "Cyan"
        exit 1
    }
    Noter "     .venv cree." "Green"
} else {
    Noter "     .venv deja present : reutilise." "Green"
}

# --- 3. Dependances ---------------------------------------------------------
Etape "3/11" "Dependances Python..."
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
        if ($attendue -and $attendue -ne $python.Version) {
            Noter ""
            Noter "  Le dossier paquets\ a ete prepare pour Python $attendue," "Red"
            Noter "  ce poste a Python $($python.Version). Les deux doivent concorder." "Red"
            Noter ""
            Noter "  Deux issues :" "Yellow"
            Noter "   - installer Python $attendue sur ce poste ; ou" "Yellow"
            Noter "   - refaire le dossier paquets\ sur un poste en Python $($python.Version)" "Yellow"
            Noter "     avec deploiement\windows\Preparer-Paquets.ps1." "Yellow"
            Noter ""
            exit 1
        }
    }
    Noter "     Installation hors ligne depuis paquets\ (aucun acces internet requis)."
    & $Py -m pip install --no-index --find-links "$Paquets" --upgrade pip --quiet 2>$null
    & $Py -m pip install --no-index --find-links "$Paquets" -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) {
        Noter ""
        Noter "  L'installation hors ligne a echoue." "Red"
        Noter "  Le dossier paquets\ est incomplet ou prepare pour un autre Python." "Yellow"
        Noter "  Refaites-le : deploiement\windows\Preparer-Paquets.ps1" "Yellow"
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
        Noter "     deploiement\windows\Preparer-Paquets.ps1" "Yellow"
        Noter "  puis recopiez-le ici et relancez." "Yellow"
        exit 1
    }
}
Noter "     Dependances installees." "Green"

# --- 4. Configuration -------------------------------------------------------
Etape "4/11" "Fichier .env (cle secrete, mode exploitation)..."
& $Py outils\preparer_env.py
if ($LASTEXITCODE -ne 0) { throw "La preparation de .env a echoue." }

# --- 5. PostgreSQL ----------------------------------------------------------
Etape "5/11" "PostgreSQL : service, role applicatif et base..."
if ($SansPostgreSQL) {
    Noter "     Saute : la base sera le fichier SQLite db.sqlite3." "Yellow"
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
$MdpSecure = Read-Host "     Mot de passe a donner au compte '$Utilisateur'" -AsSecureString
$MdpApp = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($MdpSecure))
if ([string]::IsNullOrWhiteSpace($MdpApp)) { throw "Mot de passe vide : abandon." }
$MdpAdminSecure = Read-Host "     Mot de passe du compte 'postgres'" -AsSecureString
$MdpAdmin = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($MdpAdminSecure))

Preparer-BasePostgreSQL -Base $Base -Utilisateur $Utilisateur -MotDePasse $MdpApp `
    -MotDePasseAdmin $MdpAdmin -Hote $Hote -Port $Port
$MdpAdmin = $null
Noter "     Base '$Base' prete." "Green"
}

# --- 6. Inscription dans .env -----------------------------------------------
Etape "6/11" "Inscription de la base dans .env..."
if ($SansPostgreSQL) {
    Noter "     Saute : .env reste sur SQLite." "Yellow"
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
Etape "7/11" "Application du schema (migrate)..."
& $Py manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw "Les migrations ont echoue : voir le message ci-dessus." }
Noter "     Schema a jour." "Green"

# --- 8. Donnees et compte administrateur ------------------------------------
Etape "8/11" "Donnees..."
if (Test-Path "$Projet\reprise\donnees.json") {
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
Etape "9/11" "Certificat HTTPS de ce poste..."
# Le certificat porte les adresses IP du poste : celui de l'ancien PC ne vaut
# rien ici. On le fabrique donc sur place, jamais on ne le recopie.
$certificatOk = $true
if ($Tunnel) {
    Noter "     Saute : Cloudflare fournit un certificat reconnu par les telephones." "Cyan"
    $certificatOk = $false
} else {
    & $Py outils\certificat_https.py
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
Etape "10/11" "Pare-feu : port $PortHttps en entree..."
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
}

# --- 11. Controle de pre-vol ------------------------------------------------
Etape "11/11" "Controle de pre-vol..."
& $Py outils\preparer_serveur.py
$prevol = $LASTEXITCODE

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
    Noter "  Pour demarrer le WMS :  Demarrer-WMS.bat  (toujours en HTTPS)" "Cyan"
    Noter ""
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
