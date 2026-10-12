"""Restaurer une sauvegarde : `manage.py restaurer`.

Ce qui compte le jour où l'on en a besoin : que la restauration refuse de
tourner sous les pieds des caristes, qu'elle garde la base actuelle avant de
l'écraser, et qu'un incident en cours de route ne laisse JAMAIS une base à
moitié rechargée.
"""
import io
import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import textwrap
from pathlib import Path
from unittest import mock, skipUnless

from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase

from wms import exploitation as X
from wms.management.commands import restaurer as R
from wms.management.commands import sauvegarder as S

from .test_exploitation import AvecDossiers


def _base_wms(chemin, cabines=("26_01_01", "26_01_02")):
    base = sqlite3.connect(chemin)
    base.executescript("""
        DROP TABLE IF EXISTS django_migrations; DROP TABLE IF EXISTS wms_cabine;
        DROP TABLE IF EXISTS wms_emplacement;
        CREATE TABLE django_migrations (id INTEGER PRIMARY KEY, app TEXT, name TEXT);
        CREATE TABLE wms_cabine (id INTEGER PRIMARY KEY, numero TEXT);
        CREATE TABLE wms_emplacement (id INTEGER PRIMARY KEY, code TEXT);
        INSERT INTO django_migrations (app, name) VALUES ('wms', '0001_initial');
        INSERT INTO wms_emplacement (code) VALUES ('A-01');
    """)
    base.executemany("INSERT INTO wms_cabine (numero) VALUES (?)", [(c,) for c in cabines])
    base.commit()
    base.close()


def _cabines(chemin):
    base = sqlite3.connect(chemin)
    try:
        return [n for (n,) in base.execute("SELECT numero FROM wms_cabine ORDER BY numero")]
    finally:
        base.close()


class AvecUneSauvegarde(AvecDossiers):
    def setUp(self):
        super().setUp()
        _base_wms(self.base)
        for patch in (mock.patch.object(X, "wms_en_marche", return_value=False),
                      mock.patch.object(X, "tache_service_active", return_value=None)):
            patch.start()
            self.addCleanup(patch.stop)
        self.sauvegarder()
        (self.horodatage, self.fichiers), = X.jeux(self.destination).items()
        self.nom = f"{self.horodatage:%Y-%m-%d_%H%M%S}"

    def restaurer(self, *args, **options):
        sortie = io.StringIO()
        call_command("restaurer", *args, stdout=sortie, stderr=io.StringIO(), **options)
        return sortie.getvalue()


