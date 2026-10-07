"""La taille d'un modèle, et l'emplacement qu'elle occupe.

Deux cabines tiennent dans un emplacement — une seule si c'est un grand modèle.
Cette règle a trois pièces, et chacune peut se casser seule :

- `ModeleCabine` dit quels modèles sont grands, et se règle à l'écran ;
- `services_cabines.ranger()` l'applique, en refusant l'emplacement déjà occupé ;
- `/emplacements/<id>/places/?pour_cabine=<id>` la fait connaître à l'écran AVANT le
  geste, pour ne pas proposer « Gauche » à une cabine qui remplit l'emplacement.

Le cas qui coûte cher n'est pas le refus : c'est l'acceptation silencieuse. Une
cabine posée à côté d'un grand modèle tient physiquement de travers, et on ne
s'en aperçoit qu'en venant la chercher.
"""
from rest_framework.test import APITestCase

from wms import services_cabines
from wms.models import (Cabine, CabineAttendue, Emplacement, ModeleCabine,
                        Occupation, Utilisateur, Zone)


class BaseModeles(APITestCase):
    def setUp(self):
        self.user = Utilisateur.objects.create_user(
            username="op", password="secret123", role=Utilisateur.ADMIN, nom="Luka G.")
        self.client.force_authenticate(user=self.user)
        self.zone = Zone.objects.create(nom="Rack A", ordre=1)
        self.e1 = Emplacement.objects.create(code="C001", zone_cabine=self.zone)
        self.e2 = Emplacement.objects.create(code="C002", zone_cabine=self.zone)
        self.tampon = Emplacement.objects.create(
            code="TAMPON", zone_cabine=self.zone, mode_places=Emplacement.ILLIMITE)
        # `update_or_create` et non `create` : la migration a déjà semé les six
        # grands modèles connus, QUATTRO compris. Les tests règlent la taille
        # qu'ils veulent examiner sans supposer une base vierge.
        ModeleCabine.objects.update_or_create(
            cle="QUATTRO", defaults={"nom": "QUATTRO", "grand": True})
        ModeleCabine.objects.update_or_create(
            cle="DUO", defaults={"nom": "DUO", "grand": False})

    def cabine(self, numero="00_00_01", chantier="000123", **kw):
        return services_cabines.creer_cabine(
            numero=numero, chantier=chantier, utilisateur=self.user, **kw)


class TailleDuModeleTest(BaseModeles):
    def test_normalisation_de_la_cle(self):
        """« xl  (2Modules) » et « XL (2MODULES) » sont le même modèle.

        Le fichier de production écrit « XL (2modules) », avec une minuscule au
        milieu. Comparer sur le nom tel quel en aurait fait deux modèles réglés
        séparément — et l'un des deux serait resté « une place » sans que
        personne le voie.
        """
        self.assertEqual(ModeleCabine.normaliser(" xl  (2Modules) "), "XL (2MODULES)")
        ModeleCabine.objects.update_or_create(
            cle="XL (2MODULES)", defaults={"nom": "XL (2modules)", "grand": True})
        self.assertTrue(ModeleCabine.est_grand("xl (2MODULES)"))
        self.assertTrue(ModeleCabine.est_grand("XL  (2modules)"))

    def test_modele_inconnu_compte_pour_normal(self):
        """Le défaut laisse ranger.

        Refuser tout modèle non déclaré bloquerait l'entrepôt un lundi matin sur
        une ligne de tableur. Un modèle nouveau apparaît dans l'écran des
        modèles, marqué « une place », et se corrige d'une touche.
        """
        self.assertFalse(ModeleCabine.est_grand("K1B"))
        self.assertFalse(ModeleCabine.est_grand(""))
        self.assertFalse(ModeleCabine.est_grand(None))

    def test_la_cabine_lit_la_taille_de_son_modele(self):
        grande = self.cabine(numero="00_00_01", modele="QUATTRO")
        petite = self.cabine(numero="00_00_02", chantier="000456", modele="DUO")
        self.assertTrue(grande.prend_tout_l_emplacement)
        self.assertFalse(petite.prend_tout_l_emplacement)

    def test_reclasser_un_modele_change_les_cabines_deja_en_stock(self):
        """La taille n'est pas recopiée sur la fiche, elle est lue.

        Un modèle reclassé doit valoir pour les cabines DÉJÀ entrées : une copie
        au moment de l'entrée aurait figé la règle, et la même cabine aurait été
        petite ou grande selon le jour de son arrivée.
        """
        c = self.cabine(modele="DUO")
        self.assertFalse(c.prend_tout_l_emplacement)
        ModeleCabine.objects.filter(cle="DUO").update(grand=True)
        self.assertTrue(c.prend_tout_l_emplacement)


