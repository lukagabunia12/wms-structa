"""Mettre un emplacement hors service, condamner une place, comparer les semaines.

Trois demandes du terrain, et pour les deux premières la même règle de fond : le
WMS ne déplace jamais une cabine tout seul. Retirer du stock un emplacement qui
en porte une écrirait une position que personne n'a vérifiée devant le rack — il
refuse, et il dit QUELLE cabine est là. Un refus qui ne nomme personne oblige à
aller chercher soi-même ce que le WMS savait déjà.

Ce qui est vérifié ici n'est pas seulement le refus, mais aussi :

- qu'une place condamnée ne se propose plus, et qu'un grand modèle ne peut plus
  prendre l'emplacement — il lui faut les DEUX places ;
- que `actif` ne s'écrit pas par le PATCH ordinaire. C'est le point : une case à
  cocher dans le formulaire contournait toutes les règles, et c'est comme cela
  qu'un emplacement occupé sortait du stock sans un mot ;
- que le comparateur compte les cabines ENTRÉES UN JOUR, envoyées comprises. La
  question est « la production de S37 est-elle arrivée ? », et une cabine partie
  en chantier est bien arrivée. Compter le stock du moment ferait baisser le
  chiffre à mesure que la production part.
"""
import tempfile

from rest_framework.test import APITestCase

from wms import services_cabines
from wms.models import (CabineAttendue, Emplacement, ModeleCabine, Occupation,
                        PlaceCondamnee, Utilisateur, Zone)


class BaseActivation(APITestCase):
    def setUp(self):
        self.user = Utilisateur.objects.create_user(
            username="op", password="secret123", role=Utilisateur.ADMIN, nom="Luka G.")
        self.client.force_authenticate(user=self.user)
        self.zone = Zone.objects.create(nom="Rack A", ordre=1)
        self.e1 = Emplacement.objects.create(code="C001", zone_cabine=self.zone)
        self.e2 = Emplacement.objects.create(code="C002", zone_cabine=self.zone)
        self.tampon = Emplacement.objects.create(
            code="TAMPON", zone_cabine=self.zone, mode_places=Emplacement.ILLIMITE)
        ModeleCabine.objects.update_or_create(
            cle="QUATTRO", defaults={"nom": "QUATTRO", "grand": True})
        ModeleCabine.objects.update_or_create(
            cle="DUO", defaults={"nom": "DUO", "grand": False})

    def cabine(self, numero="00_00_01", chantier="000123", modele="DUO", semaine=""):
        CabineAttendue.objects.update_or_create(
            numero=numero,
            defaults={"modele": modele, "chantier": chantier,
                      "semaine_production": semaine})
        return services_cabines.creer_cabine(
            numero=numero, chantier=chantier, modele=modele, utilisateur=self.user)


