"""Génération d'un rack entier et impression par colonne.

Créer un rack de 10 colonnes sur 3 niveaux à la main, c'est 30 formulaires
identiques — et une faute de frappe garantie quelque part. Le générateur produit
les codes, et surtout les montre AVANT d'écrire quoi que ce soit.
"""
from rest_framework.test import APITestCase

from wms import services_emplacements
from wms.models import Emplacement, Utilisateur


class BaseRack(APITestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create_user(
            username="chef", password="motdepasse123", role=Utilisateur.ADMIN)
        self.client.force_authenticate(user=self.admin)

    def generer(self, **kw):
        corps = {"prefixe": "AC", "debut": "550", "pas": 10, "colonnes": 10, "niveaux": 3}
        corps.update(kw)
        return self.client.post("/api/emplacements/generer/", corps, format="json")


class CodesGeneresTest(BaseRack):
    def test_exemple_de_l_exploitation(self):
        """Rack AC, 10 colonnes à partir de 550, pas de 10, 3 niveaux."""
        codes = [x["code"] for x in services_emplacements.codes_de_rack(
            prefixe="AC", debut="550", pas=10, colonnes=10, niveaux=3)]
        self.assertEqual(len(codes), 30)
        self.assertEqual(codes[:6], ["AC550", "AC551", "AC552", "AC560", "AC561", "AC562"])
        self.assertEqual(codes[-3:], ["AC640", "AC641", "AC642"])

    def test_ordre_physique_colonne_par_colonne(self):
        """L'ordre est celui de l'impression : une colonne entière, puis la suivante."""
        liste = services_emplacements.codes_de_rack(prefixe="AC", debut="550", pas=10,
                                       colonnes=2, niveaux=3)
        self.assertEqual([(x["colonne"], x["niveau"]) for x in liste],
                         [(550, 0), (550, 1), (550, 2), (560, 0), (560, 1), (560, 2)])

    def test_un_seul_niveau(self):
        codes = [x["code"] for x in services_emplacements.codes_de_rack(
            prefixe="B", debut="1", pas=1, colonnes=4, niveaux=1)]
        self.assertEqual(codes, ["B1", "B2", "B3", "B4"])

    def test_les_zeros_de_tete_sont_conservés(self):
        """« 050 » saisi doit rester « 050 » : c'est ce qui sera peint sur le rack."""
        codes = [x["code"] for x in services_emplacements.codes_de_rack(
            prefixe="AC", debut="050", pas=10, colonnes=2, niveaux=2)]
        self.assertEqual(codes, ["AC050", "AC051", "AC060", "AC061"])

    def test_prefixe_normalise(self):
        codes = [x["code"] for x in services_emplacements.codes_de_rack(
            prefixe="  ac ", debut="10", pas=10, colonnes=1, niveaux=1)]
        self.assertEqual(codes, ["AC10"])

    def test_separateur_optionnel(self):
        codes = [x["code"] for x in services_emplacements.codes_de_rack(
            prefixe="AC", debut="550", pas=10, colonnes=1, niveaux=2, separateur="-")]
        self.assertEqual(codes, ["AC-550", "AC-551"])


class GardeFousTest(BaseRack):
    def test_niveaux_superieurs_au_pas_refuses(self):
        """Avec un pas de 2 et 3 niveaux, la colonne 550 déborderait sur la 552."""
        r = self.generer(pas=2, niveaux=3, colonnes=5)
        self.assertEqual(r.status_code, 400)
        self.assertIn("déborderaient", " ".join(r.data["erreur"]))
        self.assertEqual(Emplacement.objects.count(), 0)

    def test_faute_de_frappe_sur_le_nombre_de_colonnes(self):
        r = self.generer(colonnes=1000)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Emplacement.objects.count(), 0)

    def test_total_borne(self):
        r = self.generer(colonnes=200, niveaux=10, pas=10)
        self.assertEqual(r.status_code, 400)
        self.assertIn("500", " ".join(r.data["erreur"]))

    def test_prefixe_obligatoire(self):
        self.assertEqual(self.generer(prefixe="  ").status_code, 400)

    def test_debut_non_numerique_refuse(self):
        self.assertEqual(self.generer(debut="AB").status_code, 400)

    def test_lecture_seule_ne_genere_rien(self):
        self.client.force_authenticate(user=Utilisateur.objects.create_user(
            username="obs", password="motdepasse123", role=Utilisateur.LECTURE))
        self.assertEqual(self.generer().status_code, 403)
        self.assertEqual(Emplacement.objects.count(), 0)


