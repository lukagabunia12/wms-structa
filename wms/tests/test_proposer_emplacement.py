"""« Où est-ce que celle-ci rentre ? » — la question posée devant le rack.

Deux défauts, un seul remède. L'écran listait les places libres « en général »,
sans savoir quelle cabine il rangeait : un grand modèle, qui prend l'emplacement
entier, se voyait proposer une place où il ne tient pas, et le serveur refusait
après coup — la cabine déjà descendue du rack. Et rien ne permettait de demander
au WMS de chercher, alors qu'il est le seul à connaître l'état de deux cents
emplacements.

Ce qui est vérifié ici :

- chaque emplacement répond POUR la cabine qu'on tient ;
- un refus dit toujours POURQUOI. « Complet » devant une place qu'on voit vide
  fait douter de l'écran ; « ce modèle prend l'emplacement entier » se comprend ;
- l'ordre des propositions est celui de l'entrepôt : finir un emplacement
  entamé avant d'en ouvrir un autre, parce que les grands modèles n'acceptent
  que les emplacements entiers ;
- le tout en un nombre de requêtes qui ne suit PAS le nombre d'emplacements.
"""
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from wms import services_cabines
from wms.models import (CabineAttendue, Emplacement, ModeleCabine, Occupation,
                        Utilisateur, Zone)


class BaseProposition(APITestCase):
    def setUp(self):
        self.user = Utilisateur.objects.create_user(
            username="op", password="secret123", role=Utilisateur.ADMIN, nom="Luka G.")
        self.client.force_authenticate(user=self.user)
        self.zone = Zone.objects.create(nom="Rack A", ordre=1)
        ModeleCabine.objects.update_or_create(
            cle="DUO", defaults={"nom": "DUO", "grand": False})
        ModeleCabine.objects.update_or_create(
            cle="QUATTRO", defaults={"nom": "QUATTRO", "grand": True})
        # A001 sera entamé, A002 restera vide : c'est la paire qui décide de
        # l'ordre des propositions.
        self.a1 = Emplacement.objects.create(code="A001", zone_cabine=self.zone)
        self.a2 = Emplacement.objects.create(code="A002", zone_cabine=self.zone)

    def cabine(self, numero, modele="DUO"):
        CabineAttendue.objects.create(numero=numero, modele=modele, chantier="000123")
        return services_cabines.creer_cabine(
            numero=numero, chantier="000123", modele=modele, utilisateur=self.user)

    def ligne(self, lignes, code):
        return next(ligne for ligne in lignes if ligne["emplacement"].code == code)


class OrdreDesPropositionsTest(BaseProposition):
    def test_on_finit_un_emplacement_entame_avant_d_en_ouvrir_un_autre(self):
        """La règle qui garde des emplacements ENTIERS pour les grands modèles."""
        occupante = self.cabine("00_00_01")
        services_cabines.ranger(cabine=occupante, emplacement=self.a1,
                                place=Occupation.GAUCHE, utilisateur=self.user)

        lignes = services_cabines.emplacements_pour(self.cabine("00_00_02"))
        codes = [ligne["emplacement"].code for ligne in lignes if ligne["possible"]]
        self.assertEqual(codes[0], "A001",
                         "l'emplacement entamé doit venir avant l'emplacement vide")
        self.assertIn("A002", codes)

    def test_une_zone_de_reception_ne_se_propose_pas_en_premier(self):
        """On y dépose en attendant : la proposer comme destination tourne en rond."""
        Emplacement.objects.create(code="ARANGER", staging=True,
                                   mode_places=Emplacement.ILLIMITE)
        lignes = services_cabines.emplacements_pour(self.cabine("00_00_03"))
        possibles = [ligne["emplacement"].code for ligne in lignes if ligne["possible"]]
        self.assertIn("ARANGER", possibles)
        self.assertEqual(possibles[-1], "ARANGER")


