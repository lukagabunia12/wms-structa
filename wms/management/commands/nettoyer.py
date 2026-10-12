"""Ménage des journaux, et mesure de ce qu'ils pèsent.

Lancé chaque semaine par la tâche planifiée « WMS Structa\\Nettoyage » (la
fréquence se règle à l'installation des tâches), ou à la main :

    python manage.py nettoyer --simulation     # dit ce qui partirait, n'efface rien
    python manage.py nettoyer --jours 60

Ce qui grossit si personne n'y touche, et ce que la commande en fait :

    journaux de PostgreSQL (data\\log)   un fichier par jour et par redémarrage,
                                        jamais effacé par PostgreSQL sous
                                        Windows : effacés au-delà de N jours
                                        (WMS_JOURNAUX_JOURS, 30 par défaut)
    sessions expirées (base)            une ligne par connexion à
                                        l'administration : effacées
    fichiers « .partiel » abandonnés    reliquats d'une écriture interrompue :
                                        effacés après un jour
    logs/installation.log               ramené à ses dernières lignes s'il
                                        dépasse 1 Mo

Ce qu'elle ne touche pas, parce que c'est déjà borné : `logs/wms.log` (six
fichiers de 2 Mo, par rotation — c'est aussi l'historique des gestes sensibles,
qui disent qui a supprimé quoi), `logs/sauvegarde.log` et `logs/nettoyage.log`
(quatre fichiers de 1 Mo), `logs/service.log` (quelques lignes par démarrage,
renommé au-delà de 5 Mo, trois anciens gardés) et `logs/taches-erreurs.log`
(renommé en .1 au-delà de 2 Mo). Ni les sauvegardes, dont la rotation
appartient à `manage.py sauvegarder`.

Le bilan — ce qui est parti, ce que pèsent les journaux, la base et ses plus
grosses tables, la place libre — est écrit dans `logs/nettoyage.log`, dans
`logs/nettoyage-etat.json` (affiché par l'accueil de l'administration) et à
l'écran.
"""
import re
import time
from pathlib import Path

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection
from django.utils import timezone

from wms import exploitation as X

MOTIF_JOURNAL_PG = re.compile(r"^postgresql-.*\.(log|csv|json)$", re.IGNORECASE)
TAILLE_MAX_INSTALLATION = 1_000_000
GARDE_INSTALLATION = 256_000


