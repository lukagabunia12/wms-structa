"""Moteur de recherche de cabines : filtres, listes déroulantes, compteurs.

Ces tests portent sur ce que l'écran « Cabines » interroge réellement. Ils
existent parce que la question posée par l'utilisatrice — « je n'arrive pas à
retrouver les cabines qui ne sont pas rangées » — se traduit par un filtre :
si le filtre ment, l'écran ment.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from wms import services_cabines
from wms.models import (Cabine, Emplacement, MouvementCabine,
                        Utilisateur, Zone)


class RechercheCabinesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.u = Utilisateur.objects.create_user(
            username="chef", password="x", role=Utilisateur.ADMIN)
        cls.zone = Zone.objects.create(nom="Attente depart", role=Zone.ENVOI)
        cls.emp_ac = Emplacement.objects.create(code="AC-100-1", rack="AC",
                                                colonne="100", niveau=1,
                                                zone_cabine=cls.zone)
        cls.emp_y = Emplacement.objects.create(code="Y-010-1", rack="Y",
                                               colonne="010", niveau=1)
        # Rack sans la moindre cabine : il doit rester proposé dans la liste.
        Emplacement.objects.create(code="AD-001-1", rack="AD", colonne="001", niveau=1)

        cls.rangee = Cabine.objects.create(numero="01_01_01", chantier="100001",
                                           modele="Duo 120")
        services_cabines.ranger(cabine=cls.rangee, emplacement=cls.emp_ac,
                                place="G", utilisateur=cls.u)
        cls.non_rangee = Cabine.objects.create(numero="01_01_02", chantier="100002",
                                               modele="Solo 90")
        cls.quarantaine = Cabine.objects.create(numero="01_01_03", chantier="100001")
        services_cabines.changer_statut(cabine=cls.quarantaine,
                                        statut=Cabine.QUARANTAINE,
                                        utilisateur=cls.u, motif="choc")
        cls.salon = Cabine.objects.create(numero="01_01_04", type_cabine=Cabine.SALON)
        cls.envoyee = Cabine.objects.create(numero="01_01_05", chantier="100003")
        services_cabines.envoyer(cabine=cls.envoyee, utilisateur=cls.u)

    def setUp(self):
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def numeros(self, url):
        r = self.c.get(url)
        self.assertEqual(r.status_code, 200, r.data)
        return sorted(x["numero"] for x in r.data["results"])

    # --- filtres ------------------------------------------------------------
    def test_non_rangees(self):
        """Le besoin d'origine : lister ce qui n'est nulle part."""
        self.assertEqual(self.numeros("/api/cabines/?rangee=0"),
                         ["01_01_02", "01_01_03", "01_01_04"])

    def test_rangees(self):
        self.assertEqual(self.numeros("/api/cabines/?rangee=1"), ["01_01_01"])

    def test_filtre_rack(self):
        self.assertEqual(self.numeros("/api/cabines/?rack=AC"), ["01_01_01"])
        self.assertEqual(self.numeros("/api/cabines/?rack=Y"), [])

    def test_filtre_rack_insensible_a_la_casse(self):
        """Le rack se tape parfois en minuscules ; ce n'est pas un autre rack."""
        self.assertEqual(self.numeros("/api/cabines/?rack=ac"), ["01_01_01"])

    def test_envoyees_exclues_par_defaut(self):
        self.assertNotIn("01_01_05", self.numeros("/api/cabines/"))
        self.assertIn("01_01_05", self.numeros("/api/cabines/?toutes=1"))

    def test_sans_chantier(self):
        self.assertEqual(self.numeros("/api/cabines/?sans_chantier=1"), ["01_01_04"])

    def test_immobile(self):
        """Une cabine sans mouvement depuis N jours doit ressortir, les autres non."""
        vieux = timezone.now() - timedelta(days=30)
        MouvementCabine.objects.filter(cabine=self.non_rangee).update(date=vieux)
        Cabine.objects.filter(pk=self.non_rangee.pk).update(date=vieux)
        self.assertEqual(self.numeros("/api/cabines/?immobile=7"), ["01_01_02"])

    def test_immobile_non_numerique_repond_400(self):
        r = self.c.get("/api/cabines/?immobile=beaucoup")
        self.assertEqual(r.status_code, 400)
        self.assertIn("immobile", str(r.data))

    def test_tri_par_derniere_activite(self):
        r = self.c.get("/api/cabines/?ordering=-derniere_activite_date")
        self.assertEqual(r.status_code, 200, r.data)
        dates = [x["derniere_activite"] for x in r.data["results"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_combinaison_de_filtres(self):
        """Deux filtres se cumulent — ils ne se remplacent pas."""
        self.assertEqual(
            self.numeros("/api/cabines/?rangee=0&statut=quarantaine"), ["01_01_03"])

    # --- listes déroulantes -------------------------------------------------
    def test_filtres_listes_et_compteurs(self):
        r = self.c.get("/api/cabines/filtres/")
        self.assertEqual(r.status_code, 200, r.data)
        d = r.data
        self.assertEqual(d["chantiers"], ["100001", "100002"])
        self.assertEqual(d["modeles"], ["Duo 120", "Solo 90"])
        self.assertEqual(d["racks"], ["AC", "AD", "Y"])
        self.assertEqual(d["compteurs"]["total"], 4)
        self.assertEqual(d["compteurs"]["non_rangees"], 3)
        self.assertEqual(d["compteurs"]["quarantaine"], 1)
        self.assertEqual(d["compteurs"]["sans_chantier"], 1)
        self.assertEqual(d["compteurs"]["envoyees"], 1)

    def test_les_chantiers_des_cabines_envoyees_ne_polluent_pas(self):
        """100003 n'appartient qu'a une cabine envoyee : hors parc, hors liste."""
        d = self.c.get("/api/cabines/filtres/").data
        self.assertNotIn("100003", d["chantiers"])

    def test_compteur_immobiles(self):
        vieux = timezone.now() - timedelta(days=30)
        MouvementCabine.objects.filter(cabine=self.non_rangee).update(date=vieux)
        Cabine.objects.filter(pk=self.non_rangee.pk).update(date=vieux)
        d = self.c.get("/api/cabines/filtres/").data
        self.assertEqual(d["compteurs"]["immobiles"], 1)
        self.assertEqual(d["seuil_immobile_jours"], 7)

    def test_filtres_exige_une_connexion(self):
        anonyme = APIClient()
        self.assertIn(anonyme.get("/api/cabines/filtres/").status_code, (401, 403))


class ChantierObligatoireTest(TestCase):
    """Le sérialiseur doit dispenser les mêmes types que le modèle.

    Il n'en dispensait qu'un — « express » — alors que le modèle en dispense
    trois : toute cabine salon ou occasion était refusée par l'API.
    """

    def setUp(self):
        self.u = Utilisateur.objects.create_user(
            username="op", password="x", role=Utilisateur.ADMIN)
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def test_types_dispenses_de_chantier(self):
        for i, t in enumerate(sorted(Cabine.SANS_CHANTIER)):
            with self.subTest(type=t):
                r = self.c.post("/api/cabines/",
                                {"numero": "02_00_0%d" % i, "type_cabine": t},
                                format="json")
                self.assertEqual(r.status_code, 201, r.data)

    def test_type_normale_exige_toujours_un_chantier(self):
        r = self.c.post("/api/cabines/",
                        {"numero": "02_01_01", "type_cabine": Cabine.NORMALE},
                        format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("chantier", r.data)

    def test_le_message_cite_les_types_dispenses(self):
        r = self.c.post("/api/cabines/", {"numero": "02_01_02"}, format="json")
        message = str(r.data["chantier"][0])
        for _, libelle in Cabine.TYPES:
            if _ in Cabine.SANS_CHANTIER:
                self.assertIn(libelle, message)


class ListesDeroulantesExactesTest(TestCase):
    """Une valeur choisie dans une liste est complète : elle doit filtrer exactement."""

    @classmethod
    def setUpTestData(cls):
        cls.u = Utilisateur.objects.create_user(
            username="chef2", password="x", role=Utilisateur.ADMIN)
        Cabine.objects.create(numero="03_00_01", chantier="100001", modele="Duo 120")
        Cabine.objects.create(numero="03_00_02", chantier="100001", modele="Duo 1200")

    def setUp(self):
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def test_modele_exact_ne_ramene_pas_les_voisins(self):
        r = self.c.get("/api/cabines/?modele_exact=Duo 120")
        self.assertEqual([x["numero"] for x in r.data["results"]], ["03_00_01"])

    def test_modele_contient_ramene_les_deux(self):
        """L'ancien filtre reste intact : la recherche libre cherche toujours « contient »."""
        r = self.c.get("/api/cabines/?modele=Duo 120")
        self.assertEqual(r.data["count"], 2)

    def test_chantier_exact(self):
        r = self.c.get("/api/cabines/?chantier_exact=100001")
        self.assertEqual(r.data["count"], 2)
        self.assertEqual(self.c.get("/api/cabines/?chantier_exact=10000").data["count"], 0)


class RelectureParIdentifiantsTest(TestCase):
    """Les « Récents » du scanner relisent leurs cabines au lieu de les inventer.

    La liste vivait dans le navigateur : elle proposait des cabines effacées par
    une remise à zéro, présentait comme en stock des cabines déjà envoyées, et
    affichait le libellé de statut figé au moment du clic.
    """

    @classmethod
    def setUpTestData(cls):
        cls.u = Utilisateur.objects.create_user(
            username="scan", password="x", role=Utilisateur.ADMIN)
        cls.a = Cabine.objects.create(numero="04_00_01", chantier="100001")
        cls.b = Cabine.objects.create(numero="04_00_02", chantier="100002")
        cls.partie = Cabine.objects.create(numero="04_00_03", chantier="100003")
        services_cabines.envoyer(cabine=cls.partie, utilisateur=cls.u)

    def setUp(self):
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def test_relit_les_identifiants_demandes(self):
        r = self.c.get(f"/api/cabines/?toutes=1&ids={self.a.pk},{self.b.pk}")
        self.assertEqual(sorted(x["numero"] for x in r.data["results"]),
                         ["04_00_01", "04_00_02"])

    def test_un_identifiant_disparu_est_simplement_absent(self):
        """Aucune erreur : l'écran doit pouvoir oublier ce qui n'existe plus."""
        r = self.c.get(f"/api/cabines/?toutes=1&ids={self.a.pk},999999")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["numero"] for x in r.data["results"]], ["04_00_01"])

    def test_une_cabine_envoyee_est_relue_avec_son_vrai_statut(self):
        """C'est ce statut qui permet à l'écran de la retirer des récents."""
        r = self.c.get(f"/api/cabines/?toutes=1&ids={self.partie.pk}")
        self.assertEqual(r.data["results"][0]["statut"], Cabine.ENVOYE)

    def test_ids_non_numeriques_repondent_400(self):
        r = self.c.get("/api/cabines/?ids=abc")
        self.assertEqual(r.status_code, 400)
        self.assertIn("ids", str(r.data))

    def test_le_libelle_de_statut_vient_du_serveur(self):
        """Le renommage « Libre » → « Rien à signaler » doit se propager tout seul."""
        r = self.c.get(f"/api/cabines/?ids={self.a.pk}")
        self.assertEqual(r.data["results"][0]["statut_libelle"],
                         dict(Cabine.STATUTS)[Cabine.LIBRE])

    def test_archives_par_statut_et_toutes(self):
        """Le filtre rapide « Envoyées » : toutes=1 + statut=envoye."""
        r = self.c.get("/api/cabines/?toutes=1&statut=envoye")
        self.assertEqual([x["numero"] for x in r.data["results"]], ["04_00_03"])


class MotifDeQuarantaineTest(TestCase):
    """Le motif du dernier changement de statut remonte sur la fiche.

    Il sert au moment de confirmer la sortie d'une cabine bloquée : « rayure sur
    la paroi » est ce qu'il faut avoir sous les yeux pour trancher.
    """

    def setUp(self):
        self.u = Utilisateur.objects.create_user(
            username="q", password="x", role=Utilisateur.ADMIN)
        self.c = APIClient()
        self.c.force_authenticate(self.u)
        self.cab = Cabine.objects.create(numero="05_00_01", chantier="100001")

    def test_motif_sur_la_fiche(self):
        services_cabines.changer_statut(cabine=self.cab, statut=Cabine.QUARANTAINE,
                                        utilisateur=self.u, motif="rayure sur la paroi")
        r = self.c.get(f"/api/cabines/{self.cab.pk}/")
        self.assertEqual(r.data["statut_motif"], "rayure sur la paroi")

    def test_pas_de_motif_sans_changement(self):
        r = self.c.get(f"/api/cabines/{self.cab.pk}/")
        self.assertEqual(r.data["statut_motif"], "")

    def test_la_liste_ne_paye_pas_le_calcul(self):
        """Une requête d'historique par ligne sur 50 lignes : jamais."""
        services_cabines.changer_statut(cabine=self.cab, statut=Cabine.QUARANTAINE,
                                        utilisateur=self.u, motif="choc")
        r = self.c.get("/api/cabines/")
        self.assertIsNone(r.data["results"][0]["statut_motif"])

    def test_le_motif_suit_le_statut_courant(self):
        """Quarantaine levée : le motif affiché est celui du retour, pas l'ancien."""
        services_cabines.changer_statut(cabine=self.cab, statut=Cabine.QUARANTAINE,
                                        utilisateur=self.u, motif="choc")
        services_cabines.changer_statut(cabine=self.cab, statut=Cabine.LIBRE,
                                        utilisateur=self.u, motif="reparee")
        r = self.c.get(f"/api/cabines/{self.cab.pk}/")
        self.assertEqual(r.data["statut_motif"], "reparee")


class RechercheLibreTest(TestCase):
    """Le bandeau « Cabines » cherche le n°, le chantier et le modèle à la fois.

    C'est le seul champ où le masque XX_XX_XX ne peut pas être imposé : un n° de
    chantier n'a pas de tirets bas. Le serveur rattrape donc la forme sans
    tirets, sinon taper « 260347 » ne ramènerait rien.
    """

    @classmethod
    def setUpTestData(cls):
        cls.u = Utilisateur.objects.create_user(
            username="libre", password="x", role=Utilisateur.ADMIN)
        cls.cab = Cabine.objects.create(numero="26_03_47", chantier="260204",
                                        modele="Duo 120")
        cls.autre = Cabine.objects.create(numero="25_12_80", chantier="251280",
                                          modele="Quattro")

    def setUp(self):
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def numeros(self, terme):
        r = self.c.get("/api/cabines/?search=" + terme)
        self.assertEqual(r.status_code, 200, r.data)
        return sorted(x["numero"] for x in r.data["results"])

    def test_forme_complete(self):
        self.assertEqual(self.numeros("26_03_47"), ["26_03_47"])

    def test_six_chiffres_sans_tirets(self):
        """« 260347 » tapé au pavé numérique doit ramener 26_03_47."""
        self.assertEqual(self.numeros("260347"), ["26_03_47"])

    def test_espaces_ou_tirets_a_la_place_des_tirets_bas(self):
        for terme in ("26 03 47", "26-03-47"):
            with self.subTest(terme=terme):
                self.assertEqual(self.numeros(terme), ["26_03_47"])

    def test_le_chantier_reste_cherchable(self):
        """Six chiffres ambigus : le chantier 251280 ET la cabine 25_12_80."""
        self.assertEqual(self.numeros("251280"), ["25_12_80"])
        self.assertIn("26_03_47", self.numeros("260204"))

    def test_le_modele_reste_cherchable(self):
        self.assertEqual(self.numeros("Quattro"), ["25_12_80"])

    def test_recherche_partielle(self):
        self.assertEqual(self.numeros("26_03"), ["26_03_47"])

    def test_terme_absent_ne_ramene_rien(self):
        self.assertEqual(self.numeros("999999"), [])

    def test_les_archives_cherchent_pareil(self):
        """L'écran des cabines envoyées passe par le même filtre."""
        services_cabines.envoyer(cabine=self.autre, utilisateur=self.u)
        r = self.c.get("/api/cabines/archives/?search=251280")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([x["numero"] for x in r.data["results"]], ["25_12_80"])
