"""Tests des cabines : places gauche/droite, statuts, express, archives, historique."""
from django.core.exceptions import ValidationError
from rest_framework.test import APITestCase

from wms import services_cabines
from wms.models import Cabine, Emplacement, MouvementCabine, Utilisateur, Zone


class BaseCabines(APITestCase):
    def setUp(self):
        self.user = Utilisateur.objects.create_user(
            username="op", password="secret123", role=Utilisateur.ADMIN, nom="Luka G.")
        self.client.force_authenticate(user=self.user)
        self.zone_ranger = Zone.objects.create(nom="À ranger cabines", ordre=1)
        self.zone_prod = Zone.objects.create(nom="Sortie prod", ordre=2)
        self.e1 = Emplacement.objects.create(code="C001", zone_cabine=self.zone_ranger)
        self.e2 = Emplacement.objects.create(code="C002", zone_cabine=self.zone_prod)

    def cabine(self, numero="00_00_01", chantier="000123", **kw):
        return services_cabines.creer_cabine(
            numero=numero, chantier=chantier, utilisateur=self.user, **kw)


class ZonesTest(BaseCabines):
    def test_emplacement_expose_sa_zone(self):
        r = self.client.get(f"/api/emplacements/{self.e1.id}/")
        self.assertEqual(r.data["zone_cabine_nom"], "À ranger cabines")


