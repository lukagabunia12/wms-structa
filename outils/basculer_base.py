"""Bascule le WMS entre SQLite et PostgreSQL, dans les deux sens.

Sert à répéter le passage sur serveur **depuis son propre poste** : on installe
PostgreSQL en local, on bascule, on éprouve l'application sur les vraies données,
et on revient à SQLite si quelque chose cloche. Sans cette marche arrière, on
n'essaie pas — on subit.

    python outils/basculer_base.py etat
    python outils/basculer_base.py postgresql --mot-de-passe SECRET
    set WMS_DB_PASSWORD=SECRET & python outils/basculer_base.py postgresql
    python outils/basculer_base.py sqlite
    python outils/basculer_base.py en-service   (code 0 : base PostgreSQL en service)
    python outils/basculer_base.py sqlite-occupee  (code 0 : SQLite actif, avec des données)
    python outils/basculer_base.py wms-arrete   (code 0 : le WMS ne tourne pas ici)

Les réglages PostgreSQL ne sont jamais perdus : en repassant sur SQLite ils sont
simplement mis en commentaire dans `.env`, prêts à resservir.

`.env` est sauvegardé avant chaque écriture — c'est le fichier qui décide où
partent les écritures de l'entrepôt, il ne se modifie pas à l'aveugle.
"""
import argparse
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
ENV = RACINE / ".env"
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "outils"))

DEBUT = "# --- Base de données (géré par outils/basculer_base.py) ---"
FIN = "# --- fin base de données ---"
CLES = ["DJANGO_DB_ENGINE", "DJANGO_DB_NAME", "DJANGO_DB_USER",
        "DJANGO_DB_PASSWORD", "DJANGO_DB_HOST", "DJANGO_DB_PORT"]


def lire():
    if not ENV.is_file():
        sys.exit("`.env` est absent. Lancez d'abord : python outils/preparer_env.py")
    return ENV.read_text(encoding="utf-8")


def sauvegarder():
    """Copie datée de `.env`, en gardant les dix dernières.

    `with_suffix()` produisait « .env.env.avant-… » sur un fichier nommé `.env`
    (dont le nom est entièrement un suffixe), et deux bascules dans la même
    seconde écrasaient la même copie : le nom est donc construit à la main, avec
    les millisecondes.
    """
    copie = ENV.parent / f".env.avant-{datetime.now():%Y%m%d-%H%M%S-%f}"
    shutil.copy2(ENV, copie)
    anciennes = sorted(ENV.parent.glob(".env.avant-*"))
    for vieille in anciennes[:-10]:
        vieille.unlink(missing_ok=True)
    return copie


def reglages_connus(texte):
    """Réglages PostgreSQL présents dans `.env`, actifs ou en commentaire."""
    trouves = {}
    for cle in CLES:
        m = re.search(rf"(?m)^\s*#?\s*({re.escape(cle)})=(.*)$", texte)
        if m and m.group(2).strip():
            trouves[cle] = m.group(2).strip()
    return trouves


def sans_bloc(texte):
    """Retire le bloc géré et toute ligne DJANGO_DB_* qui traînerait ailleurs."""
    texte = re.sub(rf"{re.escape(DEBUT)}.*?{re.escape(FIN)}\n?", "", texte, flags=re.S)
    for cle in CLES:
        texte = re.sub(rf"(?m)^\s*#?\s*{re.escape(cle)}=.*\n?", "", texte)
    return texte.rstrip("\n") + "\n"


def ecrire_bloc(texte, valeurs, actif):
    diese = "" if actif else "#"
    lignes = [DEBUT,
              f"# Profil actif : {'PostgreSQL' if actif else 'SQLite (fichier db.sqlite3)'}"]
    if not actif:
        lignes.append("# Réglages PostgreSQL conservés, prêts à resservir :")
    lignes += [f"{diese}{cle}={valeurs[cle]}" for cle in CLES if cle in valeurs]
    lignes.append(FIN)
    return sans_bloc(texte) + "\n" + "\n".join(lignes) + "\n"


