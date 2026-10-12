@echo off
rem =====================================================================
rem  WMS Structa - sauvegarde, lancee par la tache planifiee
rem  "WMS Structa\Sauvegarde" (12:30 et 22:30 par defaut).
rem
rem  Pour une sauvegarde a la main : Sauvegarder-WMS.bat, a la racine.
rem  Le compte rendu : logs\sauvegarde.log, et l'accueil de
rem  l'administration. Les erreurs imprevues : logs\taches-erreurs.log.
rem =====================================================================
setlocal
cd /d "%~dp0..\.."
if not exist "logs" mkdir "logs"
set "PYTHONIOENCODING=utf-8"
set "DJANGO_LOG_CONSOLE=False"

if exist "logs\taches-erreurs.log" for %%F in ("logs\taches-erreurs.log") do if %%~zF GTR 2000000 (
    move /y "logs\taches-erreurs.log" "logs\taches-erreurs.log.1" >nul
)

".venv\Scripts\python.exe" manage.py sauvegarder 1>nul 2>>"logs\taches-erreurs.log"
exit /b %errorlevel%