class EmplacementEntierTest(BaseModeles):
    def test_un_grand_modele_prend_l_emplacement_entier(self):
        c = self.cabine(modele="QUATTRO")
        services_cabines.ranger(cabine=c, emplacement=self.e1, utilisateur=self.user)
        occupation = c.occupations.first()
        self.assertEqual(occupation.place, Occupation.ENTIER)
        self.assertEqual(services_cabines.places_libres(self.e1), [])
        self.assertTrue(services_cabines.est_complet(self.e1))

    def test_la_place_envoyee_est_corrigee_et_non_refusee(self):
        """Un écran qui ignore encore la règle ne doit pas empêcher de ranger.

        C'est le modèle qui décide, pas l'écran. Refuser « place=G » aurait
        bloqué le rangement sur un détail que l'opérateur ne contrôle pas.
        """
        c = self.cabine(modele="QUATTRO")
        services_cabines.ranger(cabine=c, emplacement=self.e1, place="G",
                                utilisateur=self.user)
        self.assertEqual(c.occupations.first().place, Occupation.ENTIER)

    def test_un_grand_modele_refuse_un_emplacement_deja_occupe(self):
        petite = self.cabine(numero="00_00_01", modele="DUO")
        services_cabines.ranger(cabine=petite, emplacement=self.e1, place="G",
                                utilisateur=self.user)
        grande = self.cabine(numero="00_00_02", chantier="000456", modele="QUATTRO")
        with self.assertRaises(services_cabines.ErreurCabine) as bilan:
            services_cabines.ranger(cabine=grande, emplacement=self.e1,
                                    utilisateur=self.user)
        message = " ".join(bilan.exception.messages)
        self.assertIn("tout l'emplacement", message)
        self.assertIn("00_00_01", message)      # on dit QUI est là
        self.assertIsNone(grande.occupations.first().emplacement_id)

    def test_aucune_voisine_a_cote_d_un_grand_modele(self):
        grande = self.cabine(numero="00_00_01", modele="QUATTRO")
        services_cabines.ranger(cabine=grande, emplacement=self.e1, utilisateur=self.user)
        petite = self.cabine(numero="00_00_02", chantier="000456", modele="DUO")
        with self.assertRaises(services_cabines.ErreurCabine) as bilan:
            services_cabines.ranger(cabine=petite, emplacement=self.e1, place="D",
                                    utilisateur=self.user)
        message = " ".join(bilan.exception.messages)
        self.assertIn("en entier", message)
        self.assertIn("00_00_01", message)

    def test_l_emplacement_entier_remplit_les_deux_places_a_l_ecran(self):
        """L'écran doit montrer les deux places prises, et par qui.

        Laisser « Droite » vide alors que rien n'y rentre enverrait un cariste
        essayer, et l'échec arriverait après qu'il a soulevé la cabine.
        """
        c = self.cabine(modele="QUATTRO")
        services_cabines.ranger(cabine=c, emplacement=self.e1, utilisateur=self.user)
        etat = services_cabines.occupation(self.e1)
        self.assertEqual(sorted(etat), ["D", "G"])
        self.assertIsNotNone(etat["G"])
        self.assertIsNotNone(etat["D"])
        self.assertEqual(etat["G"].cabine.numero, "00_00_01")
        self.assertEqual(etat["D"].cabine, etat["G"].cabine)

    def test_deux_cabines_normales_tiennent_ensemble(self):
        a = self.cabine(numero="00_00_01", modele="DUO")
        b = self.cabine(numero="00_00_02", chantier="000456", modele="DUO")
        services_cabines.ranger(cabine=a, emplacement=self.e1, place="G",
                                utilisateur=self.user)
        services_cabines.ranger(cabine=b, emplacement=self.e1, place="D",
                                utilisateur=self.user)
        self.assertEqual(services_cabines.places_libres(self.e1), [])
        self.assertEqual(services_cabines.cabines_presentes(self.e1).count(), 2)

    def test_capacite_illimitee_ignore_la_taille(self):
        """Une aire tampon n'a pas de places : la règle ne s'y applique pas."""
        a = self.cabine(numero="00_00_01", modele="QUATTRO")
        b = self.cabine(numero="00_00_02", chantier="000456", modele="QUATTRO")
        services_cabines.ranger(cabine=a, emplacement=self.tampon, utilisateur=self.user)
        services_cabines.ranger(cabine=b, emplacement=self.tampon, utilisateur=self.user)
        self.assertFalse(services_cabines.est_complet(self.tampon))
        self.assertEqual(services_cabines.cabines_presentes(self.tampon).count(), 2)

    def test_l_emplacement_libere_reprend_ses_deux_places(self):
        c = self.cabine(modele="QUATTRO")
        services_cabines.ranger(cabine=c, emplacement=self.e1, utilisateur=self.user)
        services_cabines.envoyer(cabine=c, utilisateur=self.user, note="départ chantier")
        self.assertEqual(services_cabines.places_libres(self.e1), ["G", "D"])