def profil_actif(texte):
    return "postgresql" if re.search(r"(?m)^\s*DJANGO_DB_ENGINE=.*postgresql", texte) \
        else "sqlite"


def etat(_=None):
    texte = lire()
    profil = profil_actif(texte)
    print(f"\n  Profil actif : {'PostgreSQL' if profil == 'postgresql' else 'SQLite'}")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        import django
        django.setup()
        from django.db import connection
        reglages = connection.settings_dict
        with connection.cursor() as curseur:
            curseur.execute("SELECT 1")
            curseur.fetchone()
        cible = reglages.get("NAME") if connection.vendor != "sqlite" else reglages["NAME"]
        print(f"  Moteur       : {connection.vendor}")
        print(f"  Base         : {cible}"
              + (f" sur {reglages['HOST']}:{reglages['PORT'] or 5432}"
                 if connection.vendor != "sqlite" else ""))
        # Le compte de lignes est le seul repère fiable : deux bases peuvent
        # répondre toutes les deux, une seule contient le travail du jour.
        from wms.models import Cabine, Emplacement, MouvementCabine
        print(f"  Contenu      : {Emplacement.objects.count()} emplacements · "
              f"{Cabine.objects.count()} cabines · "
              f"{MouvementCabine.objects.count()} événements au journal\n")
    except Exception as e:
        print(f"  ÉTAT        : base injoignable — {str(e).splitlines()[0]}\n")
        return 1
    return 0


def en_service(_=None):
    """Code 0 si `.env` désigne une base PostgreSQL joignable qui porte déjà le
    schéma du WMS — une base en service, donc, qu'une réinstallation ne doit
    plus toucher. Code 1 sinon (pas de .env, SQLite, base vide ou injoignable).

    C'est le contrôle qui manquait à Installer-WMS : relancé sur un serveur en
    production, il changeait le mot de passe du compte de la base, puis
    s'arrêtait sur « base non vide » avant d'écrire le nouveau dans .env — et
    le WMS perdait sa base dans la minute.
    """
    if not ENV.is_file() or profil_actif(ENV.read_text(encoding="utf-8")) != "postgresql":
        print("  Pas de base PostgreSQL inscrite dans .env.")
        return 1
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("DJANGO_LOG_CONSOLE", "False")
    try:
        import django
        django.setup()
        from django.db import connection
        tables = connection.introspection.table_names()
    except Exception as e:
        print(f"  Base inscrite dans .env, mais injoignable : {str(e).splitlines()[0]}")
        return 1
    if "django_migrations" not in tables or "wms_emplacement" not in tables:
        print("  Base inscrite dans .env, joignable, encore vide.")
        return 1
    from wms.models import Cabine, Emplacement
    print(f"  Base en service : {connection.settings_dict['NAME']} — "
          f"{Emplacement.objects.count()} emplacements, {Cabine.objects.count()} cabines.")
    return 0


def _valeur_env(texte, cle):
    m = re.search(rf"(?m)^\s*{re.escape(cle)}=(.*)$", texte)
    return m.group(1).split(" #", 1)[0].strip().strip('"').strip("'") if m else ""