class PlacesTest(BaseCabines):
    def test_deux_places_libres_au_depart(self):
        """Deux places, plus trois : les modèles ont grandi, l'emplacement non."""
        r = self.client.get(f"/api/emplacements/{self.e1.id}/places/")
        self.assertEqual(r.data["libres"], ["G", "D"])
        self.assertFalse(r.data["complet"])

    def test_place_prise_disparait_des_options(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.e1, place="G", utilisateur=self.user)
        r = self.client.get(f"/api/emplacements/{self.e1.id}/places/")
        self.assertEqual(r.data["libres"], ["D"])
        occupee = [p for p in r.data["places"] if p["code"] == "G"][0]
        self.assertFalse(occupee["libre"])
        self.assertEqual(occupee["cabine"]["numero"], "00_00_01")

    def test_emplacement_complet_bloque_le_rangement(self):
        for i, place in enumerate(["G", "D"], start=1):
            c = self.cabine(numero=f"00_00_0{i}", chantier=f"00000{i}")
            services_cabines.ranger(cabine=c, emplacement=self.e1, place=place,
                                    utilisateur=self.user)
        r = self.client.get(f"/api/emplacements/{self.e1.id}/places/")
        self.assertEqual(r.data["libres"], [])
        self.assertTrue(r.data["complet"])

        trop = self.cabine(numero="00_00_09", chantier="000009")
        rep = self.client.post(f"/api/cabines/{trop.id}/ranger/",
                               {"emplacement": self.e1.id, "place": "G"}, format="json")
        self.assertEqual(rep.status_code, 400)
        self.assertIn("occupée", " ".join(rep.data["erreur"]))

    def test_place_liberee_redevient_disponible(self):
        """Déplacer la cabine rend sa place : c'est le geste « La déplacer »."""
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.e1, place="D", utilisateur=self.user)
        services_cabines.ranger(cabine=c, emplacement=self.e2, place="G", utilisateur=self.user)
        r = self.client.get(f"/api/emplacements/{self.e1.id}/places/")
        self.assertEqual(r.data["libres"], ["G", "D"])

    def test_place_inconnue_refusee(self):
        c = self.cabine()
        r = self.client.post(f"/api/cabines/{c.id}/ranger/",
                             {"emplacement": self.e1.id, "place": "X"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_cabine_envoyee_ne_reserve_plus_sa_place(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.e1, place="G", utilisateur=self.user)
        services_cabines.envoyer(cabine=c, utilisateur=self.user, note="départ chantier")
        autre = self.cabine(numero="00_00_02", chantier="000002")
        services_cabines.ranger(cabine=autre, emplacement=self.e1, place="G",
                                utilisateur=self.user)
        self.assertEqual(autre.place, "G")


class RangementTest(BaseCabines):
    def test_rangement_puis_transfert(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.e1, place="G", utilisateur=self.user)
        services_cabines.ranger(cabine=c, emplacement=self.e2, place="D", utilisateur=self.user)
        c.refresh_from_db()
        self.assertEqual(c.emplacement, self.e2)
        self.assertEqual(c.place, "D")
        types = list(MouvementCabine.objects.filter(cabine=c).values_list("type", flat=True))
        self.assertEqual(types, [MouvementCabine.TRANSFERT, MouvementCabine.RANGEMENT,
                                 MouvementCabine.CREATION])

    def test_transfert_note_les_deux_positions(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.e1, place="G", utilisateur=self.user)
        services_cabines.ranger(cabine=c, emplacement=self.e2, place="D", utilisateur=self.user)
        mv = MouvementCabine.objects.filter(type=MouvementCabine.TRANSFERT).first()
        self.assertEqual(mv.depuis, "À ranger cabines / C001·G")
        self.assertEqual(mv.vers, "Sortie prod / C002·D")

    def test_ranger_deux_fois_la_meme_place_refuse(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.e1, place="G", utilisateur=self.user)
        with self.assertRaises(services_cabines.ErreurCabine):
            services_cabines.ranger(cabine=c, emplacement=self.e1, place="G",
                                    utilisateur=self.user)

    def test_emplacement_inactif_refuse(self):
        self.e1.actif = False
        self.e1.save(update_fields=["actif"])
        c = self.cabine()
        r = self.client.post(f"/api/cabines/{c.id}/ranger/",
                             {"emplacement": self.e1.id, "place": "G"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_emplacement_manquant_refuse(self):
        c = self.cabine()
        r = self.client.post(f"/api/cabines/{c.id}/ranger/", {"place": "G"}, format="json")
        self.assertEqual(r.status_code, 400)


class ExpressTest(BaseCabines):
    """Express : rangeable sans chantier, mais pas sortable sans chantier."""

    def test_cabine_normale_exige_un_chantier(self):
        with self.assertRaises(ValidationError):
            services_cabines.creer_cabine(numero="00_00_07", chantier="",
                                          utilisateur=self.user)

    def test_api_refuse_une_normale_sans_chantier_en_400(self):
        """La règle du modèle doit remonter en 400, pas en 500.

        Le contrôle n'existait qu'au niveau du modèle : sa ValidationError n'étant pas
        une exception DRF, POST /api/cabines/ renvoyait une erreur serveur.
        """
        r = self.client.post("/api/cabines/", {"numero": "00_00_07", "chantier": ""},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("chantier", r.data)
        self.assertFalse(Cabine.objects.filter(numero="00_00_07").exists())

    def test_api_accepte_une_express_sans_chantier(self):
        r = self.client.post("/api/cabines/",
                             {"numero": "00_00_08", "chantier": "",
                              "type_cabine": Cabine.EXPRESS}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Cabine.objects.get(numero="00_00_08").chantier, "")

    def test_express_se_cree_sans_chantier(self):
        c = services_cabines.creer_cabine(numero="00_00_08", chantier="",
                                          type_cabine=Cabine.EXPRESS, utilisateur=self.user)
        self.assertEqual(c.chantier, "")
        self.assertEqual(c.type_cabine, Cabine.EXPRESS)

    def test_express_se_range_sans_chantier(self):
        c = services_cabines.creer_cabine(numero="00_00_08", chantier="",
                                          type_cabine=Cabine.EXPRESS, utilisateur=self.user)
        r = self.client.post(f"/api/cabines/{c.id}/ranger/",
                             {"emplacement": self.e1.id, "place": "G"}, format="json")
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.place, "G")

    def test_express_part_apres_affectation_du_chantier(self):
        c = services_cabines.creer_cabine(numero="00_00_08", chantier="",
                                          type_cabine=Cabine.EXPRESS, utilisateur=self.user)
        services_cabines.ranger(cabine=c, emplacement=self.e1, place="G", utilisateur=self.user)
        r = self.client.post(f"/api/cabines/{c.id}/chantier/", {"chantier": "123456"},
                             format="json")
        self.assertEqual(r.status_code, 200)
        r = self.client.post(f"/api/cabines/{c.id}/envoyer/",
                             {"note": "départ chantier"}, format="json")
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.place, "")
        self.assertEqual(c.statut, Cabine.ENVOYE)
        self.assertEqual(c.chantier, "123456")

    def test_express_ne_s_envoie_pas_sans_chantier(self):
        c = services_cabines.creer_cabine(numero="00_00_08", chantier="",
                                          type_cabine=Cabine.EXPRESS, utilisateur=self.user)
        # Avec son motif : sans lui, le refus viendrait du motif manquant et cet
        # essai ne prouverait plus rien sur le chantier.
        r = self.client.post(f"/api/cabines/{c.id}/envoyer/",
                             {"note": "départ chantier"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("chantier", str(r.data).lower())
        c.refresh_from_db()
        self.assertNotEqual(c.statut, Cabine.ENVOYE)

    def test_chantier_vide_refuse(self):
        c = services_cabines.creer_cabine(numero="00_00_08", chantier="",
                                          type_cabine=Cabine.EXPRESS, utilisateur=self.user)
        r = self.client.post(f"/api/cabines/{c.id}/chantier/", {"chantier": "  "}, format="json")
        self.assertEqual(r.status_code, 400)


class StatutsTest(BaseCabines):
    def test_statut_par_defaut_libre(self):
        self.assertEqual(self.cabine().statut, Cabine.LIBRE)

    def test_parcours_des_statuts(self):
        c = self.cabine()
        for statut in (Cabine.QUARANTAINE, Cabine.LIBRE):
            # Le motif n'est exigé QUE pour poser la quarantaine ; l'envoyer
            # aussi à la levée masquerait une régression dans un sens.
            corps = {"statut": statut}
            if statut == Cabine.QUARANTAINE:
                corps["motif"] = "paroi à reprendre"
            r = self.client.post(f"/api/cabines/{c.id}/statut/", corps, format="json")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data["statut"], statut)
        c.refresh_from_db()
        self.assertEqual(c.statut, Cabine.LIBRE)
        self.assertIsNotNone(c.statut_date)

    def test_historique_des_statuts_avec_auteur(self):
        c = self.cabine()
        r = self.client.post(f"/api/cabines/{c.id}/statut/",
                             {"statut": Cabine.QUARANTAINE, "motif": "paroi à reprendre"},
                             format="json")
        # Le code de retour AVANT de lire le journal : sans lui, un refus
        # laisserait le journal vide et l'échec dirait « NoneType », pas
        # « la requête a été refusée ».
        self.assertEqual(r.status_code, 200, r.data)
        mv = MouvementCabine.objects.filter(type=MouvementCabine.STATUT).first()
        self.assertEqual(mv.statut_avant, Cabine.LIBRE)
        self.assertEqual(mv.statut_apres, Cabine.QUARANTAINE)
        self.assertEqual(mv.utilisateur_nom, "Luka G.")
        self.assertIsNotNone(mv.date)

    def test_statut_inconnu_refuse(self):
        c = self.cabine()
        r = self.client.post(f"/api/cabines/{c.id}/statut/", {"statut": "nawak"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_meme_statut_refuse(self):
        c = self.cabine()
        r = self.client.post(f"/api/cabines/{c.id}/statut/", {"statut": Cabine.LIBRE},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_statut_envoye_passe_par_l_envoi(self):
        """Demander le statut « envoyé » doit appliquer les règles de l'envoi.

        Dont le motif, désormais : la sortie et l'envoi sont un seul geste, et
        ce chemin-ci ne doit pas être une porte de service qui l'évite.
        """
        c = self.cabine()
        r = self.client.post(f"/api/cabines/{c.id}/statut/", {"statut": Cabine.ENVOYE},
                             format="json")
        self.assertEqual(r.status_code, 400, "sans motif, l'envoi doit être refusé")
        r = self.client.post(f"/api/cabines/{c.id}/statut/",
                             {"statut": Cabine.ENVOYE, "motif": "camion 12"},
                             format="json")
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.statut, Cabine.ENVOYE)
        self.assertIsNotNone(c.envoi_date)
        self.assertEqual(MouvementCabine.objects.filter(type=MouvementCabine.ENVOI).count(), 1)


class EnvoiEtArchivesTest(BaseCabines):
    def test_envoi_libere_la_place_et_archive(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.e1, place="D", utilisateur=self.user)
        r = self.client.post(f"/api/cabines/{c.id}/envoyer/", {"note": "Camion 12"},
                             format="json")
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.statut, Cabine.ENVOYE)
        self.assertIsNone(c.emplacement)
        self.assertEqual(c.place, "")
        mv = MouvementCabine.objects.filter(type=MouvementCabine.ENVOI).first()
        self.assertEqual(mv.depuis, "À ranger cabines / C001·D")
        self.assertEqual(mv.note, "Camion 12")

    def test_cabine_envoyee_absente_de_la_liste_active(self):
        c = self.cabine()
        services_cabines.envoyer(cabine=c, utilisateur=self.user, note="départ chantier")
        self.assertEqual(self.client.get("/api/cabines/").data["count"], 0)

    def test_fichier_a_part_des_cabines_envoyees(self):
        active = self.cabine(numero="00_00_01", chantier="000111")
        envoyee = self.cabine(numero="00_00_02", chantier="000222")
        services_cabines.envoyer(cabine=envoyee, utilisateur=self.user, note="départ chantier")
        r = self.client.get(f"/api/cabines/?toutes=1&statut={Cabine.ENVOYE}")
        self.assertEqual([c["numero"] for c in r.data["results"]], ["00_00_02"])
        self.assertEqual(self.client.get("/api/cabines/").data["count"], 1)
        self.assertEqual(self.client.get("/api/cabines/").data["results"][0]["numero"],
                         active.numero)

    def test_cabine_envoyee_n_a_plus_de_position(self):
        """Une cabine partie ne doit plus afficher « rangée en … »."""
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.e1, place="G", utilisateur=self.user)
        services_cabines.envoyer(cabine=c, utilisateur=self.user, note="départ chantier")
        c.refresh_from_db()
        self.assertEqual(c.position, "")
        fiche = self.client.get(f"/api/cabines/{c.id}/").data
        self.assertEqual(fiche["position"], "")
        self.assertIsNone(fiche["emplacement_code"])
        self.assertEqual(fiche["place"], "")
        # La position au moment de l'envoi reste dans l'historique.
        mv = MouvementCabine.objects.filter(type=MouvementCabine.ENVOI).first()
        self.assertEqual(mv.depuis, "À ranger cabines / C001·G")

    def test_envoi_irreversible(self):
        c = self.cabine()
        services_cabines.envoyer(cabine=c, utilisateur=self.user, note="départ chantier")
        for chemin, corps in [("envoyer", {}),
                              ("statut", {"statut": Cabine.LIBRE}),
                              ("ranger", {"emplacement": self.e1.id, "place": "G"})]:
            with self.subTest(operation=chemin):
                r = self.client.post(f"/api/cabines/{c.id}/{chemin}/", corps, format="json")
                self.assertEqual(r.status_code, 400)

    def test_envoi_non_annulable_par_modification(self):
        c = self.cabine()
        services_cabines.envoyer(cabine=c, utilisateur=self.user, note="départ chantier")
        self.client.patch(f"/api/cabines/{c.id}/", {"statut": Cabine.LIBRE}, format="json")
        c.refresh_from_db()
        self.assertEqual(c.statut, Cabine.ENVOYE)

    def test_historique_complet_apres_envoi(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.e1, place="G", utilisateur=self.user)
        services_cabines.changer_statut(cabine=c, statut=Cabine.QUARANTAINE,
                                        utilisateur=self.user, motif="paroi à reprendre")
        services_cabines.ranger(cabine=c, emplacement=self.e2, place="D", utilisateur=self.user)
        services_cabines.envoyer(cabine=c, utilisateur=self.user, note="départ chantier")
        r = self.client.get(f"/api/cabines/{c.id}/historique/")
        types = [m["type"] for m in r.data]
        self.assertEqual(types, [MouvementCabine.ENVOI, MouvementCabine.TRANSFERT,
                                 MouvementCabine.STATUT, MouvementCabine.RANGEMENT,
                                 MouvementCabine.CREATION])
        self.assertTrue(all(m["utilisateur_nom"] == "Luka G." for m in r.data))

    def test_historique_survit_a_la_suppression_du_compte(self):
        c = self.cabine()
        services_cabines.changer_statut(cabine=c, statut=Cabine.QUARANTAINE,
                                        utilisateur=self.user, motif="paroi à reprendre")
        self.user.delete()
        mv = MouvementCabine.objects.filter(type=MouvementCabine.STATUT).first()
        self.assertIsNone(mv.utilisateur)
        self.assertEqual(mv.utilisateur_nom, "Luka G.")


class RechercheCabinesTest(BaseCabines):
    def setUp(self):
        super().setUp()
        self.c1 = self.cabine(numero="00_00_01", chantier="000123")
        self.c2 = self.cabine(numero="00_00_02", chantier="000123")
        self.c3 = self.cabine(numero="99_88_77", chantier="000999", modele="QUATTRO")
        self.express = services_cabines.creer_cabine(
            numero="55_55_55", chantier="", type_cabine=Cabine.EXPRESS, utilisateur=self.user)

    def test_recherche_par_numero_unique(self):
        r = self.client.get("/api/cabines/?numero=99_88_77")
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["numero"], "99_88_77")

    def test_recherche_par_numero_partiel(self):
        self.assertEqual(self.client.get("/api/cabines/?numero=00_00").data["count"], 2)

    def test_toutes_les_cabines_d_un_chantier(self):
        r = self.client.get("/api/cabines/?chantier_exact=000123")
        self.assertEqual(r.data["count"], 2)
        self.assertEqual(sorted(c["numero"] for c in r.data["results"]),
                         ["00_00_01", "00_00_02"])

    def test_filtre_par_statut(self):
        services_cabines.changer_statut(cabine=self.c1, statut=Cabine.QUARANTAINE,
                                        utilisateur=self.user, motif="paroi à reprendre")
        r = self.client.get(f"/api/cabines/?statut={Cabine.QUARANTAINE}")
        self.assertEqual([c["numero"] for c in r.data["results"]], ["00_00_01"])

    def test_filtre_par_type(self):
        r = self.client.get(f"/api/cabines/?type={Cabine.EXPRESS}")
        self.assertEqual([c["numero"] for c in r.data["results"]], ["55_55_55"])

    def test_filtre_sans_chantier(self):
        r = self.client.get("/api/cabines/?sans_chantier=1")
        self.assertEqual([c["numero"] for c in r.data["results"]], ["55_55_55"])

    def test_filtre_non_rangees(self):
        services_cabines.ranger(cabine=self.c1, emplacement=self.e1, place="G",
                                utilisateur=self.user)
        r = self.client.get("/api/cabines/?rangee=0")
        self.assertNotIn("00_00_01", [c["numero"] for c in r.data["results"]])
        self.assertEqual(r.data["count"], 3)

    def test_recherche_libre_sur_modele(self):
        self.assertEqual(self.client.get("/api/cabines/?search=QUATTRO").data["count"], 1)

    def test_position_et_zone_exposees(self):
        services_cabines.ranger(cabine=self.c1, emplacement=self.e1, place="D",
                                utilisateur=self.user)
        fiche = self.client.get(f"/api/cabines/{self.c1.id}/").data
        self.assertEqual(fiche["position"], "C001·D")
        self.assertEqual(fiche["zone_nom"], "À ranger cabines")
        self.assertEqual(fiche["statut_libelle"], "Conforme")
        self.assertEqual(fiche["type_libelle"], "Normale")

    def test_journal_filtrable_par_chantier(self):
        services_cabines.changer_statut(cabine=self.c1, statut=Cabine.QUARANTAINE,
                                        utilisateur=self.user, motif="paroi à reprendre")
        r = self.client.get("/api/mouvements-cabine/?search=000123")
        self.assertTrue(r.data["count"] >= 1)
        self.assertTrue(all(m["chantier"] == "000123" for m in r.data["results"]))

    def test_journal_en_lecture_seule(self):
        r = self.client.post("/api/mouvements-cabine/", {"cabine_numero": "x", "type": "statut"},
                             format="json")
        self.assertIn(r.status_code, (403, 405))


class ListeEmplacementsTest(BaseCabines):
    """Écran « Emplacements » : occupation, filtres et tris."""

    def setUp(self):
        super().setUp()
        self.e3 = Emplacement.objects.create(code="C003", zone_cabine=self.zone_prod)
        self.c1 = self.cabine(numero="00_00_01", chantier="000111")
        self.c2 = self.cabine(numero="00_00_02", chantier="000222")
        self.c3 = self.cabine(numero="99_88_77", chantier="000111", modele="QUATTRO")
        services_cabines.ranger(cabine=self.c1, emplacement=self.e1, place="G",
                                utilisateur=self.user)
        services_cabines.ranger(cabine=self.c2, emplacement=self.e1, place="D",
                                utilisateur=self.user)
        services_cabines.ranger(cabine=self.c3, emplacement=self.e2, place="D",
                                utilisateur=self.user)

    def codes(self, url):
        return [e["code"] for e in self.client.get(url).data["results"]]

    def test_cabines_associees_dans_la_liste(self):
        e = [x for x in self.client.get("/api/emplacements/").data["results"]
             if x["code"] == "C001"][0]
        # Ordre par place, de gauche à droite : c'est l'ordre où on les voit
        # devant le rack, et non l'ordre des numéros.
        self.assertEqual(sorted(c["numero"] for c in e["cabines"]),
                         ["00_00_01", "00_00_02"])
        # Les deux places sont prises : l'emplacement est plein.
        self.assertEqual(e["places_libres"], [])
        self.assertEqual(e["zone_cabine_nom"], "À ranger cabines")

    def test_cabine_envoyee_absente_de_l_emplacement(self):
        services_cabines.envoyer(cabine=self.c1, utilisateur=self.user, note="départ chantier")
        e = [x for x in self.client.get("/api/emplacements/").data["results"]
             if x["code"] == "C001"][0]
        self.assertEqual([c["numero"] for c in e["cabines"]], ["00_00_02"])
        # Une seule place rendue : l'autre porte toujours sa cabine.
        self.assertEqual(e["places_libres"], ["G"])

    def test_emplacement_complet_detecte(self):
        """Une troisième cabine n'entre plus : l'emplacement n'a que deux places."""
        self.assertTrue(self.client.get(f"/api/emplacements/{self.e1.id}/places/").data["complet"])
        c4 = self.cabine(numero="44_44_44", chantier="000444")
        with self.assertRaises(services_cabines.ErreurCabine):
            services_cabines.ranger(cabine=c4, emplacement=self.e1, place="D",
                                    utilisateur=self.user)

    def test_tri_par_code(self):
        self.assertEqual(self.codes("/api/emplacements/?ordering=code")[:3],
                         ["C001", "C002", "C003"])
        self.assertEqual(self.codes("/api/emplacements/?ordering=-code")[0], "C003")

    def test_recherche_libre_sur_le_code(self):
        self.assertEqual(self.codes("/api/emplacements/?search=C003"), ["C003"])


class ModeDeRangementTest(BaseCabines):
    """Chaque emplacement choisit son mode : deux places ou capacité illimitée."""

    def setUp(self):
        super().setUp()
        self.tampon = Emplacement.objects.create(
            code="ARANGER", zone_cabine=self.zone_ranger,
            mode_places=Emplacement.ILLIMITE)

    def test_mode_par_defaut_deux_places(self):
        self.assertEqual(self.e1.mode_places, Emplacement.GD)
        self.assertFalse(self.e1.illimite)

    def test_illimite_accepte_plus_de_deux_cabines(self):
        for i in range(1, 6):
            c = self.cabine(numero=f"00_00_0{i}", chantier=f"00000{i}")
            services_cabines.ranger(cabine=c, emplacement=self.tampon, utilisateur=self.user)
        self.assertEqual(services_cabines.cabines_presentes(self.tampon).count(), 5)
        self.assertFalse(services_cabines.est_complet(self.tampon))

    def test_illimite_range_sans_place(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.tampon, utilisateur=self.user)
        c.refresh_from_db()
        self.assertEqual(c.place, "")
        self.assertEqual(c.position, "ARANGER")

    def test_illimite_refuse_une_place(self):
        c = self.cabine()
        r = self.client.post(f"/api/cabines/{c.id}/ranger/",
                             {"emplacement": self.tampon.id, "place": "G"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("illimitée", " ".join(r.data["erreur"]))

    def test_deux_places_exige_une_place(self):
        c = self.cabine()
        r = self.client.post(f"/api/cabines/{c.id}/ranger/",
                             {"emplacement": self.e1.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_places_de_l_emplacement_illimite(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.tampon, utilisateur=self.user)
        r = self.client.get(f"/api/emplacements/{self.tampon.id}/places/")
        self.assertTrue(r.data["illimite"])
        self.assertEqual(r.data["places"], [])
        self.assertEqual(r.data["libres"], [])
        self.assertFalse(r.data["complet"])
        self.assertEqual(r.data["nb_cabines"], 1)
        self.assertEqual([x["numero"] for x in r.data["cabines"]], ["00_00_01"])

    def test_sortie_depuis_un_illimite(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.tampon, utilisateur=self.user)
        r = self.client.post(f"/api/cabines/{c.id}/envoyer/",
                             {"note": "départ chantier"}, format="json")
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertIsNone(c.emplacement)

    def test_transfert_entre_les_deux_modes(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.tampon, utilisateur=self.user)
        services_cabines.ranger(cabine=c, emplacement=self.e1, place="D", utilisateur=self.user)
        c.refresh_from_db()
        self.assertEqual(c.place, "D")
        mv = MouvementCabine.objects.filter(type=MouvementCabine.TRANSFERT).first()
        self.assertEqual(mv.depuis, "À ranger cabines / ARANGER")
        self.assertEqual(mv.vers, "À ranger cabines / C001·D")

    def test_creation_par_api_avec_choix_du_mode(self):
        r = self.client.post("/api/emplacements/",
                             {"code": "prod1", "zone_cabine": self.zone_prod.id,
                              "mode_places": Emplacement.ILLIMITE}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["code"], "PROD1")
        self.assertTrue(r.data["illimite"])
        self.assertEqual(r.data["mode_libelle"], "Capacité illimitée")

    def test_changement_de_mode_sur_emplacement_vide(self):
        r = self.client.patch(f"/api/emplacements/{self.tampon.id}/",
                              {"mode_places": Emplacement.GD}, format="json")
        self.assertEqual(r.status_code, 200)
        self.tampon.refresh_from_db()
        self.assertEqual(self.tampon.mode_places, Emplacement.GD)

    def test_changement_de_mode_refuse_si_occupe(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.tampon, utilisateur=self.user)
        r = self.client.patch(f"/api/emplacements/{self.tampon.id}/",
                              {"mode_places": Emplacement.GD}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("mode_places", r.data)
        self.tampon.refresh_from_db()
        self.assertEqual(self.tampon.mode_places, Emplacement.ILLIMITE)

    def test_liste_expose_le_mode_et_le_nombre(self):
        for i in range(1, 5):
            c = self.cabine(numero=f"00_00_0{i}", chantier=f"00000{i}")
            services_cabines.ranger(cabine=c, emplacement=self.tampon, utilisateur=self.user)
        e = [x for x in self.client.get("/api/emplacements/").data["results"]
             if x["code"] == "ARANGER"][0]
        self.assertTrue(e["illimite"])
        self.assertEqual(e["nb_cabines"], 4)
        self.assertEqual(e["places_libres"], [])

    def test_creation_directe_avec_place_sur_illimite_refusee(self):
        cabine = Cabine.objects.create(numero="00_00_09", chantier="000009")
        occupation = cabine.occupations.first()
        occupation.emplacement, occupation.place = self.tampon, "G"
        with self.assertRaises(ValidationError):
            occupation.full_clean()


class EtapesProcessusTest(BaseCabines):
    """L'étape est dérivée du statut et du rôle de la zone : jamais stockée."""

    def setUp(self):
        super().setUp()
        self.zone_ranger.role = Zone.RANGEMENT
        self.zone_ranger.save(update_fields=["role"])
        self.zone_envoi = Zone.objects.create(nom="Attente départ", role=Zone.ENVOI, ordre=3)
        self.zone_sortie_prod = Zone.objects.create(nom="Sortie de prod", role=Zone.PRODUCTION,
                                                   ordre=0)
        self.quai = Emplacement.objects.create(code="QUAI1", zone_cabine=self.zone_envoi)
        self.sortie = Emplacement.objects.create(code="SORTIE1",
                                                 zone_cabine=self.zone_sortie_prod)

    def etape(self, cabine):
        cabine.refresh_from_db()
        return cabine.etape

    def test_cabine_non_rangee_sort_de_production(self):
        self.assertEqual(self.etape(self.cabine()), "production")

    def test_cabine_dans_une_zone_de_production(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.sortie, place="G",
                                utilisateur=self.user)
        self.assertEqual(self.etape(c), "production")

    def test_cabine_rangee_est_en_stock(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.e1, place="G", utilisateur=self.user)
        self.assertEqual(self.etape(c), "rangement")

    def test_cabine_en_zone_d_envoi_attend_le_depart(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.quai, place="G",
                                utilisateur=self.user)
        self.assertEqual(self.etape(c), "envoi")

    def test_la_quarantaine_prime_sur_la_position(self):
        """Une cabine en quarantaine reste en quarantaine, même rangée en zone d'envoi."""
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.quai, place="G",
                                utilisateur=self.user)
        services_cabines.changer_statut(cabine=c, statut=Cabine.QUARANTAINE,
                                        utilisateur=self.user, motif="paroi à reprendre")
        self.assertEqual(self.etape(c), "quarantaine")
        services_cabines.changer_statut(cabine=c, statut=Cabine.LIBRE, utilisateur=self.user)
        self.assertEqual(self.etape(c), "envoi")   # redevient conforme, position reprise

    def test_etapes_chargee_et_envoyee(self):
        c = self.cabine()
        services_cabines.changer_statut(cabine=c, statut=Cabine.QUARANTAINE,
                                        utilisateur=self.user, motif="paroi à reprendre")
        self.assertEqual(self.etape(c), "quarantaine")
        services_cabines.envoyer(cabine=c, utilisateur=self.user, note="départ chantier")
        self.assertEqual(self.etape(c), "envoyee")

    def test_emplacement_sans_zone_compte_comme_rangement(self):
        libre = Emplacement.objects.create(code="SANSZONE")
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=libre, place="G", utilisateur=self.user)
        self.assertEqual(self.etape(c), "rangement")

    def test_etape_exposee_par_l_api(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.quai, place="D",
                                utilisateur=self.user)
        fiche = self.client.get(f"/api/cabines/{c.id}/").data
        self.assertEqual(fiche["etape"], "envoi")
        self.assertEqual(fiche["etape_libelle"], "En attente de départ")
        self.assertEqual(fiche["jours_immobile"], 0)
        self.assertIsNotNone(fiche["derniere_activite"])


class MotifTest(BaseCabines):
    def test_motif_consigne_dans_l_historique(self):
        c = self.cabine()
        r = self.client.post(f"/api/cabines/{c.id}/statut/",
                             {"statut": Cabine.QUARANTAINE, "motif": "Rayure sur le vitrage"},
                             format="json")
        self.assertEqual(r.status_code, 200)
        mv = MouvementCabine.objects.filter(type=MouvementCabine.STATUT).first()
        self.assertEqual(mv.note, "Rayure sur le vitrage")

    def test_motif_obligatoire_pour_poser_une_quarantaine(self):
        """Ce test disait l'inverse jusqu'à cette règle.

        Une quarantaine immobilise une cabine. Sans la raison au journal,
        personne ne sait quoi réparer pour la lever, et la cabine reste en
        travers du rack.
        """
        c = self.cabine()
        r = self.client.post(f"/api/cabines/{c.id}/statut/", {"statut": Cabine.QUARANTAINE},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("quoi réparer", " ".join(r.data["erreur"]))
        c.refresh_from_db()
        self.assertEqual(c.statut, Cabine.LIBRE)
        self.assertFalse(MouvementCabine.objects.filter(type=MouvementCabine.STATUT).exists())

    def test_motif_reste_facultatif_pour_lever_une_quarantaine(self):
        """L'autre moitié de la règle, celle qu'on casse en la durcissant.

        Constater qu'une cabine est redevenue conforme n'a rien à expliquer.
        Exiger un motif dans les deux sens ferait taper « ok » à la levée, et
        l'habitude gagnerait ensuite la pose — là où le motif compte.
        """
        c = self.cabine()
        services_cabines.changer_statut(cabine=c, statut=Cabine.QUARANTAINE,
                                        utilisateur=self.user, motif="choc à réception")
        r = self.client.post(f"/api/cabines/{c.id}/statut/", {"statut": Cabine.LIBRE},
                             format="json")
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.statut, Cabine.LIBRE)

    def test_motif_de_levee(self):
        c = self.cabine(numero="00_00_02", chantier="000002")
        services_cabines.changer_statut(cabine=c, statut=Cabine.QUARANTAINE,
                                        utilisateur=self.user, motif="Choc à réception")
        # Lever la quarantaine, c'est revenir à « Conforme » : le motif de
        # la levée doit rester consigné au journal, c'est la seule trace qu'il
        # s'est passé quelque chose sur cette cabine.
        services_cabines.changer_statut(cabine=c, statut=Cabine.LIBRE,
                                        utilisateur=self.user, motif="Contrôle OK, PV 2026-114")
        motifs = list(MouvementCabine.objects.filter(cabine=c, type=MouvementCabine.STATUT)
                      .order_by("id").values_list("note", flat=True))
        self.assertEqual(motifs, ["Choc à réception", "Contrôle OK, PV 2026-114"])


class TypesEtStatutsTest(BaseCabines):
    """Les deux règles introduites avec « Salon » et « Occasion ».

    Elles se ressemblent assez pour être confondues : trois types circulent sans
    chantier, mais AUCUN ne sort de l'entrepôt sans lui. C'est cette seconde
    moitié qu'on oublie, et c'est elle qui garantit qu'une cabine partie est
    rattachable à une commande.
    """

    def test_salon_et_occasion_se_creent_sans_chantier(self):
        for i, type_cabine in enumerate((Cabine.SALON, Cabine.OCCASION, Cabine.EXPRESS)):
            with self.subTest(type=type_cabine):
                c = services_cabines.creer_cabine(numero=f"00_10_0{i}", chantier="",
                                                  type_cabine=type_cabine,
                                                  utilisateur=self.user)
                self.assertEqual(c.chantier, "")

    def test_cabine_normale_exige_toujours_un_chantier(self):
        with self.assertRaises(Exception):
            services_cabines.creer_cabine(numero="00_10_09", chantier="",
                                          type_cabine=Cabine.NORMALE,
                                          utilisateur=self.user)

    def test_salon_et_occasion_ne_sortent_pas_sans_chantier(self):
        """L'exemption s'arrête à la porte de l'entrepôt."""
        for i, type_cabine in enumerate((Cabine.SALON, Cabine.OCCASION)):
            with self.subTest(type=type_cabine):
                c = services_cabines.creer_cabine(numero=f"00_11_0{i}", chantier="",
                                                  type_cabine=type_cabine,
                                                  utilisateur=self.user)
                services_cabines.ranger(cabine=c, emplacement=self.e1,
                                        place=Cabine.PLACES[i][0], utilisateur=self.user)
                with self.assertRaises(services_cabines.ErreurCabine):
                    services_cabines.envoyer(cabine=c, utilisateur=self.user,
                                             note="départ chantier")

    def test_le_statut_levee_n_existe_plus(self):
        c = self.cabine(numero="00_12_00", chantier="000012")
        r = self.client.post(f"/api/cabines/{c.id}/statut/", {"statut": "levee"},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_lever_une_quarantaine_rend_la_cabine_conforme(self):
        c = self.cabine(numero="00_12_01", chantier="000013")
        services_cabines.changer_statut(cabine=c, statut=Cabine.QUARANTAINE,
                                        utilisateur=self.user, motif="Rayure")
        services_cabines.changer_statut(cabine=c, statut=Cabine.LIBRE,
                                        utilisateur=self.user, motif="Retouchée")
        c.refresh_from_db()
        self.assertEqual(c.statut, Cabine.LIBRE)
        self.assertEqual(c.get_statut_display(), "Conforme")
        # Le passage par la quarantaine reste lisible dans le journal : c'est
        # là qu'on va le chercher, pas dans le statut courant.
        notes = list(MouvementCabine.objects.filter(cabine=c, type=MouvementCabine.STATUT)
                     .order_by("id").values_list("note", flat=True))
        self.assertEqual(notes, ["Rayure", "Retouchée"])


class RolesDeZoneTest(BaseCabines):
    def test_role_par_defaut_rangement(self):
        self.assertEqual(self.zone_ranger.role, Zone.RANGEMENT)


class ReferentielsTest(BaseCabines):
    def test_listes_de_choix(self):
        r = self.client.get("/api/referentiels-cabine/")
        self.assertEqual([s["code"] for s in r.data["statuts"]],
                         ["libre", "quarantaine", "envoye"])
        self.assertEqual([p["code"] for p in r.data["places"]], ["G", "D"])
        self.assertEqual([t["code"] for t in r.data["types"]],
                         ["normale", "express", "salon", "occasion"])


class DroitsCabinesTest(BaseCabines):
    def test_lecture_seule_ne_peut_pas_ranger(self):
        c = self.cabine()
        lecteur = Utilisateur.objects.create_user(username="lect", password="secret123",
                                                  role=Utilisateur.LECTURE)
        self.client.force_authenticate(user=lecteur)
        for chemin, corps in [("ranger", {"emplacement": self.e1.id, "place": "G"}),
                              ("statut", {"statut": Cabine.QUARANTAINE}),
                              ("envoyer", {})]:
            with self.subTest(operation=chemin):
                r = self.client.post(f"/api/cabines/{c.id}/{chemin}/", corps, format="json")
                self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get("/api/cabines/").status_code, 200)

    def test_operateur_sans_la_case_statut_refuse(self):
        """Toutes les autres cases cochées — ranger, sortir, corriger, le
        référentiel : aucune ne vaut « changer le statut »."""
        c = self.cabine()
        autres = {f"droit_{d}": True for d in Utilisateur.DROITS if d != "cab_statut"}
        op = Utilisateur.objects.create_user(username="op2", password="secret123",
                                             role=Utilisateur.OPERATEUR, **autres)
        self.client.force_authenticate(user=op)
        r = self.client.post(f"/api/cabines/{c.id}/statut/", {"statut": Cabine.QUARANTAINE},
                             format="json")
        self.assertEqual(r.status_code, 403)

    def test_operateur_avec_la_case_statut_autorise(self):
        c = self.cabine()
        op = Utilisateur.objects.create_user(username="op3", password="secret123",
                                             role=Utilisateur.OPERATEUR,
                                             droit_cab_statut=True)
        self.client.force_authenticate(user=op)
        r = self.client.post(f"/api/cabines/{c.id}/statut/",
                             {"statut": Cabine.QUARANTAINE, "motif": "paroi à reprendre"},
                             format="json")
        self.assertEqual(r.status_code, 200)


class CreationCabineTest(BaseCabines):
    def test_creation_par_api_journalisee(self):
        r = self.client.post("/api/cabines/", {"numero": "12_34_56", "chantier": "000777",
                                               "modele": "XL"}, format="json")
        self.assertEqual(r.status_code, 201)
        c = Cabine.objects.get(numero="12_34_56")
        self.assertEqual(c.utilisateur, self.user)
        mv = MouvementCabine.objects.get(cabine=c, type=MouvementCabine.CREATION)
        self.assertEqual(mv.statut_apres, Cabine.LIBRE)
        self.assertEqual(mv.utilisateur_nom, "Luka G.")

    def test_numero_invalide_refuse(self):
        r = self.client.post("/api/cabines/", {"numero": "123456", "chantier": "000777"},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_chantier_invalide_refuse(self):
        r = self.client.post("/api/cabines/", {"numero": "12_34_57", "chantier": "12"},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_numero_unique(self):
        self.cabine(numero="00_00_01")
        r = self.client.post("/api/cabines/", {"numero": "00_00_01", "chantier": "000777"},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_creation_directe_valide_les_formats(self):
        with self.assertRaises(ValidationError):
            Cabine.objects.create(numero="nawak", chantier="000123")

    def test_place_sans_emplacement_refusee(self):
        """La règle a suivi la position : elle porte sur l'emplacement occupé."""
        cabine = Cabine.objects.create(numero="00_00_05", chantier="000005")
        occupation = cabine.occupations.first()
        occupation.place = "G"
        with self.assertRaises(ValidationError):
            occupation.full_clean()
