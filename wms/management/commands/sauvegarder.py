"""Sauvegarde de la base et des fichiers de configuration, avec rotation.

Lancée deux fois par jour par la tâche planifiée « WMS Structa\\Sauvegarde »
(voir `outils/serveur_wms.py`), ou à la main avec `Sauvegarder-WMS.bat`.

Un passage produit un JEU, deux fichiers sous le même horodatage :

- `wms_<date>.dump` : la base PostgreSQL, par `pg_dump` au format « custom »
  (compressé, restaurable table par table). Sur SQLite : `wms_<date>.sqlite3` ;
- `wms_<date>_fichiers.zip` : `.env`, `certificats\\` et les sauvegardes de
  « Repartir de zéro ». Sans eux, une base restaurée sur une machine neuve
  repart avec une nouvelle autorité de certification — à réinstaller sur
  chaque téléphone.

Une sauvegarde qu'on ne sait pas relire n'est pas une sauvegarde : le fichier
de la base est relu (`pg_restore --list`, ou `PRAGMA integrity_check`), et
chaque table de la base doit y figurer. Les fichiers sont écrits sous un nom
provisoire puis renommés : un jeu à moitié écrit ne porte jamais le nom d'un
jeu complet.

Le résultat — réussite ou échec — est écrit dans `logs/sauvegarde-etat.json`,
que l'accueil de l'administration affiche, dans `logs/sauvegarde.log`, et dans
le journal Application de Windows. Un échec rend le code 1, que le
Planificateur de tâches affiche comme « dernier résultat ».

Restauration : `Restaurer-WMS.bat`, ou `manage.py restaurer` (voir
docs/guide-serveur.md) — le WMS arrêté, la base actuelle gardée d'abord, le
rechargement en une seule transaction.
"""
import datetime as dt
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import time
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from wms import exploitation as X

#: Ce que le zip emporte, relatif à la racine du projet.
FICHIERS_CONFIGURATION = [".env"]
DOSSIERS_CONFIGURATION = ["certificats"]

#: Marge d'espace libre exigée avant d'écrire : deux fois la dernière sauvegarde,
#: et jamais moins que ceci.
ESPACE_MINIMUM = 50 * 1024 * 1024

DELAI_PG_DUMP = 3600