class RestaurationSQLiteTest(AvecUneSauvegarde):
    def test_la_base_revient_a_la_sauvegarde_et_l_actuelle_est_gardee(self):
        # La journée continue : une cabine sort, une autre entre.
        _base_wms(self.base, cabines=("26_01_02", "26_09_09"))
        with mock.patch("builtins.input", return_value="RESTAURER"):
            sortie = self.restaurer(self.nom)
        self.assertEqual(_cabines(self.base), ["26_01_01", "26_01_02"])
        self.assertIn("Base restaurée", sortie)
        self.assertIn("Redemarrer-WMS.bat", sortie)
        # Le filet : la base d'avant la restauration, en sauvegarde à part.
        jeux = X.jeux(self.destination)
        self.assertEqual(len(jeux), 2)
        filet = next(f for q, fs in jeux.items() if q != self.horodatage
                     for f in fs if f.name.endswith(".sqlite3"))
        self.assertEqual(_cabines(filet), ["26_01_02", "26_09_09"])

    def test_sans_le_mot_exact_rien_ne_change(self):
        _base_wms(self.base, cabines=("26_09_09",))
        with mock.patch("builtins.input", return_value="oui"):
            with self.assertRaisesMessage(CommandError, "rien n'a été modifié"):
                self.restaurer(self.nom, sans_filet=True)
        self.assertEqual(_cabines(self.base), ["26_09_09"])

    def test_sans_console_pour_confirmer_rien_ne_change(self):
        _base_wms(self.base, cabines=("26_09_09",))
        with mock.patch("builtins.input", side_effect=EOFError):
            with self.assertRaisesMessage(CommandError, "--oui"):
                self.restaurer(self.nom, sans_filet=True)
        self.assertEqual(_cabines(self.base), ["26_09_09"])

    def test_refus_tant_que_le_wms_tourne(self):
        _base_wms(self.base, cabines=("26_09_09",))
        with mock.patch.object(X, "wms_en_marche", return_value=True):
            with self.assertRaisesMessage(CommandError, "Arreter-WMS.bat"):
                self.restaurer(self.nom, oui=True)
        self.assertEqual(_cabines(self.base), ["26_09_09"])

    def test_refus_tant_que_la_tache_peut_le_relancer(self):
        with mock.patch.object(X, "tache_service_active", return_value=True):
            with self.assertRaisesMessage(CommandError, "relancerait"):
                self.restaurer(self.nom, oui=True)

    def test_un_fichier_qui_n_est_pas_une_sauvegarde_du_wms_est_refuse(self):
        autre = self.tmp / "wms_2026-01-01_120000.sqlite3"
        base = sqlite3.connect(autre)
        base.execute("CREATE TABLE wms_cabine (id INTEGER PRIMARY KEY)")
        base.commit()
        base.close()
        with self.assertRaisesMessage(CommandError, "django_migrations"):
            self.restaurer(str(autre), oui=True)

    def test_un_dump_postgresql_ne_se_restaure_pas_dans_sqlite(self):
        dump = self.tmp / "wms_2026-01-01_120000.dump"
        dump.write_bytes(b"PGDMP")
        with self.assertRaisesMessage(CommandError, "attendu : un fichier .sqlite3"):
            self.restaurer(str(dump), oui=True)

    def test_filet_impossible_rien_ne_change(self):
        _base_wms(self.base, cabines=("26_09_09",))
        with mock.patch.object(S.Command, "base_sqlite", side_effect=RuntimeError("disque plein")):
            with self.assertRaisesMessage(CommandError, "--sans-filet"):
                self.restaurer(self.nom, oui=True)
        self.assertEqual(_cabines(self.base), ["26_09_09"])

    def test_liste_des_sauvegardes(self):
        sortie = self.restaurer()
        self.assertIn(self.nom, sortie)
        self.assertIn("Restaurer-WMS.bat", sortie)

    def test_horodatage_ambigu(self):
        second = self.destination / f"wms_{self.horodatage:%Y-%m-%d}_235959.sqlite3"
        shutil.copyfile(self.fichiers[0] if self.fichiers[0].suffix == ".sqlite3"
                        else self.fichiers[1], second)
        with self.assertRaisesMessage(CommandError, "Précisez l'heure"):
            self.restaurer(f"{self.horodatage:%Y-%m-%d}", oui=True)

    def test_horodatage_inconnu(self):
        with self.assertRaisesMessage(CommandError, "Aucune sauvegarde ne correspond"):
            self.restaurer("2001-01-01_000000", oui=True)


def _faux_outils(dossier, code_restauration, psql_refuse=False):
    """Un pg_restore et un psql de théâtre : le premier rend un script SQL puis
    sort avec `code_restauration`, le second recopie ce qu'il reçoit — ou, avec
    `psql_refuse`, s'arrête aussitôt comme sur un mot de passe refusé."""
    dossier.mkdir(parents=True, exist_ok=True)
    recu = dossier / "recu.sql"
    scripts = {
        "pg_restore": f"""\
            #!/bin/sh
            if [ "$1" = "--list" ]; then
              echo "1; 0 0 TABLE DATA public django_migrations wms"
              echo "2; 0 0 TABLE DATA public wms_cabine wms"
              echo "3; 0 0 TABLE DATA public wms_emplacement wms"
              exit 0
            fi
            i=0
            while [ $i -lt 4000 ]; do
              echo "CREATE TABLE public.wms_cabine (id integer); -- ligne de remplissage"
              i=$((i+1))
            done
            [ {code_restauration} -ne 0 ] && echo "pg_restore: error: could not read input file: end of file" >&2
            exit {code_restauration}
            """,
        "psql": f"""\
            #!/bin/sh
            for a in "$@"; do [ "$a" = "-c" ] && {{ echo "3 0 0"; exit 0; }}; done
            if [ "{1 if psql_refuse else 0}" = "1" ]; then
              echo 'psql: error: FATAL:  password authentication failed for user "wms"' >&2
              : > "{recu}"
              exit 2
            fi
            cat > "{recu}"
            exit 0
            """,
    }
    for nom, texte in scripts.items():
        chemin = dossier / nom
        chemin.write_text(textwrap.dedent(texte))
        chemin.chmod(chemin.stat().st_mode | stat.S_IEXEC)
    return recu


