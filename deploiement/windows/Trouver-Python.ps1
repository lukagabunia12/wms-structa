<#
    Localise un interpreteur Python utilisable sur ce poste.

    Pourquoi ce fichier existe -- trois pieges, tous rencontres en vrai :

    1. L'installeur de python.org ne coche PAS "Add python.exe to PATH" par
       defaut. `Get-Command python` echoue alors sur un poste ou Python est
       parfaitement installe.

    2. Il propose par defaut "Install just for me", qui pose Python sous
       %LOCALAPPDATA%\Programs\Python. Or l'installation du WMS tourne en
       ADMINISTRATEUR : sur un poste du domaine, l'elevation bascule souvent
       sur un autre compte, dont le %LOCALAPPDATA% n'a pas ce Python. Le
       script cherche donc aussi dans les profils des autres utilisateurs.

    3. Windows fournit un faux `python.exe` dans WindowsApps : un raccourci qui
       ouvre le Microsoft Store. Il repond a `python --version` sans rien
       lancer, et sait creer un .venv inutilisable. On l'ecarte explicitement.

    Usage, en dot-source :
        . "$PSScriptRoot\Trouver-Python.ps1"
        $py = Initialiser-Python            # objet, ou $null
        $py = Initialiser-Python -Impose "C:\Python314\python.exe"
#>

function Combiner {
    # [System.IO.Path]::Combine est une operation de chaine pure. `Join-Path`
    # passe par le fournisseur de lecteurs de PowerShell et echoue en
    # "Cannot find drive" sur un poste sans disque D: -- benin, mais FATAL
    # sous $ErrorActionPreference = 'Stop'.
    param([string]$Gauche, [string]$Droite)
    return [System.IO.Path]::Combine($Gauche, $Droite)
}

function Est-FauxPython {
    <# Le raccourci du Microsoft Store, a ecarter. #>
    param([string]$Chemin)
    return $Chemin -like "*\WindowsApps\*"
}

function Interroger-Python {
    <#
        Demande sa version a un candidat. Rend un objet, ou $null si le
        candidat n'est pas un interpreteur Python.

        Deux precautions, apprises a la dure :

        1. La version est extraite avec [regex]::Match plutot qu'avec
           l'operateur -match et la variable automatique $Matches. $Matches
           est une variable de session : selon la version de PowerShell et ce
           qui l'a modifiee avant, elle peut ne pas contenir ce qu'on croit.
           Un poste a ainsi lu "0.0" sur un Python 3.14 parfaitement installe,
           et l'installation a refuse de continuer en "version trop ancienne".

        2. On demande d'abord sys.version_info.major / .minor -- sans
           parenthese, sans pourcentage, sans apostrophe imbriquee. Les
           chaines qui traversent cmd.exe puis PowerShell puis Python sont
           trois occasions de perdre un caractere. Si cette voie echoue, on
           retombe sur `--version`, dont la sortie est encore plus simple.
    #>
    param([string]$Exe, [string[]]$Arguments = @())
    if (Est-FauxPython $Exe) { return $null }

    # CE REGLAGE EST LE COEUR DE LA FONCTION, pas une precaution decorative.
    #
    # Installer-WMS.ps1 tourne sous $ErrorActionPreference = 'Stop'. Sous
    # Windows PowerShell 5.1, un programme externe qui ecrit sur sa sortie
    # d'erreur voit ces lignes converties en enregistrements d'erreur -- et
    # sous 'Stop', le premier d'entre eux INTERROMPT l'appel. L'interpreteur
    # etait alors ecarte comme "pas un Python", alors qu'il repondait
    # parfaitement.
    #
    # C'est ce qui expliquait le symptome deroutant : Trouver-Python.bat
    # trouvait Python (il n'impose pas 'Stop'), Installer-WMS.bat ne le
    # trouvait pas -- avec le meme code, sur la meme machine.
    $ErrorActionPreference = 'Continue'

    # 2>&1 puis filtrage, plutot que 2>$null : on garde la main sur ce qui est
    # une vraie sortie et ce qui est un message d'erreur, au lieu de confier
    # l'arbitrage a la redirection.
    $brut = ""
    try {
        $sortie = & $Exe @Arguments -c "import sys;print(sys.version_info.major);print(sys.version_info.minor)" 2>&1
        $brut = (($sortie | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }) -join " ").Trim()
    } catch { $brut = "" }

    $nombres = [regex]::Matches($brut, '\d+')
    if ($nombres.Count -lt 2) {
        # Deuxieme tentative : `python --version` -> "Python 3.14.6"
        # (les Python anciens l'ecrivaient sur la sortie d'erreur : on prend tout)
        try {
            $sortie = & $Exe @Arguments --version 2>&1
            $brut = ($sortie | ForEach-Object { "$_" }) -join " "
            $brut = $brut.Trim()
        } catch { return $null }
        $trouve = [regex]::Match($brut, 'Python\s+(\d+)\.(\d+)')
        if (-not $trouve.Success) { return $null }
        return [pscustomobject]@{
            Exe = $Exe; Arguments = $Arguments
            Majeur = [int]$trouve.Groups[1].Value
            Mineur = [int]$trouve.Groups[2].Value
            Version = $trouve.Groups[1].Value + "." + $trouve.Groups[2].Value
            Brut = $brut
        }
    }

    $majeur = [int]$nombres[0].Value
    $mineur = [int]$nombres[1].Value
    # Un interpreteur qui annonce une version 0 n'existe pas : c'est une
    # lecture ratee, pas un vieux Python. On refuse plutot que d'accuser
    # l'installation de l'utilisateur.
    if ($majeur -lt 1) { return $null }
    return [pscustomobject]@{
        Exe = $Exe; Arguments = $Arguments
        Majeur = $majeur; Mineur = $mineur
        Version = "$majeur.$mineur"
        Brut = $brut
    }
}