class GabaritTest(BaseProposition):
    def test_un_grand_modele_n_accepte_que_les_emplacements_entiers(self):
        voisine = self.cabine("00_00_01")
        services_cabines.ranger(cabine=voisine, emplacement=self.a1,
                                place=Occupation.GAUCHE, utilisateur=self.user)

        lignes = services_cabines.emplacements_pour(self.cabine("00_00_09", "QUATTRO"))
        entame = self.ligne(lignes, "A001")
        vide = self.ligne(lignes, "A002")
        self.assertFalse(entame["possible"])
        self.assertIn("entier", entame["pourquoi"],
                      "le refus doit nommer la règle, pas dire « complet »")
        self.assertTrue(vide["possible"])
        self.assertEqual(vide["libres"], [Occupation.ENTIER])

    def test_une_place_condamnee_ferme_l_emplacement_aux_grands_modeles(self):
        services_cabines.condamner_place(emplacement=self.a1, place=Occupation.DROITE,
                                         motif="pilier", utilisateur=self.user)
        lignes = services_cabines.emplacements_pour(self.cabine("00_00_09", "QUATTRO"))
        entame = self.ligne(lignes, "A001")
        self.assertFalse(entame["possible"])
        self.assertIn("condamnée", entame["pourquoi"])

        # …mais une cabine ordinaire prend l'autre place, et l'écran doit le dire.
        ordinaire = self.ligne(
            services_cabines.emplacements_pour(self.cabine("00_00_04")), "A001")
        self.assertTrue(ordinaire["possible"])
        self.assertEqual(ordinaire["libres"], [Occupation.GAUCHE])

    def test_un_emplacement_hors_service_dit_son_motif(self):
        services_cabines.changer_activation(emplacement=self.a1, actif=False,
                                            motif="rack en réparation",
                                            utilisateur=self.user)
        ligne = self.ligne(services_cabines.emplacements_pour(self.cabine("00_00_05")),
                           "A001")
        self.assertFalse(ligne["possible"])
        self.assertIn("rack en réparation", ligne["pourquoi"])

    def test_un_refus_a_TOUJOURS_une_raison(self):
        """Sans raison, « complet » devant une place vide fait douter de l'écran."""
        services_cabines.ranger(cabine=self.cabine("00_00_01"), emplacement=self.a1,
                                place=Occupation.GAUCHE, utilisateur=self.user)
        services_cabines.ranger(cabine=self.cabine("00_00_02"), emplacement=self.a1,
                                place=Occupation.DROITE, utilisateur=self.user)
        services_cabines.changer_activation(emplacement=self.a2, actif=False,
                                            motif="allée bloquée", utilisateur=self.user)
        for ligne in services_cabines.emplacements_pour(self.cabine("00_00_06")):
            if not ligne["possible"]:
                self.assertTrue(ligne["pourquoi"].strip(),
                                f"{ligne['emplacement'].code} refuse sans dire pourquoi")


class ApiPropositionTest(BaseProposition):
    def test_l_api_propose_le_meilleur_et_compte_les_possibles(self):
        cab = self.cabine("00_00_07")
        r = self.client.get(f"/api/emplacements/pour_cabine/?cabine={cab.id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["possibles"], 2)
        self.assertEqual(r.data["proposition"], self.a1.id)
        self.assertFalse(r.data["cabine"]["tout_l_emplacement"])
        premier = r.data["emplacements"][0]
        self.assertEqual(premier["code"], "A001")
        self.assertEqual(premier["libres"], [Occupation.GAUCHE, Occupation.DROITE])

    def test_sans_emplacement_possible_la_proposition_est_vide(self):
        """L'écran doit pouvoir dire « aucun », pas rester muet."""
        cab = self.cabine("00_00_09", "QUATTRO")
        for emplacement in (self.a1, self.a2):
            services_cabines.changer_activation(emplacement=emplacement, actif=False,
                                                motif="rack démonté",
                                                utilisateur=self.user)
        r = self.client.get(f"/api/emplacements/pour_cabine/?cabine={cab.id}")
        self.assertEqual(r.data["possibles"], 0)
        self.assertIsNone(r.data["proposition"])

    def test_la_recherche_filtre_sans_perdre_le_gabarit(self):
        Emplacement.objects.create(code="B001", zone_cabine=self.zone)
        cab = self.cabine("00_00_08")
        r = self.client.get(f"/api/emplacements/pour_cabine/?cabine={cab.id}&q=B00")
        codes = [e["code"] for e in r.data["emplacements"]]
        self.assertEqual(codes, ["B001"])

    def test_sans_cabine_l_api_refuse_au_lieu_de_deviner(self):
        r = self.client.get("/api/emplacements/pour_cabine/")
        self.assertEqual(r.status_code, 400)

    def test_le_cout_ne_suit_pas_le_nombre_d_emplacements(self):
        """Deux requêtes pour tout l'entrepôt, pas deux par emplacement.

        La façon naïve interroge les occupations et les places condamnées
        emplacement par emplacement. Sur un entrepôt réel, l'écran devient
        injouable — et c'est l'écran qu'on utilise le plus.
        """
        cab = self.cabine("00_00_07")
        avec_deux = self._requetes(cab)
        Emplacement.objects.bulk_create(
            [Emplacement(code=f"C{i:03d}", zone_cabine=self.zone) for i in range(20)])
        self.assertEqual(self._requetes(cab), avec_deux,
                         "le coût suit le nombre d'emplacements : la lecture "
                         "groupée a été remplacée par une boucle")

    def _requetes(self, cabine):
        with CaptureQueriesContext(connection) as capture:
            r = self.client.get(f"/api/emplacements/pour_cabine/?cabine={cabine.id}")
            self.assertEqual(r.status_code, 200)
        return len(capture.captured_queries)