@skipUnless(os.name == "posix", "faux outils écrits en shell")
class TransactionPostgreSQLTest(SimpleTestCase):
    """Le protocole : BEGIN d'abord, COMMIT seulement si tout le fichier a été
    relu. Un fichier abîmé ne doit rien laisser à moitié chargé."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.dump = self.tmp / "wms_2026-10-12_223000.dump"
        self.dump.write_bytes(b"PGDMP")
        reglages = {"ENGINE": "django.db.backends.postgresql", "NAME": "wms", "USER": "wms",
                    "PASSWORD": "secret-de-base", "HOST": "127.0.0.1", "PORT": "5432"}
        for patch in (mock.patch.dict(settings.DATABASES["default"], reglages),
                      mock.patch.object(X, "wms_en_marche", return_value=False),
                      mock.patch.object(X, "tache_service_active", return_value=None),
                      mock.patch.object(X, "evenement_windows", return_value=False),
                      mock.patch.object(X, "dossier_logs", return_value=self.tmp / "logs")):
            patch.start()
            self.addCleanup(patch.stop)

    def restaurer(self, code_restauration, psql_refuse=False):
        recu = _faux_outils(self.tmp / "bin", code_restauration, psql_refuse)
        with mock.patch.object(X, "trouver_outil", side_effect=lambda nom: self.tmp / "bin" / nom), \
                mock.patch.object(R.subprocess, "Popen", wraps=subprocess.Popen) as popen:
            try:
                call_command("restaurer", str(self.dump), oui=True, sans_filet=True,
                             stdout=io.StringIO())
            finally:
                self.commandes = [c.args[0] for c in popen.call_args_list]
                self.environnements = [c.kwargs.get("env") for c in popen.call_args_list]
        return recu.read_text()

    def test_tout_relu_un_seul_commit(self):
        script = self.restaurer(0)
        self.assertTrue(script.startswith("BEGIN;"))
        self.assertIn("DROP SCHEMA IF EXISTS public CASCADE;", script)
        self.assertIn("CREATE TABLE public.wms_cabine", script)
        self.assertTrue(script.rstrip().endswith("COMMIT;"))

    def test_fichier_abime_pas_de_commit(self):
        """Sans COMMIT, psql arrive au bout du flux et le serveur annule : la
        base reste ce qu'elle était."""
        with self.assertRaisesMessage(CommandError, "rien n'a été modifié"):
            self.restaurer(1)
        script = (self.tmp / "bin" / "recu.sql").read_text()
        self.assertIn("BEGIN;", script)
        self.assertNotIn("COMMIT", script)

    def test_psql_qui_s_arrete_aussitot_dit_pourquoi(self):
        """psql coupe le flux (mot de passe refusé) : pg_restore est arrêté, et
        c'est le message de psql qui remonte — pas « fichier illisible »."""
        with self.assertRaisesMessage(CommandError, "password authentication failed"):
            self.restaurer(0, psql_refuse=True)
        self.assertNotIn("COMMIT", (self.tmp / "bin" / "recu.sql").read_text())

    def test_un_seul_commit_meme_avec_des_large_objects(self):
        """Sans --single-transaction, pg_restore écrit ses propres BEGIN/COMMIT
        autour des « large objects » : un COMMIT au milieu du flux."""
        self.restaurer(0)
        restauration = next(c for c in self.commandes if "--file" in c)
        self.assertIn("--single-transaction", restauration)

    def test_l_echec_est_ecrit_au_journal_des_sauvegardes(self):
        with mock.patch.object(X, "evenement_windows") as evenement:
            with self.assertRaises(CommandError):
                self.restaurer(1)
        journal = (self.tmp / "logs" / "sauvegarde.log").read_text(encoding="utf-8")
        self.assertIn("Restauration depuis wms_2026-10-12_223000.dump en échec", journal)
        erreur, _texte = evenement.call_args.args
        self.assertTrue(erreur)
        self.assertEqual(evenement.call_args.kwargs["base"], X.EVENEMENT_RESTAURATION)

    def test_mot_de_passe_jamais_sur_la_ligne_de_commande(self):
        self.restaurer(0)
        for commande in self.commandes:
            self.assertNotIn("secret-de-base", " ".join(map(str, commande)))
        psql = next(e for e in self.environnements if e)
        self.assertEqual(psql["PGPASSWORD"], "secret-de-base")


