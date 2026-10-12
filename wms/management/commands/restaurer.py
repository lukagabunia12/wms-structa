"""Restaure la base du WMS depuis une sauvegarde de `manage.py sauvegarder`.

    python manage.py restaurer                      # les sauvegardes disponibles
    python manage.py restaurer 2026-10-12_223000    # restaure ce jeu
    python manage.py restaurer D:\\...\\wms_2026-10-12_223000.dump

Ou, sur le serveur, `Restaurer-WMS.bat`, qui pose les mêmes questions.

Dans l'ordre :

1. refus si le WMS tourne, ou si la tâche planifiée peut le relancer : une
   restauration sous les pieds des caristes mélangerait leurs gestes du jour à
   une base qui recule dans le temps (Arreter-WMS.bat d'abord) ;
2. le fichier est relu : il doit contenir les tables du WMS ;
3. LE FILET : la base actuelle est sauvegardée d'abord. Une restauration
   choisie par erreur se défait avec cette même commande ;
4. confirmation : taper RESTAURER ;
5. PostgreSQL : le schéma est vidé puis rechargé en UNE transaction. Le COMMIT
   n'est écrit qu'une fois le fichier entièrement relu : un fichier abîmé, une
   erreur, une fenêtre fermée en plein milieu, et la base reste telle qu'elle
   était. SQLite : copie par l'API de sauvegarde de SQLite.

Le compte de la base, celui de `.env`, suffit : il possède la base et son
schéma (Installer-WMS). Les tables qu'une version plus récente aurait ajoutées
partent avec le schéma — sinon le démarrage suivant, qui rejoue les migrations,
buterait sur une table « déjà existante ».

Le zip de configuration (`.env`, `certificats\\`) n'est PAS restauré ici :
remettre un ancien `.env` changerait le mot de passe de la base sous les pieds
du WMS. Voir docs/guide-serveur.md, « Restaurer sur une machine neuve ».
"""
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from wms import exploitation as X

#: Les tables sans lesquelles un fichier n'est pas une sauvegarde du WMS.
TABLES_INDISPENSABLES = ("django_migrations", "wms_cabine", "wms_emplacement")
MOT_DE_CONFIRMATION = "RESTAURER"
DELAI_RESTAURATION = 3600


