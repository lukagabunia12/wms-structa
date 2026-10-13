"""Le WMS en service sur le serveur Windows : tâches planifiées, état, arrêt.

    python outils/serveur_wms.py taches [options]   pose (ou repose) les tâches
    python outils/serveur_wms.py etat               tout l'état du serveur, en un écran
    python outils/serveur_wms.py arreter            arrête le WMS (maintenance, mise à jour)
    python outils/serveur_wms.py demarrer           le remet en service
    python outils/serveur_wms.py retirer            supprime les tâches

Les fichiers Etat-WMS.bat, Arreter-WMS.bat et Redemarrer-WMS.bat, à la
racine, appellent ce script avec les droits administrateur (Sauvegarder-WMS.bat
et Restaurer-WMS.bat, eux, appellent `manage.py sauvegarder` et `restaurer`).
Installer-WMS.bat pose les tâches à la fin de l'installation.

Trois tâches, rangées dans le dossier « WMS Structa » du Planificateur :

- Service : `deploiement\\windows\\Demarrer-serveur.bat` au démarrage de la
  machine, SANS session ouverte, puis toutes les deux minutes : s'il tourne,
  rien ne se passe ; s'il est tombé, il repart. C'est ce qui remet le WMS en
  route après une coupure de courant ou un plantage, sans personne ;
- Sauvegarde : `manage.py sauvegarder`, à 12:30 et 22:30 par défaut ;
- Nettoyage : `manage.py nettoyer`, chaque dimanche à 03:15 par défaut.

Le XML de chaque tâche est écrit en entier, parce que les réglages par défaut
du Planificateur sont des pièges pour un serveur :

- une tâche est arrêtée au bout de trois jours : le WMS se serait éteint tous
  les trois jours ;
- elle s'arrête quand la machine passe sur batterie — c'est ce que croit
  Windows quand un onduleur branché en USB prend le relais ;
- elle tourne en priorité « basse », disque compris : un WMS lent pour rien ;
- « redémarrer en cas d'échec » ne réagit pas au code de sortie d'un
  programme : d'où le déclencheur toutes les deux minutes, avec « ne pas
  lancer de nouvelle instance » tant que la précédente tourne.

Les tâches tournent sous le compte SYSTEM : aucun mot de passe à stocker, rien
qui expire. La copie des sauvegardes vers un partage réseau se fait alors sous
le compte de la machine (DOMAINE\\SERVEUR$) : c'est à lui que le partage doit
ouvrir l'écriture. Sinon, `--compte-sauvegarde` fait tourner la sauvegarde
sous un compte dédié (son mot de passe est demandé par Windows).
"""
import argparse
import datetime as dt
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "outils"))
sys.path.insert(0, str(RACINE))

DOSSIER_TACHES = "\\WMS Structa\\"
TACHE_SERVICE = DOSSIER_TACHES + "Service"
TACHE_SAUVEGARDE = DOSSIER_TACHES + "Sauvegarde"
TACHE_NETTOYAGE = DOSSIER_TACHES + "Nettoyage"
TACHES = (TACHE_SERVICE, TACHE_SAUVEGARDE, TACHE_NETTOYAGE)

import certificat_https as _C  # noqa: E402
PORT_HTTPS, PORT_APPLI = _C.port_https(), 8000
SID_SYSTEME = "S-1-5-18"
SID_ADMINISTRATEURS = "S-1-5-32-544"

#: Les réglages des tâches, gardés dans .env : sans eux, toute réinstallation
#: (une mise à jour, un -Taches pour changer une heure) remettait en silence les
#: horaires par défaut — et la sauvegarde sous SYSTEM, quand elle tournait sous
#: un compte dédié pour atteindre un NAS hors du domaine.
CLE_HEURES = "WMS_TACHE_SAUVEGARDE_HEURES"
CLE_COMPTE = "WMS_TACHE_SAUVEGARDE_COMPTE"
CLE_MENAGE_JOURS = "WMS_TACHE_NETTOYAGE_JOURS"
CLE_MENAGE_JOUR = "WMS_TACHE_NETTOYAGE_JOUR"
CLE_MENAGE_HEURE = "WMS_TACHE_NETTOYAGE_HEURE"
DEFAUTS = {CLE_HEURES: "12:30,22:30", CLE_MENAGE_JOURS: "7",
           CLE_MENAGE_JOUR: "dimanche", CLE_MENAGE_HEURE: "03:15"}

