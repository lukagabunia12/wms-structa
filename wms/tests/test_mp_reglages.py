"""Matières premières : régler les emplacements et les seuils, alerter, déplacer.

Ce que ces tests tiennent :
- un emplacement MP se réserve à un ou plusieurs codes — à l'unité comme en
  nombre —, et seuls ceux-là y entrent ; une réservation ne déplace rien ;
- le seuil d'alerte se règle pour un ou plusieurs codes, par le référentiel ;
- la cloche signale les codes sous leur seuil et les lignes posées là où leur
  code n'est plus accepté — et le pouls suit l'ensemble, pas seulement le nombre ;
- changer d'emplacement est UN geste : tout ou rien, une ligne de journal par
  ligne déplacée — d'où, vers où —, jamais une sortie suivie d'une entrée.
"""
from rest_framework.test import APIClient, APITestCase

from wms import services_mp
from wms.admin import ArticleMPAdmin, ArticleMPForm, EmplacementForm
from wms.models import (ArticleMP, Emplacement, MouvementMP, PlaceCondamnee, StockMP,
                        Utilisateur)


class BaseReglages(APITestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create_user(
            username="chef", password="motdepasse123", role=Utilisateur.ADMIN, nom="Véro")
        self.client.force_authenticate(self.admin)
        self.ah500 = Emplacement.objects.create(
            code="AH500", rack="AH", colonne=500, niveau=0, usage=Emplacement.MP_VITRAGE)
        self.ah510 = Emplacement.objects.create(
            code="AH510", rack="AH", colonne=510, niveau=0, usage=Emplacement.MP_VITRAGE)
        self.cartons = Emplacement.objects.create(
            code="AH501", rack="AH", colonne=500, niveau=1, usage=Emplacement.MP_CARTON)
        self.cabines = Emplacement.objects.create(code="AC550", rack="AC")
        self.v470 = ArticleMP.objects.get(code="VITR.470X2072.BP")      # seuil 50
        self.v927 = ArticleMP.objects.get(code="VITR.927X2075.BP")      # seuil 50
        self.v1060 = ArticleMP.objects.get(code="VITR.1060X2075.BP")    # sans seuil
        self.v445 = ArticleMP.objects.get(code="VITR.445X2072.BP")      # ancienne gen
        self.c8fd = ArticleMP.objects.get(code="C8.FD.2115X1015X90")

    def entrer(self, emplacement=None, place="G", article=None, quantite=19, **extra):
        return services_mp.entrer(emplacement=emplacement or self.ah500, place=place,
                                  article=article or self.v470, quantite=quantite,
                                  utilisateur=self.admin, **extra)

    def reserver(self, emplacements, articles, mode="remplacer"):
        return services_mp.regler_codes([e.pk for e in emplacements],
                                        [a.pk for a in articles], mode,
                                        utilisateur=self.admin)

    def codes(self, emplacement):
        return [a.code for a in services_mp.codes_acceptes(emplacement)]

    def client_avec(self, **droits):
        u = Utilisateur.objects.create_user(username="op", password="motdepasse123",
                                            role=Utilisateur.OPERATEUR, **droits)
        c = APIClient()
        c.force_authenticate(u)
        return c


class CodesAcceptesTest(BaseReglages):
    def test_un_emplacement_ouvert_accepte_toute_sa_famille(self):
        self.assertEqual(self.codes(self.ah500), [])
        self.entrer(article=self.v470)
        self.entrer(article=self.v927)
        self.assertEqual(StockMP.objects.count(), 2)

    def test_reserve_seuls_ses_codes_entrent(self):
        bilan = self.reserver([self.ah500], [self.v470])
        self.assertEqual(bilan["changes"], ["AH500"])
        self.entrer(article=self.v470)
        with self.assertRaisesMessage(services_mp.ErreurMP,
                                      "AH500 est réservé à VITR.470X2072.BP"):
            self.entrer(article=self.v927)
        self.assertEqual(StockMP.objects.count(), 1)

    def test_le_refus_nomme_les_codes_attendus(self):
        self.reserver([self.ah500], [self.v470, self.v927, self.v1060,
                                     ArticleMP.objects.get(code="VITR.474X2075.BP")])
        with self.assertRaisesMessage(services_mp.ErreurMP, "et 1 autre"):
            self.entrer(article=ArticleMP.objects.get(code="VITR.572X2072.BP"))

    def test_les_suggestions_se_limitent_aux_codes_acceptes(self):
        self.reserver([self.ah500], [self.v470])
        codes = [a["code"] for a in services_mp.suggerer("vitr.4", emplacement=self.ah500)]
        self.assertEqual(codes, ["VITR.470X2072.BP"])
        ouverts = [a["code"] for a in services_mp.suggerer("vitr.4", emplacement=self.ah510)]
        self.assertIn("VITR.474X2075.BP", ouverts)

    def test_une_suggestion_dit_ou_le_code_est_attendu(self):
        self.reserver([self.ah510, self.ah500], [self.v470])
        r = self.client.get("/api/mp/suggestions/", {"q": "vitr.470",
                                                     "emplacement": self.ah500.id})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data[0]["reserve_sur"], ["AH500", "AH510"])

    def test_le_contenu_donne_les_codes_et_marque_ce_qui_n_y_va_plus(self):
        self.entrer(article=self.v927)
        self.reserver([self.ah500], [self.v470])
        d = services_mp.contenu(self.ah500)
        self.assertEqual([a["code"] for a in d["codes_acceptes"]], ["VITR.470X2072.BP"])
        ligne = d["places"][0]["lignes"][0]
        self.assertEqual(ligne["code"], "VITR.927X2075.BP")
        self.assertTrue(ligne["hors_reservation"])

    def test_ajouter_garde_ce_qui_y_etait(self):
        self.reserver([self.ah500], [self.v470])
        self.reserver([self.ah500], [self.v927], mode="ajouter")
        self.assertEqual(self.codes(self.ah500), ["VITR.470X2072.BP", "VITR.927X2075.BP"])

    def test_ajouter_ne_ferme_pas_un_emplacement_ouvert(self):
        """Ouvert à toute sa famille, il accepte déjà le code : « ajouter » ne
        doit pas le réserver à ce seul code."""
        self.reserver([self.ah510], [self.v470])
        bilan = self.reserver([self.ah500, self.ah510], [self.v927], mode="ajouter")
        self.assertEqual((bilan["changes"], bilan["deja"]), (["AH510"], ["AH500"]))
        self.assertEqual(self.codes(self.ah500), [])
        self.entrer(article=self.v1060)

    def test_tous_retire_la_reservation(self):
        self.reserver([self.ah500], [self.v470])
        bilan = self.reserver([self.ah500], [], mode="tous")
        self.assertEqual(bilan["changes"], ["AH500"])
        self.assertEqual(self.codes(self.ah500), [])
        self.entrer(article=self.v927)

    def test_chaque_emplacement_prend_les_codes_de_sa_famille(self):
        """Le sol aux VITR.470, le niveau du dessus aux C8.FD : un seul réglage."""
        bilan = self.reserver([self.ah500, self.cartons], [self.v470, self.c8fd])
        self.assertEqual(sorted(bilan["changes"]), ["AH500", "AH501"])
        self.assertEqual(self.codes(self.ah500), ["VITR.470X2072.BP"])
        self.assertEqual(self.codes(self.cartons), ["C8.FD.2115X1015X90"])

    def test_sans_code_de_sa_famille_rien_ne_change_et_c_est_dit(self):
        """« Remplacer par rien » voudrait dire « tout accepter » : refusé."""
        self.reserver([self.cartons], [self.c8fd])
        bilan = self.reserver([self.ah500, self.cartons], [self.v470])
        self.assertEqual(bilan["changes"], ["AH500"])
        self.assertEqual(bilan["bloques"][0]["code"], "AH501")
        self.assertIn("aucun des codes choisis", bilan["bloques"][0]["message"])
        self.assertEqual(self.codes(self.cartons), ["C8.FD.2115X1015X90"])

    def test_un_emplacement_de_cabines_est_nomme(self):
        bilan = self.reserver([self.cabines, self.ah500], [self.v470])
        self.assertEqual(bilan["bloques"][0]["code"], "AC550")
        self.assertIn("cabines", bilan["bloques"][0]["message"])

    def test_deja_regle(self):
        self.reserver([self.ah500], [self.v470])
        bilan = self.reserver([self.ah500], [self.v470])
        self.assertEqual((bilan["changes"], bilan["deja"]), ([], ["AH500"]))

    def test_le_stock_deja_pose_reste_et_est_nomme(self):
        self.entrer(article=self.v927)
        bilan = self.reserver([self.ah500], [self.v470])
        self.assertEqual(bilan["hors_reservation"],
                         [{"id": self.ah500.id, "code": "AH500", "codes": ["VITR.927X2075.BP"]}])
        self.assertEqual(StockMP.objects.get().article, self.v927)

    def test_un_code_retire_ne_se_reserve_pas(self):
        ArticleMP.objects.filter(pk=self.v1060.pk).update(actif=False)
        self.v1060.refresh_from_db()
        with self.assertRaisesMessage(services_mp.ErreurMP, "n'est plus actif"):
            self.reserver([self.ah500], [self.v1060])

    def test_l_apercu_n_ecrit_rien(self):
        bilan = services_mp.apercu_codes([self.ah500.id], [self.v470.id], "remplacer")
        self.assertEqual(bilan["changes"], ["AH500"])
        self.assertEqual(self.codes(self.ah500), [])

    def test_changer_de_famille_oublie_les_codes(self):
        self.reserver([self.ah500], [self.v470])
        services_mp.changer_usage([self.ah500.id], "carton")
        self.assertEqual(self.codes(self.ah500), [])
        self.reserver([self.ah510], [self.v470])
        r = self.client.patch(f"/api/emplacements/{self.ah510.id}/", {"usage": "carton"},
                              format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["codes_acceptes"], [])

    def test_le_patch_n_ecrit_pas_les_codes(self):
        """Le champ du modèle aurait laissé passer un carton sur des vitrages."""
        r = self.client.patch(f"/api/emplacements/{self.ah500.id}/",
                              {"codes_acceptes": [self.c8fd.id]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.codes(self.ah500), [])

    def test_api_codes(self):
        r = self.client.post("/api/emplacements/codes/", {
            "ids": [self.ah500.id], "articles": [self.v470.id], "mode": "remplacer",
            "apercu": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.codes(self.ah500), [])
        r = self.client.post("/api/emplacements/codes/", {
            "ids": [self.ah500.id], "articles": [self.v470.id], "mode": "remplacer"},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.codes(self.ah500), ["VITR.470X2072.BP"])
        r = self.client.get(f"/api/emplacements/{self.ah500.id}/")
        self.assertEqual(r.data["codes_acceptes"], [{"id": self.v470.id,
                                                     "code": "VITR.470X2072.BP"}])

    def test_api_codes_refus_lisibles(self):
        for corps, morceau in [
                ({"ids": [self.ah500.id], "articles": [], "mode": "remplacer"}, "au moins un"),
                ({"ids": [self.ah500.id], "articles": [999999], "mode": "remplacer"},
                 "n'existent plus"),
                ({"ids": [self.ah500.id], "articles": [self.v470.id], "mode": "x"}, "inconnu"),
                ({"ids": [], "articles": [self.v470.id], "mode": "remplacer"}, "Aucun")]:
            with self.subTest(corps=corps):
                r = self.client.post("/api/emplacements/codes/", corps, format="json")
                self.assertEqual(r.status_code, 400)
                self.assertIn(morceau, str(r.data))

    def test_api_codes_demande_le_reglage_des_emplacements(self):
        c = self.client_avec(**{f"droit_{d}": True for d in Utilisateur.DROITS
                                if d != "empl_regler"})
        r = c.post("/api/emplacements/codes/", {"ids": [self.ah500.id],
                                                 "articles": [self.v470.id],
                                                 "mode": "remplacer"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_l_administration_suit_la_meme_regle(self):
        from wms.models import FamilleMP
        vitrage = FamilleMP.objects.get(code="vitrage")
        donnees = {"code": "AH500", "usage": "mp", "mode_places": "gd",
                   "familles": [vitrage.pk], "codes_acceptes": [self.c8fd.pk], "actif": True}
        form = EmplacementForm(data=donnees, instance=self.ah500)
        self.assertFalse(form.is_valid())
        self.assertIn("codes_acceptes", form.errors)
        form = EmplacementForm(data={**donnees, "codes_acceptes": [self.v470.pk]},
                               instance=self.ah500)
        self.assertTrue(form.is_valid(), form.errors)
        # Toutes les familles : un carton peut y être réservé.
        form = EmplacementForm(data={**donnees, "familles": []}, instance=self.ah500)
        self.assertTrue(form.is_valid(), form.errors)

    def test_un_code_reserve_ne_change_pas_de_famille_ni_ne_se_retire(self):
        """Sinon l'emplacement qui le réserve n'accepterait plus rien."""
        self.reserver([self.ah500], [self.v470])
        base = {"code": self.v470.code, "famille": "vitrage", "designation": "x",
                "fournisseur": "", "numero": "", "references": "", "actif": True}
        for changement, champ in [({"famille": "carton"}, "famille"), ({"actif": False}, "actif")]:
            with self.subTest(champ=champ):
                form = ArticleMPForm(data={**base, **changement}, instance=self.v470)
                self.assertFalse(form.is_valid())
                self.assertIn("AH500", str(form.errors[champ]))
        self.assertTrue(ArticleMPForm(data=base, instance=self.v470).is_valid())
        # La liste modifiable de l'administration passe par la même règle.
        from django.contrib.admin.sites import site
        from django.test import RequestFactory
        requete = RequestFactory().get("/")
        requete.user = self.admin
        liste = ArticleMPAdmin(ArticleMP, site).get_changelist_form(requete)
        self.assertTrue(issubclass(liste, ArticleMPForm))

    def test_la_fiche_d_un_code_dit_ou_il_est_attendu(self):
        self.reserver([self.ah510], [self.v470])
        r = self.client.get("/api/mp/article/", {"id": self.v470.id})
        self.assertEqual(r.data["reserve_sur"], [{"id": self.ah510.id, "code": "AH510"}])

    def test_la_liste_des_emplacements_ne_coute_pas_une_requete_par_emplacement(self):
        self.reserver([self.ah500, self.ah510], [self.v470])
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as avant:
            self.client.get("/api/emplacements/", {"rack": "AH"})
        for i in range(6):
            e = Emplacement.objects.create(code=f"AH6{i}0", rack="AH", colonne=600 + i,
                                           niveau=0, usage=Emplacement.MP_VITRAGE)
            self.reserver([e], [self.v927])
        with CaptureQueriesContext(connection) as apres:
            self.client.get("/api/emplacements/", {"rack": "AH"})
        self.assertEqual(len(apres.captured_queries), len(avant.captured_queries))


class SeuilsTest(BaseReglages):
    def test_le_meme_seuil_pour_plusieurs_codes(self):
        r = services_mp.regler_seuils([self.v470.id, self.v1060.id], "20",
                                      utilisateur=self.admin)
        self.assertEqual((r["seuil"], r["nombre"]), (20, 2))
        self.assertEqual(set(ArticleMP.objects.filter(pk__in=[self.v470.pk, self.v1060.pk])
                             .values_list("seuil_reappro", flat=True)), {20})

    def test_vide_ou_zero_retire_l_alerte(self):
        for brut in ["", None, "0", "aucun"]:
            with self.subTest(brut=brut):
                services_mp.regler_seuils([self.v470.id], brut)
                self.v470.refresh_from_db()
                self.assertIsNone(self.v470.seuil_reappro)

    def test_seuils_illisibles(self):
        for brut, morceau in [("2,5", "illisible"), ("-1", "illisible"),
                              ("1000000", "faute de frappe"), ("²", "illisible")]:
            with self.subTest(brut=brut), self.assertRaisesMessage(services_mp.ErreurMP, morceau):
                services_mp.regler_seuils([self.v470.id], brut)
        self.v470.refresh_from_db()
        self.assertEqual(self.v470.seuil_reappro, 50)

    def test_dit_quand_le_seuil_n_aura_pas_d_effet(self):
        r = services_mp.regler_seuils([self.v445.id, self.v470.id], 10)
        self.assertEqual(r["sans_effet"], ["VITR.445X2072.BP"])

    def test_api_seuils_demande_sa_case(self):
        corps = {"articles": [self.v470.id], "seuil": 12}
        self.assertEqual(self.client_avec(droit_mp=True).post(
            "/api/mp/seuils/", corps, format="json").status_code, 403)
        r = self.client.post("/api/mp/seuils/", corps, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.v470.refresh_from_db()
        self.assertEqual(self.v470.seuil_reappro, 12)

    def test_api_seuils_avec_la_seule_case_des_seuils(self):
        c = self.client_avec(droit_mp_seuils=True)
        r = c.post("/api/mp/seuils/", {"articles": [self.v470.id], "seuil": 30}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def test_api_code_inconnu(self):
        r = self.client.post("/api/mp/seuils/", {"articles": [999999], "seuil": 3},
                             format="json")
        self.assertEqual(r.status_code, 400)


class AlertesTest(BaseReglages):
    def setUp(self):
        super().setUp()
        # Une base de départ connue : un seul code surveillé, le 470.
        ArticleMP.objects.exclude(pk=self.v470.pk).update(seuil_reappro=None)

    def cles(self):
        return [x["cle"] for g in services_mp.alertes()["groupes"] for x in g["items"]]

    def test_un_code_sans_stock_avec_un_seuil_sonne(self):
        a = services_mp.alertes()
        self.assertEqual(a["total"], 1)
        item = a["groupes"][0]["items"][0]
        self.assertEqual((item["code"], item["en_stock"], item["seuil"]),
                         ("VITR.470X2072.BP", 0, 50))

    def test_le_seuil_se_franchit_en_dessous(self):
        self.entrer(quantite=50)
        self.assertEqual(services_mp.alertes()["total"], 0)
        ligne = StockMP.objects.get()
        services_mp.sortir(ligne=ligne, quantite=1)
        self.assertEqual(self.cles(), [f"seuil:{self.v470.id}"])

    def test_ancienne_generation_et_code_retire_ne_sonnent_jamais(self):
        ArticleMP.objects.filter(pk=self.v445.pk).update(seuil_reappro=100)
        ArticleMP.objects.filter(pk=self.v1060.pk).update(seuil_reappro=10, actif=False)
        self.assertEqual(self.cles(), [f"seuil:{self.v470.id}"])

    def test_le_plus_urgent_d_abord(self):
        services_mp.regler_seuils([self.v927.id], 50)
        self.entrer(article=self.v470, quantite=40)
        cles = self.cles()
        self.assertEqual(cles, [f"seuil:{self.v927.id}", f"seuil:{self.v470.id}"])

    def test_une_ligne_qui_n_est_plus_acceptee_sonne(self):
        self.entrer(quantite=60)
        ligne = self.entrer(article=self.v927, place="D", quantite=3)
        self.reserver([self.ah500], [self.v470])
        a = services_mp.alertes()
        groupe = [g for g in a["groupes"] if g["type"] == "hors_reservation"][0]
        self.assertEqual(groupe["items"][0]["ligne"], ligne.id)
        self.assertEqual(groupe["items"][0]["acceptes"], ["VITR.470X2072.BP"])
        self.assertEqual(groupe["items"][0]["position"], "AH500·D")

    def test_api_alertes(self):
        r = self.client.get("/api/alertes/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sorted(r.data), ["empreinte", "groupes", "total"])
        self.assertEqual(r.data["groupes"][0]["type"], "seuil")
        self.assertEqual(APIClient().get("/api/alertes/").status_code, 401)

    def test_le_pouls_suit_les_alertes(self):
        p = self.client.get("/api/pouls/").data
        self.assertEqual(p["alertes"], 1)
        self.entrer(quantite=60)
        apres = self.client.get("/api/pouls/").data
        self.assertEqual(apres["alertes"], 0)
        self.assertNotEqual(apres["alertes_empreinte"], p["alertes_empreinte"])

    def test_l_empreinte_change_meme_si_le_nombre_reste(self):
        """Une alerte se règle pendant qu'une autre naît : même nombre, autre ensemble."""
        avant = services_mp.empreinte_alertes()
        services_mp.regler_seuils([self.v470.id], None)
        services_mp.regler_seuils([self.v927.id], 5)
        apres = services_mp.empreinte_alertes()
        self.assertEqual(avant[0], apres[0])
        self.assertNotEqual(avant[1], apres[1])

    def test_l_empreinte_suit_ce_que_dit_l_alerte(self):
        """De 8 à 0 sous le seuil : même ensemble, mais une alerte plus urgente."""
        ligne = self.entrer(quantite=8)
        avant = services_mp.empreinte_alertes()
        services_mp.sortir(ligne=ligne)
        apres = services_mp.empreinte_alertes()
        self.assertEqual(avant[0], apres[0])
        self.assertNotEqual(avant[1], apres[1])

    def test_le_pouls_et_la_liste_disent_la_meme_chose(self):
        self.entrer(article=self.v927, quantite=2)
        self.reserver([self.ah500], [self.v470])
        a = services_mp.alertes()
        self.assertEqual((a["total"], a["empreinte"]), services_mp.empreinte_alertes())

    def test_la_sortie_dit_que_le_code_passe_sous_le_seuil(self):
        ligne = self.entrer(quantite=55)
        r = self.client.post("/api/mp/sortir/", {"ligne": ligne.id, "quantite": 10},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["article"]["en_stock"], 45)
        self.assertTrue(r.data["article"]["sous_seuil"])


class DeplacerTest(BaseReglages):
    def deplacer(self, lignes, vers=None, place="D", **extra):
        corps = [{"ligne": x.pk if hasattr(x, "pk") else x[0].pk,
                  "quantite": None if hasattr(x, "pk") else x[1]} for x in lignes]
        return services_mp.deplacer(lignes=corps, vers=vers or self.ah510, place=place,
                                    utilisateur=self.admin, **extra)

    def stock(self):
        return sorted((x.emplacement.code, x.place, x.article.code, x.quantite)
                      for x in StockMP.objects.select_related("emplacement", "article"))

    def test_toute_la_ligne_change_d_emplacement(self):
        ligne = self.entrer(quantite=19)
        r = self.deplacer([ligne])
        self.assertEqual(self.stock(), [("AH510", "D", "VITR.470X2072.BP", 19)])
        self.assertEqual(r["deplaces"][0]["origine"], "AH500·G")
        self.assertEqual(r["deplaces"][0]["destination"], "AH510·D")

    def test_une_partie_seulement(self):
        ligne = self.entrer(quantite=19)
        self.deplacer([(ligne, 4)])
        self.assertEqual(self.stock(), [("AH500", "G", "VITR.470X2072.BP", 15),
                                        ("AH510", "D", "VITR.470X2072.BP", 4)])

    def test_plusieurs_lignes_d_un_geste(self):
        a = self.entrer(quantite=19)
        b = self.entrer(article=self.v927, place="M", quantite=7)
        r = self.deplacer([a, b])
        self.assertEqual(len(r["deplaces"]), 2)
        self.assertEqual(self.stock(), [("AH510", "D", "VITR.470X2072.BP", 19),
                                        ("AH510", "D", "VITR.927X2075.BP", 7)])

    def test_sur_le_meme_emplacement_une_autre_place(self):
        ligne = self.entrer(quantite=19)
        self.deplacer([ligne], vers=self.ah500, place="M")
        self.assertEqual(self.stock(), [("AH500", "M", "VITR.470X2072.BP", 19)])

    def test_s_ajoute_a_ce_qui_est_deja_a_l_arrivee(self):
        ligne = self.entrer(quantite=19)
        self.entrer(emplacement=self.ah510, place="D", quantite=5)
        r = self.deplacer([ligne])
        self.assertEqual(self.stock(), [("AH510", "D", "VITR.470X2072.BP", 24)])
        self.assertEqual(r["deplaces"][0]["reste"], 24)

    def test_deux_lignes_du_meme_code_vers_la_meme_place(self):
        a = self.entrer(quantite=19)
        b = self.entrer(place="M", quantite=6)
        self.deplacer([a, b])
        self.assertEqual(self.stock(), [("AH510", "D", "VITR.470X2072.BP", 25)])

    def test_le_journal_ecrit_une_ligne_par_ligne_deplacee(self):
        ligne = self.entrer(quantite=19)
        MouvementMP.objects.all().delete()
        self.deplacer([(ligne, 4)])
        m = MouvementMP.objects.get()
        self.assertEqual((m.type, m.article_code, m.origine, m.position, m.quantite,
                          m.reste, m.reste_origine),
                         ("transfert", "VITR.470X2072.BP", "AH500·G", "AH510·D", 4, 4, 15))
        self.assertEqual(m.utilisateur_nom, "Véro")
        self.assertIn("AH500·G → AH510·D", str(m))

    def test_un_deplacement_n_est_ni_une_sortie_ni_une_entree(self):
        ligne = self.entrer(quantite=19)
        self.deplacer([ligne])
        self.assertEqual(MouvementMP.objects.filter(type="sortie").count(), 0)
        self.assertEqual(MouvementMP.objects.filter(type="entree").count(), 1)

    def test_l_ancienne_generation_se_deplace_sans_confirmation(self):
        ligne = self.entrer(article=self.v445, ancienne_confirmee=True)
        self.deplacer([ligne])
        self.assertEqual(self.stock()[0][:3], ("AH510", "D", "VITR.445X2072.BP"))

    def test_depuis_un_emplacement_hors_service(self):
        """Ce qui reste sur un emplacement hors service peut toujours en partir."""
        ligne = self.entrer(quantite=19)
        Emplacement.objects.filter(pk=self.ah500.pk).update(actif=False, motif_inactif="lisse")
        self.deplacer([ligne])
        self.assertEqual(self.stock()[0][0], "AH510")

    def test_refus_et_rien_ne_bouge(self):
        ligne = self.entrer(quantite=19)
        PlaceCondamnee.objects.create(emplacement=self.ah510, place="M", motif="pilier")
        hors = Emplacement.objects.create(code="AH520", usage=Emplacement.MP_VITRAGE,
                                          actif=False, motif_inactif="lisse tordue")
        reserve = Emplacement.objects.create(code="AH530", usage=Emplacement.MP_VITRAGE)
        self.reserver([reserve], [self.v927])
        cas = [
            ({"vers": self.cabines}, "range des cabines"),
            ({"vers": self.cartons}, "n'accepte que les cartons"),
            ({"vers": hors}, "lisse tordue"),
            ({"place": "M"}, "pilier"),
            ({"place": "X"}, "gauche, milieu ou droite"),
            ({"vers": reserve}, "réservé à VITR.927X2075.BP"),
            ({"vers": self.ah500, "place": "G"}, "déjà en AH500·G"),
            ({"lignes": [(ligne, 20)]}, "Il n'y a que 19"),
            ({"lignes": [(ligne, "2,5")]}, "illisible"),
            ({"lignes": []}, "au moins une ligne"),
        ]
        for options, morceau in cas:
            with self.subTest(morceau=morceau):
                lignes = options.pop("lignes", [ligne])
                with self.assertRaisesMessage(services_mp.ErreurMP, morceau):
                    self.deplacer(lignes, **options)
        self.assertEqual(self.stock(), [("AH500", "G", "VITR.470X2072.BP", 19)])
        self.assertEqual(MouvementMP.objects.filter(type="transfert").count(), 0)

    def test_tout_ou_rien(self):
        """La deuxième ligne n'est pas acceptée à l'arrivée : la première ne part pas."""
        a = self.entrer(quantite=19)
        b = self.entrer(article=self.v927, place="M", quantite=7)
        self.reserver([self.ah510], [self.v470])
        with self.assertRaisesMessage(services_mp.ErreurMP, "VITR.927X2075.BP n'y entre pas"):
            self.deplacer([a, b])
        self.assertEqual(self.stock(), [("AH500", "G", "VITR.470X2072.BP", 19),
                                        ("AH500", "M", "VITR.927X2075.BP", 7)])

    def test_une_meme_ligne_deux_fois_est_refusee(self):
        ligne = self.entrer(quantite=19)
        with self.assertRaisesMessage(services_mp.ErreurMP, "deux fois"):
            services_mp.deplacer(lignes=[{"ligne": ligne.pk, "quantite": 2},
                                         {"ligne": ligne.pk, "quantite": 5}],
                                 vers=self.ah510, place="D")
        self.assertEqual(self.stock(), [("AH500", "G", "VITR.470X2072.BP", 19)])

    def test_une_ligne_disparue_entre_temps(self):
        ligne = self.entrer(quantite=19)
        services_mp.sortir(ligne=ligne)
        with self.assertRaisesMessage(services_mp.ErreurMP, "n'existe plus"):
            self.deplacer([ligne])

    def test_api_deplacer(self):
        ligne = self.entrer(quantite=19)
        r = self.client.post("/api/mp/deplacer/", {
            "lignes": [{"ligne": ligne.id, "quantite": 5}], "code": "LOC:ah510",
            "place": "d"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["deplaces"][0]["quantite"], 5)
        self.assertEqual(r.data["destination"]["code"], "AH510")
        self.assertEqual(r.data["destination"]["places"][2]["quantite"], 5)
        self.assertEqual([s["code"] for s in r.data["sources"]], ["AH500"])
        self.assertEqual(r.data["sources"][0]["quantite"], 14)

    def test_api_refus_en_400(self):
        ligne = self.entrer(quantite=19)
        r = self.client.post("/api/mp/deplacer/", {
            "lignes": [{"ligne": ligne.id}], "emplacement": self.cabines.id, "place": "G"},
            format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("range des cabines", r.data["erreur"][0])
        r = self.client.post("/api/mp/deplacer/", {"lignes": "n'importe quoi",
                                                   "emplacement": self.ah510.id, "place": "G"},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_api_deplacer_demande_la_case_mp(self):
        ligne = self.entrer(quantite=19)
        corps = {"lignes": [{"ligne": ligne.id}], "emplacement": self.ah510.id, "place": "D"}
        for droits in ({"droit_cab_ranger": True, "droit_cab_envoyer": True},
                       {"droit_empl_regler": True, "droit_mp_seuils": True}):
            with self.subTest(droits=droits):
                c = self.client_avec(**droits)
                self.assertEqual(c.post("/api/mp/deplacer/", corps, format="json")
                                 .status_code, 403)
                Utilisateur.objects.filter(username="op").delete()
        c = self.client_avec(droit_mp=True)
        self.assertEqual(c.post("/api/mp/deplacer/", corps, format="json").status_code, 200)

    def test_le_journal_retrouve_un_deplacement_par_son_depart(self):
        ligne = self.entrer(quantite=19)
        self.deplacer([ligne])
        r = self.client.get("/api/mp/journal/", {"search": "AH500", "type": "transfert"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["origine"], "AH500·G")
        self.assertEqual(r.data["results"][0]["type_libelle"], "Changement d'emplacement")