class Command(BaseCommand):
    help = ("Efface les journaux trop vieux (PostgreSQL, sessions expirées) et "
            "mesure ce que pèsent journaux, sauvegardes et base.")

    def add_arguments(self, parser):
        parser.add_argument("--jours", type=int,
                            help="âge au-delà duquel un journal est effacé "
                                 "(défaut : WMS_JOURNAUX_JOURS, 30)")
        parser.add_argument("--simulation", action="store_true",
                            help="dit ce qui serait effacé, sans rien effacer")

    def handle(self, *args, **options):
        self.journal = X.journal("nettoyage")
        self.simulation = options["simulation"]
        jours = options["jours"] if options["jours"] else X.jours_journaux()
        limite = time.time() - jours * 86400
        self.effaces, self.liberes = 0, 0
        lignes = []

        if self.simulation:
            self.stdout.write("  SIMULATION : rien ne sera effacé.\n")

        # 1. Journaux du serveur PostgreSQL ----------------------------------
        dossiers = X.dossiers_journaux_postgresql()
        if not dossiers and settings.DATABASES["default"]["ENGINE"].endswith("postgresql"):
            lignes.append("Journaux PostgreSQL : dossier non trouvé (indiquez-le dans "
                          ".env : WMS_POSTGRESQL_JOURNAUX=…\\data\\log).")
        for dossier in dossiers:
            lignes.append(self.journaux_postgresql(dossier, limite, jours))

        # 2. Sessions expirées -----------------------------------------------
        try:
            expirees = Session.objects.filter(expire_date__lt=timezone.now()).count()
            if expirees and not self.simulation:
                call_command("clearsessions")
            lignes.append(f"Sessions expirées : {expirees} "
                          + ("à effacer." if self.simulation else "effacée(s)."))
        except DatabaseError as e:
            lignes.append(f"Sessions : base injoignable ({_premiere_ligne(e)}).")

        # 3. Reliquats d'écritures interrompues --------------------------------
        partiels = 0
        for dossier in (X.racine() / "sauvegardes", X.dossier_logs()):
            for chemin in dossier.glob("*.partiel") if dossier.is_dir() else []:
                if self.effacer_si_vieux(chemin, time.time() - 86400):
                    partiels += 1
        if partiels:
            lignes.append(f"Fichiers provisoires abandonnés : {partiels} effacé(s).")

        # 4. Journal de l'installation ------------------------------------------
        lignes.extend(self.raccourcir(X.dossier_logs() / "installation.log"))

        # 5. Mesures -------------------------------------------------------------
        lignes.extend(self.mesures())

        bilan = {
            "date": timezone.now().isoformat(),
            "jours": jours,
            "simulation": self.simulation,
            "fichiers_effaces": self.effaces,
            "octets_liberes": self.liberes,
            "lignes": lignes,
        }
        if not self.simulation:
            try:
                X.ecrire_json(X.dossier_logs() / X.FICHIER_ETAT_NETTOYAGE, bilan)
            except OSError as e:
                lignes.append(f"(bilan non écrit : {e})")

        entete = (f"Ménage {'simulé' if self.simulation else 'fait'} : "
                  f"{self.effaces} fichier(s), {X.lisible(self.liberes)} "
                  f"{'à libérer' if self.simulation else 'libérés'} "
                  f"(journaux de plus de {jours} jours).")
        self.journal.info(entete)
        self.stdout.write(self.style.SUCCESS(entete))
        for ligne in lignes:
            self.journal.info("  " + ligne)
            self.stdout.write("  " + ligne)

    # ------------------------------------------------------------------------
    def effacer_si_vieux(self, chemin, limite):
        try:
            info = chemin.stat()
            if info.st_mtime >= limite:
                return False
            if not self.simulation:
                chemin.unlink()
        except OSError:
            # Sous Windows, le fichier que PostgreSQL écrit encore est verrouillé :
            # il partira la prochaine fois.
            return False
        self.effaces += 1
        self.liberes += info.st_size
        return True

    def journaux_postgresql(self, dossier, limite, jours):
        dossier = Path(dossier)
        if not dossier.is_dir():
            return f"Journaux PostgreSQL : {dossier} introuvable."
        fichiers = []
        for chemin in dossier.iterdir():
            try:
                if chemin.is_file() and MOTIF_JOURNAL_PG.match(chemin.name):
                    fichiers.append((chemin.stat().st_mtime, chemin))
            except OSError:
                continue
        # Jamais le plus récent : c'est celui que PostgreSQL est en train d'écrire.
        fichiers = [c for _, c in sorted(fichiers)]
        effaces = sum(1 for c in fichiers[:-1] if self.effacer_si_vieux(c, limite))
        taille, nombre = X.taille_dossier(dossier)
        return (f"Journaux PostgreSQL ({dossier}) : {effaces} de plus de {jours} jours "
                f"{'à effacer' if self.simulation else 'effacé(s)'} ; "
                f"{nombre} fichier(s), {X.lisible(taille)} restants.")

    def raccourcir(self, chemin):
        try:
            taille = chemin.stat().st_size
        except OSError:
            return []
        if taille <= TAILLE_MAX_INSTALLATION:
            return []
        if not self.simulation:
            with open(chemin, "rb") as f:
                f.seek(-GARDE_INSTALLATION, 2)
                fin = f.read()
            # Repartir d'une ligne entière.
            fin = fin[fin.find(b"\n") + 1:]
            chemin.write_bytes(fin)
        self.liberes += taille - GARDE_INSTALLATION
        return [f"{chemin.name} ramené de {X.lisible(taille)} à "
                f"{X.lisible(GARDE_INSTALLATION)}."]

    def mesures(self):
        lignes = []
        taille, nombre = X.taille_dossier(X.dossier_logs())
        lignes.append(f"Dossier logs : {nombre} fichier(s), {X.lisible(taille)}.")
        taille, nombre = X.taille_dossier(X.dossier_sauvegardes())
        lignes.append(f"Sauvegardes ({X.dossier_sauvegardes()}) : {nombre} fichier(s), "
                      f"{X.lisible(taille)}.")
        reset = list((X.racine() / "sauvegardes").glob("*.json"))
        if reset:
            lignes.append(f"Sauvegardes de « Repartir de zéro » : {len(reset)} fichier(s), "
                          f"{X.lisible(sum(c.stat().st_size for c in reset))} (conservées).")
        lignes.extend(self.poids_base())
        mesure = X.espace_libre(X.racine())
        if mesure:
            lignes.append(f"Disque du WMS : {X.lisible(mesure[0])} libres sur "
                          f"{X.lisible(mesure[1])}.")
        return lignes

    def poids_base(self):
        try:
            if connection.vendor == "postgresql":
                with connection.cursor() as c:
                    c.execute("SELECT pg_database_size(current_database())")
                    total = c.fetchone()[0]
                    c.execute("""
                        SELECT c.relname, pg_total_relation_size(c.oid)
                          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                         WHERE n.nspname = 'public' AND c.relkind = 'r'
                         ORDER BY 2 DESC LIMIT 5""")
                    tables = c.fetchall()
                detail = ", ".join(f"{nom} {X.lisible(t)}" for nom, t in tables)
                return [f"Base PostgreSQL : {X.lisible(total)} (plus grosses tables : "
                        f"{detail})."]
            if connection.vendor == "sqlite":
                fichier = Path(settings.DATABASES["default"]["NAME"])
                if fichier.is_file():
                    return [f"Base SQLite : {X.lisible(fichier.stat().st_size)}."]
        except DatabaseError as e:
            return [f"Base : poids non mesuré ({_premiere_ligne(e)})."]
        return []


def _premiere_ligne(e):
    return (str(e).strip().splitlines() or [e.__class__.__name__])[0]
