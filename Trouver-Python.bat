@echo off
rem =====================================================================
rem  OU EST PYTHON SUR CE POSTE ?
rem
rem  A double-cliquer quand Installer-WMS.bat repond que Python est
rem  introuvable. Ce fichier ne modifie rien : il cherche et il affiche.
rem
rem  Il cherche au meme endroit que l'installateur : le PATH, le registre,
rem  les dossiers d'installation habituels, et les profils de TOUS les
rem  comptes du poste -- car un Python installe "pour moi seulement" est
rem  invisible depuis une fenetre administrateur ouverte sous un autre
rem  compte.
rem =====================================================================
title WMS Structa - ou est Python
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  ". '%~dp0deploiement\windows\Trouver-Python.ps1';" ^
  "Write-Host '';" ^
  "Write-Host '  Compte de cette fenetre : ' -NoNewline; Write-Host $env:USERNAME -ForegroundColor Cyan;" ^
  "Write-Host '';" ^
  "Write-Host '  --- Candidats trouves sur le disque et dans le registre ---';" ^
  "$tous = @(Candidats-Python);" ^
  "if ($tous.Count -eq 0) { Write-Host '     aucun' -ForegroundColor Yellow }" ^
  "else { foreach ($c in $tous) { $v = Interroger-Python -Exe $c;" ^
  "  if ($v) { Write-Host ('     ' + $c + '   -> Python ' + $v.Version +" ^
  "    '   [lu: ' + ($v.Brut -replace '\r?\n', ' ') + ']') -ForegroundColor Green }" ^
  "  else { Write-Host ('     ' + $c + '   -> inutilisable') -ForegroundColor DarkGray } } }" ^
  "Write-Host '';" ^
  "Write-Host '  --- Ce que retiendrait l installateur ---';" ^
  "$p = Initialiser-Python;" ^
  "if ($p) { Write-Host ('     Python ' + $p.Version + ' : ' + $p.Exe + ' ' + $p.Arguments) -ForegroundColor Green;" ^
  "  Write-Host ('     lecture brute : [' + ($p.Brut -replace '\r?\n', ' / ') + ']') -ForegroundColor Gray;" ^
  "  Write-Host ''; Write-Host '  L installation devrait fonctionner. Relancez Installer-WMS.bat.' -ForegroundColor Cyan }" ^
  "else { Message-PythonIntrouvable }"

echo.
pause