class MettreHorsServiceTest(BaseActivation):
    def test_desactiver_sans_motif_est_refuse(self):
        with self.assertRaises(services_cabines.ErreurCabine) as bilan:
            services_cabines.changer_activation(
                emplacement=self.e1, actif=False, utilisateur=self.user)
        self.assertIn("remettre en service", " ".join(bilan.exception.messages))
        self.e1.refresh_from_db()
        self.assertTrue(self.e1.actif)

    def test_desactiver_un_emplacement_occupe_est_refuse_en_nommant_la_cabine(self):
        """Le point de la règle : le refus doit dire QUI est là.

        « Emplacement occupé » oblige à aller chercher dans le Parc ce que le WMS
        savait déjà, et devant un rack on n'a pas les deux mains libres.
        """
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.e1,
                                place=Occupation.GAUCHE, utilisateur=self.user)
        with self.assertRaises(services_cabines.ErreurCabine) as bilan:
            services_cabines.changer_activation(
                emplacement=self.e1, actif=False, motif="rack démonté",
                utilisateur=self.user)
        message = " ".join(bilan.exception.messages)
        self.assertIn("00_00_01", message)
        self.assertIn("C001", message)
        self.e1.refresh_from_db()
        self.assertTrue(self.e1.actif)

    def test_desactiver_un_emplacement_vide_marche_et_garde_le_motif(self):
        services_cabines.changer_activation(
            emplacement=self.e1, actif=False, motif="pilier devant",
            utilisateur=self.user)
        self.e1.refresh_from_db()
        self.assertFalse(self.e1.actif)
        self.assertEqual(self.e1.motif_inactif, "pilier devant")
        self.assertEqual(self.e1.actif_par, self.user)
        self.assertIsNotNone(self.e1.actif_le)

    def test_un_emplacement_inactif_ne_propose_plus_aucune_place(self):
        services_cabines.changer_activation(
            emplacement=self.e1, actif=False, motif="rack démonté",
            utilisateur=self.user)
        self.e1.refresh_from_db()
        self.assertEqual(services_cabines.places_libres(self.e1), [])
        self.assertTrue(services_cabines.est_complet(self.e1))

    def test_ranger_dans_un_emplacement_inactif_est_refuse(self):
        services_cabines.changer_activation(
            emplacement=self.e1, actif=False, motif="rack démonté",
            utilisateur=self.user)
        self.e1.refresh_from_db()
        c = self.cabine()
        with self.assertRaises(services_cabines.ErreurCabine):
            services_cabines.ranger(cabine=c, emplacement=self.e1,
                                    place=Occupation.GAUCHE, utilisateur=self.user)

    def test_reactiver_n_exige_aucun_motif_et_efface_le_precedent(self):
        """Constater qu'un obstacle a disparu n'a pas à s'expliquer.

        Et le motif précédent DOIT partir : le garder ferait croire, six mois
        plus tard, que l'emplacement est encore condamné.
        """
        services_cabines.changer_activation(
            emplacement=self.e1, actif=False, motif="pilier devant",
            utilisateur=self.user)
        self.e1.refresh_from_db()
        services_cabines.changer_activation(
            emplacement=self.e1, actif=True, utilisateur=self.user)
        self.e1.refresh_from_db()
        self.assertTrue(self.e1.actif)
        self.assertEqual(self.e1.motif_inactif, "")
        self.assertEqual(services_cabines.places_libres(self.e1), ["G", "D"])

    def test_desactiver_deux_fois_est_refuse(self):
        services_cabines.changer_activation(
            emplacement=self.e1, actif=False, motif="pilier", utilisateur=self.user)
        self.e1.refresh_from_db()
        with self.assertRaises(services_cabines.ErreurCabine) as bilan:
            services_cabines.changer_activation(
                emplacement=self.e1, actif=False, motif="pilier", utilisateur=self.user)
        self.assertIn("déjà", " ".join(bilan.exception.messages))

    def test_l_api_expose_le_geste(self):
        r = self.client.post(f"/api/emplacements/{self.e1.id}/activation/",
                             {"actif": False, "motif": "rack démonté"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data["actif"])
        self.assertEqual(r.data["motif_inactif"], "rack démonté")
        self.assertEqual(r.data["actif_par_nom"], "Luka G.")

    def test_l_api_refuse_sans_motif(self):
        r = self.client.post(f"/api/emplacements/{self.e1.id}/activation/",
                             {"actif": False}, format="json")
        self.assertEqual(r.status_code, 400)
        self.e1.refresh_from_db()
        self.assertTrue(self.e1.actif)

    def test_le_patch_ordinaire_ne_peut_pas_desactiver(self):
        """LE test de non-régression de cet écran.

        Une case à cocher envoyait `actif` dans le PATCH du formulaire : elle
        passait donc à côté du motif obligatoire ET du refus sur emplacement
        occupé. Décocher puis « Enregistrer les modifications » retirait du stock
        un emplacement portant une cabine, sans un mot.
        """
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.e1,
                                place=Occupation.GAUCHE, utilisateur=self.user)
        r = self.client.patch(f"/api/emplacements/{self.e1.id}/",
                              {"actif": False}, format="json")
        # Le champ est en lecture seule : DRF l'ignore au lieu de refuser, ce
        # qui est le comportement voulu — le reste du formulaire s'enregistre.
        self.assertEqual(r.status_code, 200, r.data)
        self.e1.refresh_from_db()
        self.assertTrue(self.e1.actif)