class PlacesSelonLaCabineTest(BaseModeles):
    """`/places/?pour_cabine=` : ce que l'écran apprend AVANT le geste."""

    def test_sans_cabine_la_reponse_est_celle_d_une_cabine_ordinaire(self):
        r = self.client.get(f"/api/emplacements/{self.e1.id}/places/")
        self.assertEqual(r.data["libres"], ["G", "D"])
        self.assertIsNone(r.data["pour_cabine"])

    def test_avec_un_grand_modele_il_n_y_a_rien_a_choisir(self):
        c = self.cabine(modele="QUATTRO")
        r = self.client.get(f"/api/emplacements/{self.e1.id}/places/?pour_cabine={c.id}")
        self.assertEqual(r.data["libres"], ["T"])
        self.assertTrue(r.data["pour_cabine"]["tout_l_emplacement"])
        self.assertEqual(r.data["pour_cabine"]["modele"], "QUATTRO")
        self.assertFalse(r.data["complet"])

    def test_un_grand_modele_devant_un_emplacement_occupe_est_annonce_complet(self):
        """Complet POUR CETTE CABINE, alors qu'une place reste libre.

        C'est toute la raison du paramètre : l'emplacement n'est pas plein, mais
        elle l'est pour celle-là. Sans cela l'écran proposait « Droite », le
        cariste soulevait la cabine, et le serveur refusait ensuite.
        """
        petite = self.cabine(numero="00_00_01", modele="DUO")
        services_cabines.ranger(cabine=petite, emplacement=self.e1, place="G",
                                utilisateur=self.user)
        grande = self.cabine(numero="00_00_02", chantier="000456", modele="QUATTRO")
        r = self.client.get(f"/api/emplacements/{self.e1.id}/places/?pour_cabine={grande.id}")
        self.assertEqual(r.data["libres"], [])
        self.assertTrue(r.data["complet"])
        # Le même emplacement, pour une cabine ordinaire, a encore une place.
        r2 = self.client.get(f"/api/emplacements/{self.e1.id}/places/?pour_cabine={petite.id}")
        self.assertIn("D", r2.data["libres"])

    def test_un_parametre_absurde_ne_fait_pas_lever(self):
        for valeur in ["", "abc", "0", "999999"]:
            with self.subTest(cabine=valeur):
                r = self.client.get(
                    f"/api/emplacements/{self.e1.id}/places/?pour_cabine={valeur}")
                self.assertEqual(r.status_code, 200)


