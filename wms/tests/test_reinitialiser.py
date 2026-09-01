"""Remise à zéro de la base.

Opération irréversible : ce qui est testé ici, ce sont les garde-fous — l'ordre
de suppression (une contrainte PROTECT la ferait échouer à mi-parcours), ce qui
survit, et le refus sans confirmation.
"""
from django.core.management import CommandError, call_command
from django.test import TestCase
from rest_framework.authtoken.models import Token

from wms import services, services_cabines
from wms.models import (Article, Cabine, Categorie, Emplacement, Mouvement,
                        MouvementCabine, Reception, Stock, Utilisateur, Zone)


class BaseReinit(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create_user(
            username="chef", password="motdepasse123", role=Utilisateur.ADMIN)
        Token.objects.create(user=self.admin)
        self.zone = Zone.objects.create(nom="Attente départ", role=Zone.ENVOI)
        self.emp = Emplacement.objects.create(code="C001", zone_cabine=self.zone)
        self.article = Article.objects.create(
            ref="V0001", designation="Vis M6",
            categorie=Categorie.objects.create(nom="Visserie"))
        # Du stock : c'est lui qui rend l'ordre de suppression obligatoire.
        services.entree(article=self.article, emplacement=self.emp, qte=5,
                        utilisateur=self.admin)
        cabine = Cabine.objects.create(numero="26_01_01", chantier="000123")
        services_cabines.ranger(cabine=cabine, emplacement=self.emp, place="G",
                                utilisateur=self.admin)
        services.receptionner(article=self.article, emplacement=self.emp, qte=2,
                              utilisateur=self.admin)

    def vider(self, **kw):
        call_command("reinitialiser", oui=True, sans_sauvegarde=True, verbosity=0, **kw)


class RemiseAZeroTest(BaseReinit):
    def test_tout_sauf_les_comptes(self):
        self.vider()
        for modele in (Cabine, MouvementCabine, Emplacement, Zone, Article,
                       Categorie, Stock, Mouvement, Reception):
            self.assertEqual(modele.objects.count(), 0, modele.__name__)
        # Le compte et son jeton survivent : on doit pouvoir se reconnecter.
        self.assertEqual(Utilisateur.objects.count(), 1)
        self.assertEqual(Token.objects.count(), 1)

    def test_le_stock_ne_bloque_pas_la_suppression(self):
        """`Stock.emplacement` est en PROTECT : supprimer les emplacements avant
        les lignes de stock ferait échouer l'opération à mi-parcours."""
        self.assertTrue(Stock.objects.exists())
        self.vider()
        self.assertEqual(Emplacement.objects.count(), 0)

    def test_garder_le_referentiel(self):
        self.vider(garder_referentiel=True)
        self.assertEqual(Emplacement.objects.count(), 1)
        self.assertEqual(Zone.objects.count(), 1)
        self.assertEqual(Cabine.objects.count(), 0)
        self.assertEqual(Article.objects.count(), 0)
        # Le stock part quand même : il porte sur des articles qui n'existent plus.
        self.assertEqual(Stock.objects.count(), 0)

    def test_tout_y_compris_les_comptes(self):
        self.vider(tout=True)
        self.assertEqual(Utilisateur.objects.count(), 0)
        self.assertEqual(Token.objects.count(), 0)

    def test_sans_confirmation_rien_n_est_efface(self):
        with self.assertRaises((CommandError, EOFError, OSError)):
            call_command("reinitialiser", sans_sauvegarde=True, verbosity=0)
        self.assertEqual(Cabine.objects.count(), 1)
        self.assertEqual(Emplacement.objects.count(), 1)

    def test_rejouable_sur_une_base_deja_vide(self):
        self.vider()
        self.vider()
        self.assertEqual(Cabine.objects.count(), 0)

    def test_une_base_neuve_fonctionne_apres(self):
        """Le vrai test : l'entrepôt se reconstruit sans rien casser."""
        self.vider()
        zone = Zone.objects.create(nom="Rack A", role=Zone.RANGEMENT)
        emp = Emplacement.objects.create(code="A001", zone_cabine=zone)
        cabine = Cabine.objects.create(numero="26_02_01", chantier="000200")
        services_cabines.ranger(cabine=cabine, emplacement=emp, place="G")
        self.assertEqual(Cabine.objects.get(numero="26_02_01").position, "A001·G")