class CondamnerUnePlaceTest(BaseActivation):
    def test_condamner_sans_motif_est_refuse(self):
        with self.assertRaises(services_cabines.ErreurCabine) as bilan:
            services_cabines.condamner_place(
                emplacement=self.e1, place=Occupation.GAUCHE, utilisateur=self.user)
        self.assertIn("rouvrir", " ".join(bilan.exception.messages))
        self.assertEqual(PlaceCondamnee.objects.count(), 0)

    def test_une_place_condamnee_ne_se_propose_plus_mais_l_autre_reste(self):
        """Tout l'intérêt : désactiver l'emplacement aurait perdu la place saine."""
        services_cabines.condamner_place(
            emplacement=self.e1, place=Occupation.GAUCHE, motif="pilier",
            utilisateur=self.user)
        self.assertEqual(services_cabines.places_libres(self.e1), ["D"])
        self.assertFalse(services_cabines.est_complet(self.e1))

    def test_ranger_sur_une_place_condamnee_est_refuse_avec_le_motif(self):
        services_cabines.condamner_place(
            emplacement=self.e1, place=Occupation.GAUCHE, motif="pilier béton",
            utilisateur=self.user)
        c = self.cabine()
        with self.assertRaises(services_cabines.ErreurCabine) as bilan:
            services_cabines.ranger(cabine=c, emplacement=self.e1,
                                    place=Occupation.GAUCHE, utilisateur=self.user)
        # Le motif est dans le refus : sans lui, on croit à un défaut du WMS.
        self.assertIn("pilier béton", " ".join(bilan.exception.messages))

    def test_l_autre_place_reste_utilisable(self):
        services_cabines.condamner_place(
            emplacement=self.e1, place=Occupation.GAUCHE, motif="pilier",
            utilisateur=self.user)
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.e1,
                                place=Occupation.DROITE, utilisateur=self.user)
        self.assertEqual(c.occupations.first().place, Occupation.DROITE)

    def test_un_grand_modele_ne_prend_plus_l_emplacement(self):
        """Il lui faut les DEUX places : une seule condamnée suffit à l'exclure.

        C'est la règle qu'on oublie en écrivant la condamnation : sans elle, un
        QUATTRO se serait posé sur un emplacement dont la moitié est bloquée par
        un pilier.
        """
        services_cabines.condamner_place(
            emplacement=self.e1, place=Occupation.GAUCHE, motif="pilier",
            utilisateur=self.user)
        grande = self.cabine(numero="00_00_02", modele="QUATTRO")
        self.assertEqual(services_cabines.places_libres(self.e1, grande), [])
        self.assertTrue(services_cabines.est_complet(self.e1, grande))
        with self.assertRaises(services_cabines.ErreurCabine):
            services_cabines.ranger(cabine=grande, emplacement=self.e1,
                                    utilisateur=self.user)

    def test_condamner_une_place_occupee_est_refuse_en_nommant_la_cabine(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.e1,
                                place=Occupation.GAUCHE, utilisateur=self.user)
        with self.assertRaises(services_cabines.ErreurCabine) as bilan:
            services_cabines.condamner_place(
                emplacement=self.e1, place=Occupation.GAUCHE, motif="pilier",
                utilisateur=self.user)
        self.assertIn("00_00_01", " ".join(bilan.exception.messages))
        self.assertEqual(PlaceCondamnee.objects.count(), 0)

    def test_une_cabine_qui_prend_tout_bloque_les_deux_places(self):
        """Elle occupe les deux : elle empêche donc de condamner l'une comme l'autre."""
        grande = self.cabine(numero="00_00_02", modele="QUATTRO")
        services_cabines.ranger(cabine=grande, emplacement=self.e1,
                                utilisateur=self.user)
        for place in (Occupation.GAUCHE, Occupation.DROITE):
            with self.subTest(place=place):
                with self.assertRaises(services_cabines.ErreurCabine) as bilan:
                    services_cabines.condamner_place(
                        emplacement=self.e1, place=place, motif="pilier",
                        utilisateur=self.user)
                self.assertIn("00_00_02", " ".join(bilan.exception.messages))

    def test_condamner_deux_fois_est_refuse(self):
        services_cabines.condamner_place(
            emplacement=self.e1, place=Occupation.GAUCHE, motif="pilier",
            utilisateur=self.user)
        with self.assertRaises(services_cabines.ErreurCabine) as bilan:
            services_cabines.condamner_place(
                emplacement=self.e1, place=Occupation.GAUCHE, motif="encore",
                utilisateur=self.user)
        self.assertIn("déjà", " ".join(bilan.exception.messages))
        self.assertEqual(PlaceCondamnee.objects.count(), 1)

    def test_une_place_inconnue_est_refusee(self):
        for place in ("T", "M", "", "gauche"):
            with self.subTest(place=place):
                with self.assertRaises(services_cabines.ErreurCabine):
                    services_cabines.condamner_place(
                        emplacement=self.e1, place=place, motif="x",
                        utilisateur=self.user)

    def test_une_aire_illimitee_n_a_pas_de_place_a_condamner(self):
        with self.assertRaises(services_cabines.ErreurCabine) as bilan:
            services_cabines.condamner_place(
                emplacement=self.tampon, place=Occupation.GAUCHE, motif="x",
                utilisateur=self.user)
        self.assertIn("Désactivez", " ".join(bilan.exception.messages))

    def test_rouvrir_rend_la_place(self):
        services_cabines.condamner_place(
            emplacement=self.e1, place=Occupation.GAUCHE, motif="pilier",
            utilisateur=self.user)
        services_cabines.rouvrir_place(
            emplacement=self.e1, place=Occupation.GAUCHE, utilisateur=self.user)
        self.assertEqual(services_cabines.places_libres(self.e1), ["G", "D"])
        self.assertEqual(PlaceCondamnee.objects.count(), 0)

    def test_rouvrir_une_place_qui_n_est_pas_condamnee_est_refuse(self):
        with self.assertRaises(services_cabines.ErreurCabine):
            services_cabines.rouvrir_place(
                emplacement=self.e1, place=Occupation.GAUCHE, utilisateur=self.user)

    def test_l_ecran_des_places_dit_condamnee_et_pourquoi(self):
        """Condamnée n'est pas occupée, et l'écran doit faire la différence.

        Une place qui disparaît sans explication passe pour un défaut
        d'affichage, et quelqu'un finit par y poser une cabine à la main.
        """
        services_cabines.condamner_place(
            emplacement=self.e1, place=Occupation.GAUCHE, motif="pilier béton",
            utilisateur=self.user)
        r = self.client.get(f"/api/emplacements/{self.e1.id}/places/")
        self.assertEqual(r.status_code, 200, r.data)
        gauche = next(p for p in r.data["places"] if p["code"] == "G")
        droite = next(p for p in r.data["places"] if p["code"] == "D")
        self.assertFalse(gauche["libre"])
        self.assertEqual(gauche["condamnee"], "pilier béton")
        self.assertIsNone(gauche["cabine"])      # condamnée, pas occupée
        self.assertTrue(droite["libre"])
        self.assertIsNone(droite["condamnee"])
        self.assertEqual(r.data["libres"], ["D"])

    def test_l_api_condamne_et_rouvre(self):
        url = f"/api/emplacements/{self.e1.id}/place/"
        r = self.client.post(url, {"place": "G", "condamnee": True,
                                   "motif": "pilier"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([p["place"] for p in r.data["places_condamnees"]], ["G"])
        self.assertEqual(r.data["places_condamnees"][0]["motif"], "pilier")
        self.assertEqual(r.data["places_condamnees"][0]["cree_par"], "Luka G.")

        r = self.client.post(url, {"place": "G", "condamnee": False}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["places_condamnees"], [])

    def test_une_place_condamnee_survit_a_la_remise_a_zero(self):
        """Un pilier est toujours là après un vidage du stock.

        La condamnation décrit l'entrepôt, pas le stock — l'effacer obligerait à
        recondamner les mêmes places après chaque essai.
        """
        services_cabines.condamner_place(
            emplacement=self.e1, place=Occupation.GAUCHE, motif="pilier",
            utilisateur=self.user)
        self.cabine()
        with tempfile.TemporaryDirectory() as dossier:
            services_cabines.vider_le_stock(utilisateur=self.user, dossier=dossier)
        self.assertEqual(PlaceCondamnee.objects.count(), 1)
        self.assertEqual(
            services_cabines.etat_du_stock()["conserves"]["places_condamnees"], 1)

    def test_supprimer_l_emplacement_emporte_ses_condamnations(self):
        """CASCADE : une condamnation sans emplacement ne veut rien dire."""
        services_cabines.condamner_place(
            emplacement=self.e2, place=Occupation.GAUCHE, motif="pilier",
            utilisateur=self.user)
        self.e2.delete()
        self.assertEqual(PlaceCondamnee.objects.count(), 0)


class ComparateurParSemaineTest(BaseActivation):
    URL = "/api/cabines-attendues/par_semaine/"

    def setUp(self):
        super().setUp()
        # S37 : trois annoncées, une arrivée et rangée, une arrivée puis envoyée.
        for i, semaine in enumerate(["S37", "S37", "S37", "S38"], start=1):
            CabineAttendue.objects.update_or_create(
                numero=f"00_00_1{i}",
                defaults={"modele": "DUO", "chantier": "000200",
                          "semaine_production": semaine})

    def lignes(self):
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 200, r.data)
        return r.data, {x["semaine"]: x for x in r.data["semaines"]}

    def test_sans_aucune_cabine_tout_reste_a_venir(self):
        d, par = self.lignes()
        self.assertEqual(par["S37"]["annoncees"], 3)
        self.assertEqual(par["S37"]["arrivees"], 0)
        self.assertEqual(par["S37"]["reste"], 3)
        self.assertEqual(par["S38"]["annoncees"], 1)
        self.assertEqual(d["annoncees"], 4)
        self.assertEqual(d["arrivees"], 0)

    def test_une_cabine_entree_compte_pour_sa_semaine(self):
        services_cabines.creer_cabine(numero="00_00_11", chantier="000200",
                                      modele="DUO", utilisateur=self.user)
        _, par = self.lignes()
        self.assertEqual(par["S37"]["arrivees"], 1)
        self.assertEqual(par["S37"]["reste"], 2)
        self.assertEqual(par["S38"]["arrivees"], 0)

    def test_une_cabine_envoyee_reste_arrivee(self):
        """LE point du comparateur.

        La question est « la production de S37 est-elle arrivée ? ». Une cabine
        posée puis livrée est bien arrivée : la retirer du compte ferait baisser
        le chiffre à mesure que la production part, et la comparaison ne
        voudrait plus rien dire.
        """
        c = services_cabines.creer_cabine(numero="00_00_11", chantier="000200",
                                          modele="DUO", utilisateur=self.user)
        services_cabines.envoyer(cabine=c, utilisateur=self.user, note="départ chantier")
        _, par = self.lignes()
        self.assertEqual(par["S37"]["arrivees"], 1)
        # « Rangées » est la question suivante, et elle répond autrement.
        self.assertEqual(par["S37"]["rangees"], 0)

    def test_rangees_compte_celles_qui_sont_encore_quelque_part(self):
        c = services_cabines.creer_cabine(numero="00_00_11", chantier="000200",
                                          modele="DUO", utilisateur=self.user)
        services_cabines.ranger(cabine=c, emplacement=self.e1,
                                place=Occupation.GAUCHE, utilisateur=self.user)
        _, par = self.lignes()
        self.assertEqual(par["S37"]["arrivees"], 1)
        self.assertEqual(par["S37"]["rangees"], 1)

    def test_les_semaines_sont_triees_et_les_sans_semaine_en_dernier(self):
        CabineAttendue.objects.update_or_create(
            numero="00_00_99", defaults={"modele": "DUO", "chantier": "000201",
                                         "semaine_production": ""})
        d, _ = self.lignes()
        noms = [x["semaine"] for x in d["semaines"]]
        self.assertEqual(noms, ["S37", "S38", ""])

    def test_une_cabine_hors_fichier_est_comptee_a_part(self):
        """Elle n'appartient à aucune semaine : la rattacher au hasard serait faux."""
        services_cabines.creer_cabine(
            numero="00_00_77", chantier="000202", modele="DUO",
            utilisateur=self.user, motif_hors_fichier="essai de recette")
        d, par = self.lignes()
        self.assertEqual(d["hors_fichier"], 1)
        self.assertEqual(sum(x["arrivees"] for x in d["semaines"]), 0)

    def test_la_lecture_est_ouverte_a_tout_compte(self):
        """Comme le reste de la vue, et c'est délibéré.

        L'écran d'entrée lit `CabineAttendue` pour se pré-remplir : fermer la
        lecture casserait l'entrée en stock. Ce tableau n'est donc pas caché par
        un droit — il est simplement réservé aux administrateurs à l'AFFICHAGE,
        parce qu'un cariste range des cabines et n'analyse pas le plan de
        production.
        """
        operateur = Utilisateur.objects.create_user(
            username="cariste", password="secret123", role=Utilisateur.OPERATEUR)
        self.client.force_authenticate(user=operateur)
        self.assertEqual(self.client.get(self.URL).status_code, 200)

    def test_sans_compte_c_est_refuse(self):
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(self.URL).status_code, (401, 403))