#: Ce que le Planificateur répond quand une tâche n'a pas pu tourner.
CODES_TACHE = {
    2147943726: "mot de passe du compte refusé, ou expiré",
    2147943785: "le compte n'a pas le droit « Ouvrir une session en tant que tâche »",
    2147942402: "fichier introuvable",
    2147942405: "accès refusé",
    267014: "arrêtée avant la fin",
}
JOURS = {"lundi": "Monday", "mardi": "Tuesday", "mercredi": "Wednesday",
         "jeudi": "Thursday", "vendredi": "Friday", "samedi": "Saturday",
         "dimanche": "Sunday"}
#: Programmes que `arreter` accepte de terminer : jamais un autre logiciel qui
#: aurait le malheur d'écouter sur le port 8000.
PROGRAMMES_WMS = {"python.exe", "pythonw.exe", "waitress-serve.exe"}


# --- Le XML des tâches --------------------------------------------------------
def _heure(texte):
    m = re.fullmatch(r"\s*(\d{1,2})[:hH](\d{2})\s*", texte or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"heure illisible : « {texte} » (attendu : 22:30)")
    return int(m.group(1)), int(m.group(2))


def _debut(heure, minute, maintenant=None, jour=None):
    """Le prochain instant à cette heure (et ce jour de la semaine), au format
    attendu par le Planificateur : 2026-10-12T22:30:00, heure locale."""
    maintenant = maintenant or dt.datetime.now()
    quand = maintenant.replace(hour=heure, minute=minute, second=0, microsecond=0)
    if jour is not None:
        quand += dt.timedelta(days=(jour - quand.weekday()) % 7)
    if quand <= maintenant:
        quand += dt.timedelta(days=7 if jour is not None else 1)
    return quand.strftime("%Y-%m-%dT%H:%M:%S")


def declencheurs_service(maintenant=None):
    debut = (maintenant or dt.datetime.now()).replace(second=0, microsecond=0)
    return f"""    <BootTrigger>
      <Enabled>true</Enabled>
      <Delay>PT1M</Delay>
    </BootTrigger>
    <TimeTrigger>
      <Repetition>
        <Interval>PT2M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{debut:%Y-%m-%dT%H:%M:%S}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
"""


def declencheurs_quotidiens(heures, maintenant=None):
    sortie = ""
    for texte in heures:
        h, m = _heure(texte)
        sortie += f"""    <CalendarTrigger>
      <StartBoundary>{_debut(h, m, maintenant)}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
"""
    return sortie


def declencheur_nettoyage(tous_les, jour, heure, maintenant=None):
    """Tous les N jours ; un multiple de sept devient « chaque <jour> »."""
    h, m = _heure(heure)
    if tous_les % 7 == 0:
        nom = JOURS[jour]
        indice = list(JOURS.values()).index(nom)
        return f"""    <CalendarTrigger>
      <StartBoundary>{_debut(h, m, maintenant, jour=indice)}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek>
          <{nom} />
        </DaysOfWeek>
        <WeeksInterval>{tous_les // 7}</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>
"""
    return f"""    <CalendarTrigger>
      <StartBoundary>{_debut(h, m, maintenant)}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>{tous_les}</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
"""


def principal(compte=None):
    if not compte:
        return f"""    <Principal id="Author">
      <UserId>{SID_SYSTEME}</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
"""
    return f"""    <Principal id="Author">
      <UserId>{escape(compte)}</UserId>
      <LogonType>Password</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
"""


