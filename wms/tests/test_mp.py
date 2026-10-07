"""Matières premières : vitrages et cartons, place par place.

Ce que ces tests tiennent :
- la base est là dès l'installation, avec ses anciennes générations ;
- ce qu'on tape au poste retrouve le bon code (« vitr.8 », « 445 », « ESS 1 F ») ;
- on ne range un code que sur un emplacement MP de sa famille, sur une place
  en service, et une ancienne génération se confirme ;
- on ne sort jamais plus que ce qui est là, et tout s'écrit au journal ;
- cabines et MP ne se mélangent pas : ni dans un sens, ni dans l'autre ;
- l'usage des emplacements se change en nombre, sans jamais rien déplacer.
"""
from rest_framework.test import APIClient, APITestCase

from wms import services_cabines, services_mp
from wms.models import (ArticleMP, Cabine, Emplacement, MouvementMP, PlaceCondamnee,
                        StockMP, Utilisateur)


class BaseMP(APITestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create_user(
            username="chef", password="motdepasse123", role=Utilisateur.ADMIN, nom="Véro")
        self.client.force_authenticate(self.admin)
        self.vitrages = Emplacement.objects.create(
            code="AH500", rack="AH", colonne=500, niveau=0, usage=Emplacement.MP_VITRAGE)
        self.cartons = Emplacement.objects.create(
            code="AH501", rack="AH", colonne=500, niveau=1, usage=Emplacement.MP_CARTON)
        self.cabines = Emplacement.objects.create(code="AC550", rack="AC")
        self.v445 = ArticleMP.objects.get(code="VITR.445X2072.BP")     # ancienne gen
        self.v470 = ArticleMP.objects.get(code="VITR.470X2072.BP")
        self.c8fd = ArticleMP.objects.get(code="C8.FD.2115X1015X90")

    def entrer(self, emplacement=None, place="G", article=None, quantite=19, **extra):
        return services_mp.entrer(emplacement=emplacement or self.vitrages, place=place,
                                  article=article or self.v470, quantite=quantite,
                                  utilisateur=self.admin, **extra)


class BaseDesCodesTest(BaseMP):
    def test_la_base_est_prete(self):
        self.assertEqual(ArticleMP.objects.filter(famille=ArticleMP.VITRAGE).count(), 19)
        self.assertEqual(ArticleMP.objects.filter(famille=ArticleMP.CARTON).count(), 26)

    def test_anciennes_generations_du_fichier(self):
        """Lignes grisées des vitrages, lignes rouges des cartons."""
        anciens = set(ArticleMP.objects.filter(ancienne_generation=True)
                      .values_list("code", flat=True))
        self.assertEqual(anciens, {
            "VITR.449X2075.BP", "VITR.445X2072.BP", "VITR.694X2075.BP",
            "VITR.831X1981", "VITR.831X1977.BB",
            "C13.CF.1325X500X120", "C13.FD.1325X500X120",
            "C14.CF.1730X500X120", "C14.FD.1730X500X120"})

    def test_un_carton_donne_couvercle_et_fond(self):
        couvercle = ArticleMP.objects.get(code="C8.CF.2115X1015X90")
        self.assertIn("couvercle", couvercle.designation)
        self.assertIn("fond", self.c8fd.designation)
        self.assertEqual(self.c8fd.colisage, 160)
        self.assertIn("PFC1ESS-FD", self.c8fd.references)

    def test_le_code_se_normalise_a_l_enregistrement(self):
        a = ArticleMP.objects.create(code=" vitr.900x2000.bp ", famille=ArticleMP.VITRAGE,
                                     references="REF-1 · ref 2")
        self.assertEqual(a.code, "VITR.900X2000.BP")
        self.assertEqual(a.cle, "VITR900X2000BP")
        self.assertEqual(a.cle_references, "REF1|REF2")


class SuggestionsTest(BaseMP):
    def codes(self, texte, famille=None):
        return [a["code"] for a in services_mp.suggerer(texte, famille=famille)]

    def test_le_debut_du_code_sans_la_ponctuation(self):
        """L'exemple de l'exploitation : « vitr.8 » propose les VITR.8…"""
        codes = self.codes("vitr.8")
        self.assertTrue(codes)
        self.assertTrue(all(c.startswith("VITR.8") for c in codes), codes)

    def test_l_ancienne_generation_vient_apres(self):
        codes = self.codes("vitr.8")
        anciens = [c for c in codes if ArticleMP.objects.get(code=c).ancienne_generation]
        self.assertEqual(codes[-len(anciens):], anciens)

    def test_une_dimension_seule(self):
        self.assertEqual(self.codes("445"), ["VITR.445X2072.BP"])

    def test_le_numero_d_article(self):
        self.assertEqual(self.codes("434"), ["VITR.445X2072.BP"])

    def test_le_marquage_de_la_palette(self):
        self.assertEqual(self.codes("ESS 1 F"), ["C8.FD.2115X1015X90"])

    def test_la_famille_filtre(self):
        self.assertTrue(all(c.startswith("C") for c in self.codes("1", famille="carton")))

    def test_les_codes_inactifs_ne_se_proposent_plus(self):
        ArticleMP.objects.filter(code="VITR.445X2072.BP").update(actif=False)
        self.assertEqual(self.codes("445"), [])

    def test_l_api(self):
        r = self.client.get("/api/mp/suggestions/", {"q": "vitr.47", "famille": "vitrage"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([a["code"] for a in r.data], ["VITR.470X2072.BP", "VITR.474X2075.BP"])


class EntreeTest(BaseMP):
    def test_entrer_cree_la_ligne_et_le_journal(self):
        ligne = self.entrer(quantite=19)
        self.assertEqual((ligne.place, ligne.quantite), ("G", 19))
        m = MouvementMP.objects.get()
        self.assertEqual((m.type, m.article_code, m.position, m.quantite, m.reste),
                         ("entree", "VITR.470X2072.BP", "AH500·G", 19, 19))
        self.assertEqual(m.utilisateur_nom, "Véro")

    def test_le_meme_code_sur_la_meme_place_s_additionne(self):
        self.entrer(quantite=19)
        ligne = self.entrer(quantite=5)
        self.assertEqual(ligne.quantite, 24)
        self.assertEqual(StockMP.objects.count(), 1)
        self.assertEqual(MouvementMP.objects.first().reste, 24)

    def test_plusieurs_codes_partagent_une_place(self):
        self.entrer(quantite=19)
        self.entrer(article=ArticleMP.objects.get(code="VITR.927X2075.BP"), quantite=10)
        contenu = services_mp.contenu(self.vitrages)
        self.assertEqual(len(contenu["places"][0]["lignes"]), 2)
        self.assertEqual([p["code"] for p in contenu["places"]], ["G", "M", "D"])

    def test_refuse_un_emplacement_de_cabines(self):
        with self.assertRaisesMessage(services_mp.ErreurMP, "range des cabines"):
            self.entrer(emplacement=self.cabines)

    def test_refuse_la_mauvaise_famille(self):
        with self.assertRaisesMessage(services_mp.ErreurMP, "range des vitrages"):
            self.entrer(article=self.c8fd)

    def test_refuse_une_place_inconnue(self):
        with self.assertRaisesMessage(services_mp.ErreurMP, "gauche, milieu ou droite"):
            self.entrer(place="T")

    def test_refuse_une_place_condamnee(self):
        PlaceCondamnee.objects.create(emplacement=self.vitrages, place="M", motif="pilier")
        with self.assertRaisesMessage(services_mp.ErreurMP, "pilier"):
            self.entrer(place="M")

    def test_refuse_un_emplacement_hors_service(self):
        Emplacement.objects.filter(pk=self.vitrages.pk).update(actif=False,
                                                               motif_inactif="lisse tordue")
        with self.assertRaisesMessage(services_mp.ErreurMP, "lisse tordue"):
            self.entrer()

    def test_quantites_refusees(self):
        for brut, morceau in [("", "Indique"), ("2,5", "illisible"), ("0", "au moins 1"),
                              ("-3", "illisible"), ("1000000", "faute de frappe")]:
            with self.subTest(brut=brut), self.assertRaisesMessage(services_mp.ErreurMP, morceau):
                self.entrer(quantite=brut)
        self.assertFalse(StockMP.objects.exists())

    def test_l_ancienne_generation_se_confirme(self):
        with self.assertRaisesMessage(services_mp.ErreurMP, "ANCIENNE GÉNÉRATION"):
            self.entrer(article=self.v445)
        self.assertFalse(StockMP.objects.exists())
        self.entrer(article=self.v445, ancienne_confirmee=True)
        self.assertIn("ancienne génération confirmée", MouvementMP.objects.get().note)

    def test_api_entrer(self):
        r = self.client.post("/api/mp/entrer/", {
            "emplacement": self.vitrages.id, "place": "d", "article": self.v470.id,
            "quantite": "19"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["emplacement"]["places"][2]["quantite"], 19)

    def test_api_un_code_doit_venir_de_la_base(self):
        r = self.client.post("/api/mp/entrer/", {
            "emplacement": self.vitrages.id, "place": "G", "article": "VITR.123",
            "quantite": 1}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("liste", r.data["erreur"][0])

    def test_api_ancienne_generation_confirmee(self):
        corps = {"emplacement": self.vitrages.id, "place": "G", "article": self.v445.id,
                 "quantite": 19}
        r = self.client.post("/api/mp/entrer/", corps, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/mp/entrer/", {**corps, "ancienne_confirmee": True},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)


class SortieTest(BaseMP):
    def test_sortie_partielle(self):
        ligne = self.entrer(quantite=19)
        self.assertEqual(services_mp.sortir(ligne=ligne, quantite=5, utilisateur=self.admin), 14)
        ligne.refresh_from_db()
        self.assertEqual(ligne.quantite, 14)
        m = MouvementMP.objects.first()
        self.assertEqual((m.type, m.quantite, m.reste), ("sortie", 5, 14))

    def test_tout_sortir_efface_la_ligne(self):
        ligne = self.entrer(quantite=19)
        self.assertEqual(services_mp.sortir(ligne=ligne, utilisateur=self.admin), 0)
        self.assertFalse(StockMP.objects.exists())
        self.assertEqual(MouvementMP.objects.first().quantite, 19)

    def test_jamais_plus_que_ce_qui_est_la(self):
        ligne = self.entrer(quantite=19)
        with self.assertRaisesMessage(services_mp.ErreurMP, "Il n'y a que 19"):
            services_mp.sortir(ligne=ligne, quantite=20)
        ligne.refresh_from_db()
        self.assertEqual(ligne.quantite, 19)

    def test_une_ligne_deja_sortie(self):
        ligne = self.entrer(quantite=19)
        services_mp.sortir(ligne=ligne)
        with self.assertRaisesMessage(services_mp.ErreurMP, "n'existe plus"):
            services_mp.sortir(ligne=ligne.pk)

    def test_api_sortir(self):
        ligne = self.entrer(quantite=19)
        r = self.client.post("/api/mp/sortir/", {"ligne": ligne.id, "quantite": 4,
                                                 "note": "production"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["reste"], 15)
        self.assertEqual(MouvementMP.objects.first().note, "production")


class DroitsTest(BaseMP):
    def connecter(self, **droits):
        u = Utilisateur.objects.create_user(username="op", password="motdepasse123",
                                            role=Utilisateur.OPERATEUR, **droits)
        client = APIClient()
        client.force_authenticate(u)
        return client

    def test_sans_la_case_mp_on_consulte_mais_on_ne_bouge_rien(self):
        client = self.connecter(droit_cab=True)
        self.assertEqual(client.get("/api/mp/stock/").status_code, 200)
        r = client.post("/api/mp/entrer/", {"emplacement": self.vitrages.id, "place": "G",
                                            "article": self.v470.id, "quantite": 1},
                        format="json")
        self.assertEqual(r.status_code, 403)

    def test_avec_la_case_mp(self):
        client = self.connecter(droit_mp=True)
        r = client.post("/api/mp/entrer/", {"emplacement": self.vitrages.id, "place": "G",
                                            "article": self.v470.id, "quantite": 1},
                        format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_la_case_mp_ne_donne_pas_les_cabines(self):
        u = Utilisateur.objects.create_user(username="mp", password="motdepasse123",
                                            droit_mp=True)
        self.assertEqual(u.droits_effectifs(), {"cab": False, "ref": False, "mp": True})


class CabinesEtMPNeSeMelangentPasTest(BaseMP):
    def setUp(self):
        super().setUp()
        self.cabine = Cabine.objects.create(numero="26_03_47", chantier="260204")

    def test_pas_de_cabine_sur_un_emplacement_mp(self):
        with self.assertRaisesMessage(services_cabines.ErreurCabine, "matières premières"):
            services_cabines.ranger(cabine=self.cabine, emplacement=self.vitrages, place="G")

    def test_un_emplacement_mp_n_est_jamais_propose_a_une_cabine(self):
        lignes = services_cabines.emplacements_pour(self.cabine)
        mp = [x for x in lignes if x["emplacement"].est_mp]
        self.assertTrue(mp)
        self.assertTrue(all(not x["possible"] for x in mp))
        self.assertIn("matières premières", mp[0]["pourquoi"])
        self.assertEqual(lignes[0]["emplacement"], self.cabines)

    def test_places_de_l_ecran_de_rangement(self):
        r = self.client.get(f"/api/emplacements/{self.vitrages.id}/places/")
        self.assertTrue(r.data["est_mp"])
        self.assertTrue(r.data["complet"])

    def test_suppression_refusee_tant_qu_il_y_a_du_stock(self):
        self.entrer()
        r = self.client.delete(f"/api/emplacements/{self.vitrages.id}/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("stock MP", str(r.data))
        self.assertTrue(Emplacement.objects.filter(pk=self.vitrages.pk).exists())

    def test_mise_hors_service_refusee_tant_qu_il_y_a_du_stock(self):
        self.entrer()
        with self.assertRaisesMessage(services_cabines.ErreurCabine, "VITR.470X2072.BP"):
            services_cabines.changer_activation(emplacement=self.vitrages, actif=False,
                                                motif="travaux")

    def test_condamner_le_milieu(self):
        """Trois places en MP : le milieu se condamne. Pas pour des cabines."""
        services_cabines.condamner_place(emplacement=self.vitrages, place="M", motif="pied")
        with self.assertRaisesMessage(services_cabines.ErreurCabine, "gauche ou droite"):
            services_cabines.condamner_place(emplacement=self.cabines, place="M", motif="x")

    def test_condamner_une_place_chargee_est_refuse(self):
        self.entrer(place="D")
        with self.assertRaisesMessage(services_cabines.ErreurCabine, "stock MP"):
            services_cabines.condamner_place(emplacement=self.vitrages, place="D", motif="x")

    def test_la_remise_a_zero_ne_touche_pas_au_stock_mp(self):
        self.entrer()
        services_cabines.vider_le_stock(dossier=self._dossier())
        self.assertEqual(StockMP.objects.count(), 1)
        self.assertEqual(services_cabines.etat_du_stock()["conserves"]["lignes_stock_mp"], 1)

    def _dossier(self):
        import tempfile
        return tempfile.mkdtemp()


class UsageDesEmplacementsTest(BaseMP):
    def ids(self, *emps):
        return [e.id for e in emps]

    def test_apercu_sans_rien_ecrire(self):
        bilan = services_mp.apercu_usage(self.ids(self.cabines), "vitrage")
        self.assertEqual(bilan["changes"], ["AC550"])
        self.cabines.refresh_from_db()
        self.assertEqual(self.cabines.usage, Emplacement.CABINES)

    def test_changer_ce_qui_est_libre_et_nommer_le_reste(self):
        cabine = Cabine.objects.create(numero="26_03_47", chantier="260204")
        services_cabines.ranger(cabine=cabine, emplacement=self.cabines, place="G")
        libre = Emplacement.objects.create(code="AC551", rack="AC")
        self.entrer()                                   # du stock sur AH500
        bilan = services_mp.changer_usage(
            self.ids(self.cabines, libre, self.vitrages, self.cartons), "carton",
            utilisateur=self.admin)
        self.assertEqual(bilan["changes"], ["AC551"])
        self.assertEqual(bilan["deja"], ["AH501"])
        self.assertEqual({b["code"] for b in bilan["bloques"]}, {"AC550", "AH500"})
        libre.refresh_from_db()
        self.assertEqual(libre.usage, Emplacement.MP_CARTON)
        self.vitrages.refresh_from_db()
        self.assertEqual(self.vitrages.usage, Emplacement.MP_VITRAGE)

    def test_revenir_aux_cabines_avec_le_mode(self):
        bilan = services_mp.changer_usage(self.ids(self.cartons), "cabines-illimite")
        self.assertEqual(bilan["changes"], ["AH501"])
        self.cartons.refresh_from_db()
        self.assertEqual((self.cartons.usage, self.cartons.mode_places),
                         (Emplacement.CABINES, Emplacement.ILLIMITE))

    def test_un_milieu_condamne_retient_le_retour_aux_cabines(self):
        PlaceCondamnee.objects.create(emplacement=self.cartons, place="M", motif="pied")
        bilan = services_mp.changer_usage(self.ids(self.cartons), "cabines-gd")
        self.assertEqual(bilan["changes"], [])
        self.assertIn("milieu", bilan["bloques"][0]["message"])

    def test_api_droit_referentiel(self):
        op = Utilisateur.objects.create_user(username="op", password="motdepasse123",
                                             droit_cab=True, droit_mp=True)
        client = APIClient()
        client.force_authenticate(op)
        r = client.post("/api/emplacements/usage/", {"ids": [self.cabines.id],
                                                      "choix": "vitrage"}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.client.post("/api/emplacements/usage/", {"ids": [self.cabines.id],
                                                           "choix": "vitrage"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["changes"], ["AC550"])

    def test_api_choix_inconnu(self):
        r = self.client.post("/api/emplacements/usage/", {"ids": [self.cabines.id],
                                                           "choix": "verre"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_la_fiche_refuse_comme_la_selection(self):
        self.entrer()
        r = self.client.patch(f"/api/emplacements/{self.vitrages.id}/",
                              {"usage": "cabines"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("stock MP", str(r.data))
        r = self.client.patch(f"/api/emplacements/{self.cabines.id}/",
                              {"usage": "carton"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["est_mp"])

    def test_la_liste_resume_le_stock_mp(self):
        self.entrer(quantite=19)
        self.entrer(place="D", article=ArticleMP.objects.get(code="VITR.927X2075.BP"),
                    quantite=3)
        r = self.client.get("/api/emplacements/", {"rack": "AH"})
        par_code = {e["code"]: e for e in r.data["results"]}
        self.assertEqual(par_code["AH500"]["mp"],
                         {"lignes": 2, "codes": 2, "quantite": 22, "places": ["G", "D"]})
        self.assertEqual(par_code["AH501"]["mp"]["lignes"], 0)
        r = self.client.get("/api/emplacements/", {"rack": "AC"})
        self.assertIsNone(r.data["results"][0]["mp"])


class ConsultationTest(BaseMP):
    def setUp(self):
        super().setUp()
        self.entrer(quantite=19)
        self.entrer(emplacement=self.cartons, article=self.c8fd, quantite=160, place="M")

    def test_le_stock_par_code(self):
        r = self.client.get("/api/mp/stock/")
        self.assertEqual([a["code"] for a in r.data],
                         ["VITR.470X2072.BP", "C8.FD.2115X1015X90"])
        self.assertEqual(r.data[1]["positions"][0]["position"], "AH501·M")

    def test_chercher_un_emplacement(self):
        r = self.client.get("/api/mp/stock/", {"q": "ah501"})
        self.assertEqual([a["code"] for a in r.data], ["C8.FD.2115X1015X90"])

    def test_toute_la_base(self):
        r = self.client.get("/api/mp/stock/", {"tous": 1, "famille": "vitrage"})
        self.assertEqual(len(r.data), 19)

    def test_sous_le_seuil(self):
        """Seuil 50 pour le 470 (ATV) : 19 en stock, il faut en recommander. Jamais
        une ancienne génération : on l'écoule."""
        r = self.client.get("/api/mp/stock/", {"sous_seuil": 1})
        codes = [a["code"] for a in r.data]
        self.assertIn("VITR.470X2072.BP", codes)
        self.assertNotIn("VITR.445X2072.BP", codes)

    def test_le_contenu_d_un_emplacement_par_son_code(self):
        r = self.client.get("/api/mp/emplacement/", {"code": "LOC:ah500"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["places"][0]["lignes"][0]["code"], "VITR.470X2072.BP")
        r = self.client.get("/api/mp/emplacement/", {"code": "AC550"})
        self.assertFalse(r.data["est_mp"])
        self.assertIn("range des cabines", r.data["refus"])

    def test_la_fiche_d_un_code(self):
        r = self.client.get("/api/mp/article/", {"id": self.v470.id})
        self.assertEqual(r.data["en_stock"], 19)
        self.assertEqual(r.data["mouvements"][0]["type"], "entree")

    def test_les_compteurs(self):
        r = self.client.get("/api/mp/filtres/")
        self.assertEqual(r.data["familles"]["vitrage"], {"codes": 1, "quantite": 19})
        self.assertEqual(r.data["familles"]["carton"], {"codes": 1, "quantite": 160})
        self.assertEqual(r.data["racks"], ["AH"])

    def test_le_journal(self):
        r = self.client.get("/api/mp/journal/", {"search": "c8"})
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["code"], "C8.FD.2115X1015X90")

    def test_l_export(self):
        r = self.client.get("/api/mp/export/")
        self.assertEqual(r.status_code, 200)
        texte = r.content.decode("utf-8-sig")
        self.assertIn("C8.FD.2115X1015X90", texte)
        self.assertIn("AH501;M;160", texte)
        self.assertTrue(r["Content-Disposition"].startswith('attachment; filename="stock-mp-'))

    def test_le_pouls_voit_les_mouvements_mp(self):
        avant = self.client.get("/api/pouls/").data
        services_mp.sortir(ligne=StockMP.objects.first(), quantite=1)
        apres = self.client.get("/api/pouls/").data
        self.assertGreater(apres["mouvements_mp"], avant["mouvements_mp"])


class CreationEtFiltresTest(BaseMP):
    def test_un_rack_se_cree_directement_pour_les_vitrages(self):
        r = self.client.post("/api/emplacements/generer/", {
            "prefixe": "AV", "debut": "100", "pas": 10, "colonnes": 2, "niveaux": 1,
            "usage": "vitrage"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(set(Emplacement.objects.filter(rack="AV")
                             .values_list("usage", flat=True)), {Emplacement.MP_VITRAGE})

    def test_un_usage_inconnu_est_refuse_a_la_creation_du_rack(self):
        r = self.client.post("/api/emplacements/generer/", {
            "prefixe": "AV", "debut": "100", "colonnes": 1, "usage": "verre"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Emplacement.objects.filter(rack="AV").exists())

    def test_un_emplacement_se_cree_pour_les_cartons(self):
        r = self.client.post("/api/emplacements/", {"code": "mur-1", "usage": "carton"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["usage_libelle"], "MP · cartons")

    def test_filtrer_les_emplacements_mp(self):
        r = self.client.get("/api/emplacements/", {"usage": "mp"})
        self.assertEqual({e["code"] for e in r.data["results"]}, {"AH500", "AH501"})
        r = self.client.get("/api/emplacements/", {"usage": "vitrage"})
        self.assertEqual([e["code"] for e in r.data["results"]], ["AH500"])

    def test_l_ordre_des_positions_est_celui_du_rack(self):
        """Gauche, milieu, droite — pas D, G, M comme l'alphabet."""
        for place in ("D", "G", "M"):
            self.entrer(place=place, quantite=1)
        r = self.client.get("/api/mp/stock/")
        self.assertEqual([p["place"] for p in r.data[0]["positions"]], ["G", "M", "D"])


class EcranEtServeurAlignesTest(APITestCase):
    """L'écran écrit les choix d'usage et les familles en dur ; le serveur les
    définit. Le jour où l'un bouge sans l'autre, chaque réglage serait refusé —
    c'est déjà arrivé aux modes de rangement (« gmd »)."""

    def setUp(self):
        from pathlib import Path
        self.app = (Path(__file__).resolve().parents[1] / "static" / "app" / "app.js").read_text("utf-8")

    def test_les_choix_d_usage(self):
        import re
        modes = re.findall(r"\['([a-z]+)',", re.search(r"const MODES_EMP = \[(.*?)\];", self.app).group(1))
        familles_mp = re.findall(r"\['(carton|vitrage)', 'MP — ", self.app)
        self.assertEqual([f"cabines-{m}" for m in modes] + familles_mp,
                         list(services_mp.CHOIX_USAGE))

    def test_les_familles(self):
        import re
        bloc = re.search(r"const FAMILLES_MP = \{(.*?)\n\};", self.app, re.S).group(1)
        self.assertEqual(sorted(re.findall(r"^\s+(\w+): \{", bloc, re.M)),
                         sorted(code for code, _ in ArticleMP.FAMILLES))


class AdministrationDeLaBaseTest(APITestCase):
    def test_un_doublon_en_minuscules_est_refuse_proprement(self):
        """L'administration dit « existe déjà » au lieu d'une erreur 500."""
        from django.contrib.admin.sites import site
        from django.test import RequestFactory

        admin_vue = site._registry[ArticleMP]
        Formulaire = admin_vue.get_form(RequestFactory().get("/"))
        f = Formulaire(data={"code": "vitr.445x2072.bp", "famille": "vitrage",
                             "designation": "", "fournisseur": "", "numero": "",
                             "references": "", "actif": "on"})
        self.assertFalse(f.is_valid())
        self.assertIn("code", f.errors)

    def test_le_code_lu_sur_l_etiquette_en_minuscules(self):
        u = Utilisateur.objects.create_user(username="v", password="motdepasse123",
                                            role=Utilisateur.ADMIN)
        self.client.force_authenticate(u)
        Emplacement.objects.create(code="AH900", usage=Emplacement.MP_CARTON)
        r = self.client.get("/api/mp/emplacement/", {"code": "loc:ah900"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["est_mp"])


class GardeFousDeLAdministrationTest(BaseMP):
    """L'administration ne passe ni par l'écran ni par l'API : les règles doivent
    tenir là aussi."""

    def test_l_usage_d_un_emplacement_charge_ne_change_pas(self):
        from django.core.exceptions import ValidationError
        self.entrer()
        self.vitrages.usage = Emplacement.CABINES
        with self.assertRaises(ValidationError) as refus:
            self.vitrages.full_clean()
        self.assertIn("stock MP", str(refus.exception))

    def test_l_usage_d_un_emplacement_vide_change(self):
        self.cartons.usage = Emplacement.MP_VITRAGE
        self.cartons.full_clean()           # ne lève pas

    def test_pas_de_cabine_sur_un_emplacement_mp_par_l_administration(self):
        from django.core.exceptions import ValidationError

        from wms.models import Occupation
        cabine = Cabine.objects.create(numero="26_03_49", chantier="260204")
        occupation = Occupation(cabine=cabine, numero=2, emplacement=self.vitrages, place="G")
        with self.assertRaises(ValidationError) as refus:
            occupation.full_clean()
        self.assertIn("matières premières", str(refus.exception))

    def test_un_identifiant_exotique_ne_fait_pas_d_erreur_serveur(self):
        """« ² » passe `isdigit()` et casse `int()` : un 400, pas un 500."""
        for url, params in [("/api/mp/emplacement/", {"id": "²"}),
                            ("/api/mp/article/", {"id": "²"}),
                            ("/api/mp/journal/", {"article": "²"})]:
            with self.subTest(url=url):
                self.assertIn(self.client.get(url, params).status_code, (200, 400))
        r = self.client.post("/api/mp/sortir/", {"ligne": "²"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/mp/entrer/", {"emplacement": self.vitrages.id, "place": "G",
                                                 "article": self.v470.id, "quantite": "1²"},
                             format="json")
        self.assertEqual(r.status_code, 400)


class LeParcDesCabinesNeProposePasLesRacksMPTest(BaseMP):
    def test_un_rack_tout_mp_n_est_pas_dans_les_filtres_des_cabines(self):
        Emplacement.objects.create(code="AV100", rack="AV", usage=Emplacement.MP_VITRAGE)
        racks = self.client.get("/api/cabines/filtres/").data["racks"]
        self.assertIn("AC", racks)
        self.assertNotIn("AV", racks)