@skipUnless(os.environ.get("WMS_TEST_PG_PORT"), "pas de PostgreSQL d'essai (WMS_TEST_PG_PORT)")
class RestaurationPostgreSQLReelleTest(AvecDossiers):
    """Avec un vrai serveur. WMS_TEST_PG_PORT, WMS_TEST_PG_MOT_DE_PASSE : le
    compte `wms` possède la base `wms_essai_restauration` et son schéma public,
    comme l'installe Installer-WMS ; pg_dump, pg_restore et psql dans le PATH."""

    BASE = "wms_essai_restauration"

    def setUp(self):
        super().setUp()
        self.reglages = {"ENGINE": "django.db.backends.postgresql", "NAME": self.BASE,
                         "USER": "wms", "PASSWORD": os.environ["WMS_TEST_PG_MOT_DE_PASSE"],
                         "HOST": "127.0.0.1", "PORT": os.environ["WMS_TEST_PG_PORT"]}
        for patch in (mock.patch.dict(settings.DATABASES["default"], self.reglages),
                      mock.patch.object(S.connection.introspection, "table_names",
                                        return_value=list(R.TABLES_INDISPENSABLES)),
                      mock.patch.object(X, "wms_en_marche", return_value=False),
                      mock.patch.object(X, "tache_service_active", return_value=None)):
            patch.start()
            self.addCleanup(patch.stop)
        self.sql("""
            DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;
            CREATE TABLE django_migrations (id serial PRIMARY KEY, app text, name text);
            CREATE TABLE wms_cabine (id serial PRIMARY KEY, numero varchar(16) UNIQUE);
            CREATE TABLE wms_emplacement (id serial PRIMARY KEY, code varchar(32));
            INSERT INTO django_migrations (app, name) VALUES ('wms', '0001_initial');
            INSERT INTO wms_cabine (numero) VALUES ('26_01_01'), ('26_01_02');
            INSERT INTO wms_emplacement (code) VALUES ('A-01');
        """)
        self.sauvegarder()
        self.dump = next(self.destination.glob("wms_*.dump"))
        # La journée continue, et une mise à jour a ajouté une table.
        self.sql("""
            DELETE FROM wms_cabine WHERE numero = '26_01_01';
            INSERT INTO wms_cabine (numero) VALUES ('26_09_09');
            CREATE TABLE wms_nouvelle (id serial PRIMARY KEY);
        """)

    def sql(self, texte):
        env = dict(os.environ, PGPASSWORD=self.reglages["PASSWORD"])
        r = subprocess.run(["psql", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1",
                            "-h", "127.0.0.1", "-p", self.reglages["PORT"], "-U", "wms",
                            "-d", self.BASE, "-c", texte],
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_restauration_complete(self):
        sortie = io.StringIO()
        call_command("restaurer", str(self.dump), oui=True, sans_filet=True, stdout=sortie)
        self.assertEqual(self.sql("SELECT string_agg(numero, ',' ORDER BY numero) "
                                  "FROM wms_cabine"), "26_01_01,26_01_02")
        # La table d'une version plus récente est partie avec le schéma : les
        # migrations du démarrage la recréeront sans buter dessus.
        self.assertEqual(self.sql("SELECT count(*) FROM pg_tables WHERE tablename = "
                                  "'wms_nouvelle'"), "0")
        # Les séquences suivent : la prochaine cabine ne heurte pas un id existant.
        self.sql("INSERT INTO wms_cabine (numero) VALUES ('26_10_10')")
        self.assertIn("3 tables, 2 cabines, 1 emplacements", sortie.getvalue())

    def test_fichier_tronque_la_base_ne_bouge_pas(self):
        """Le sommaire est en tête du fichier : `--list` le lit, la casse
        n'apparaît qu'en cours de chargement — après le DROP SCHEMA."""
        tronque = self.tmp / "wms_2026-01-01_120000.dump"
        donnees = self.dump.read_bytes()
        tronque.write_bytes(donnees[: int(len(donnees) * 0.7)])
        with self.assertRaises(CommandError):
            call_command("restaurer", str(tronque), oui=True, sans_filet=True,
                         stdout=io.StringIO())
        self.assertEqual(self.sql("SELECT string_agg(numero, ',' ORDER BY numero) "
                                  "FROM wms_cabine"), "26_01_02,26_09_09")
        self.assertEqual(self.sql("SELECT count(*) FROM pg_tables WHERE tablename = "
                                  "'wms_nouvelle'"), "1")

    def test_mauvais_mot_de_passe_rien_ne_change(self):
        with mock.patch.dict(settings.DATABASES["default"], {"PASSWORD": "faux"}):
            with self.assertRaisesMessage(CommandError, "rien n'a été modifié"):
                call_command("restaurer", str(self.dump), oui=True, sans_filet=True,
                             stdout=io.StringIO())
        self.assertEqual(self.sql("SELECT count(*) FROM wms_cabine"), "2")