def xml_tache(description, declencheurs, script, *, duree_max="PT0S", priorite=7,
              compte=None, interpreteur=None):
    """Le XML complet d'une tâche qui lance `script` (un .bat) par cmd.exe."""
    cmd = interpreteur or os.environ.get("ComSpec") or r"C:\Windows\System32\cmd.exe"
    # cmd /c ""chemin avec espaces.bat"" : la paire extérieure est retirée par
    # cmd, l'intérieure protège les espaces du chemin.
    arguments = f'/d /c ""{script}""'
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>WMS Structa</Author>
    <Description>{escape(description)}</Description>
  </RegistrationInfo>
  <Triggers>
{declencheurs.rstrip()}
  </Triggers>
  <Principals>
{principal(compte).rstrip()}
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>{duree_max}</ExecutionTimeLimit>
    <Priority>{priorite}</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(cmd)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(str(RACINE))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def definitions(args, maintenant=None):
    """Les tâches à poser : [(nom, xml, compte)]."""
    scripts = RACINE / "deploiement" / "windows"
    taches = []
    if not args.sans_service:
        taches.append((TACHE_SERVICE, xml_tache(
            "Démarre le WMS Structa au démarrage de la machine, sans session "
            "ouverte, et le relance s'il est tombé (vérification toutes les deux "
            "minutes).",
            declencheurs_service(maintenant), scripts / "Demarrer-serveur.bat",
            duree_max="PT0S", priorite=4), None))
    taches.append((TACHE_SAUVEGARDE, xml_tache(
        "Sauvegarde la base du WMS Structa (pg_dump vérifié) et sa configuration, "
        "avec rotation. Résultat : logs\\sauvegarde.log et l'accueil de "
        "l'administration.",
        declencheurs_quotidiens(args.heures, maintenant),
        scripts / "Tache-Sauvegarde.bat", duree_max="PT2H",
        compte=args.compte_sauvegarde), args.compte_sauvegarde))
    taches.append((TACHE_NETTOYAGE, xml_tache(
        "Efface les journaux trop anciens (PostgreSQL, sessions expirées ; âge "
        "réglé par WMS_JOURNAUX_JOURS dans .env) et mesure ce qu'ils pèsent. "
        "Bilan : logs\\nettoyage.log.",
        declencheur_nettoyage(args.nettoyage_tous_les, args.nettoyage_jour,
                              args.heure_nettoyage, maintenant),
        scripts / "Tache-Nettoyage.bat", duree_max="PT1H"), None))
    return taches


# --- Windows --------------------------------------------------------------------
def _executer(commande, timeout=120):
    return subprocess.run(commande, capture_output=True, text=True,
                          timeout=timeout, errors="replace")


def administrateur():
    if os.name != "nt":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def exiger_windows_administrateur():
    if os.name != "nt":
        sys.exit("Ce script pilote le Planificateur de tâches de Windows : il ne "
                 "sert que sur le serveur Windows.")
    if not administrateur():
        sys.exit("Droits administrateur nécessaires. Passez par Installer-WMS.bat, "
                 "Etat-WMS.bat, Arreter-WMS.bat ou Redemarrer-WMS.bat, qui les "
                 "demandent, ou ouvrez l'invite de commandes « en tant "
                 "qu'administrateur ».")


def poser(nom, xml, compte=None):
    """Inscrit (ou remplace) une tâche. Rend True si Windows l'a acceptée."""
    with tempfile.TemporaryDirectory() as dossier:
        fichier = Path(dossier) / "tache.xml"
        # UTF-16 avec BOM : le seul encodage que schtasks lit sans broncher,
        # celui des tâches qu'il exporte lui-même.
        fichier.write_text(xml, encoding="utf-16")
        commande = ["schtasks", "/Create", "/TN", nom, "/XML", str(fichier), "/F"]
        if compte:
            # « /RP * » : Windows demande lui-même le mot de passe, qui ne passe
            # ni par ce script, ni par la ligne de commande.
            commande += ["/RU", compte, "/RP", "*"]
            print(f"    Windows demande maintenant le mot de passe de {compte}, "
                  "compte de la sauvegarde :")
            try:
                r = subprocess.run(commande, timeout=900)
            except subprocess.TimeoutExpired:
                print("    Pas de mot de passe saisi en 15 minutes : tâche non reposée.")
                return False
            return r.returncode == 0
        r = _executer(commande)
    if r.returncode != 0:
        print(f"    {(r.stderr or r.stdout).strip()}")
    return r.returncode == 0


def normaliser_compte(compte):
    """Le compte sous lequel tourne la sauvegarde, ou None pour SYSTEM.

    « .\\nom » (un compte local) devient « POSTE\\nom » : icacls ne résout pas
    toujours le point."""
    compte = (compte or "").strip()
    if compte.upper().replace("È", "E") in ("", "SYSTEM", "SYSTEME", "NT AUTHORITY\\SYSTEM",
                                             "AUTORITE NT\\SYSTEME"):
        return None
    if compte.startswith(".\\"):
        compte = (os.environ.get("COMPUTERNAME") or socket.gethostname()) + compte[1:]
    return compte


def valeur_env(cle):
    import certificat_https as C
    return C.valeur_env(cle, "")


def dossier_des_sauvegardes():
    """Le même calcul que `wms.exploitation.dossier_sauvegardes`, sans Django."""
    reglage = valeur_env("WMS_SAUVEGARDE_DOSSIER").strip()
    return Path(reglage) if reglage else RACINE.parent / "WMS-Sauvegardes"