function Candidats-Python {
    <# Tous les emplacements plausibles, du plus sur au plus rare. #>
    $ErrorActionPreference = 'SilentlyContinue'
    $candidats = @()

    # a. Le registre : c'est la source d'autorite. HKLM pour une installation
    #    "for all users", HKCU pour "just for me" -- mais sous elevation, HKCU
    #    est la ruche de l'administrateur, d'ou les recherches suivantes.
    foreach ($ruche in @("HKLM:\SOFTWARE\Python\PythonCore",
                         "HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore",
                         "HKCU:\SOFTWARE\Python\PythonCore")) {
        foreach ($cle in (Get-ChildItem $ruche -ErrorAction SilentlyContinue)) {
            $chemin = (Get-ItemProperty "$($cle.PSPath)\InstallPath" -ErrorAction SilentlyContinue).'(default)'
            if ($chemin) { $candidats += (Combiner $chemin 'python.exe') }
        }
    }

    # b. Emplacements standards, toutes versions confondues.
    $racines = @()
    foreach ($base in @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)},
                        'C:\Program Files', 'C:\Program Files (x86)')) {
        if ($base) { $racines += (Combiner $base 'Programs\Python'); $racines += $base }
    }
    $racines += 'C:\'

    # c. Les profils des AUTRES utilisateurs : cas d'une installation
    #    "just for me" faite par la personne, puis d'une elevation qui bascule
    #    sur un compte administrateur different.
    foreach ($profil in (Get-ChildItem 'C:\Users' -Directory -ErrorAction SilentlyContinue)) {
        $racines += (Combiner $profil.FullName 'AppData\Local\Programs\Python')
    }

    foreach ($racine in ($racines | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $racine)) { continue }
        foreach ($dossier in (Get-ChildItem -LiteralPath $racine -Directory -Filter 'Python*' -ErrorAction SilentlyContinue)) {
            $candidats += (Combiner $dossier.FullName 'python.exe')
        }
    }

    return ($candidats | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique)
}

