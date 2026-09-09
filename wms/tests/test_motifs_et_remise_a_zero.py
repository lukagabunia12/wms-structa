"""Trois règles écrites après un essai sur le terrain.

1. On ne pose pas une quarantaine sans motif. Une quarantaine immobilise une
   cabine ; sans la raison au journal, personne ne sait quoi réparer pour la
   lever, et la cabine reste en travers du rack pendant des semaines.

2. On ne sort pas une cabine de son emplacement sans motif. Le geste libère une
   place et laisse la cabine nulle part : le lendemain, la question « où est la
   00_00_01 ? » n'a plus de réponse.

3. On peut repartir de zéro depuis l'application. Pendant les essais, la remise
   à zéro sert plusieurs fois de suite — et le terminal est sur le serveur, pas
   dans la poche de la personne qui teste.

Ce qui est vérifié ici n'est pas seulement le refus : c'est aussi ce qui SURVIT.
Une remise à zéro qui emporterait le fichier de production désarmerait la règle
« une cabine non annoncée ne s'enregistre pas », et il faudrait réimporter
2 000 lignes avant de pouvoir entrer la première cabine.
"""
from rest_framework.test import APITestCase

from wms import services_cabines
from wms.models import (Cabine, CabineAttendue, Emplacement, ModeleCabine,
                        MouvementCabine, Occupation, Utilisateur, Zone)


class BaseMotifs(APITestCase):
    def setUp(self):
        self.user = Utilisateur.objects.create_user(
            username="op", password="secret123", role=Utilisateur.ADMIN, nom="Luka G.")
        self.client.force_authenticate(user=self.user)
        self.zone = Zone.objects.create(nom="Rack A", ordre=1)
        self.emp = Emplacement.objects.create(code="C001", zone_cabine=self.zone)
        CabineAttendue.objects.create(numero="00_00_01", modele="DUO", chantier="000123")
        ModeleCabine.objects.update_or_create(
            cle="DUO", defaults={"nom": "DUO", "grand": False})
        self.cab = services_cabines.creer_cabine(
            numero="00_00_01", chantier="000123", modele="DUO", utilisateur=self.user)

    def places_prises(self, cabine=None):
        """Les places tenues, lues en base.

        `Cabine.emplacements_occupes` filtre un cache de prefetch : sur une
        instance chargée avant le geste, il renverrait l'état d'avant et le
        test passerait pour de mauvaises raisons.
        """
        return Occupation.objects.filter(
            cabine=(cabine or self.cab), emplacement__isnull=False).count()


class QuarantaineSansMotifTest(BaseMotifs):
    def test_poser_une_quarantaine_sans_motif_est_refuse(self):
        with self.assertRaises(services_cabines.ErreurCabine) as bilan:
            services_cabines.changer_statut(
                cabine=self.cab, statut=Cabine.QUARANTAINE, utilisateur=self.user)
        message = " ".join(bilan.exception.messages)
        # Le refus doit dire À QUOI SERT le motif, sinon on tape « ok » pour passer.
        self.assertIn("quoi réparer", message)
        self.cab.refresh_from_db()
        self.assertNotEqual(self.cab.statut, Cabine.QUARANTAINE)

    def test_un_motif_d_espaces_ne_compte_pas(self):
        """« ok » passerait ; «    » ne doit pas.

        On ne peut pas juger de la qualité d'un motif, mais on peut refuser le
        vide déguisé — c'est ce qu'écrit un champ qu'on a effleuré.
        """
        with self.assertRaises(services_cabines.ErreurCabine):
            services_cabines.changer_statut(
                cabine=self.cab, statut=Cabine.QUARANTAINE, utilisateur=self.user,
                motif="   ")

    def test_avec_motif_la_quarantaine_passe_et_le_journal_le_garde(self):
        services_cabines.changer_statut(
            cabine=self.cab, statut=Cabine.QUARANTAINE, utilisateur=self.user,
            motif="rayure sur la paroi gauche")
        self.cab.refresh_from_db()
        self.assertEqual(self.cab.statut, Cabine.QUARANTAINE)
        mvt = (MouvementCabine.objects.filter(cabine=self.cab,
                                              type=MouvementCabine.STATUT).latest("id"))
        self.assertIn("rayure", mvt.note)

    def test_lever_une_quarantaine_n_exige_aucun_motif(self):
        """Constater qu'une cabine est redevenue conforme n'a rien à expliquer.

        Exiger un motif dans les deux sens ferait taper « ok » à la levée, et
        l'habitude gagnerait ensuite la pose — là où le motif compte.
        """
        services_cabines.changer_statut(
            cabine=self.cab, statut=Cabine.QUARANTAINE, utilisateur=self.user,
            motif="paroi à reprendre")
        services_cabines.changer_statut(
            cabine=self.cab, statut=Cabine.LIBRE, utilisateur=self.user)
        self.cab.refresh_from_db()
        self.assertEqual(self.cab.statut, Cabine.LIBRE)

    def test_la_garde_ne_deborde_pas_sur_l_envoi(self):
        """L'envoi passe par `envoyer()`, qui a ses propres règles.

        Il n'y a que trois statuts : Conforme, En quarantaine, Envoyée. Écrire
        la garde « quarantaine » un cran trop haut la ferait s'appliquer à
        l'envoi, et plus une cabine ne partirait sans qu'on tape une phrase —
        alors que le n° de chantier, lui déjà obligatoire, dit où elle va.
        """
        services_cabines.changer_statut(
            cabine=self.cab, statut=Cabine.ENVOYE, utilisateur=self.user)
        self.cab.refresh_from_db()
        self.assertEqual(self.cab.statut, Cabine.ENVOYE)

    def test_l_api_refuse_aussi(self):
        r = self.client.post(f"/api/cabines/{self.cab.id}/statut/",
                             {"statut": Cabine.QUARANTAINE}, format="json")
        self.assertEqual(r.status_code, 400)
        self.cab.refresh_from_db()
        self.assertNotEqual(self.cab.statut, Cabine.QUARANTAINE)


