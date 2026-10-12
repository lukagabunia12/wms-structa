<#
    Sauvegarde du WMS Structa -- ancien point d'entree, garde par compatibilite.

    La sauvegarde est maintenant faite par la commande Django
        .venv\Scripts\python.exe manage.py sauvegarder
    lancee par la tache planifiee "WMS Structa\Sauvegarde" (posee par
    Installer-WMS.bat), ou a la main par Sauvegarder-WMS.bat a la racine.

    Ce qu'elle fait de plus que l'ancien script : elle relit le fichier produit
    (chaque table de la base doit y figurer), sauvegarde aussi .env et
    certificats\, copie le tout vers une seconde destination, garde une
    sauvegarde par mois sur un an, et inscrit son resultat la ou on le voit :
    l'accueil de l'administration et le journal Application de Windows.

    Les anciens parametres restent acceptes :
        Sauvegarder.ps1 -Destination "D:\Sauvegardes\WMS" -JoursConserves 30
#>
param(
    [string]$Destination = "",
    [int]$JoursConserves = 0
)
$Projet = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $Projet
if ($JoursConserves -gt 0) { $env:WMS_SAUVEGARDE_JOURS = "$JoursConserves" }
$arguments = @("manage.py", "sauvegarder")
if ($Destination) { $arguments += @("--destination", $Destination) }
& "$Projet\.venv\Scripts\python.exe" @arguments
exit $LASTEXITCODE