class Command(BaseCommand):
    help = ("Restaure la base depuis une sauvegarde (sans argument : la liste). "
            "Le WMS doit être arrêté ; la base actuelle est sauvegardée d'abord.")

    def add_arguments(self, parser):
        parser.add_argument("jeu", nargs="?",
                            help="horodatage du jeu (2026-10-12_223000) ou chemin du fichier")
        parser.add_argument("--dossier", help="où chercher (défaut : WMS_SAUVEGARDE_DOSSIER "
                                              "et WMS_SAUVEGARDE_COPIE)")
        parser.add_argument("--oui", action="store_true",
                            help="sans demander de confirmation")
        parser.add_argument("--sans-filet", action="store_true",
                            help="ne pas sauvegarder la base actuelle avant (base illisible)")

    # ------------------------------------------------------------------------
    def handle(self, *args, **options):
        try:
            self.restaurer(options)
        except X.ErreurExploitation as e:   # pg_restore ou psql introuvable
            raise CommandError(str(e)) from None

    def restaurer(self, options):
        dossiers =([Path(options["dossier"])] if options["dossier"] else
                    [d for d in (X.dossier_sauvegardes(), X.dossier_copie()) if d])
        moteur = settings.DATABASES["default"]["ENGINE"]
        postgres = moteur.endswith("postgresql")
        if not postgres and not moteur.endswith("sqlite3"):
            raise CommandError(f"Moteur de base non pris en charge : {moteur}")
        extension = ".dump" if postgres else ".sqlite3"

        if not options["jeu"]:
            self.lister(dossiers, extension)
            return

        fichier = self.trouver(options["jeu"], dossiers, extension)
        self.verifier_arret()
        tables = self.relire_dump(fichier) if postgres else self.relire_sqlite(fichier)
        self.stdout.write(f"\n  Fichier : {fichier}\n  Relu : {tables} tables, dont "
                          f"{', '.join(TABLES_INDISPENSABLES)}.")

        filet = None
        if not options["sans_filet"]:
            filet = self.filet()

        if not options["oui"]:
            self.stdout.write(self.style.WARNING(
                "\n  La base actuelle va être REMPLACÉE par celle de ce fichier : tout ce qui "
                "a été fait depuis\n  cette sauvegarde disparaît du WMS"
                + (f" (le filet le garde : {filet})." if filet else ".")))
            try:
                reponse = input(f"\n  Pour confirmer, tapez {MOT_DE_CONFIRMATION} : ").strip()
            except EOFError:
                raise CommandError("Personne pour confirmer (lancement sans console) : "
                                   "rien n'a été modifié. Ajoutez --oui.") from None
            if reponse != MOT_DE_CONFIRMATION:
                raise CommandError("Restauration abandonnée : rien n'a été modifié.")

        connections.close_all()
        try:
            if postgres:
                bilan = self.restaurer_postgresql(fichier)
            else:
                bilan = self.restaurer_sqlite(fichier)
        except (CommandError, OSError, sqlite3.Error) as e:
            # Un échec à ce stade s'écrit lui aussi : le lendemain, c'est la
            # seule trace qu'une restauration a été tentée.
            texte = f"Restauration depuis {fichier.name} en échec : {e}"
            X.journal("sauvegarde").error(texte)
            logging.getLogger("wms").error(texte)
            X.evenement_windows(True, texte, base=X.EVENEMENT_RESTAURATION)
            if isinstance(e, CommandError):
                raise
            raise CommandError(texte) from None

        texte = (f"Base restaurée depuis {fichier.name} ({bilan})"
                 + (f" ; base d'avant gardée dans {filet}" if filet else "") + ".")
        X.journal("sauvegarde").warning(texte)
        logging.getLogger("wms").warning(texte)
        X.evenement_windows(False, texte, base=X.EVENEMENT_RESTAURATION)
        self.stdout.write(self.style.SUCCESS(f"\n  {texte}"))
        self.stdout.write("\n  Remettez le WMS en service : Redemarrer-WMS.bat (les "
                          "migrations éventuelles\n  s'appliquent au démarrage).\n")

    # --- Choisir -------------------------------------------------------------
    def lister(self, dossiers, extension):
        trouves = self.jeux(dossiers, extension)
        if not trouves:
            lieux = ", ".join(str(d) for d in dossiers) or "aucun dossier réglé"
            self.stdout.write(f"\n  Aucune sauvegarde trouvée ({lieux}).\n")
            return
        self.stdout.write("\n  Sauvegardes disponibles, de la plus récente à la plus ancienne :\n")
        for quand, fichier in trouves[:40]:
            self.stdout.write(f"    {quand:%Y-%m-%d_%H%M%S}   {quand:%d/%m/%Y à %H:%M}   "
                              f"{X.lisible(fichier.stat().st_size):>9}   {fichier.parent}")
        if len(trouves) > 40:
            self.stdout.write(f"    … et {len(trouves) - 40} plus anciennes.")
        self.stdout.write("\n  Pour restaurer : la première colonne, par exemple\n"
                          f"      Restaurer-WMS.bat   puis   {trouves[0][0]:%Y-%m-%d_%H%M%S}\n")

    @staticmethod
    def jeux(dossiers, extension):
        """[(date, fichier de base)], du plus récent au plus ancien, sans doublon
        entre la destination et sa copie (la première trouvée l'emporte)."""
        vus = {}
        for dossier in dossiers:
            for quand, fichiers in X.jeux(dossier).items():
                for f in fichiers:
                    if f.name.endswith(extension) and quand not in vus:
                        vus[quand] = f
        return sorted(vus.items(), reverse=True)

    def trouver(self, demande, dossiers, extension):
        chemin = Path(demande.strip().strip('"'))
        if chemin.is_file():
            if not chemin.name.endswith(extension):
                raise CommandError(
                    f"{chemin.name} n'est pas une sauvegarde de cette base (attendu : "
                    f"un fichier {extension}).")
            return chemin
        chiffres = re.sub(r"\D", "", demande)
        if len(chiffres) < 8:
            raise CommandError(f"« {demande} » : ni un fichier, ni un horodatage "
                               "(attendu : 2026-10-12_223000).")
        candidats = [(q, f) for q, f in self.jeux(dossiers, extension)
                     if f"{q:%Y%m%d%H%M%S}".startswith(chiffres)]
        if not candidats:
            raise CommandError(f"Aucune sauvegarde ne correspond à « {demande} ». "
                               "La liste : sans argument.")
        if len(candidats) > 1:
            raise CommandError(
                f"« {demande} » désigne {len(candidats)} sauvegardes : "
                + ", ".join(f"{q:%Y-%m-%d_%H%M%S}" for q, _ in candidats[:6])
                + ". Précisez l'heure.")
        return candidats[0][1]

    # --- Garde-fous ------------------------------------------------------------
    def verifier_arret(self):
        if X.wms_en_marche():
            raise CommandError(
                "Le WMS tourne : arrêtez-le d'abord (Arreter-WMS.bat sur le serveur, ou "
                "fermez sa fenêtre). Une restauration sous les pieds des caristes "
                "mélangerait leurs gestes à une base qui recule dans le temps.")
        if X.tache_service_active():
            raise CommandError(
                "La tâche planifiée « WMS Structa\\Service » est active : elle relancerait "
                "le WMS pendant la restauration. Arrêtez-le avec Arreter-WMS.bat, qui la "
                "désactive.")

    def filet(self):
        """Sauvegarde la base actuelle. Rend le nom du jeu produit."""
        self.stdout.write("\n  Filet : sauvegarde de la base actuelle avant de la remplacer…")
        avant = set(X.jeux(X.dossier_sauvegardes()))
        try:
            call_command("sauvegarder", sans_rotation=True, copie="aucune",
                         stdout=self.stdout, stderr=self.stderr)
        except CommandError as e:
            raise CommandError(
                f"Le filet n'a pas pu être fait ({e}). Rien n'a été modifié. Si la base "
                "actuelle est illisible — c'est souvent pourquoi on restaure — relancez "
                "avec --sans-filet.") from None
        nouveaux = sorted(set(X.jeux(X.dossier_sauvegardes())) - avant)
        return f"wms_{nouveaux[-1]:%Y-%m-%d_%H%M%S}" if nouveaux else "la dernière sauvegarde"

    # --- PostgreSQL --------------------------------------------------------------
    def _connexion(self):
        reglages = settings.DATABASES["default"]
        env = dict(os.environ)
        # Le mot de passe par l'environnement : jamais sur la ligne de commande.
        env.update(PGPASSWORD=reglages.get("PASSWORD") or "", PGCONNECT_TIMEOUT="20",
                   PGAPPNAME="wms-restauration", PGCLIENTENCODING="UTF8")
        arguments = ["--host", str(reglages.get("HOST") or "127.0.0.1"),
                     "--port", str(reglages.get("PORT") or "5432"),
                     "--username", str(reglages.get("USER") or ""),
                     "--dbname", str(reglages.get("NAME")),
                     "--no-password"]
        return arguments, env

    def relire_dump(self, fichier):
        pg_restore = X.trouver_outil("pg_restore")
        r = subprocess.run([str(pg_restore), "--list", str(fichier)], capture_output=True,
                           text=True, timeout=600, errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            raise CommandError("Fichier illisible par pg_restore : "
                               + (_derniere_ligne(r.stderr) or f"code {r.returncode}"))
        tables = set(re.findall(r"TABLE DATA \S+ (\S+) ", r.stdout))
        manquantes = [t for t in TABLES_INDISPENSABLES if t not in tables]
        if manquantes:
            raise CommandError(f"{fichier.name} n'est pas une sauvegarde du WMS : "
                               f"tables absentes ({', '.join(manquantes)}).")
        return len(tables)

    def restaurer_postgresql(self, fichier):
        pg_restore = X.trouver_outil("pg_restore")
        # psql du MÊME dossier que pg_restore : le script que produit l'un
        # porte des commandes (\restrict) que seul un psql de la même version
        # comprend.
        voisin = pg_restore.with_name("psql" + pg_restore.suffix)
        psql = voisin if voisin.is_file() else X.trouver_outil("psql")
        connexion, env = self._connexion()
        sans_fenetre = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.stdout.write("\n  Restauration en cours (une seule transaction)…")
        with tempfile.TemporaryFile() as err_lecture, tempfile.TemporaryFile() as err_ecriture:
            # --single-transaction : sans lui, pg_restore écrit ses propres
            # BEGIN/COMMIT autour des « large objects » — un COMMIT au milieu du
            # flux, qui validerait la moitié déjà chargée. Avec lui, il n'en
            # écrit qu'un, tout à la fin ; le nôtre suit, sans effet.
            lecteur = subprocess.Popen(
                [str(pg_restore), "--no-owner", "--no-privileges", "--single-transaction",
                 "--file", "-", str(fichier)],
                stdout=subprocess.PIPE, stderr=err_lecture, creationflags=sans_fenetre)
            ecrivain = subprocess.Popen(
                [str(psql), "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", "-", *connexion],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err_ecriture,
                env=env, creationflags=sans_fenetre)
            coupe = False
            try:
                # BEGIN ici, COMMIT seulement si pg_restore a tout rendu. Si le
                # flux s'interrompt avant — fichier abîmé, erreur, fenêtre
                # fermée —, psql arrive au bout sans COMMIT : le serveur annule.
                ecrivain.stdin.write(
                    b"BEGIN;\n"
                    # Un pgAdmin resté ouvert sur une table ne doit pas faire
                    # attendre la restauration indéfiniment.
                    b"SET LOCAL lock_timeout = '30s';\n"
                    b"DROP SCHEMA IF EXISTS public CASCADE;\n"
                    b"CREATE SCHEMA public;\n")
                shutil.copyfileobj(lecteur.stdout, ecrivain.stdin, 1 << 20)
            except (BrokenPipeError, OSError):
                coupe = True   # psql s'est arrêté sur une erreur : il dit laquelle
            code_lecture = _attendre(lecteur, couper=coupe)
            try:
                if code_lecture == 0 and not coupe:
                    ecrivain.stdin.write(b"COMMIT;\n")
                ecrivain.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            code_ecriture = _attendre(ecrivain, delai=DELAI_RESTAURATION)
            erreur_lecture = _lire(err_lecture)
            erreur_ecriture = _lire(err_ecriture)

        # psql d'abord : s'il s'est arrêté, c'est lui qui a coupé pg_restore, et
        # son message dit pourquoi (mot de passe, droits, verrou).
        if code_lecture != 0 and not coupe:
            raise CommandError("Fichier illisible en cours de route : rien n'a été modifié. "
                               + (_derniere_ligne(erreur_lecture) or ""))
        if code_ecriture != 0 or coupe:
            message = _derniere_ligne(erreur_ecriture) or f"code {code_ecriture}"
            if re.search(r"must be owner of schema|propriétaire du schéma|proprietaire du schema",
                         erreur_ecriture, re.IGNORECASE):
                reglages = settings.DATABASES["default"]
                message += (f" — le compte {reglages.get('USER')} ne possède pas le schéma "
                            "public. Une fois, en administrateur : psql -h 127.0.0.1 -U "
                            f"postgres -d {reglages.get('NAME')} -c \"ALTER SCHEMA public "
                            f"OWNER TO {reglages.get('USER')}\", puis relancez")
            raise CommandError(f"Restauration refusée par PostgreSQL : rien n'a été "
                               f"modifié. {message}")
        return self.bilan_postgresql(psql, connexion, env)

    def bilan_postgresql(self, psql, connexion, env):
        """Ce que contient la base restaurée, compté par PostgreSQL lui-même."""
        requete = ("SELECT (SELECT count(*) FROM pg_tables WHERE schemaname = 'public'), "
                   "(SELECT count(*) FROM public.wms_cabine), "
                   "(SELECT count(*) FROM public.wms_emplacement)")
        r = subprocess.run([str(psql), "-X", "-q", "-t", "-A", "-F", " ", "-c", requete,
                            *connexion], capture_output=True, text=True, env=env,
                           timeout=120, errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        valeurs = r.stdout.split()
        if r.returncode != 0 or len(valeurs) != 3:
            return "comptages indisponibles"
        return f"{valeurs[0]} tables, {valeurs[1]} cabines, {valeurs[2]} emplacements"

    # --- SQLite ------------------------------------------------------------------
    def relire_sqlite(self, fichier):
        base = sqlite3.connect(f"file:{fichier.as_posix()}?mode=ro", uri=True)
        try:
            controle = base.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {n for (n,) in base.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
        except sqlite3.DatabaseError as e:
            raise CommandError(f"{fichier.name} n'est pas une base SQLite lisible : {e}") from None
        finally:
            base.close()
        if controle != "ok":
            raise CommandError(f"{fichier.name} est abîmé : {controle}")
        manquantes = [t for t in TABLES_INDISPENSABLES if t not in tables]
        if manquantes:
            raise CommandError(f"{fichier.name} n'est pas une sauvegarde du WMS : "
                               f"tables absentes ({', '.join(manquantes)}).")
        return len(tables)

    def restaurer_sqlite(self, fichier):
        cible = Path(settings.DATABASES["default"]["NAME"])
        source = sqlite3.connect(f"file:{fichier.as_posix()}?mode=ro", uri=True)
        destination = sqlite3.connect(str(cible))
        try:
            # D'un seul pas : la base de destination devient la copie exacte du
            # fichier, ou reste ce qu'elle était.
            source.backup(destination)
            cabines = destination.execute("SELECT count(*) FROM wms_cabine").fetchone()[0]
            emplacements = destination.execute(
                "SELECT count(*) FROM wms_emplacement").fetchone()[0]
        finally:
            destination.close()
            source.close()
        return f"{cabines} cabines, {emplacements} emplacements"


def _attendre(processus, delai=600, couper=False):
    if couper:
        processus.kill()
    try:
        return processus.wait(timeout=delai)
    except subprocess.TimeoutExpired:
        processus.kill()
        return processus.wait()


def _lire(fichier):
    fichier.seek(0)
    return fichier.read().decode("utf-8", "replace")


def _derniere_ligne(texte):
    lignes = [x.strip() for x in (texte or "").splitlines() if x.strip()]
    return lignes[-1] if lignes else ""
