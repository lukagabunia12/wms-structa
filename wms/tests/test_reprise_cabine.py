"""Reprendre une cabine envoyée plutôt que la refuser.

L'envoi était sans retour : toute opération sur une cabine envoyée était refusée.
Une cabine sortie par erreur n'avait donc pour issue qu'une nouvelle fiche sous un
autre numéro — deux historiques pour un seul objet, et un stock qui ment.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from wms import services_cabines
from wms.models import Cabine, Emplacement, MouvementCabine, Utilisateur
from wms.services_cabines import ErreurCabine


class RepriseTest(TestCase):
    def setUp(self):
        self.u = Utilisateur.objects.create_user(
            username="op", password="x", role=Utilisateur.ADMIN)
        self.emp = Emplacement.objects.create(code="AC-100-1", rack="AC",
                                              colonne="100", niveau=1)
        self.cab = Cabine.objects.create(numero="06_00_01", chantier="100001")
        services_cabines.ranger(cabine=self.cab, emplacement=self.emp, place="G",
                                utilisateur=self.u)
        services_cabines.envoyer(cabine=self.cab, utilisateur=self.u, note="BL 42")
        self.cab.refresh_from_db()
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    # --- service --------------------------------------------------------
    def test_la_cabine_revient_en_stock(self):
        services_cabines.reprendre(cabine=self.cab, utilisateur=self.u, motif="retour chantier")
        self.cab.refresh_from_db()
        self.assertEqual(self.cab.statut, Cabine.LIBRE)
        self.assertFalse(self.cab.envoyee)
        self.assertIsNone(self.cab.envoi_date)

    def test_elle_revient_non_rangee(self):
        """Sa place a pu être réattribuée : c'est le rangement qui tranche."""
        services_cabines.reprendre(cabine=self.cab, utilisateur=self.u)
        self.cab.refresh_from_db()
        self.assertIsNone(self.cab.emplacement)
        self.assertFalse(self.cab.rangee)

    def test_l_envoi_reste_au_journal(self):
        services_cabines.reprendre(cabine=self.cab, utilisateur=self.u, motif="erreur de scan")
        types = list(self.cab.historique.order_by("date").values_list("type", flat=True))
        self.assertIn(MouvementCabine.ENVOI, types)
        self.assertEqual(types[-1], MouvementCabine.STATUT)
        dernier = self.cab.historique.order_by("-date").first()
        self.assertEqual(dernier.statut_avant, Cabine.ENVOYE)
        self.assertEqual(dernier.statut_apres, Cabine.LIBRE)
        self.assertEqual(dernier.note, "erreur de scan")

    def test_un_motif_vide_laisse_une_trace_lisible(self):
        services_cabines.reprendre(cabine=self.cab, utilisateur=self.u)
        self.assertIn("Retour en stock",
                      self.cab.historique.order_by("-date").first().note)

    def test_reprendre_une_cabine_non_envoyee_est_refuse(self):
        saine = Cabine.objects.create(numero="06_00_02", chantier="100002")
        with self.assertRaises(ErreurCabine):
            services_cabines.reprendre(cabine=saine, utilisateur=self.u)

    def test_elle_peut_etre_rangee_apres_reprise(self):
        """Le but de l'opération : pouvoir la reposer dans un rack."""
        services_cabines.reprendre(cabine=self.cab, utilisateur=self.u)
        self.cab.refresh_from_db()
        services_cabines.ranger(cabine=self.cab, emplacement=self.emp, place="D",
                                utilisateur=self.u)
        self.cab.refresh_from_db()
        self.assertEqual(self.cab.emplacement, self.emp)
        self.assertEqual(self.cab.place, "D")

    def test_ranger_reste_refuse_tant_qu_elle_est_envoyee(self):
        with self.assertRaises(ErreurCabine):
            services_cabines.ranger(cabine=self.cab, emplacement=self.emp,
                                    place="D", utilisateur=self.u)

    # --- API ------------------------------------------------------------
    def test_api_reprendre(self):
        r = self.c.post(f"/api/cabines/{self.cab.pk}/reprendre/",
                        {"motif": "revenue du chantier"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.cab.refresh_from_db()
        self.assertEqual(self.cab.statut, Cabine.LIBRE)

    def test_api_refuse_sans_le_droit_de_sortir(self):
        lecteur = Utilisateur.objects.create_user(
            username="lect", password="x", role=Utilisateur.LECTURE)
        c = APIClient()
        c.force_authenticate(lecteur)
        r = c.post(f"/api/cabines/{self.cab.pk}/reprendre/", {}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_api_message_clair_si_pas_envoyee(self):
        saine = Cabine.objects.create(numero="06_00_03", chantier="100003")
        r = self.c.post(f"/api/cabines/{saine.pk}/reprendre/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("pas envoyée", str(r.data))

    def test_la_cabine_reapparait_dans_le_stock(self):
        self.assertNotIn("06_00_01",
                         [x["numero"] for x in self.c.get("/api/cabines/").data["results"]])
        self.c.post(f"/api/cabines/{self.cab.pk}/reprendre/", {}, format="json")
        self.assertIn("06_00_01",
                      [x["numero"] for x in self.c.get("/api/cabines/").data["results"]])