def ouvrir_au_compte(compte):
    """Donne au compte dédié à la sauvegarde l'accès dont il a besoin.

    Installer-WMS réserve le dossier du projet aux administrateurs et à SYSTEM ;
    la première sauvegarde, faite sous SYSTEM, réserve de même le dossier des
    sauvegardes. Un compte dédié, s'il n'est pas administrateur, n'y lirait ni
    Python ni `.env`, et n'écrirait pas ses sauvegardes : elles échoueraient
    chaque nuit avec « accès refusé ». Il reçoit la lecture du projet,
    l'écriture de `logs\\` et du dossier des sauvegardes — rien de plus. Rend
    la liste des échecs."""
    echecs = []
    (RACINE / "logs").mkdir(exist_ok=True)
    commandes = [["icacls", str(RACINE), "/grant", f"{compte}:(OI)(CI)RX", "/Q"],
                 ["icacls", str(RACINE / "logs"), "/grant", f"{compte}:(OI)(CI)M", "/Q"]]
    sauvegardes = dossier_des_sauvegardes()
    if not str(sauvegardes).startswith("\\\\"):   # un partage : ses droits sont ceux du NAS
        if sauvegardes.exists():
            commandes.append(["icacls", str(sauvegardes), "/grant",
                              f"{compte}:(OI)(CI)M", "/Q"])
        else:
            # Créé ici : réservé d'emblée, comme le ferait la première sauvegarde.
            try:
                sauvegardes.mkdir(parents=True)
            except OSError as e:
                echecs.append(f"{sauvegardes} : {e}")
            else:
                commandes.append(["icacls", str(sauvegardes), "/inheritance:r", "/grant:r",
                                  f"*{SID_ADMINISTRATEURS}:(OI)(CI)F",
                                  f"*{SID_SYSTEME}:(OI)(CI)F", f"{compte}:(OI)(CI)F", "/Q"])
    for commande in commandes:
        r = _executer(commande)
        if r.returncode != 0:
            echecs.append(f"{commande[1]} : {(r.stderr or r.stdout).strip()}")
    return echecs


def reglages_taches(args):
    """Complète `args` : l'option si elle est donnée, sinon le réglage de la
    fois précédente (dans .env), sinon la valeur par défaut."""
    def lu(cle):
        return valeur_env(cle).strip() or DEFAUTS.get(cle, "")
    if args.heures is None:
        args.heures = [h.strip() for h in lu(CLE_HEURES).split(",") if h.strip()]
    if args.nettoyage_tous_les is None:
        try:
            args.nettoyage_tous_les = int(lu(CLE_MENAGE_JOURS))
        except ValueError:
            args.nettoyage_tous_les = int(DEFAUTS[CLE_MENAGE_JOURS])
    if args.nettoyage_jour is None:
        jour = lu(CLE_MENAGE_JOUR).lower()
        args.nettoyage_jour = jour if jour in JOURS else DEFAUTS[CLE_MENAGE_JOUR]
    if args.heure_nettoyage is None:
        args.heure_nettoyage = lu(CLE_MENAGE_HEURE)
    if args.compte_sauvegarde is None:
        args.compte_sauvegarde = valeur_env(CLE_COMPTE).strip() or None
    args.compte_sauvegarde = normaliser_compte(args.compte_sauvegarde)
    return args