class ApercuTest(BaseRack):
    def test_l_apercu_n_ecrit_rien(self):
        r = self.generer(apercu=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["total"], 30)
        self.assertEqual(r.data["nouveaux"], 30)
        self.assertEqual(Emplacement.objects.count(), 0)

    def test_l_apercu_signale_les_codes_deja_pris(self):
        Emplacement.objects.create(code="AC551")
        r = self.generer(apercu=True)
        self.assertEqual(r.data["existants"], ["AC551"])
        self.assertEqual(r.data["nouveaux"], 29)

    def test_l_apercu_montre_exactement_ce_qui_sera_cree(self):
        """Un aperçu calculé côté navigateur pourrait diverger de l'écriture réelle."""
        annonce = [x["code"] for x in self.generer(apercu=True).data["codes"]]
        self.generer()
        self.assertEqual(sorted(Emplacement.objects.values_list("code", flat=True)),
                         sorted(annonce))


class CreationTest(BaseRack):
    def test_creation_complete(self):
        r = self.generer()
        self.assertEqual(r.status_code, 201, getattr(r, "data", None))
        self.assertEqual(len(r.data["crees"]), 30)
        self.assertEqual(Emplacement.objects.count(), 30)

    def test_position_enregistree(self):
        """Sans rack/colonne/niveau, imprimer « par colonne » obligerait à
        redécouper le code à coups d'expressions régulières."""
        self.generer()
        e = Emplacement.objects.get(code="AC561")
        self.assertEqual((e.rack, e.colonne, e.niveau), ("AC", 560, 1))

    def test_mode_et_description_appliques_a_tout_le_rack(self):
        self.generer(mode_places=Emplacement.ILLIMITE, description="allée centrale")
        for e in Emplacement.objects.all():
            self.assertEqual(e.mode_places, Emplacement.ILLIMITE)
            self.assertEqual(e.description, "allée centrale")

    def test_un_mode_inconnu_est_refuse_sans_rien_creer(self):
        """`save()` ne contrôle pas les choix : « gmd », que l'écran envoyait
        encore après le passage à deux places, était écrit tel quel."""
        r = self.generer(mode_places="gmd")
        self.assertEqual(r.status_code, 400)
        self.assertIn("gmd", " ".join(r.data["erreur"]))
        self.assertEqual(Emplacement.objects.count(), 0)

    def test_rejouable_pour_ajouter_un_niveau(self):
        """Ajouter un 4e niveau à un rack existant = relancer avec niveaux=4."""
        self.generer(niveaux=3)
        r = self.generer(niveaux=4)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(r.data["crees"]), 10)      # un par colonne
        self.assertEqual(len(r.data["ignores"]), 30)    # les trois premiers niveaux
        self.assertEqual(Emplacement.objects.count(), 40)
        self.assertTrue(Emplacement.objects.filter(code="AC553").exists())

    def test_un_code_existant_n_est_pas_modifie(self):
        deja = Emplacement.objects.create(code="AC551", description="posé à la main")
        self.generer(description="généré")
        deja.refresh_from_db()
        self.assertEqual(deja.description, "posé à la main")
        self.assertEqual(deja.rack, "")


class ImpressionParGroupeTest(BaseRack):
    """Ce que l'écran d'impression interroge pour composer ses bandes."""

    def setUp(self):
        super().setUp()
        self.generer()
        self.generer(prefixe="BD", debut="10", colonnes=2, niveaux=2)

    def test_filtrer_une_colonne(self):
        r = self.client.get("/api/emplacements/?rack=AC&colonne=560&ordering=code")
        self.assertEqual([e["code"] for e in r.data["results"]],
                         ["AC560", "AC561", "AC562"])

    def test_filtrer_un_rack_entier(self):
        r = self.client.get("/api/emplacements/?rack=ac&ordering=code")
        self.assertEqual(r.data["count"], 30)

    def test_inventaire_des_racks(self):
        r = self.client.get("/api/emplacements/racks/")
        self.assertEqual(r.status_code, 200)
        racks = {x["rack"]: x for x in r.data}
        self.assertEqual(racks["AC"]["colonnes"], 10)
        self.assertEqual(racks["AC"]["niveaux"], 3)
        self.assertEqual(racks["AC"]["emplacements"], 30)
        self.assertEqual(racks["AC"]["premier"], "AC550")
        self.assertEqual(racks["AC"]["dernier"], "AC642")
        self.assertEqual(racks["BD"]["liste_colonnes"], [10, 20])

    def test_les_emplacements_a_l_unite_ne_sont_pas_des_racks(self):
        Emplacement.objects.create(code="ZONE-TAMPON")
        self.assertEqual({x["rack"] for x in self.client.get("/api/emplacements/racks/").data},
                         {"AC", "BD"})