class SortieSansMotifTest(BaseMotifs):
    def setUp(self):
        super().setUp()
        services_cabines.ranger(cabine=self.cab, emplacement=self.emp,
                                place=Occupation.GAUCHE, utilisateur=self.user)

    def test_sortir_de_l_emplacement_sans_motif_est_refuse(self):
        with self.assertRaises(services_cabines.ErreurCabine) as bilan:
            services_cabines.sortir_de_l_emplacement(
                cabine=self.cab, utilisateur=self.user)
        self.assertIn("où elle est passée", " ".join(bilan.exception.messages))
        # Et la place n'a PAS été libérée : un refus qui libère quand même
        # serait pire que pas de règle du tout.
        self.assertEqual(self.places_prises(), 1)

    def test_un_motif_d_espaces_ne_compte_pas(self):
        with self.assertRaises(services_cabines.ErreurCabine):
            services_cabines.sortir_de_l_emplacement(
                cabine=self.cab, utilisateur=self.user, note=" \t ")
        self.assertEqual(self.places_prises(), 1)

    def test_avec_motif_la_place_est_liberee_et_le_journal_le_dit(self):
        services_cabines.sortir_de_l_emplacement(
            cabine=self.cab, utilisateur=self.user, note="remontée à l'atelier")
        self.assertEqual(self.places_prises(), 0)
        mvt = (MouvementCabine.objects.filter(cabine=self.cab,
                                              type=MouvementCabine.RETRAIT).latest("id"))
        self.assertIn("atelier", mvt.note)
        # Le journal dit AUSSI d'où elle sort : sans cela, le motif est une
        # phrase en l'air.
        self.assertIn("C001", mvt.depuis)

    def test_l_api_refuse_aussi(self):
        r = self.client.post(f"/api/cabines/{self.cab.id}/sortir/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.places_prises(), 1)

    def test_l_api_accepte_avec_note(self):
        r = self.client.post(f"/api/cabines/{self.cab.id}/sortir/",
                             {"note": "déplacée à la main"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.places_prises(), 0)


class RemiseAZeroTest(BaseMotifs):
    """`POST /api/cabines/vider_le_stock/` — la remise à zéro des essais."""

    URL = "/api/cabines/vider_le_stock/"

    def setUp(self):
        super().setUp()
        services_cabines.ranger(cabine=self.cab, emplacement=self.emp,
                                place=Occupation.GAUCHE, utilisateur=self.user)
        CabineAttendue.objects.create(numero="00_00_02", modele="DUO", chantier="000124")
        self.operateur = Utilisateur.objects.create_user(
            username="operateur", password="secret123", role=Utilisateur.OPERATEUR)

    def test_le_get_annonce_ce_qui_partira_sans_rien_effacer(self):
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data["efface"])
        self.assertEqual(r.data["cabines"], 1)
        self.assertEqual(r.data["rangees"], 1)
        self.assertGreaterEqual(r.data["journal"], 2)   # création + rangement
        self.assertEqual(Cabine.objects.count(), 1)     # rien n'a bougé

    def test_le_get_annonce_le_mot_a_retaper(self):
        """L'écran ne doit pas écrire le mot en dur : deux orthographes et il
        devient inutilisable sans que rien ne le signale."""
        r = self.client.get(self.URL)
        self.assertEqual(r.data["mot"], "EFFACER")

    def test_sans_confirmation_rien_n_est_efface(self):
        r = self.client.post(self.URL, {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Cabine.objects.count(), 1)

    def test_avec_une_mauvaise_confirmation_rien_n_est_efface(self):
        r = self.client.post(self.URL, {"confirmation": "effacer"}, format="json")
        self.assertEqual(r.status_code, 400)
        # Le refus DOIT rappeler le mot exact : sinon on retape trois fois
        # « effacer » sans comprendre que c'est la casse qui bloque.
        self.assertIn("EFFACER", str(r.data))
        self.assertEqual(Cabine.objects.count(), 1)

    def test_avec_la_confirmation_les_cabines_et_le_journal_partent(self):
        r = self.client.post(self.URL, {"confirmation": "EFFACER"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["efface"])
        self.assertEqual(r.data["cabines"], 1)
        self.assertEqual(Cabine.objects.count(), 0)
        self.assertEqual(MouvementCabine.objects.count(), 0)
        # Les occupations partent avec les cabines (CASCADE) : sans cela, la
        # place resterait réservée par une cabine qui n'existe plus.
        self.assertEqual(Occupation.objects.count(), 0)

    def test_ce_qui_survit_a_la_remise_a_zero(self):
        """Le point de la règle. Effacer le fichier de production obligerait à
        réimporter 2 000 lignes avant la première cabine."""
        avant_attendues = CabineAttendue.objects.count()
        avant_modeles = ModeleCabine.objects.count()
        r = self.client.post(self.URL, {"confirmation": "EFFACER"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(CabineAttendue.objects.count(), avant_attendues)
        self.assertEqual(ModeleCabine.objects.count(), avant_modeles)
        self.assertEqual(Emplacement.objects.count(), 1)
        self.assertEqual(Zone.objects.count(), 1)
        self.assertEqual(Utilisateur.objects.count(), 2)
        # Et l'écran l'annonce, avec les mêmes nombres.
        self.assertEqual(r.data["conserves"]["cabines_attendues"], avant_attendues)
        self.assertEqual(r.data["conserves"]["emplacements"], 1)

    def test_l_emplacement_est_libre_apres(self):
        """La preuve utile : on doit pouvoir ranger tout de suite au même endroit."""
        self.client.post(self.URL, {"confirmation": "EFFACER"}, format="json")
        neuve = services_cabines.creer_cabine(
            numero="00_00_02", chantier="000124", modele="DUO", utilisateur=self.user)
        services_cabines.ranger(cabine=neuve, emplacement=self.emp,
                                place=Occupation.GAUCHE, utilisateur=self.user)
        self.assertEqual(self.places_prises(neuve), 1)

    def test_un_operateur_ne_peut_pas_vider_le_stock(self):
        self.client.force_authenticate(user=self.operateur)
        r = self.client.post(self.URL, {"confirmation": "EFFACER"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Cabine.objects.count(), 1)

    def test_un_operateur_ne_peut_meme_pas_regarder(self):
        """Le GET est en lecture seule, mais il annonce la portée d'un geste
        d'administration : le proposer à qui ne peut pas le faire n'apprend rien
        d'utile et suggère un bouton qui répondra 403."""
        self.client.force_authenticate(user=self.operateur)
        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_sans_compte_c_est_refuse(self):
        self.client.force_authenticate(user=None)
        r = self.client.post(self.URL, {"confirmation": "EFFACER"}, format="json")
        self.assertIn(r.status_code, (401, 403))
        self.assertEqual(Cabine.objects.count(), 1)

    def test_vider_une_base_deja_vide_ne_casse_rien(self):
        """L'écran reste utilisable pour la remise à zéro suivante."""
        self.client.post(self.URL, {"confirmation": "EFFACER"}, format="json")
        r = self.client.post(self.URL, {"confirmation": "EFFACER"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["cabines"], 0)
        self.assertEqual(r.data["journal"], 0)