class Command(BaseCommand):
    help = ("Sauvegarde la base (vérifiée) et la configuration, puis applique la "
            "rotation. Réglages : WMS_SAUVEGARDE_* dans .env.")

    def add_arguments(self, parser):
        parser.add_argument("--destination",
                            help="dossier de destination (défaut : WMS_SAUVEGARDE_DOSSIER)")
        parser.add_argument("--copie",
                            help="seconde destination (défaut : WMS_SAUVEGARDE_COPIE ; "
                                 "« aucune » pour s'en passer cette fois)")
        parser.add_argument("--sans-rotation", action="store_true",
                            help="ne rien effacer des anciennes sauvegardes")

    # ------------------------------------------------------------------------
    def handle(self, *args, **options):
        self.journal = X.journal("sauvegarde")
        debut = time.monotonic()
        precedent = X.lire_json(X.dossier_logs() / X.FICHIER_ETAT_SAUVEGARDE) or {}
        destination = Path(options["destination"]) if options["destination"] \
            else X.dossier_sauvegardes()
        sans_copie = bool(options["copie"]) and options["copie"].strip().lower() == "aucune"
        if options["copie"]:
            copie = None if sans_copie else Path(options["copie"])
        else:
            copie = X.dossier_copie()

        etat = {
            "derniere_tentative": timezone.now().isoformat(),
            "derniere_reussite": precedent.get("derniere_reussite"),
            "statut": "echec",
            "destination": str(destination),
            "copie": str(copie) if copie else None,
            "copie_ok": None,
        }
        if sans_copie:
            # Le filet d'une restauration, ou une sauvegarde faite exprès sans
            # copie : l'état de la copie régulière reste celui de la dernière
            # fois. L'effacer faisait annoncer « aucune copie hors de cette
            # machine » — et taisait une copie en échec — jusqu'au soir.
            for cle in ("copie", "copie_ok", "message_copie"):
                if precedent.get(cle) is not None:
                    etat[cle] = precedent[cle]
        try:
            # La rotation d'abord : un disque plein ne se libérait jamais, puisque
            # la rotation ne passait qu'après une sauvegarde réussie — et qu'elle
            # échouait justement faute de place. Les N dernières sont toujours
            # gardées, quel que soit leur âge.
            if not options["sans_rotation"] and destination.is_dir():
                X.appliquer_rotation(destination)
            produits, verification = self.sauvegarder(destination)
            etat.update(verification)
            etat["fichier"] = produits[0].name
            etat["taille"] = sum(p.stat().st_size for p in produits)
            etat["derniere_reussite"] = etat["derniere_tentative"]
            etat["statut"] = "ok"

            if not options["sans_rotation"]:
                conserves, effaces, liberes = X.appliquer_rotation(destination)
                etat["jeux_conserves"], etat["effaces"] = conserves, effaces
                if effaces:
                    self.dire(f"Rotation : {effaces} fichier(s) ancien(s) effacé(s), "
                              f"{X.lisible(liberes)} libérés.")
            else:
                etat["jeux_conserves"] = len(X.jeux(destination))

            if copie:
                try:
                    self.copier(produits, copie)
                    if not options["sans_rotation"]:
                        X.appliquer_rotation(copie)
                    etat["copie_ok"] = True
                    self.dire(f"Copie : {copie}")
                except (OSError, X.ErreurExploitation) as e:
                    etat["copie_ok"] = False
                    etat["statut"] = "copie_en_echec"
                    etat["message_copie"] = str(e)
        except Exception as e:  # noqa: BLE001 - tout échec doit être inscrit et visible
            etat["message"] = str(e) or e.__class__.__name__
            etat["duree_s"] = round(time.monotonic() - debut, 1)
            self.terminer(etat)
            raise CommandError(f"Sauvegarde en échec : {e}") from None

        etat["duree_s"] = round(time.monotonic() - debut, 1)
        self.terminer(etat)
        if etat["statut"] == "copie_en_echec":
            raise CommandError(
                f"Sauvegarde faite dans {destination}, mais la copie vers {copie} a "
                f"échoué : {etat['message_copie']}")
        self.stdout.write(self.style.SUCCESS(
            f"OK — {etat['fichier']} et la configuration ({X.lisible(etat['taille'])} "
            f"en tout) dans {destination}"))

    # ------------------------------------------------------------------------
    def dire(self, texte):
        self.stdout.write("  " + texte)
        self.journal.info(texte)

    def terminer(self, etat):
        """Écrit l'état pour l'administration, le journal, l'événement Windows."""
        try:
            X.ecrire_json(X.dossier_logs() / X.FICHIER_ETAT_SAUVEGARDE, etat)
        except OSError as e:
            self.stderr.write(f"  (état non écrit : {e})")
        if etat["statut"] == "ok":
            texte = (f"Sauvegarde réussie : {etat.get('fichier')} "
                     f"({X.lisible(etat.get('taille'))}) dans {etat['destination']}"
                     + (f", copie dans {etat['copie']}" if etat.get("copie_ok") else ""))
            self.journal.info(texte)
            X.evenement_windows(False, texte)
        else:
            texte = ("Sauvegarde du WMS en échec : "
                     + (etat.get("message") or
                        f"copie vers {etat.get('copie')} impossible — "
                        f"{etat.get('message_copie')}"))
            self.journal.error(texte)
            logging.getLogger("wms").error(texte)
            X.evenement_windows(True, texte)

    # ------------------------------------------------------------------------
    def sauvegarder(self, destination):
        """Écrit le jeu complet dans `destination`. Rend (fichiers, vérification)."""
        nouveau = not destination.exists()
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise X.ErreurExploitation(
                f"dossier de sauvegarde inaccessible ({destination}) : {e}") from None
        if nouveau and X.restreindre_acces(destination):
            self.dire(f"Dossier créé et réservé aux administrateurs : {destination}")
        self.verifier_espace(destination)

        horodatage = dt.datetime.now().strftime(X.FORMAT_HORODATAGE)
        # Deux sauvegardes dans la même seconde — le filet d'une restauration
        # lancée aussitôt après une sauvegarde — porteraient le même nom : la
        # seconde écraserait la première. On attend la seconde suivante.
        while any(destination.glob(f"wms_{horodatage}*")):
            time.sleep(0.2)
            horodatage = dt.datetime.now().strftime(X.FORMAT_HORODATAGE)
        moteur = settings.DATABASES["default"]["ENGINE"]
        if moteur.endswith("postgresql"):
            base, verification = self.base_postgresql(destination, horodatage)
        elif moteur.endswith("sqlite3"):
            base, verification = self.base_sqlite(destination, horodatage)
        else:
            raise X.ErreurExploitation(f"moteur de base non pris en charge : {moteur}")
        fichiers = self.fichiers_configuration(destination, horodatage)
        return [base, fichiers], verification

    def verifier_espace(self, destination):
        dernier = 0
        for fichiers in X.jeux(destination).values():
            dernier = max(dernier, sum(f.stat().st_size for f in fichiers))
        exige = max(ESPACE_MINIMUM, 2 * dernier)
        mesure = X.espace_libre(destination)
        if mesure and mesure[0] < exige:
            raise X.ErreurExploitation(
                f"espace insuffisant sur le disque de {destination} : "
                f"{X.lisible(mesure[0])} libres, {X.lisible(exige)} nécessaires.")

    # --- PostgreSQL -----------------------------------------------------------
    def base_postgresql(self, destination, horodatage):
        reglages = settings.DATABASES["default"]
        pg_dump, pg_restore = X.trouver_outil("pg_dump"), X.trouver_outil("pg_restore")
        final = destination / f"wms_{horodatage}.dump"
        provisoire = final.with_name(final.name + ".partiel")
        env = dict(os.environ)
        # Le mot de passe par l'environnement du seul pg_dump : jamais sur la
        # ligne de commande, que tout compte du poste peut lire.
        env["PGPASSWORD"] = reglages.get("PASSWORD") or ""
        env["PGCONNECT_TIMEOUT"] = "20"
        env["PGAPPNAME"] = "wms-sauvegarde"
        commande = [str(pg_dump),
                    "--host", str(reglages.get("HOST") or "127.0.0.1"),
                    "--port", str(reglages.get("PORT") or "5432"),
                    "--username", str(reglages.get("USER") or ""),
                    "--dbname", str(reglages.get("NAME")),
                    "--format=custom",
                    # Jamais de question : une tâche planifiée qui attend un mot
                    # de passe attend jusqu'au lendemain.
                    "--no-password",
                    "--file", str(provisoire)]
        try:
            r = subprocess.run(commande, env=env, capture_output=True, text=True,
                               timeout=DELAI_PG_DUMP, errors="replace",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            provisoire.unlink(missing_ok=True)
            raise X.ErreurExploitation("pg_dump n'a pas fini en une heure.") from None
        if r.returncode != 0:
            provisoire.unlink(missing_ok=True)
            raise X.ErreurExploitation("pg_dump a échoué : "
                                       + (_derniere_ligne(r.stderr) or f"code {r.returncode}"))
        tables = self.verifier_dump(pg_restore, provisoire)
        os.replace(provisoire, final)
        self.dire(f"Base : {final.name} ({X.lisible(final.stat().st_size)}), "
                  f"{tables} tables relues.")
        return final, {"tables": tables}

    def verifier_dump(self, pg_restore, fichier):
        """Relit le fichier produit : toutes les tables de la base doivent y être."""
        try:
            r = subprocess.run([str(pg_restore), "--list", str(fichier)],
                               capture_output=True, text=True, timeout=600,
                               errors="replace",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            fichier.unlink(missing_ok=True)
            raise X.ErreurExploitation("la relecture de la sauvegarde n'a pas abouti.") from None
        if r.returncode != 0:
            fichier.unlink(missing_ok=True)
            raise X.ErreurExploitation("sauvegarde illisible par pg_restore : "
                                       + (_derniere_ligne(r.stderr) or f"code {r.returncode}"))
        presentes = set(re.findall(r"TABLE DATA \S+ (\S+) ", r.stdout))
        attendues = set(connection.introspection.table_names())
        manquantes = sorted(attendues - presentes)
        if manquantes:
            fichier.unlink(missing_ok=True)
            raise X.ErreurExploitation(
                "sauvegarde incomplète, tables absentes : " + ", ".join(manquantes[:8])
                + ("…" if len(manquantes) > 8 else ""))
        return len(presentes)

    # --- SQLite ---------------------------------------------------------------
    def base_sqlite(self, destination, horodatage):
        source = Path(settings.DATABASES["default"]["NAME"])
        if not source.is_file():
            raise X.ErreurExploitation(f"base SQLite introuvable : {source}")
        final = destination / f"wms_{horodatage}.sqlite3"
        provisoire = final.with_name(final.name + ".partiel")
        provisoire.unlink(missing_ok=True)
        # La copie « à chaud » de SQLite : cohérente même si le WMS écrit pendant
        # ce temps. Copier le fichier à la main pourrait saisir une écriture à
        # moitié faite.
        lecture = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
        ecriture = sqlite3.connect(str(provisoire))
        try:
            lecture.backup(ecriture)
            controle = ecriture.execute("PRAGMA integrity_check").fetchone()[0]
            tables = ecriture.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        finally:
            ecriture.close()
            lecture.close()
        if controle != "ok":
            provisoire.unlink(missing_ok=True)
            raise X.ErreurExploitation(f"copie SQLite incohérente : {controle}")
        os.replace(provisoire, final)
        self.dire(f"Base : {final.name} ({X.lisible(final.stat().st_size)}), "
                  f"{tables} tables, intégrité vérifiée.")
        return final, {"tables": tables}

    # --- Configuration ----------------------------------------------------------
    def fichiers_configuration(self, destination, horodatage):
        racine = X.racine()
        final = destination / f"wms_{horodatage}_fichiers.zip"
        provisoire = final.with_name(final.name + ".partiel")
        nombre = 0
        with zipfile.ZipFile(provisoire, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for nom in FICHIERS_CONFIGURATION:
                chemin = racine / nom
                if chemin.is_file():
                    z.write(chemin, nom)
                    nombre += 1
            for nom in DOSSIERS_CONFIGURATION:
                for chemin in sorted((racine / nom).rglob("*")):
                    if chemin.is_file():
                        z.write(chemin, chemin.relative_to(racine).as_posix())
                        nombre += 1
            # Les sauvegardes écrites avant « Repartir de zéro » : la seule trace
            # de ce qui a été effacé ce jour-là.
            for chemin in sorted((racine / "sauvegardes").glob("*.json")):
                z.write(chemin, chemin.relative_to(racine).as_posix())
                nombre += 1
        with zipfile.ZipFile(provisoire) as z:
            abime = z.testzip()
        if abime:
            provisoire.unlink(missing_ok=True)
            raise X.ErreurExploitation(f"archive de configuration abîmée ({abime}).")
        os.replace(provisoire, final)
        self.dire(f"Configuration : {final.name} ({nombre} fichier(s)).")
        return final

    # --- Seconde destination ----------------------------------------------------
    def copier(self, fichiers, copie):
        nouveau = not copie.exists()
        try:
            copie.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise X.ErreurExploitation(f"destination injoignable : {e}") from None
        # Une copie sur un autre disque de la machine se réserve comme la
        # destination principale ; un partage réseau garde les droits du NAS.
        if nouveau and not str(copie).startswith(("\\\\", "//")):
            X.restreindre_acces(copie)
        for source in fichiers:
            cible = copie / source.name
            provisoire = cible.with_name(cible.name + ".partiel")
            shutil.copyfile(source, provisoire)
            if X.empreinte(provisoire) != X.empreinte(source):
                provisoire.unlink(missing_ok=True)
                raise X.ErreurExploitation(f"copie de {source.name} altérée en route.")
            os.replace(provisoire, cible)


def _derniere_ligne(texte):
    lignes = [x.strip() for x in (texte or "").splitlines() if x.strip()]
    return lignes[-1] if lignes else ""