class EcranDesModelesTest(BaseModeles):
    def setUp(self):
        super().setUp()
        CabineAttendue.objects.create(numero="26_02_01", chantier="251213",
                                      modele="XL (2modules)")
        CabineAttendue.objects.create(numero="26_02_02", chantier="251213",
                                      modele="XL (2modules)")
        CabineAttendue.objects.create(numero="26_02_03", chantier="251213",
                                      modele="SOLO")

    def test_la_liste_montre_les_modeles_vus_dans_les_donnees(self):
        """Un modèle nouveau se règle sans que personne ait à le créer.

        La liste n'est pas la table : c'est la table PLUS ce que le fichier de
        production et le stock montrent. Sinon on découvrirait l'existence d'un
        modèle le jour où une cabine ne rentre pas dans son emplacement.
        """
        # `motif_hors_fichier` : cette classe a semé des cabines attendues, ce qui
        # arme la règle « une cabine non annoncée ne s'enregistre pas ». On veut ici
        # une cabine EN STOCK dont le modèle n'est pas dans le fichier — c'est
        # exactement le cas que l'écran des modèles doit montrer.
        self.cabine(modele="DUO", motif_hors_fichier="essai du modèle en stock")
        r = self.client.get("/api/modeles-cabine/")
        self.assertEqual(r.status_code, 200)
        par_nom = {m["nom"]: m for m in r.data["modeles"]}
        self.assertIn("XL (2modules)", par_nom)
        self.assertIn("SOLO", par_nom)
        self.assertEqual(par_nom["XL (2modules)"]["nb_attendues"], 2)
        # Semé par la migration : déjà réglé « grand » avant toute cabine.
        self.assertTrue(par_nom["XL (2modules)"]["grand"])
        self.assertEqual(par_nom["SOLO"]["nb_attendues"], 1)
        self.assertEqual(par_nom["DUO"]["nb_en_stock"], 1)
        # Vus dans les données mais pas encore réglés : comptés « une place ».
        self.assertFalse(par_nom["SOLO"]["grand"])
        self.assertFalse(par_nom["SOLO"]["regle"])

    def test_un_modele_regle_sans_aucune_cabine_reste_montre(self):
        """« COLLAB » a été déclaré grand modèle avant sa première cabine."""
        ModeleCabine.objects.update_or_create(
            cle="COLLAB", defaults={"nom": "COLLAB", "grand": True})
        r = self.client.get("/api/modeles-cabine/")
        par_nom = {m["nom"]: m for m in r.data["modeles"]}
        self.assertIn("COLLAB", par_nom)
        self.assertTrue(par_nom["COLLAB"]["grand"])
        self.assertEqual(par_nom["COLLAB"]["nb_attendues"], 0)

    def test_regler_cree_le_modele_au_besoin(self):
        r = self.client.post("/api/modeles-cabine/regler/",
                             {"nom": "XL (2modules)", "grand": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content[:300])
        modele = ModeleCabine.objects.get(cle="XL (2MODULES)")
        self.assertTrue(modele.grand)
        self.assertEqual(modele.nom, "XL (2modules)")
        self.assertEqual(modele.modifie_par, self.user)

    def test_regler_bascule_dans_les_deux_sens(self):
        self.client.post("/api/modeles-cabine/regler/",
                         {"nom": "DUO", "grand": True}, format="json")
        self.assertTrue(ModeleCabine.objects.get(cle="DUO").grand)
        self.client.post("/api/modeles-cabine/regler/",
                         {"nom": "DUO", "grand": False}, format="json")
        self.assertFalse(ModeleCabine.objects.get(cle="DUO").grand)

    def test_regler_sans_nom_est_refuse(self):
        r = self.client.post("/api/modeles-cabine/regler/", {"grand": True},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_le_droit_modeles_est_exige(self):
        lecture = Utilisateur.objects.create_user(
            username="lecture", password="secret123", role=Utilisateur.LECTURE)
        self.client.force_authenticate(user=lecture)
        self.assertEqual(self.client.get("/api/modeles-cabine/").status_code, 200)
        r = self.client.post("/api/modeles-cabine/regler/",
                             {"nom": "DUO", "grand": True}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(ModeleCabine.objects.get(cle="DUO").grand)


class EmplacementsHorsRegleTest(BaseModeles):
    """Ce qu'un reclassement laisse derrière lui.

    Régler « DUO » sur grand modèle ne déplace aucune cabine : le WMS écrirait
    une position que personne n'a vérifiée devant le rack. Mais l'emplacement qui
    portait deux DUO côte à côte ne respecte plus la règle, et il faut le dire —
    sinon l'écart se découvre un par un, au hasard des rangements refusés.
    """

    def test_aucun_emplacement_hors_regle_au_depart(self):
        a = self.cabine(numero="00_00_01", modele="DUO")
        b = self.cabine(numero="00_00_02", chantier="000456", modele="DUO")
        services_cabines.ranger(cabine=a, emplacement=self.e1, place="G",
                                utilisateur=self.user)
        services_cabines.ranger(cabine=b, emplacement=self.e1, place="D",
                                utilisateur=self.user)
        self.assertEqual(services_cabines.emplacements_hors_regle(), [])

    def test_un_reclassement_signale_l_emplacement(self):
        a = self.cabine(numero="00_00_01", modele="DUO")
        b = self.cabine(numero="00_00_02", chantier="000456", modele="DUO")
        services_cabines.ranger(cabine=a, emplacement=self.e1, place="G",
                                utilisateur=self.user)
        services_cabines.ranger(cabine=b, emplacement=self.e1, place="D",
                                utilisateur=self.user)
        ModeleCabine.objects.filter(cle="DUO").update(grand=True)

        hors = services_cabines.emplacements_hors_regle()
        self.assertEqual([t["code"] for t in hors], ["C001"])
        self.assertEqual(sorted(c["numero"] for c in hors[0]["cabines"]),
                         ["00_00_01", "00_00_02"])
        # Rien n'a bougé : c'est un travail d'entrepôt, pas une correction de base.
        a.refresh_from_db()
        self.assertEqual(a.occupations.first().emplacement_id, self.e1.id)

    def test_une_seule_cabine_dans_son_emplacement_n_est_pas_hors_regle(self):
        c = self.cabine(modele="DUO")
        services_cabines.ranger(cabine=c, emplacement=self.e1, place="G",
                                utilisateur=self.user)
        ModeleCabine.objects.filter(cle="DUO").update(grand=True)
        self.assertEqual(services_cabines.emplacements_hors_regle(), [])

    def test_la_capacite_illimitee_n_est_jamais_hors_regle(self):
        a = self.cabine(numero="00_00_01", modele="QUATTRO")
        b = self.cabine(numero="00_00_02", chantier="000456", modele="QUATTRO")
        services_cabines.ranger(cabine=a, emplacement=self.tampon, utilisateur=self.user)
        services_cabines.ranger(cabine=b, emplacement=self.tampon, utilisateur=self.user)
        self.assertEqual(services_cabines.emplacements_hors_regle(), [])

    def test_l_ecran_des_modeles_porte_la_liste(self):
        a = self.cabine(numero="00_00_01", modele="DUO")
        b = self.cabine(numero="00_00_02", chantier="000456", modele="DUO")
        services_cabines.ranger(cabine=a, emplacement=self.e1, place="G",
                                utilisateur=self.user)
        services_cabines.ranger(cabine=b, emplacement=self.e1, place="D",
                                utilisateur=self.user)
        self.client.post("/api/modeles-cabine/regler/",
                         {"nom": "DUO", "grand": True}, format="json")
        r = self.client.get("/api/modeles-cabine/")
        self.assertEqual([t["code"] for t in r.data["emplacements_hors_regle"]], ["C001"])


class PlusieursEmplacementsTest(BaseModeles):
    """Une cabine peut tenir sur plusieurs emplacements, et il faut le VOIR.

    Un XL (3modules) occupe trois emplacements. Chacun est pris en entier, et la
    fiche de l'une doit nommer les deux autres : sinon un cariste voit une cabine
    complète là où il n'y en a qu'un tiers, et cherche le reste au hasard du rack.
    """

    def setUp(self):
        super().setUp()
        self.e3 = Emplacement.objects.create(code="C003", zone_cabine=self.zone)
        ModeleCabine.objects.update_or_create(
            cle="XL (3MODULES)", defaults={"nom": "XL (3modules)", "grand": True})
        self.cab = self.cabine(modele="XL (3modules)")
        for i, emp in enumerate([self.e1, self.e2, self.e3]):
            services_cabines.ranger(cabine=self.cab, emplacement=emp,
                                    ajouter=bool(i), utilisateur=self.user)

    def test_trois_emplacements_pris_en_entier(self):
        places = sorted(o.place for o in self.cab.occupations.all())
        self.assertEqual(places, [Occupation.ENTIER] * 3)
        for emp in [self.e1, self.e2, self.e3]:
            with self.subTest(emplacement=emp.code):
                self.assertTrue(services_cabines.est_complet(emp))

    def test_la_position_nomme_les_trois(self):
        self.cab.refresh_from_db()
        for code in ["C001", "C002", "C003"]:
            self.assertIn(code, self.cab.position)

    def test_l_api_rend_les_trois_occupations_avec_chaque_emplacement(self):
        """C'est ce que l'écran lit pour écrire « 3 emplacements : C001, C002, C003 ».

        Sans les occupations dans la charge utile, l'écran ne peut afficher que
        `position` — « C001·T, C002·T, C003·T », qui se lit comme un code de rack.
        """
        r = self.client.get(f"/api/emplacements/{self.e1.id}/places/")
        self.assertEqual(r.status_code, 200)
        occupee = [p for p in r.data["places"] if not p["libre"]][0]
        codes = sorted(o["emplacement_code"] for o in occupee["cabine"]["occupations"])
        self.assertEqual(codes, ["C001", "C002", "C003"])
        self.assertEqual(occupee["cabine"]["nb_emplacements"], 3)

    def test_une_seule_occupation_marquee_entiere_par_emplacement(self):
        """Chaque emplacement porte UNE occupation, pas deux places distinctes.

        C'est ce qui permet à l'écran de n'afficher qu'une ligne au lieu de
        répéter le même numéro de cabine sous « Gauche » puis sous « Droite ».
        """
        r = self.client.get(f"/api/emplacements/{self.e1.id}/places/")
        entieres = [p for p in r.data["places"]
                    if p["occupation"] and p["occupation"]["place"] == Occupation.ENTIER]
        self.assertEqual(len(entieres), 2)      # les deux places pointent…
        self.assertEqual(entieres[0]["occupation"]["id"],
                         entieres[1]["occupation"]["id"])   # …sur la MÊME occupation

    def test_l_envoi_libere_les_trois_emplacements(self):
        services_cabines.envoyer(cabine=self.cab, utilisateur=self.user, note="départ chantier")
        for emp in [self.e1, self.e2, self.e3]:
            with self.subTest(emplacement=emp.code):
                self.assertEqual(services_cabines.places_libres(emp), ["G", "D"])


class ReferentielTest(BaseModeles):
    def test_les_places_du_referentiel_sont_g_et_d(self):
        r = self.client.get("/api/referentiels-cabine/")
        self.assertEqual([p["code"] for p in r.data["places"]], ["G", "D"])

    def test_le_mode_par_defaut_est_deux_places(self):
        e = Emplacement.objects.create(code="C009")
        self.assertEqual(e.mode_places, Emplacement.GD)
        self.assertEqual(e.get_mode_places_display(), "2 places (gauche, droite)")
        self.assertFalse(e.illimite)

    def test_une_cabine_envoyee_rend_l_emplacement(self):
        c = self.cabine(modele="QUATTRO")
        services_cabines.ranger(cabine=c, emplacement=self.e1, utilisateur=self.user)
        services_cabines.envoyer(cabine=c, utilisateur=self.user, note="départ chantier")
        self.assertEqual(services_cabines.places_libres(self.e1), ["G", "D"])
        self.assertEqual(Cabine.objects.get(pk=c.pk).statut, Cabine.ENVOYE)
