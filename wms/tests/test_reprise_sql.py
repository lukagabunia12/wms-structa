"""Reprise des données vers un serveur SQL.

Le risque d'une reprise n'est pas qu'elle échoue : c'est qu'elle réussisse à
moitié. Ces tests portent sur le garde-fou — le manifeste de comptages — et non
sur le transfert lui-même, que `dumpdata`/`loaddata` assurent.
"""
import json
import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from wms.management.commands.reprise_sql import Command, modeles_a_recaler
from wms.models import Cabine, Emplacement, ModeleCabine, Utilisateur


class RepriseTest(TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        Utilisateur.objects.create_user(username="chef", password="motdepasse123",
                                        role=Utilisateur.ADMIN)
        Emplacement.objects.create(code="C001")
        Cabine.objects.create(numero="26_01_01", chantier="000123")

    def exporter(self):
        call_command("reprise_sql", "exporter", vers=str(self.dossier), verbosity=0)
        return json.loads((self.dossier / "manifeste.json").read_text(encoding="utf-8"))

    def test_le_manifeste_compte_ce_qui_est_exporte(self):
        manifeste = self.exporter()
        self.assertEqual(manifeste["comptages"]["wms.emplacement"], 1)
        self.assertEqual(manifeste["comptages"]["wms.cabine"], 1)
        self.assertEqual(manifeste["comptages"]["wms.utilisateur"], 1)
        self.assertTrue((self.dossier / "donnees.json").is_file())

    def test_les_tables_de_django_sont_exclues(self):
        """Les types de contenu et les permissions sont recréés par `migrate` :
        les réimporter provoque des doublons de clé — l'erreur classique."""
        manifeste = self.exporter()
        for exclu in ["contenttypes.contenttype", "auth.permission",
                      "sessions.session", "admin.logentry"]:
            self.assertNotIn(exclu, manifeste["comptages"])

    def test_les_modeles_mandataires_ne_comptent_pas_deux_fois(self):
        """`authtoken.tokenproxy` partage la table de `authtoken.token` : compté,
        il gonflerait le total d'un manifeste censé être vérifiable."""
        manifeste = self.exporter()
        self.assertIn("authtoken.token", manifeste["comptages"])
        self.assertNotIn("authtoken.tokenproxy", manifeste["comptages"])
        self.assertEqual(manifeste["total"], sum(manifeste["comptages"].values()))

    def test_export_refuse_une_base_vide(self):
        Cabine.objects.all().delete()
        Emplacement.objects.all().delete()
        Utilisateur.objects.all().delete()
        # Les grands modèles semés par la migration 0020 comptent des lignes :
        # sans les retirer, la base n'est plus « vide » et rien ne serait refusé.
        ModeleCabine.objects.all().delete()
        with self.assertRaisesMessage(CommandError, "vide"):
            call_command("reprise_sql", "exporter", vers=str(self.dossier), verbosity=0)

    def test_une_base_fraichement_migree_accepte_la_reprise(self):
        """Le cas de la remise en service, et il a failli être cassé.

        Une base neuve n'est pas vide : la migration 0020 y sème les six grands
        modèles. Le contrôle « la base cible n'est pas vide » les comptait, et
        refusait donc la reprise exactement le jour où elle doit marcher — avec
        un message qui aurait envoyé chercher des données inexistantes.

        Le chargement doit aussi passer : les mêmes modèles arrivent dans le
        fichier, et `ModeleCabine.cle` est unique.
        """
        manifeste = self.exporter()
        Cabine.objects.all().delete()
        Emplacement.objects.all().delete()
        Utilisateur.objects.all().delete()
        # Ce que `migrate` laisse sur une base neuve, et rien d'autre.
        self.assertTrue(ModeleCabine.objects.exists())

        call_command("reprise_sql", "importer", depuis=str(self.dossier), verbosity=0)
        self.assertEqual(Cabine.objects.count(), 1)
        self.assertEqual(Emplacement.objects.count(), 1)
        self.assertEqual(ModeleCabine.objects.count(),
                         manifeste["comptages"]["wms.modelecabine"])

    def test_import_refuse_une_base_deja_peuplee(self):
        """Charger par-dessus des données existantes produit des doublons de clé."""
        self.exporter()
        with self.assertRaisesMessage(CommandError, "n'est pas vide"):
            call_command("reprise_sql", "importer", depuis=str(self.dossier), verbosity=0)

    def test_la_verification_detecte_une_ligne_manquante(self):
        """Le cas qu'on veut attraper : une reprise qui a l'air d'avoir marché."""
        self.exporter()
        Cabine.objects.all().delete()          # une table perdue en route
        with self.assertRaisesMessage(CommandError, "ne correspond pas"):
            call_command("reprise_sql", "verifier", depuis=str(self.dossier), verbosity=0)

    def test_la_verification_passe_sur_des_donnees_intactes(self):
        self.exporter()
        call_command("reprise_sql", "verifier", depuis=str(self.dossier), verbosity=0)

    def test_import_sans_export_prealable_est_explicite(self):
        with self.assertRaisesMessage(CommandError, "Fichier manquant"):
            call_command("reprise_sql", "importer", depuis=str(self.dossier / "vide"),
                         verbosity=0)


class RecalageDesSequences(TestCase):
    """La reprise sur PostgreSQL doit recaler TOUTES les séquences importées.

    Le défaut corrigé ici ne se voyait pas sur SQLite — qui n'a pas de
    séquences — et pas non plus au premier essai sur PostgreSQL : il se
    déclarait la première fois qu'on associait un compte à un groupe, des
    semaines après la mise en service, en « duplicate key ».
    """

    def test_les_tables_de_liaison_sont_couvertes(self):
        tables = {m._meta.db_table for m in modeles_a_recaler()}
        # Créées automatiquement par Django, donc absentes de get_models()
        # sans include_auto_created=True.
        self.assertIn("wms_utilisateur_groups", tables)
        self.assertIn("wms_utilisateur_user_permissions", tables)

    def test_les_tables_metier_sont_couvertes(self):
        tables = {m._meta.db_table for m in modeles_a_recaler()}
        for attendue in ("wms_emplacement", "wms_occupation", "wms_placecondamnee",
                         "wms_cabine", "wms_mouvementcabine", "wms_cabineattendue",
                         "wms_modelecabine", "wms_utilisateur", "wms_zone"):
            self.assertIn(attendue, tables)

    def test_les_tables_gerees_par_migrate_sont_exclues(self):
        """Mêmes exclusions que le manifeste : ce qu'on n'importe pas, on ne recale pas."""
        tables = {m._meta.db_table for m in modeles_a_recaler()}
        for exclue in ("django_content_type", "auth_permission",
                       "django_admin_log", "django_session"):
            self.assertNotIn(exclue, tables)

    def test_aucun_modele_mandataire(self):
        """Un proxy partage la table de son modèle concret : le recaler ferait doublon."""
        self.assertFalse([m for m in modeles_a_recaler() if m._meta.proxy])

    def test_le_recalage_ne_fait_rien_hors_postgresql(self):
        """Sur SQLite la méthode sort immédiatement : la suite tourne sans PostgreSQL."""
        from django.db import connection
        if connection.vendor == "postgresql":
            self.skipTest("Ce test décrit le comportement hors PostgreSQL.")
        Command._recaler_sequences()   # ne doit rien lever
