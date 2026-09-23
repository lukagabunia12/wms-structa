"""Trois règles écrites après un essai sur le terrain.

1. On ne pose pas une quarantaine sans motif. Une quarantaine immobilise une
   cabine ; sans la raison au journal, personne ne sait quoi réparer pour la
   lever, et la cabine reste en travers du rack pendant des semaines.

2. On ne sort pas une cabine sans motif. Sortir, c'est envoyer : le geste libère
   sa place, et sans motif la question « où est la 00_00_01 ? » n'a plus de
   réponse le lendemain.

Ce qui est vérifié ici n'est pas seulement le refus : c'est aussi le MESSAGE.
Un refus qui ne dit pas à quoi sert le motif se contourne en tapant « ok ».

(La remise à zéro, troisième règle de cette série, a quitté l'application pour
l'administration Django : voir `test_remise_a_zero_admin.py`.)
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

    def test_l_envoi_exige_aussi_son_motif(self):
        """Sortir une cabine, c'est l'envoyer — et une sortie se motive.

        Cet essai soutenait l'inverse : que l'envoi n'ait pas à être motivé, le
        n° de chantier disant déjà où la cabine va. C'était tenable tant que le
        retrait d'emplacement existait à côté, lui motivé. Les deux gestes n'en
        font plus qu'un : la règle « pas de sortie sans motif » doit donc tenir
        sur celui qui reste, sinon elle disparaît avec l'autre.
        """
        with self.assertRaises(services_cabines.ErreurCabine) as bilan:
            services_cabines.changer_statut(
                cabine=self.cab, statut=Cabine.ENVOYE, utilisateur=self.user)
        self.assertIn("pourquoi", str(bilan.exception).lower())
        self.cab.refresh_from_db()
        self.assertEqual(self.cab.statut, Cabine.LIBRE)

        services_cabines.changer_statut(cabine=self.cab, statut=Cabine.ENVOYE,
                                        utilisateur=self.user, motif="chargée camion 12")
        self.cab.refresh_from_db()
        self.assertEqual(self.cab.statut, Cabine.ENVOYE)
        # Le motif ne se perd pas en route : c'est le journal qui répondra à
        # « où est passée cette cabine ? ».
        mouvement = self.cab.historique.filter(type=MouvementCabine.ENVOI).first()
        self.assertEqual(mouvement.note, "chargée camion 12")

    def test_l_api_refuse_l_envoi_sans_motif(self):
        """La même règle, par le chemin que prennent les écrans."""
        r = self.client.post(f"/api/cabines/{self.cab.id}/envoyer/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.cab.refresh_from_db()
        self.assertEqual(self.cab.statut, Cabine.LIBRE)

        r = self.client.post(f"/api/cabines/{self.cab.id}/envoyer/",
                             {"note": "départ en pose"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.cab.refresh_from_db()
        self.assertEqual(self.cab.statut, Cabine.ENVOYE)

    def test_l_api_refuse_aussi(self):
        r = self.client.post(f"/api/cabines/{self.cab.id}/statut/",
                             {"statut": Cabine.QUARANTAINE}, format="json")
        self.assertEqual(r.status_code, 400)
        self.cab.refresh_from_db()
        self.assertNotEqual(self.cab.statut, Cabine.QUARANTAINE)


class SortieSansMotifTest(BaseMotifs):
    """La sortie d'un emplacement est l'envoi : c'est sur lui que la règle tient."""

    def setUp(self):
        super().setUp()
        services_cabines.ranger(cabine=self.cab, emplacement=self.emp,
                                place=Occupation.GAUCHE, utilisateur=self.user)

    def test_sortir_sans_motif_est_refuse(self):
        with self.assertRaises(services_cabines.ErreurCabine) as bilan:
            services_cabines.envoyer(cabine=self.cab, utilisateur=self.user)
        self.assertIn("où elle est passée", " ".join(bilan.exception.messages))
        # Et la place n'a PAS été libérée : un refus qui libère quand même
        # serait pire que pas de règle du tout.
        self.assertEqual(self.places_prises(), 1)

    def test_un_motif_d_espaces_ne_compte_pas(self):
        with self.assertRaises(services_cabines.ErreurCabine):
            services_cabines.envoyer(cabine=self.cab, utilisateur=self.user, note=" \t ")
        self.assertEqual(self.places_prises(), 1)

    def test_avec_motif_la_place_est_liberee_et_le_journal_le_dit(self):
        services_cabines.envoyer(cabine=self.cab, utilisateur=self.user,
                                 note="départ en pose")
        self.assertEqual(self.places_prises(), 0)
        mvt = (MouvementCabine.objects.filter(cabine=self.cab,
                                              type=MouvementCabine.ENVOI).latest("id"))
        self.assertIn("pose", mvt.note)
        # Le journal dit AUSSI d'où elle sort : sans cela, le motif est une
        # phrase en l'air.
        self.assertIn("C001", mvt.depuis)

    def test_il_n_y_a_plus_de_sortie_a_moitie(self):
        """L'ancien retrait d'emplacement laissait la cabine « en stock, nulle
        part ». Ce chemin n'existe plus."""
        r = self.client.post(f"/api/cabines/{self.cab.id}/sortir/",
                             {"note": "déplacée à la main"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.places_prises(), 1)
