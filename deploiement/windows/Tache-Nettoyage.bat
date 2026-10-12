@echo off
rem =====================================================================
rem  WMS Structa - menage des journaux, lance par la tache planifiee
rem  "WMS Structa\Nettoyage" (chaque dimanche a 03:15 par defaut).
rem
rem  Pour voir ce qui partirait, sans rien effacer :
rem      .venv\Scripts\python.exe manage.py nettoyer --simulation
rem  Le bilan : logs\nettoyage.log, et l'accueil de l'administration.
rem =====================================================================
setlocal
cd /d "%~dp0..\.."
if not exist "logs" mkdir "logs"
set "PYTHONIOENCODING=utf-8"
set "DJANGO_LOG_CONSOLE=False"

if exist "logs\taches-erreurs.log" for %%F in ("logs\taches-erreurs.log") do if %%~zF GTR 2000000 (
    move /y "logs\taches-erreurs.log" "logs\taches-erreurs.log.1" >nul
)

".venv\Scripts\python.exe" manage.py nettoyer 1>nul 2>>"logs\taches-erreurs.log"
exit /b %errorlevel%