function Initialiser-Python {
    param([string]$Impose, [switch]$Detaille)
    # Meme raison que dans Interroger-Python : cette recherche ne doit jamais
    # etre interrompue par le reglage d'erreur du script appelant.
    $ErrorActionPreference = 'Continue'
    $script:JournalPython = @()

    # 0. Chemin donne a la main : c'est un choix explicite, il prime.
    if ($Impose) {
        if (-not (Test-Path -LiteralPath $Impose)) {
            Write-Host "  Le chemin donne n'existe pas : $Impose" -ForegroundColor Red
            return $null
        }
        return (Interroger-Python -Exe $Impose)
    }

    # 1. Le lanceur `py`, puis le PATH.
    foreach ($essai in @(@("py", "-3"), @("python"), @("python3"))) {
        $exe = $essai[0]
        $arguments = @()
        if ($essai.Count -gt 1) { $arguments = $essai[1..($essai.Count - 1)] }
        $commande = Get-Command $exe -ErrorAction SilentlyContinue
        if (-not $commande) { continue }
        if ($commande.Source -and (Est-FauxPython $commande.Source)) { continue }
        $trouve = Interroger-Python -Exe $exe -Arguments $arguments
        if ($trouve) { return $trouve }
        $script:JournalPython += "  PATH   $exe $arguments -> pas exploitable"
    }

    # 2. Le disque et le registre. On garde la version la plus recente qui
    #    convienne : sur un poste qui a vu passer deux installations, c'est
    #    celle qui porte les modules a jour.
    $valides = @()
    foreach ($chemin in (Candidats-Python)) {
        $trouve = Interroger-Python -Exe $chemin
        if ($trouve) {
            $valides += $trouve
            $script:JournalPython += "  disque $chemin -> Python $($trouve.Version)"
        } else {
            $script:JournalPython += "  disque $chemin -> pas exploitable"
        }
    }
    if ($valides.Count -eq 0) { return $null }
    return ($valides | Sort-Object Majeur, Mineur -Descending | Select-Object -First 1)
}

function Message-PythonIntrouvable {
    Write-Host ""
    Write-Host "  Aucun interpreteur Python utilisable sur ce poste." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Compte de cette fenetre : $env:USERNAME" -ForegroundColor Gray
    if ($script:JournalPython -and $script:JournalPython.Count -gt 0) {
        Write-Host "  Ce qui a ete essaye :" -ForegroundColor Gray
        foreach ($ligne in $script:JournalPython) { Write-Host $ligne -ForegroundColor DarkGray }
        Write-Host ""
    }
    Write-Host "  Cherche dans le PATH (py, python), dans le registre, et dans :" -ForegroundColor Gray
    Write-Host "     %LOCALAPPDATA%\Programs\Python\Python3xx\" -ForegroundColor Gray
    Write-Host "     C:\Users\<chaque compte>\AppData\Local\Programs\Python\Python3xx\" -ForegroundColor Gray
    Write-Host "     C:\Program Files\Python3xx\" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Trois causes possibles :" -ForegroundColor Yellow
    Write-Host "   1. Python n'est pas installe." -ForegroundColor Yellow
    Write-Host "      https://www.python.org/downloads/windows/" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   2. Il est installe pour VOTRE compte seulement, et cette fenetre" -ForegroundColor Yellow
    Write-Host "      tourne sous un compte administrateur different." -ForegroundColor Yellow
    Write-Host "      Reinstallez-le en choisissant 'Install for all users'," -ForegroundColor Yellow
    Write-Host "      ou indiquez son chemin (voir 3)." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   3. Il est ailleurs. Trouvez-le, puis passez le chemin :" -ForegroundColor Yellow
    Write-Host "        Installer-WMS.bat -Python ""C:\chemin\vers\python.exe""" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Pour le chercher vous-meme, dans PowerShell :" -ForegroundColor Cyan
    Write-Host "     Get-ChildItem C:\ -Recurse -Filter python.exe -ErrorAction SilentlyContinue |" -ForegroundColor Cyan
    Write-Host "       Where-Object FullName -notlike '*WindowsApps*' | Select-Object -First 10 FullName" -ForegroundColor Cyan
    Write-Host ""
}
