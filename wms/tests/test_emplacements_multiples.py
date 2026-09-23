"""Une cabine occupe un emplacement — parfois plusieurs.

Rien n'est déclaré à l'avance : on ne sait pas avant de décharger si une cabine
tiendra en un ou deux endroits. Elle est rangée dès qu'elle est quelque part, et
le cariste ajoute un emplacement s'il en trouve un second.

Ces tests fixent surtout ce qui NE change pas : le cas courant — une cabine, un
emplacement — doit se comporter exactement comme avant.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from wms import services_cabines
from wms.models import Emplacement, Utilisateur, Zone
from wms.services_cabines import ErreurCabine


class BaseMulti(TestCase):
    def setUp(self):
        self.u = Utilisateur.objects.create_user(
            username="op", password="x", role=Utilisateur.ADMIN)
        self.zone = Zone.objects.create(nom="Hall", role=Zone.RANGEMENT)
        self.e1 = Emplacement.objects.create(code="AC-100-1", rack="AC", colonne="100",
                                             niveau=1, zone_cabine=self.zone)
        self.e2 = Emplacement.objects.create(code="AC-110-1", rack="AC", colonne="110",
                                             niveau=1, zone_cabine=self.zone)
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def cabine(self, numero="08_00_01"):
        return services_cabines.creer_cabine(numero=numero, chantier="100001",
                                             utilisateur=self.u)


class LeCasCourantNeChangePasTest(BaseMulti):
    def test_une_cabine_neuve_n_est_nulle_part(self):
        cabine = self.cabine()
        self.assertFalse(cabine.rangee)
        self.assertEqual(cabine.position, "")
        self.assertEqual(cabine.rangement_libelle, "Non rangé")

    def test_rangee_des_le_premier_emplacement(self):
        cabine = self.cabine()
        services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="G",
                                utilisateur=self.u)
        cabine.refresh_from_db()
        self.assertTrue(cabine.rangee)
        self.assertEqual(cabine.position, "AC-100-1·G")
        self.assertEqual(cabine.rangement_libelle, "Rangé")

    def test_ranger_ailleurs_deplace_par_defaut(self):
        """Sans rien préciser, une cabine déjà rangée est DÉPLACÉE, comme avant."""
        cabine = self.cabine()
        services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="G",
                                utilisateur=self.u)
        services_cabines.ranger(cabine=cabine, emplacement=self.e2, place="D",
                                utilisateur=self.u)
        cabine.refresh_from_db()
        self.assertEqual(cabine.position, "AC-110-1·D")
        self.assertEqual(len(cabine.emplacements_occupes), 1)
        # L'ancienne place est libérée.
        self.assertIn("G", services_cabines.places_libres(self.e1))

    def test_le_deplacement_est_journalise_comme_transfert(self):
        cabine = self.cabine()
        services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="G",
                                utilisateur=self.u)
        services_cabines.ranger(cabine=cabine, emplacement=self.e2, place="D",
                                utilisateur=self.u)
        dernier = cabine.historique.order_by("-date").first()
        self.assertEqual(dernier.type, "transfert")


class AjouterUnEmplacementTest(BaseMulti):
    """Le cas rare : la cabine ne tient pas dans un seul emplacement."""

    def test_ajouter_ne_libere_pas_le_premier(self):
        cabine = self.cabine()
        services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="G",
                                utilisateur=self.u)
        services_cabines.ranger(cabine=cabine, emplacement=self.e2, place="D",
                                ajouter=True, utilisateur=self.u)
        cabine.refresh_from_db()
        self.assertEqual(cabine.position, "AC-100-1·G, AC-110-1·D")
        self.assertEqual(len(cabine.emplacements_occupes), 2)
        # La première place reste prise.
        self.assertNotIn("G", services_cabines.places_libres(self.e1))

    def test_elle_reste_rangee(self):
        cabine = self.cabine()
        services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="G",
                                utilisateur=self.u)
        services_cabines.ranger(cabine=cabine, emplacement=self.e2, place="D",
                                ajouter=True, utilisateur=self.u)
        cabine.refresh_from_db()
        self.assertTrue(cabine.rangee)
        self.assertEqual(cabine.rangement_libelle, "Rangé · 2 emplacements")

    def test_l_ajout_est_journalise_comme_rangement(self):
        """Rien n'a été libéré : ce n'est pas un transfert."""
        cabine = self.cabine()
        services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="G",
                                utilisateur=self.u)
        services_cabines.ranger(cabine=cabine, emplacement=self.e2, place="D",
                                ajouter=True, utilisateur=self.u)
        dernier = cabine.historique.order_by("-date").first()
        self.assertEqual(dernier.type, "rangement")
        self.assertIn("supplémentaire", dernier.note)

    def test_trois_emplacements(self):
        cabine = self.cabine()
        e3 = Emplacement.objects.create(code="AC-120-1", rack="AC", colonne="120",
                                        niveau=1, zone_cabine=self.zone)
        for emp, place in ((self.e1, "G"), (self.e2, "D"), (e3, "G")):
            services_cabines.ranger(cabine=cabine, emplacement=emp, place=place,
                                    ajouter=True, utilisateur=self.u)
        cabine.refresh_from_db()
        self.assertEqual(len(cabine.emplacements_occupes), 3)

    def test_deux_cabines_ne_partagent_pas_une_place(self):
        a = self.cabine("08_00_10")
        b = self.cabine("08_00_11")
        services_cabines.ranger(cabine=a, emplacement=self.e1, place="G",
                                utilisateur=self.u)
        with self.assertRaises(ErreurCabine) as erreur:
            services_cabines.ranger(cabine=b, emplacement=self.e1, place="G",
                                    utilisateur=self.u)
        self.assertIn("08_00_10", str(erreur.exception))

    def test_une_cabine_ne_se_range_pas_deux_fois_a_la_meme_place(self):
        cabine = self.cabine()
        services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="G",
                                utilisateur=self.u)
        with self.assertRaises(ErreurCabine):
            services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="G",
                                    ajouter=True, utilisateur=self.u)


class ApiTest(BaseMulti):
    def test_ranger_avec_ajouter(self):
        cabine = self.cabine()
        self.c.post(f"/api/cabines/{cabine.pk}/ranger/",
                    {"emplacement": self.e1.pk, "place": "G"}, format="json")
        r = self.c.post(f"/api/cabines/{cabine.pk}/ranger/",
                        {"emplacement": self.e2.pk, "place": "D", "ajouter": True},
                        format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["occupations"]), 2)
        self.assertEqual(r.data["nb_emplacements"], 2)

    def test_ranger_sans_ajouter_deplace(self):
        cabine = self.cabine()
        self.c.post(f"/api/cabines/{cabine.pk}/ranger/",
                    {"emplacement": self.e1.pk, "place": "G"}, format="json")
        r = self.c.post(f"/api/cabines/{cabine.pk}/ranger/",
                        {"emplacement": self.e2.pk, "place": "D"}, format="json")
        self.assertEqual(r.data["nb_emplacements"], 1)
        self.assertEqual(r.data["position"], "AC-110-1·D")

    def test_la_fiche_liste_les_emplacements(self):
        cabine = self.cabine()
        services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="G",
                                utilisateur=self.u)
        services_cabines.ranger(cabine=cabine, emplacement=self.e2, place="D",
                                ajouter=True, utilisateur=self.u)
        d = self.c.get(f"/api/cabines/{cabine.pk}/").data
        self.assertEqual(d["nb_emplacements"], 2)
        self.assertEqual([o["position"] for o in d["occupations"]],
                         ["AC-100-1·G", "AC-110-1·D"])
        self.assertTrue(d["rangee"])

    def test_l_api_places_nomme_la_cabine(self):
        cabine = self.cabine()
        services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="D",
                                utilisateur=self.u)
        d = self.c.get(f"/api/emplacements/{self.e1.pk}/places/").data
        droite = next(p for p in d["places"] if p["code"] == "D")
        self.assertFalse(droite["libre"])
        self.assertEqual(droite["cabine"]["numero"], cabine.numero)
        self.assertEqual(droite["occupation"]["position"], "AC-100-1·D")

    def test_creer_une_cabine_ne_demande_aucun_nombre(self):
        r = self.c.post("/api/cabines/", {"numero": "08_00_20", "chantier": "100002"},
                        format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["nb_emplacements"], 0)
        self.assertFalse(r.data["rangee"])


class SortieEtEnvoiTest(BaseMulti):
    def cabine_a_deux_endroits(self, numero="08_00_30"):
        cabine = self.cabine(numero)
        services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="G",
                                utilisateur=self.u)
        services_cabines.ranger(cabine=cabine, emplacement=self.e2, place="D",
                                ajouter=True, utilisateur=self.u)
        return cabine

    def test_envoyer_libere_tout(self):
        cabine = self.cabine_a_deux_endroits()
        services_cabines.envoyer(cabine=cabine, utilisateur=self.u, note="départ chantier")
        cabine.refresh_from_db()
        self.assertEqual(cabine.position, "")
        self.assertIn("G", services_cabines.places_libres(self.e1))
        self.assertIn("D", services_cabines.places_libres(self.e2))

    def test_l_envoi_note_les_deux_positions(self):
        cabine = self.cabine_a_deux_endroits()
        services_cabines.envoyer(cabine=cabine, utilisateur=self.u, note="départ chantier")
        envoi = cabine.historique.filter(type="envoi").first()
        self.assertIn("AC-100-1·G", envoi.depuis)
        self.assertIn("AC-110-1·D", envoi.depuis)


class FiltresTest(BaseMulti):
    def numeros(self, url):
        r = self.c.get(url)
        self.assertEqual(r.status_code, 200, r.data)
        return sorted(x["numero"] for x in r.data["results"])

    def test_une_cabine_a_deux_endroits_est_rangee(self):
        cabine = self.cabine("08_00_40")
        services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="G",
                                utilisateur=self.u)
        services_cabines.ranger(cabine=cabine, emplacement=self.e2, place="D",
                                ajouter=True, utilisateur=self.u)
        self.assertIn("08_00_40", self.numeros("/api/cabines/?rangee=1"))
        self.assertNotIn("08_00_40", self.numeros("/api/cabines/?rangee=0"))

    def test_le_filtre_rack_ne_rend_pas_de_doublon(self):
        cabine = self.cabine("08_00_41")
        services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="G",
                                utilisateur=self.u)
        services_cabines.ranger(cabine=cabine, emplacement=self.e2, place="D",
                                ajouter=True, utilisateur=self.u)
        self.assertEqual(self.c.get("/api/cabines/?rack=AC").data["count"], 1)

    def test_une_cabine_nulle_part_est_non_rangee(self):
        self.cabine("08_00_42")
        self.assertIn("08_00_42", self.numeros("/api/cabines/?rangee=0"))


class SuppressionEmplacementTest(BaseMulti):
    def test_un_emplacement_occupe_ne_se_supprime_pas(self):
        cabine = self.cabine()
        services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="G",
                                utilisateur=self.u)
        from wms.services_emplacements import diagnostic_suppression
        self.assertIn("1 cabine", diagnostic_suppression(self.e1))
