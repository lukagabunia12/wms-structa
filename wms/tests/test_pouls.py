"""L'empreinte d'activité que les écrans interrogent pour se tenir à jour.

Elle doit être exacte — un écran qui ne se rafraîchit pas ment sans le dire —
et rester bon marché : elle est appelée toutes les dix secondes par poste.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from wms import services_cabines
from wms.models import Cabine, Emplacement, Utilisateur, Zone


class PoulsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.u = Utilisateur.objects.create_user(
            username="pouls", password="x", role=Utilisateur.ADMIN)
        cls.zone = Zone.objects.create(nom="Rangement", role=Zone.RANGEMENT)
        cls.emp = Emplacement.objects.create(code="AC-100-1", rack="AC",
                                             zone_cabine=cls.zone)
        cls.cab = Cabine.objects.create(numero="26_03_47", chantier="260204")

    def setUp(self):
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def pouls(self):
        r = self.c.get("/api/pouls/")
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def test_les_compteurs_sont_la(self):
        self.assertEqual(sorted(self.pouls()),
                         ["alertes", "alertes_empreinte", "cabines", "dernier", "dernier_mp",
                          "emplacements", "mouvements", "mouvements_mp"])

    def test_sans_compte_la_porte_est_fermee(self):
        self.assertEqual(APIClient().get("/api/pouls/").status_code, 401)

    def test_un_rangement_fait_bouger_l_empreinte(self):
        avant = self.pouls()
        services_cabines.ranger(cabine=self.cab, emplacement=self.emp,
                                place="G", utilisateur=self.u)
        apres = self.pouls()
        self.assertGreater(apres["mouvements"], avant["mouvements"])
        self.assertGreater(apres["dernier"], avant["dernier"])

    def test_une_cabine_creee_fait_bouger_l_empreinte(self):
        avant = self.pouls()
        Cabine.objects.create(numero="26_03_48", chantier="260204")
        self.assertEqual(self.pouls()["cabines"], avant["cabines"] + 1)

    def test_un_emplacement_cree_fait_bouger_l_empreinte(self):
        avant = self.pouls()
        Emplacement.objects.create(code="AC-100-2", rack="AC", zone_cabine=self.zone)
        self.assertEqual(self.pouls()["emplacements"], avant["emplacements"] + 1)

    def test_rien_ne_bouge_si_rien_ne_se_passe(self):
        self.assertEqual(self.pouls(), self.pouls())

    def test_l_empreinte_coute_peu(self):
        """Quelques agrégats, pas une requête par cabine : c'est appelé en boucle."""
        for i in range(20):
            Cabine.objects.create(numero=f"27_00_{i:02d}", chantier="270000")
        # Six requêtes, quel que soit le nombre de cabines : le MAX et le COUNT
        # des mouvements tiennent dans la même, de même pour le journal MP, un
        # COUNT par table, et deux pour la cloche — les codes sous leur seuil
        # (un agrégat) et les lignes hors réservation (un EXISTS).
        with self.assertNumQueries(6):
            self.c.get("/api/pouls/")