def infos_taches():
    """{nom: {etat, dernier, resultat, prochain}} depuis le Planificateur.

    Par PowerShell et en JSON : la sortie de `schtasks /Query` est traduite
    dans la langue de Windows, et ses colonnes changent de nom d'une version à
    l'autre."""
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "Get-ScheduledTask -TaskPath '\\WMS Structa\\' | ForEach-Object {"
        " $i = $_ | Get-ScheduledTaskInfo;"
        " [pscustomobject]@{ Nom = $_.TaskPath + $_.TaskName; Etat = [string]$_.State;"
        " Dernier = $(if ($i.LastRunTime) { $i.LastRunTime.ToString('s') } else { '' });"
        " Resultat = $i.LastTaskResult;"
        " Prochain = $(if ($i.NextRunTime) { $i.NextRunTime.ToString('s') } else { '' }) }"
        "} | ConvertTo-Json -Compress")
    try:
        r = _executer(["powershell", "-NoProfile", "-Command", script], timeout=60)
        donnees = json.loads(r.stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    if isinstance(donnees, dict):
        donnees = [donnees]
    return {d.get("Nom"): d for d in donnees if isinstance(d, dict)}


def port_ouvert(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def sante(port=PORT_HTTPS, delai=10):
    """(code, réponse) de /api/sante/, en vérifiant le certificat si possible."""
    url = f"https://127.0.0.1:{port}/api/sante/"
    autorite = RACINE / "certificats" / "ac-structa.crt"
    contextes = []
    if autorite.is_file():
        contextes.append(("vérifié", ssl.create_default_context(cafile=str(autorite))))
    contextes.append(("non vérifié", ssl._create_unverified_context()))
    derniere = None
    for libelle, contexte in contextes:
        try:
            with urllib.request.urlopen(url, timeout=delai, context=contexte) as r:
                return r.status, r.read().decode("utf-8", "replace"), libelle
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), libelle
        except (urllib.error.URLError, OSError, ssl.SSLError) as e:
            derniere = e
            continue
    return None, str(getattr(derniere, "reason", derniere)), ""


def processus_a_l_ecoute(port):
    """PID des programmes qui écoutent sur ce port de la machine.

    `netstat -ano` est lu par l'adresse distante (0.0.0.0:0 ou [::]:0), pas par
    le mot « LISTENING » : ce mot est traduit selon la langue de Windows."""
    try:
        r = _executer(["netstat", "-ano", "-p", "TCP"], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return set()
    pids = set()
    for ligne in r.stdout.splitlines():
        champs = ligne.split()
        if len(champs) >= 5 and champs[0].upper() == "TCP" \
                and champs[1].endswith(f":{port}") \
                and champs[2] in ("0.0.0.0:0", "[::]:0", "*:*") \
                and champs[-1].isdigit():
            pids.add(int(champs[-1]))
    return pids


def nom_programme(pid):
    try:
        r = _executer(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.match(r'"([^"]+)"', r.stdout.strip())
    return m.group(1).lower() if m else ""


def fin_du_journal(nom="service.log", lignes=12):
    chemin = RACINE / "logs" / nom
    try:
        texte = chemin.read_text(encoding="utf-8", errors="replace")
    except OSError:
        try:
            texte = chemin.read_text(encoding="cp1252", errors="replace")
        except OSError:
            return []
    return [x for x in texte.splitlines() if x.strip()][-lignes:]


# --- Les actions -------------------------------------------------------------
def action_taches(args):
    exiger_windows_administrateur()
    import preparer_env
    if args.sauvegardes or args.copie is not None:
        reglages = {}
        if args.sauvegardes:
            reglages["WMS_SAUVEGARDE_DOSSIER"] = args.sauvegardes
        if args.copie is not None:
            reglages["WMS_SAUVEGARDE_COPIE"] = args.copie
        if args.jours_journaux:
            reglages["WMS_JOURNAUX_JOURS"] = str(args.jours_journaux)
        erreurs = preparer_env.poser_reglages(reglages)
        if erreurs:
            sys.exit("\n".join(erreurs))
    elif args.jours_journaux:
        erreurs = preparer_env.poser_reglages({"WMS_JOURNAUX_JOURS": str(args.jours_journaux)})
        if erreurs:
            sys.exit("\n".join(erreurs))

    print("\n  Tâches planifiées du WMS (dossier « WMS Structa » du Planificateur) :")
    echecs = 0
    for nom, xml, compte in definitions(args):
        ok = poser(nom, xml, compte)
        echecs += 0 if ok else 1
        print(f"    {'OK   ' if ok else 'ÉCHEC'} {nom}")
    if echecs:
        print("\n  Une tâche au moins n'a pas été posée : voir le message ci-dessus.")
        return 1
    # Retenus AVANT d'ouvrir les droits du compte : les tâches sont déjà posées
    # sous lui, et si l'ouverture échouait, la fois suivante reviendrait sinon
    # en silence à SYSTEM.
    erreurs = preparer_env.poser_reglages({
        CLE_HEURES: ",".join(args.heures),
        CLE_MENAGE_JOURS: str(args.nettoyage_tous_les),
        CLE_MENAGE_JOUR: args.nettoyage_jour,
        CLE_MENAGE_HEURE: args.heure_nettoyage,
        CLE_COMPTE: args.compte_sauvegarde or "",   # vide : la ligne part, retour à SYSTEM
    })
    for ligne in erreurs:
        print(f"    (réglage non retenu dans .env : {ligne})")
    if args.compte_sauvegarde:
        refus = ouvrir_au_compte(args.compte_sauvegarde)
        for ligne in refus:
            print(f"    Accès NON donné à {args.compte_sauvegarde} — {ligne}")
        if refus:
            return 1
        print(f"    Accès au projet (lecture), à logs\\ et aux sauvegardes (écriture) "
              f"donné à {args.compte_sauvegarde}.")
    print(f"\n  Sauvegardes : chaque jour à {', '.join(args.heures)}"
          + (f", sous le compte {args.compte_sauvegarde}." if args.compte_sauvegarde
             else ", sous le compte SYSTEM."))
    print("  Ménage des journaux : "
          + (f"chaque {args.nettoyage_jour}" if args.nettoyage_tous_les == 7 else
             f"tous les {args.nettoyage_tous_les} jours")
          + f" à {args.heure_nettoyage}.")
    if not args.sans_service:
        print("  Service : au démarrage de Windows, puis vérifié toutes les deux minutes.")
    if args.essayer:
        return essayer_sauvegarde()
    return 0


def essayer_sauvegarde(attente_max=900):
    """Lance la tâche de sauvegarde MAINTENANT, sous son vrai compte, et attend
    son résultat : c'est le seul essai qui prouve que la nuit se passera bien
    (droits sur le dossier, accès au partage réseau, pg_dump trouvé).

    Une tâche qui ne démarre même pas — mot de passe refusé, droit d'ouvrir une
    session manquant — n'écrit aucun résultat : le Planificateur est donc
    interrogé aussi, pour le dire tout de suite au lieu d'attendre un quart
    d'heure."""
    etat_fichier = RACINE / "logs" / "sauvegarde-etat.json"
    avant = etat_fichier.stat().st_mtime if etat_fichier.is_file() else 0
    precedent = infos_taches().get(TACHE_SAUVEGARDE) or {}
    print("\n  Première sauvegarde, lancée par la tâche planifiée elle-même…")
    r = _executer(["schtasks", "/Run", "/TN", TACHE_SAUVEGARDE])
    if r.returncode != 0:
        print(f"    Lancement refusé : {(r.stderr or r.stdout).strip()}")
        return 1
    def resultat_ecrit():
        """Le résultat écrit par la sauvegarde, ou None s'il n'y en a pas encore."""
        if not (etat_fichier.is_file() and etat_fichier.stat().st_mtime > avant):
            return None
        time.sleep(1)
        try:
            return json.loads(etat_fichier.read_text(encoding="utf-8"))
        except ValueError:
            return None

    def dire(etat):
        if etat.get("statut") == "ok":
            print(f"    OK — {etat.get('fichier')} dans {etat.get('destination')}"
                  + (f", copie dans {etat.get('copie')}" if etat.get("copie_ok") else ""))
            return 0
        print(f"    ÉCHEC — {etat.get('message') or etat.get('message_copie')}")
        print("    Détail : logs\\sauvegarde.log et logs\\taches-erreurs.log")
        return 1

    debut = time.monotonic()
    prochaine_question = debut + 10
    while time.monotonic() - debut < attente_max:
        time.sleep(3)
        etat = resultat_ecrit()
        if etat:
            return dire(etat)
        if time.monotonic() >= prochaine_question:
            prochaine_question = time.monotonic() + 10
            echec = tache_finie_sans_resultat(infos_taches().get(TACHE_SAUVEGARDE), precedent)
            if echec:
                # La tâche a pu finir PENDANT la question au Planificateur : son
                # résultat, s'il est arrivé entre-temps, l'emporte sur le code.
                time.sleep(2)
                etat = resultat_ecrit()
                if etat:
                    return dire(etat)
                print(f"    ÉCHEC — la tâche s'est arrêtée sans écrire de résultat : {echec}.")
                print("    Détail : logs\\taches-erreurs.log, et dans le Planificateur, "
                      "l'onglet Historique de la tâche.")
                return 1
    print("    Pas de résultat après 15 minutes : voir logs\\sauvegarde.log.")
    return 1


def tache_finie_sans_resultat(info, precedent):
    """La raison, si la tâche a fini (ou n'a pas pu démarrer) depuis le
    lancement ; None tant qu'elle tourne ou qu'on ne sait rien."""
    if not info:
        return None
    resultat = info.get("Resultat")
    nouveau = (info.get("Dernier") != (precedent or {}).get("Dernier")
               or resultat != (precedent or {}).get("Resultat"))
    if not nouveau or (info.get("Etat") or "").lower() == "running" or resultat in (267009, 267011):
        return None
    if resultat == 0:
        return "elle a fini sans erreur, mais sans écrire son état (logs\\ inaccessible ?)"
    return CODES_TACHE.get(resultat, f"code {resultat}")


def action_etat(_args):
    print(f"\n  WMS Structa — état du serveur {socket.gethostname()}\n")
    if os.name == "nt":
        infos = infos_taches()
        for nom in TACHES:
            i = infos.get(nom)
            if not i:
                print(f"  {nom:28} ABSENTE")
                continue
            resultat = i.get("Resultat")
            libelle = {0: "OK", 267009: "en cours", 267011: "jamais lancée",
                       267014: "arrêtée"}.get(resultat, f"code {resultat}")
            print(f"  {nom:28} {i.get('Etat', '?'):9} dernier passage "
                  f"{(i.get('Dernier') or '—').replace('T', ' ')} ({libelle}), "
                  f"prochain {(i.get('Prochain') or '—').replace('T', ' ')}")
    print()
    print(f"  Port {PORT_HTTPS} (téléphones) : {'à l’écoute' if port_ouvert(PORT_HTTPS) else 'FERMÉ'}")
    print(f"  Port {PORT_APPLI} (application) : {'à l’écoute' if port_ouvert(PORT_APPLI) else 'FERMÉ'}")
    code, reponse, verification = sante()
    if code == 200:
        print(f"  Santé : OK (certificat {verification}) — {reponse.strip()}")
    else:
        print(f"  Santé : {'injoignable' if code is None else code} — {reponse.strip()[:200]}")

    try:
        import certificat_https as C
        x509 = C._crypto()[0]
        srv = x509.load_pem_x509_certificate(C.SRV_CERT.read_bytes())
        reste = (srv.not_valid_after_utc - dt.datetime.now(dt.timezone.utc)).days
        manquants = C.non_couverts() or []
        print(f"  Certificat : valable encore {reste} jour(s)"
              + (f" — NE COUVRE PAS {', '.join(manquants)}" if manquants else ""))
    except Exception:
        print("  Certificat : absent ou illisible.")

    try:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        os.environ.setdefault("DJANGO_LOG_CONSOLE", "False")
        import django
        django.setup()
        from wms import exploitation
        etat = exploitation.etat_sauvegarde()
        print(f"\n  Sauvegardes [{etat['niveau'].upper()}] : {etat['phrase']}")
        for ligne in etat["details"]:
            print(f"    {ligne}")
    except Exception as e:
        print(f"\n  Sauvegardes : état illisible ({str(e).splitlines()[0] if str(e) else e})")

    if code != 200:
        lignes = fin_du_journal()
        if lignes:
            print("\n  Fin de logs\\service.log :")
            for ligne in lignes:
                print(f"    {ligne}")
    print()
    return 0 if code == 200 else 1


def action_arreter(_args):
    exiger_windows_administrateur()
    print("\n  Arrêt du WMS…")
    # D'abord désactiver : sinon la vérification des deux minutes le relance.
    _executer(["schtasks", "/Change", "/TN", TACHE_SERVICE, "/DISABLE"])
    _executer(["schtasks", "/End", "/TN", TACHE_SERVICE])
    # Le Planificateur n'arrête que cmd.exe : le lanceur et le serveur
    # d'application, qu'il a lancés, continueraient de tourner sans lui.
    tues = []
    for port in (PORT_HTTPS, PORT_APPLI):
        for pid in processus_a_l_ecoute(port):
            programme = nom_programme(pid)
            if programme not in PROGRAMMES_WMS:
                print(f"    Port {port} tenu par {programme or pid} : pas un programme "
                      "du WMS, laissé tel quel.")
                continue
            _executer(["taskkill", "/PID", str(pid), "/T", "/F"])
            tues.append(f"{programme} ({pid})")
    for _ in range(20):
        if not (port_ouvert(PORT_HTTPS) or port_ouvert(PORT_APPLI)):
            break
        time.sleep(0.5)
    if port_ouvert(PORT_HTTPS):
        print(f"    Le port {PORT_HTTPS} répond encore : arrêt incomplet. Voir le Gestionnaire "
              "des tâches (python.exe).")
        return 1
    print("    Arrêté" + (f" ({', '.join(tues)})." if tues else " (il ne tournait pas)."))
    print("    Il ne repartira pas tout seul, même au redémarrage de Windows, tant que")
    print("    Redemarrer-WMS.bat n'aura pas été lancé.\n")
    return 0


def action_demarrer(args):
    exiger_windows_administrateur()
    print("\n  Démarrage du WMS…")
    r = _executer(["schtasks", "/Change", "/TN", TACHE_SERVICE, "/ENABLE"])
    if r.returncode != 0:
        print("    La tâche « WMS Structa\\Service » est absente : relancez "
              "Installer-WMS.bat -Taches.")
        return 1
    if not port_ouvert(PORT_HTTPS):
        _executer(["schtasks", "/Run", "/TN", TACHE_SERVICE])
    debut = time.monotonic()
    while time.monotonic() - debut < args.attente:
        code, reponse, _ = sante(delai=5)
        if code == 200:
            print(f"    En service : https://{socket.gethostname()}:{PORT_HTTPS}/ "
                  f"— {reponse.strip()}\n")
            return 0
        time.sleep(3)
    print(f"    Pas de réponse après {args.attente} secondes. Fin de logs\\service.log :")
    for ligne in fin_du_journal():
        print(f"      {ligne}")
    print()
    return 1


def action_retirer(_args):
    exiger_windows_administrateur()
    action_arreter(_args)
    for nom in TACHES:
        r = _executer(["schtasks", "/Delete", "/TN", nom, "/F"])
        print(f"    {'retirée' if r.returncode == 0 else 'absente '} {nom}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = p.add_subparsers(dest="action", required=True)

    t = sp.add_parser("taches", help="pose ou repose les tâches planifiées")
    # Sans option, chaque réglage reprend celui de la fois précédente (gardé
    # dans .env), sinon la valeur par défaut — voir `reglages_taches`.
    t.add_argument("--heures", default=None,
                   type=lambda x: [h.strip() for h in x.split(",") if h.strip()],
                   help="heures des sauvegardes, séparées par des virgules (défaut : 12:30,22:30)")
    t.add_argument("--nettoyage-tous-les", type=int, default=None, metavar="JOURS",
                   help="fréquence du ménage, en jours (défaut : 7, chaque semaine)")
    t.add_argument("--nettoyage-jour", default=None, choices=list(JOURS),
                   help="jour du ménage quand la fréquence est un multiple de 7 (défaut : dimanche)")
    t.add_argument("--heure-nettoyage", default=None, help="défaut : 03:15")
    t.add_argument("--jours-journaux", type=int, default=0,
                   help="âge des journaux effacés (écrit dans .env : WMS_JOURNAUX_JOURS)")
    t.add_argument("--sauvegardes", default="",
                   help="dossier des sauvegardes (écrit dans .env : WMS_SAUVEGARDE_DOSSIER)")
    t.add_argument("--copie", default=None,
                   help="seconde destination, hors de la machine (WMS_SAUVEGARDE_COPIE ; "
                        "chaîne vide pour la retirer)")
    t.add_argument("--compte-sauvegarde", default=None,
                   help="compte sous lequel tourne la sauvegarde (défaut : celui de la fois "
                        "précédente, sinon SYSTEM ; « SYSTEM » pour y revenir)")
    t.add_argument("--sans-service", action="store_true",
                   help="sauvegarde et ménage seulement (poste de travail)")
    t.add_argument("--essayer", action="store_true",
                   help="lance tout de suite une sauvegarde par la tâche, et attend son résultat")

    sp.add_parser("etat", help="l'état du serveur en un écran")
    sp.add_parser("arreter", help="arrête le WMS (il ne repart plus tout seul)")
    d = sp.add_parser("demarrer", help="remet le WMS en service")
    d.add_argument("--attente", type=int, default=120)
    sp.add_parser("retirer", help="supprime les tâches planifiées")

    args = p.parse_args(argv)
    if args.action == "taches":
        reglages_taches(args)
        if args.nettoyage_tous_les < 1:
            p.error("--nettoyage-tous-les : au moins 1 jour")
        try:
            for heure in args.heures + [args.heure_nettoyage]:
                _heure(heure)
        except ValueError as e:
            p.error(str(e))
    return {"taches": action_taches, "etat": action_etat, "arreter": action_arreter,
            "demarrer": action_demarrer, "retirer": action_retirer}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
