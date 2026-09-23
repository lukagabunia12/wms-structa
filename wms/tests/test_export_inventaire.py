"""L'export de l'inventaire : ce qu'Excel recevra, vérifié ligne par ligne.

Un export faux ne se voit pas : il s'ouvre, il a des colonnes, il a l'air juste.
D'où des tests qui lisent réellement le fichier produit.
"""
import csv
import io

from django.test import TestCase
from rest_framework.test import APIClient

from wms import services_cabines
from wms.export_inventaire import COLONNES
from wms.models import Cabine, Emplacement, Utilisateur, Zone


class ExportInventaireTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.u = Utilisateur.objects.create_user(
            username="export", password="x", role=Utilisateur.ADMIN)
        cls.zone = Zone.objects.create(nom="Hall AC", role=Zone.RANGEMENT)
        cls.e1 = Emplacement.objects.create(code="AC5601", rack="AC", zone_cabine=cls.zone)
        cls.e2 = Emplacement.objects.create(code="AC5602", rack="AC", zone_cabine=cls.zone)
        # Rangée à un endroit.
        cls.simple = Cabine.objects.create(numero="26_03_47", chantier="260204",
                                           modele="Duo 120")
        services_cabines.ranger(cabine=cls.simple, emplacement=cls.e1, place="G",
                                utilisateur=cls.u)
        # Rangée à deux endroits.
        cls.double = Cabine.objects.create(numero="26_03_48", chantier="260204")
        services_cabines.ranger(cabine=cls.double, emplacement=cls.e1, place="D",
                                utilisateur=cls.u)
        services_cabines.ranger(cabine=cls.double, emplacement=cls.e2, place="G",
                                utilisateur=cls.u, ajouter=True)
        # Rangée nulle part.
        cls.orpheline = Cabine.objects.create(numero="26_03_49", chantier="260204")

    def setUp(self):
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def fichier(self, requete=""):
        r = self.c.get("/api/cabines/export/" + requete)
        self.assertEqual(r.status_code, 200, r)
        return b"".join(r.streaming_content).decode("utf-8-sig")

    def lignes(self, requete=""):
        return list(csv.DictReader(io.StringIO(self.fichier(requete)), delimiter=";"))

    # --- ce qu'Excel doit pouvoir lire -------------------------------------
    def test_le_fichier_commence_par_le_bom(self):
        """Sans BOM, Excel affiche « CabÃ¯ne » au lieu de « Cabine »."""
        r = self.c.get("/api/cabines/export/")
        self.assertTrue(b"".join(r.streaming_content).startswith(b"\xef\xbb\xbf"))

    def test_le_separateur_est_le_point_virgule(self):
        self.assertIn(";", self.fichier().splitlines()[0])

    def test_le_nom_du_fichier_porte_la_date(self):
        r = self.c.get("/api/cabines/export/")
        self.assertRegex(r["Content-Disposition"],
                         r'attachment; filename="inventaire-cabines-\d{4}-\d{2}-\d{2}\.csv"')

    def test_les_colonnes_sont_celles_annoncees(self):
        self.assertEqual(list(self.lignes()[0].keys()), COLONNES)

    # --- une ligne par emplacement, jamais par cabine -----------------------
    def test_une_cabine_a_deux_endroits_donne_deux_lignes(self):
        lignes = [x for x in self.lignes() if x["N° cabine"] == "26_03_48"]
        self.assertEqual(len(lignes), 2)
        self.assertEqual(sorted(x["Emplacement"] for x in lignes), ["AC5601", "AC5602"])

    def test_une_cabine_rangee_nulle_part_reste_dans_l_inventaire(self):
        """C'est justement celle qu'on cherche : elle ne doit pas disparaître."""
        lignes = [x for x in self.lignes() if x["N° cabine"] == "26_03_49"]
        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes[0]["Emplacement"], "")
        self.assertEqual(lignes[0]["Rangement"], "Non rangé")

    def test_la_position_est_complete(self):
        ligne = [x for x in self.lignes() if x["N° cabine"] == "26_03_47"][0]
        self.assertEqual(ligne["Rack"], "AC")
        self.assertEqual(ligne["Emplacement"], "AC5601")
        self.assertEqual(ligne["Place"], "G")
        self.assertEqual(ligne["Zone"], "Hall AC")

    def test_les_libelles_sont_en_clair(self):
        ligne = self.lignes()[0]
        self.assertEqual(ligne["Statut"], "Conforme")
        self.assertEqual(ligne["Type"], "Normale")

    # --- l'export suit les filtres de l'écran -------------------------------
    def test_le_filtre_de_l_ecran_s_applique(self):
        numeros = {ligne["N° cabine"] for ligne in self.lignes("?rangee=0")}
        self.assertEqual(numeros, {"26_03_49"})

    def test_la_recherche_s_applique(self):
        numeros = {ligne["N° cabine"] for ligne in self.lignes("?search=26_03_47")}
        self.assertEqual(numeros, {"26_03_47"})

    def test_les_envoyees_sont_hors_inventaire_par_defaut(self):
        services_cabines.envoyer(cabine=self.orpheline, utilisateur=self.u, note="départ chantier")
        numeros = {ligne["N° cabine"] for ligne in self.lignes()}
        self.assertNotIn("26_03_49", numeros)
        self.assertIn("26_03_49", {ligne["N° cabine"] for ligne in self.lignes("?toutes=1")})

    # --- la porte est fermée sans compte ------------------------------------
    def test_sans_compte_pas_d_inventaire(self):
        self.assertEqual(APIClient().get("/api/cabines/export/").status_code, 401)