def sqlite_occupee(_=None):
    """Code 0 si `.env` désigne SQLite ET que ce fichier porte des données du WMS.

    Le garde-fou de l'installation : un serveur monté avec -SansPostgreSQL, qui
    a servi quelques jours, puis réinstallé « pour de bon » sur PostgreSQL,
    repartait du dossier reprise\\ du jour de la copie — ou d'une base vierge.
    Les jours de travail restés dans db.sqlite3 disparaissaient sans un mot.
    C'est Basculer-PostgreSQL.bat qui sait les emporter.
    """
    import sqlite3
    texte = ENV.read_text(encoding="utf-8") if ENV.is_file() else ""
    if profil_actif(texte) != "sqlite":
        return 1
    fichier = Path(_valeur_env(texte, "DJANGO_DB_PATH") or os.environ.get("DJANGO_DB_PATH")
                   or RACINE / "db.sqlite3")
    if not fichier.is_file():
        return 1
    modifie = datetime.fromtimestamp(fichier.stat().st_mtime)
    try:
        base = sqlite3.connect(f"file:{fichier.as_posix()}?mode=ro", uri=True)
        try:
            tables = {n for (n,) in base.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            comptes = {t: base.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                       for t in ("wms_emplacement", "wms_cabine", "wms_stockmp")
                       if t in tables}
        finally:
            base.close()
    except sqlite3.Error as e:
        # Dans le doute, on s'arrête : un fichier illisible peut porter des
        # semaines de travail. Le renommer suffit à passer, si l'on sait.
        print(f"  {fichier} est illisible ({e}) : s'il porte des données, "
              "Basculer-PostgreSQL.bat ; sinon, renommez-le pour continuer.")
        return 0
    if sum(comptes.values()):
        print(f"  {fichier} : {comptes.get('wms_emplacement', 0)} emplacements, "
              f"{comptes.get('wms_cabine', 0)} cabines, {comptes.get('wms_stockmp', 0)} "
              f"lignes de stock MP — modifié le {modifie:%d/%m/%Y à %H:%M}.")
        return 0
    return 1


def wms_arrete(_=None):
    """Code 0 si le WMS est arrêté sur ce poste : ni le port 8443 ni le port
    8000 ne répondent, et la tâche planifiée « WMS Structa\\Service » — si elle
    existe — est désactivée (sinon elle le relancerait dans les deux minutes).

    Une bascule ou une répétition faite pendant que le WMS tourne exporte la
    base à un instant donné, et les gestes qui suivent restent dans l'ancienne :
    perdus pour la nouvelle, sans que personne le voie."""
    import socket
    import subprocess
    for port in (8443, 8000):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                print(f"  Le WMS tourne sur ce poste (le port {port} répond).")
                return 1
    if os.name == "nt":
        script = ("$t = Get-ScheduledTask -TaskPath '\\WMS Structa\\' -TaskName 'Service' "
                  "-ErrorAction SilentlyContinue; if ($t) { [string]$t.State }")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                               capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            r = None
        if r is None or r.returncode != 0:
            # Dans le doute, on s'arrête : la tâche pourrait relancer le WMS.
            print("  État de la tâche planifiée « WMS Structa\\Service » illisible : "
                  "relancez en administrateur.")
            return 1
        etat = (r.stdout or "").strip().lower()
        fichier = Path(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "Tasks",
                       "WMS Structa", "Service")
        if not etat and fichier.exists():
            # Une tâche de SYSTEM peut être invisible à une console sans les
            # droits administrateur : elle existe, on ne sait pas si elle est active.
            print("  La tâche planifiée « WMS Structa\\Service » existe, mais son état "
                  "n'est lisible qu'en administrateur : arrêtez le WMS avec "
                  "Arreter-WMS.bat, ou relancez en administrateur.")
            return 1
        if etat and etat != "disabled":
            print("  La tâche planifiée « WMS Structa\\Service » est active : elle "
                  "relancerait le WMS.")
            return 1
    return 0


def vers_postgresql(args):
    texte = lire()
    valeurs = reglages_connus(texte)
    valeurs["DJANGO_DB_ENGINE"] = "django.db.backends.postgresql"
    for cle, valeur in (("DJANGO_DB_NAME", args.base), ("DJANGO_DB_USER", args.utilisateur),
                        ("DJANGO_DB_PASSWORD", args.mot_de_passe),
                        ("DJANGO_DB_HOST", args.hote), ("DJANGO_DB_PORT", str(args.port))):
        if valeur:
            valeurs[cle] = valeur
    manquants = [c for c in ("DJANGO_DB_NAME", "DJANGO_DB_USER", "DJANGO_DB_PASSWORD")
                 if not valeurs.get(c)]
    # Un mot de passe que `.env` relirait de travers (coupé à « # », espaces
    # ôtées…) ferait échouer toutes les connexions du WMS, avec un message qui
    # accuserait PostgreSQL. On le refuse ici, avant d'écrire quoi que ce soit.
    from preparer_env import probleme_valeur
    motif = probleme_valeur(args.mot_de_passe) if args.mot_de_passe else None
    if args.mot_de_passe and not motif and not (
            args.mot_de_passe.isascii() and args.mot_de_passe.isprintable()
            and " " not in args.mot_de_passe):
        # Un accent ne voyage pas de la même façon par psql, par .env et par
        # pg_dump (qui le lit dans l'encodage de Windows) : la sauvegarde de la
        # nuit échouerait sur un mot de passe que le WMS, lui, accepte.
        motif = "contient un accent, une espace ou un caractère spécial"
    if motif:
        sys.exit(f"Ce mot de passe ne peut pas être écrit dans .env : il {motif}.\n"
                 "Choisissez-en un autre.")
    if manquants:
        sys.exit("Réglages manquants : " + ", ".join(manquants)
                 + "\nExemple : python outils/basculer_base.py postgresql "
                   "--base wms --utilisateur wms --mot-de-passe SECRET")

    try:
        import psycopg  # noqa: F401
    except ImportError:
        sys.exit("Le pilote PostgreSQL n'est pas installé.\n"
                 "  pip install -r requirements.txt")

    copie = sauvegarder()
    ENV.write_text(ecrire_bloc(texte, valeurs, actif=True), encoding="utf-8")
    print(f"\n  .env sauvegardé : {copie.name}")
    print(f"  Bascule sur PostgreSQL — base « {valeurs['DJANGO_DB_NAME']} » "
          f"sur {valeurs.get('DJANGO_DB_HOST', '127.0.0.1')}")
    print("  (le mot de passe est écrit dans .env, il n'est pas affiché ici)\n")
    print("  Suite :  python manage.py migrate")
    print("           python manage.py reprise_sql importer --depuis reprise\n")
    return 0


def vers_sqlite(_=None):
    texte = lire()
    valeurs = reglages_connus(texte)
    copie = sauvegarder()
    ENV.write_text(ecrire_bloc(texte, valeurs, actif=False), encoding="utf-8")
    print(f"\n  .env sauvegardé : {copie.name}")
    print("  Retour sur SQLite — fichier db.sqlite3, tel que vous l'aviez laissé.")
    if valeurs:
        print("  Les réglages PostgreSQL restent en commentaire dans .env.\n")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = p.add_subparsers(dest="action", required=True)
    sp.add_parser("etat", help="quelle base est active, et ce qu'elle contient")
    sp.add_parser("sqlite", help="revenir au fichier db.sqlite3")
    sp.add_parser("en-service", help="code 0 si .env désigne une base PostgreSQL en service")
    sp.add_parser("sqlite-occupee", help="code 0 si .env désigne SQLite et qu'il porte des données")
    sp.add_parser("wms-arrete", help="code 0 si le WMS est arrêté et ne peut pas repartir seul")
    pg = sp.add_parser("postgresql", help="basculer sur PostgreSQL")
    pg.add_argument("--base", default="wms")
    pg.add_argument("--utilisateur", default="wms")
    # Le mot de passe peut venir de la variable d'environnement WMS_DB_PASSWORD
    # plutôt que de la ligne de commande : les arguments d'un processus sont
    # lisibles par n'importe quel compte du poste, l'environnement d'un
    # processus ne l'est pas. L'installateur passe par la variable.
    pg.add_argument("--mot-de-passe", dest="mot_de_passe",
                    default=os.environ.get("WMS_DB_PASSWORD", ""))
    pg.add_argument("--hote", default="127.0.0.1")
    pg.add_argument("--port", default="5432")
    args = p.parse_args()
    return {"etat": etat, "sqlite": vers_sqlite, "postgresql": vers_postgresql,
            "en-service": en_service, "sqlite-occupee": sqlite_occupee,
            "wms-arrete": wms_arrete}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
