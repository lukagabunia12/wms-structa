"""Tests de l'API REST : authentification, recherche, opérations de stock, tableau de bord."""
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase

from wms import services
from wms.models import (Article, Categorie, Emplacement, Mouvement, Reception,
                        Stock, Utilisateur)


class BaseAPITest(APITestCase):
    def setUp(self):
        self.user = Utilisateur.objects.create_user(username="op", password="secret123", role=Utilisateur.ADMIN)
        self.client.force_authenticate(user=self.user)
        self.cat = Categorie.objects.create(nom="Visserie")
        self.a = Article.objects.create(ref="V0001", designation="Vis M6", categorie=self.cat, stock_min=5)
        self.e1 = Emplacement.objects.create(code="A001")
        self.e2 = Emplacement.objects.create(code="B001")
        self.staging = Emplacement.objects.create(code="À RANGER", staging=True)

    def dispo(self, emp, art=None):
        return services.stock_disponible(art or self.a, emp)


class AuthentificationTest(APITestCase):
    def setUp(self):
        Utilisateur.objects.create_user(username="op", password="secret123")

    def test_acces_refuse_sans_authentification(self):
        r = self.client.get("/api/articles/")
        self.assertIn(r.status_code, (401, 403))

    def test_obtention_du_jeton(self):
        r = self.client.post("/api/token/", {"username": "op", "password": "secret123"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("token", r.data)

    def test_jeton_refuse_si_mauvais_mot_de_passe(self):
        r = self.client.post("/api/token/", {"username": "op", "password": "faux"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_acces_autorise_avec_jeton(self):
        t = self.client.post("/api/token/", {"username": "op", "password": "secret123"}, format="json").data["token"]
        self.client.credentials(HTTP_AUTHORIZATION="Token " + t)
        self.assertEqual(self.client.get("/api/articles/").status_code, 200)


class RechercheArticleTest(BaseAPITest):
    def test_recherche_par_reference(self):
        r = self.client.get("/api/articles/?search=V0001")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 1)

    def test_recherche_par_designation_partielle(self):
        r = self.client.get("/api/articles/?search=vis")
        self.assertEqual(r.data["count"], 1)

    def test_recherche_sans_resultat(self):
        r = self.client.get("/api/articles/?search=zzzz")
        self.assertEqual(r.data["count"], 0)

    def test_creation_article_genere_la_reference(self):
        r = self.client.post("/api/articles/", {"designation": "Écrou M6", "categorie": self.cat.id}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["ref"])
        self.assertTrue(r.data["ref"].startswith("V"))


class FiltresStockTest(BaseAPITest):
    def setUp(self):
        super().setUp()
        services.entree(article=self.a, emplacement=self.e1, qte=10)
        services.entree(article=self.a, emplacement=self.e2, qte=4)

    def test_filtre_par_article(self):
        r = self.client.get(f"/api/stock/?article={self.a.id}")
        self.assertEqual(r.data["count"], 2)

    def test_filtre_par_emplacement(self):
        r = self.client.get(f"/api/stock/?emplacement={self.e1.id}")
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(Decimal(str(r.data["results"][0]["qte"])), Decimal("10"))

    def test_codes_lisibles_exposes(self):
        r = self.client.get(f"/api/stock/?emplacement={self.e1.id}")
        ligne = r.data["results"][0]
        self.assertEqual(ligne["article_ref"], "V0001")
        self.assertEqual(ligne["emplacement_code"], "A001")


class OperationsAPITest(BaseAPITest):
    def test_entree(self):
        r = self.client.post("/api/operations/entree/",
                             {"article": self.a.id, "emplacement": self.e1.id, "qte": "7"},
                             format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.dispo(self.e1), Decimal("7"))

    def test_sortie(self):
        services.entree(article=self.a, emplacement=self.e1, qte=10)
        r = self.client.post("/api/operations/sortie/",
                             {"article": self.a.id, "emplacement": self.e1.id, "qte": "3"},
                             format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.dispo(self.e1), Decimal("7"))

    def test_sortie_insuffisante_renvoie_400_et_message(self):
        services.entree(article=self.a, emplacement=self.e1, qte=2)
        r = self.client.post("/api/operations/sortie/",
                             {"article": self.a.id, "emplacement": self.e1.id, "qte": "5"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("erreur", r.data)
        self.assertEqual(self.dispo(self.e1), Decimal("2"))

    def test_ajustement_remet_a_niveau(self):
        services.entree(article=self.a, emplacement=self.e1, qte=10)
        r = self.client.post("/api/operations/ajustement/",
                             {"article": self.a.id, "emplacement": self.e1.id, "qte": "6"},
                             format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.dispo(self.e1), Decimal("6"))

    def test_transfert_deplace_le_stock(self):
        services.entree(article=self.a, emplacement=self.e1, qte=10)
        r = self.client.post("/api/operations/transfert/",
                             {"article": self.a.id, "source": self.e1.id,
                              "destination": self.e2.id, "qte": "4"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertIn("sortie", r.data)
        self.assertIn("entree", r.data)
        self.assertEqual(self.dispo(self.e1), Decimal("6"))
        self.assertEqual(self.dispo(self.e2), Decimal("4"))

    def test_transfert_meme_emplacement_refuse(self):
        services.entree(article=self.a, emplacement=self.e1, qte=5)
        r = self.client.post("/api/operations/transfert/",
                             {"article": self.a.id, "source": self.e1.id,
                              "destination": self.e1.id, "qte": "1"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_reception_cree_mouvement_et_reception(self):
        r = self.client.post("/api/operations/reception/",
                             {"article": self.a.id, "emplacement": self.e1.id,
                              "qte": "12", "commande": "CMD9"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertIn("reception", r.data)
        # Le format est entièrement spécifié (R<AAMMJJ>-<séq sur 4>) : on l'assert en entier
        # plutôt qu'un simple startswith("R").
        attendu = "R" + timezone.localdate().strftime("%y%m%d") + "-0001"
        self.assertEqual(r.data["reception"]["numero"], attendu)
        self.assertEqual(Reception.objects.count(), 1)
        self.assertEqual(self.dispo(self.e1), Decimal("12"))

    def test_reception_en_zone_a_ranger(self):
        r = self.client.post("/api/operations/reception/",
                             {"article": self.a.id, "emplacement": self.staging.id, "qte": "5"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(Reception.objects.first().staging)
        self.assertEqual(self.dispo(self.staging), Decimal("5"))

    def test_drapeau_staging_deduit_de_l_emplacement(self):
        """Le client ne décide plus : une réception dans un emplacement normal ne peut
        plus être marquée « à ranger » (la chaîne "false" valait d'ailleurs True)."""
        r = self.client.post("/api/operations/reception/",
                             {"article": self.a.id, "emplacement": self.e1.id, "qte": "5",
                              "staging": True}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertFalse(Reception.objects.first().staging)

    def test_note_trop_longue_refusee(self):
        """Les CharField ne sont pas contrôlés par SQLite : 5000 caractères entraient
        dans un champ de 255."""
        r = self.client.post("/api/operations/entree/",
                             {"article": self.a.id, "emplacement": self.e1.id, "qte": "1",
                              "note": "x" * 5000}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Mouvement.objects.count(), 0)

    def test_rangement_depuis_zone_a_ranger(self):
        services.entree(article=self.a, emplacement=self.staging, qte=5)
        r = self.client.post("/api/operations/transfert/",
                             {"article": self.a.id, "source": self.staging.id,
                              "destination": self.e1.id, "qte": "5"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.dispo(self.staging), Decimal("0"))
        self.assertEqual(self.dispo(self.e1), Decimal("5"))

    def test_contre_passation(self):
        mv = services.entree(article=self.a, emplacement=self.e1, qte=8)
        r = self.client.post("/api/operations/contre-passer/", {"mouvement": mv.pk}, format="json")
        self.assertEqual(r.status_code, 201)
        mv.refresh_from_db()
        self.assertTrue(mv.annule)
        self.assertEqual(self.dispo(self.e1), Decimal("0"))

    def test_contre_passation_refusee_sur_ajustement(self):
        mv = services.ajustement(article=self.a, emplacement=self.e1, qte=5)
        r = self.client.post("/api/operations/contre-passer/", {"mouvement": mv.pk}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_mouvement_enregistre_l_utilisateur(self):
        self.client.post("/api/operations/entree/",
                         {"article": self.a.id, "emplacement": self.e1.id, "qte": "1"},
                         format="json")
        self.assertEqual(Mouvement.objects.first().utilisateur, self.user)

    def test_cache_stock_coherent_avec_le_journal_apres_operations_api(self):
        self.client.post("/api/operations/entree/",
                         {"article": self.a.id, "emplacement": self.e1.id, "qte": "10"},
                         format="json")
        self.client.post("/api/operations/sortie/",
                         {"article": self.a.id, "emplacement": self.e1.id, "qte": "3"},
                         format="json")
        self.client.post("/api/operations/transfert/",
                         {"article": self.a.id, "source": self.e1.id,
                          "destination": self.e2.id, "qte": "2"}, format="json")
        avant = {(s.article_id, s.emplacement_id): s.qte for s in Stock.objects.all()}
        services.recalculer_stock()
        apres = {(s.article_id, s.emplacement_id): s.qte for s in Stock.objects.all()}
        self.assertEqual(avant, apres)


class TableauDeBordTest(BaseAPITest):
    def test_indicateurs(self):
        services.entree(article=self.a, emplacement=self.e1, qte=2)
        services.entree(article=self.a, emplacement=self.staging, qte=3)
        r = self.client.get("/api/tableau-de-bord/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["references"], 1)
        self.assertEqual(float(r.data["a_ranger"]), 3.0)
        self.assertGreaterEqual(len(r.data["derniers_mouvements"]), 1)

    def test_alerte_stock_bas_se_declenche(self):
        """Prouve qu'une alerte APPARAÎT : les autres tests n'attendaient qu'une liste vide."""
        services.entree(article=self.a, emplacement=self.e1, qte=2)  # seuil = 5
        r = self.client.get("/api/tableau-de-bord/")
        self.assertEqual([b["ref"] for b in r.data["stock_bas"]], ["V0001"])
        alerte = r.data["stock_bas"][0]
        self.assertEqual(alerte["designation"], "Vis M6")
        self.assertEqual(alerte["stock"], 2.0)
        self.assertEqual(alerte["min"], 5.0)

    def test_stock_en_zone_a_ranger_compte_dans_le_total_d_alerte(self):
        """La marchandise « à ranger » est physiquement présente : elle éteint l'alerte.

        Comportement de référence de la maquette : `totalStock` (archive/index.html)
        sommait toutes les lignes de stock de l'article, la zone `__ARANGER__` comprise,
        et `lowStockArticles` comparait ce total au seuil. C'est ce point que l'ancien
        `test_indicateurs_et_alertes` ignorait : il posait 2 + 3 = 5 pour un seuil de 5
        et attendait malgré tout une alerte.
        """
        services.entree(article=self.a, emplacement=self.e1, qte=2)
        r = self.client.get("/api/tableau-de-bord/")
        self.assertEqual([b["ref"] for b in r.data["stock_bas"]], ["V0001"])

        services.entree(article=self.a, emplacement=self.staging, qte=3)  # total 5 = seuil
        r = self.client.get("/api/tableau-de-bord/")
        self.assertEqual(r.data["stock_bas"], [])

    def test_a_ranger_additionne_toutes_les_zones_de_staging(self):
        autre = Emplacement.objects.create(code="À RANGER 2", staging=True)
        services.entree(article=self.a, emplacement=self.staging, qte=3)
        services.entree(article=self.a, emplacement=autre, qte=4)
        r = self.client.get("/api/tableau-de-bord/")
        self.assertEqual(float(r.data["a_ranger"]), 7.0)

    def test_article_dormant_exclu_des_alertes(self):
        self.a.statut = Article.DORMANT
        self.a.save(update_fields=["statut"])
        services.entree(article=self.a, emplacement=self.e1, qte=1)
        r = self.client.get("/api/tableau-de-bord/")
        self.assertEqual([b["ref"] for b in r.data["stock_bas"]], [])

    def test_article_au_dessus_du_seuil_absent_des_alertes(self):
        services.entree(article=self.a, emplacement=self.e1, qte=50)
        r = self.client.get("/api/tableau-de-bord/")
        self.assertEqual([b["ref"] for b in r.data["stock_bas"]], [])


class TotalStockParArticleTest(BaseAPITest):
    """L'écran « Stock » lit le total agrégé par l'API, sans additionner côté client."""

    def test_total_et_nombre_d_emplacements(self):
        services.entree(article=self.a, emplacement=self.e1, qte=10)
        services.entree(article=self.a, emplacement=self.e2, qte=4)
        r = self.client.get(f"/api/articles/?search={self.a.ref}")
        ligne = r.data["results"][0]
        self.assertEqual(ligne["total_stock"], 14.0)
        self.assertEqual(ligne["nb_emplacements"], 2)

    def test_article_sans_stock(self):
        r = self.client.get(f"/api/articles/?search={self.a.ref}")
        ligne = r.data["results"][0]
        self.assertEqual(ligne["total_stock"], 0.0)
        self.assertEqual(ligne["nb_emplacements"], 0)

    def test_ligne_a_zero_non_comptee_comme_emplacement(self):
        services.entree(article=self.a, emplacement=self.e1, qte=5)
        services.sortie(article=self.a, emplacement=self.e1, qte=5)
        ligne = self.client.get(f"/api/articles/?search={self.a.ref}").data["results"][0]
        self.assertEqual(ligne["total_stock"], 0.0)
        self.assertEqual(ligne["nb_emplacements"], 0)

    def test_total_inclut_la_zone_a_ranger(self):
        services.entree(article=self.a, emplacement=self.staging, qte=7)
        ligne = self.client.get(f"/api/articles/?search={self.a.ref}").data["results"][0]
        self.assertEqual(ligne["total_stock"], 7.0)

    def test_creation_expose_un_total_nul(self):
        """Après un POST les annotations n'existent pas : le champ ne doit pas casser."""
        r = self.client.post("/api/articles/", {"designation": "Nouveau", "unite": "U"},
                             format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["total_stock"], 0.0)
        self.assertEqual(r.data["nb_emplacements"], 0)

    def test_emplacements_d_un_article(self):
        """Le détail d'un article : toutes ses lignes de stock."""
        services.entree(article=self.a, emplacement=self.e1, qte=10)
        services.entree(article=self.a, emplacement=self.e2, qte=4)
        r = self.client.get(f"/api/stock/?article={self.a.id}")
        self.assertEqual(r.data["count"], 2)
        codes = sorted(x["emplacement_code"] for x in r.data["results"])
        self.assertEqual(codes, ["A001", "B001"])


class MoiTest(BaseAPITest):
    """L'interface a besoin des droits du compte pour ne pas proposer l'interdit."""

    def test_identite_et_droits(self):
        r = self.client.get("/api/moi/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["username"], "op")
        self.assertEqual(r.data["role"], Utilisateur.ADMIN)
        self.assertTrue(all(r.data["droits"].values()))

    def test_droits_d_un_lecteur(self):
        lecteur = Utilisateur.objects.create_user(username="lect", password="secret123",
                                                  role=Utilisateur.LECTURE, droit_mvt=True)
        self.client.force_authenticate(user=lecteur)
        r = self.client.get("/api/moi/")
        self.assertFalse(any(r.data["droits"].values()))

    def test_pin_non_expose(self):
        self.user.pin = "1234"
        self.user.save(update_fields=["pin"])
        r = self.client.get("/api/moi/")
        self.assertNotIn("pin", r.data)
        self.assertNotIn("password", r.data)

    def test_authentification_requise(self):
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get("/api/moi/").status_code, (401, 403))


class QuantitesInvalidesTest(BaseAPITest):
    """Une saisie invalide doit donner un 400 métier, jamais une erreur 500."""

    def _entree(self, qte):
        return self.client.post(
            "/api/operations/entree/",
            {"article": self.a.id, "emplacement": self.e1.id, "qte": qte}, format="json")

    def test_quantite_non_numerique_refusee(self):
        for qte in (None, "", "abc", "1,5", "1e3", [], {}):
            with self.subTest(qte=qte):
                r = self._entree(qte)
                self.assertEqual(r.status_code, 400)
                self.assertIn("erreur", r.data)
        self.assertEqual(Mouvement.objects.count(), 0)

    def test_champ_qte_absent_refuse(self):
        r = self.client.post("/api/operations/entree/",
                             {"article": self.a.id, "emplacement": self.e1.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_quantite_hors_gabarit_refusee_sans_ecriture(self):
        """`max_digits` n'est imposé ni par SQLite ni par Django au save().

        Une quantité démesurée était donc écrite en base ; ensuite, toute relecture ORM
        de la colonne levait InvalidOperation et /api/stock/, /api/mouvements/ et le
        tableau de bord tombaient définitivement en 500, sans correction possible.
        """
        for qte in ("1e40", "12345678901234567"):
            with self.subTest(qte=qte):
                self.assertEqual(self._entree(qte).status_code, 400)
        self.assertEqual(Stock.objects.count(), 0)
        self.assertEqual(Mouvement.objects.count(), 0)
        self.assertEqual(self.client.get("/api/stock/").status_code, 200)
        self.assertEqual(self.client.get("/api/mouvements/").status_code, 200)
        self.assertEqual(self.client.get("/api/tableau-de-bord/").status_code, 200)

    def test_quantite_sous_la_precision_refusee(self):
        """0.0004 était accepté puis stocké « 0.000 » : mouvement fantôme, stock inchangé."""
        self.assertEqual(self._entree("0.0004").status_code, 400)
        self.assertEqual(Mouvement.objects.count(), 0)

    def test_quantite_decimale_valide_acceptee(self):
        self.assertEqual(self._entree("2.5").status_code, 201)
        self.assertEqual(self.dispo(self.e1), Decimal("2.5"))

    def test_toutes_les_operations_refusent_une_quantite_invalide(self):
        cas = [
            ("entree", {"article": self.a.id, "emplacement": self.e1.id}),
            ("sortie", {"article": self.a.id, "emplacement": self.e1.id}),
            ("ajustement", {"article": self.a.id, "emplacement": self.e1.id}),
            ("reception", {"article": self.a.id, "emplacement": self.e1.id}),
            ("transfert", {"article": self.a.id, "source": self.e1.id, "destination": self.e2.id}),
        ]
        for op, corps in cas:
            with self.subTest(operation=op):
                r = self.client.post(f"/api/operations/{op}/", {**corps, "qte": "abc"}, format="json")
                self.assertEqual(r.status_code, 400)


class ReferencesInvalidesTest(BaseAPITest):
    """Identifiants et filtres mal formés : 400 explicite, pas de 500."""

    def test_identifiant_non_numerique_refuse(self):
        r = self.client.post("/api/operations/entree/",
                             {"article": "abc", "emplacement": self.e1.id, "qte": "1"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("erreur", r.data)

    def test_champ_article_absent_refuse(self):
        r = self.client.post("/api/operations/entree/",
                             {"emplacement": self.e1.id, "qte": "1"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("obligatoire", " ".join(r.data["erreur"]))

    def test_emplacement_inexistant_refuse(self):
        r = self.client.post("/api/operations/entree/",
                             {"article": self.a.id, "emplacement": 999999, "qte": "1"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_transfert_sans_source_refuse(self):
        r = self.client.post("/api/operations/transfert/",
                             {"article": self.a.id, "destination": self.e2.id, "qte": "1"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_filtre_non_numerique_refuse(self):
        self.assertEqual(self.client.get("/api/stock/?article=abc").status_code, 400)
        self.assertEqual(self.client.get("/api/mouvements/?article=abc").status_code, 400)

    def test_filtre_vide_ignore(self):
        self.assertEqual(self.client.get("/api/stock/?emplacement=").status_code, 200)

    def test_contre_passation_mouvement_orphelin_refusee(self):
        """L'article supprimé, le mouvement subsiste (SET_NULL) mais n'est plus
        contre-passable : la reconstitution de la ligne de stock échouerait."""
        mv = services.entree(article=self.a, emplacement=self.e1, qte=5)
        self.a.delete()
        mv.refresh_from_db()
        r = self.client.post("/api/operations/contre-passer/", {"mouvement": mv.pk}, format="json")
        self.assertEqual(r.status_code, 400)


class UniciteCasseTest(BaseAPITest):
    """Invariant n°5 : `ref` et `code` normalisés en MAJUSCULES *et* uniques."""

    def test_reference_en_minuscules_detectee_comme_doublon(self):
        r = self.client.post("/api/articles/", {"ref": "v0001", "designation": "doublon"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Article.objects.filter(designation="doublon").count(), 0)

    def test_code_emplacement_en_minuscules_detecte_comme_doublon(self):
        self.assertEqual(self.client.post("/api/emplacements/", {"code": "a001"},
                                          format="json").status_code, 400)

    def test_reference_creee_est_normalisee(self):
        r = self.client.post("/api/articles/", {"ref": "z0009", "designation": "Neuf"},
                             format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["ref"], "Z0009")

    def test_ean_en_doublon_refuse_proprement(self):
        self.a.ean = "12345"
        self.a.save(update_fields=["ean"])
        r = self.client.post("/api/articles/",
                             {"ref": "N1", "designation": "x", "ean": "12345"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_ean_normalise_avant_controle_d_unicite(self):
        self.a.ean = "12345"
        self.a.save(update_fields=["ean"])
        r = self.client.post("/api/articles/",
                             {"ref": "N1", "designation": "x", "ean": " 12345 "}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_ean_vide_autorise_en_plusieurs_exemplaires(self):
        for ref in ("N1", "N2"):
            r = self.client.post("/api/articles/",
                                 {"ref": ref, "designation": "x", "ean": ""}, format="json")
            self.assertEqual(r.status_code, 201)


class SuppressionEmplacementTest(BaseAPITest):
    def test_refus_si_stock_present(self):
        services.entree(article=self.a, emplacement=self.e1, qte=3)
        r = self.client.delete(f"/api/emplacements/{self.e1.id}/")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Emplacement.objects.filter(pk=self.e1.id).exists())

    def test_emplacement_vide_supprimable_apres_sortie_totale(self):
        """Une ligne de stock à 0 subsiste après une sortie totale ; avec PROTECT, elle
        rendait l'emplacement définitivement non supprimable (erreur 500).

        Depuis l'ajout de la suppression dans l'interface, un emplacement déjà cité
        dans l'historique demande une confirmation explicite (`force=1`) : ce qui
        est contrôlé ici, c'est que le RÉSIDU de stock à zéro ne bloque plus, et que
        le refus porte bien sur la traçabilité — pas sur un stock fantôme.
        """
        services.entree(article=self.a, emplacement=self.e1, qte=3)
        services.sortie(article=self.a, emplacement=self.e1, qte=3)
        refus = self.client.delete(f"/api/emplacements/{self.e1.id}/")
        self.assertEqual(refus.status_code, 400)
        self.assertIn("historique", " ".join(refus.data["erreur"]).lower())
        self.assertEqual(
            self.client.delete(f"/api/emplacements/{self.e1.id}/?force=1").status_code, 204)
        self.assertFalse(Emplacement.objects.filter(pk=self.e1.id).exists())
        self.assertFalse(Stock.objects.filter(emplacement_id=self.e1.id).exists())

    def test_historique_conserve_apres_suppression(self):
        """Invariant n°4 : les FK historiques sont en SET_NULL, jamais CASCADE."""
        services.entree(article=self.a, emplacement=self.e1, qte=3)
        services.sortie(article=self.a, emplacement=self.e1, qte=3)
        self.client.delete(f"/api/emplacements/{self.e1.id}/?force=1")
        self.assertEqual(Mouvement.objects.count(), 2)
        self.assertTrue(all(m.emplacement is None for m in Mouvement.objects.all()))

    def test_suppression_article_conserve_les_mouvements(self):
        services.entree(article=self.a, emplacement=self.e1, qte=3)
        self.assertEqual(self.client.delete(f"/api/articles/{self.a.id}/").status_code, 204)
        self.assertEqual(Mouvement.objects.count(), 1)
        self.assertIsNone(Mouvement.objects.first().article)


class DroitsTest(APITestCase):
    """Les 7 droits fins étaient déclarés dans le modèle et appliqués par aucune vue."""

    def setUp(self):
        self.cat = Categorie.objects.create(nom="Visserie")
        self.a = Article.objects.create(ref="V0001", designation="Vis M6")
        self.e1 = Emplacement.objects.create(code="A001")

    def _connecter(self, username, **kw):
        u = Utilisateur.objects.create_user(username=username, password="secret123", **kw)
        self.client.force_authenticate(user=u)
        return u

    def _entree(self):
        return self.client.post(
            "/api/operations/entree/",
            {"article": self.a.id, "emplacement": self.e1.id, "qte": "1"}, format="json")

    def test_acces_refuse_sans_authentification(self):
        self.assertIn(self._entree().status_code, (401, 403))

    def test_lecture_seule_ne_peut_rien_ecrire(self):
        self._connecter("lecteur", role=Utilisateur.LECTURE)
        self.assertEqual(self._entree().status_code, 403)
        self.assertEqual(self.client.post("/api/articles/", {"ref": "Z1", "designation": "x"},
                                          format="json").status_code, 403)
        self.assertEqual(self.client.delete(f"/api/articles/{self.a.id}/").status_code, 403)
        self.assertEqual(Mouvement.objects.count(), 0)
        self.assertTrue(Article.objects.filter(pk=self.a.id).exists())

    def test_lecture_seule_peut_consulter(self):
        self._connecter("lecteur", role=Utilisateur.LECTURE)
        self.assertEqual(self.client.get("/api/articles/").status_code, 200)
        self.assertEqual(self.client.get("/api/tableau-de-bord/").status_code, 200)

    def test_lecture_seule_ignore_les_cases_cochees(self):
        self._connecter("lecteur", role=Utilisateur.LECTURE, droit_mvt=True, droit_ref=True)
        self.assertEqual(self._entree().status_code, 403)

    def test_operateur_sans_droit_mvt_refuse(self):
        self._connecter("op", role=Utilisateur.OPERATEUR)
        self.assertEqual(self._entree().status_code, 403)

    def test_operateur_avec_droit_mvt_autorise(self):
        self._connecter("op", role=Utilisateur.OPERATEUR, droit_mvt=True)
        self.assertEqual(self._entree().status_code, 201)

    def test_droit_mvt_ne_donne_pas_l_inventaire(self):
        self._connecter("op", role=Utilisateur.OPERATEUR, droit_mvt=True)
        r = self.client.post("/api/operations/ajustement/",
                             {"article": self.a.id, "emplacement": self.e1.id, "qte": "5"},
                             format="json")
        self.assertEqual(r.status_code, 403)

    def test_contre_passation_exige_le_droit_de_correction(self):
        self._connecter("op", role=Utilisateur.OPERATEUR, droit_mvt=True)
        self.assertEqual(self._entree().status_code, 201)
        mv = Mouvement.objects.first()
        r = self.client.post("/api/operations/contre-passer/", {"mouvement": mv.pk}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_referentiel_exige_le_droit_ref(self):
        self._connecter("op", role=Utilisateur.OPERATEUR, droit_mvt=True)
        r = self.client.post("/api/articles/", {"ref": "Z1", "designation": "x"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_cabines_exigent_le_droit_cab(self):
        self._connecter("op", role=Utilisateur.OPERATEUR, droit_mvt=True)
        r = self.client.post("/api/cabines/",
                             {"numero": "11_22_33", "chantier": "000111",
                              "emplacement": self.e1.id}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_role_admin_a_tous_les_droits(self):
        self._connecter("chef", role=Utilisateur.ADMIN)
        self.assertEqual(self._entree().status_code, 201)

    def test_superuser_a_tous_les_droits(self):
        """`createsuperuser` laisse role=operateur : sans `is_superuser` dans
        droits_effectifs(), le seul compte d'administration réel serait verrouillé."""
        u = Utilisateur.objects.create_superuser(username="boss", password="secret123", email="")
        self.assertEqual(u.role, Utilisateur.OPERATEUR)
        self.client.force_authenticate(user=u)
        self.assertEqual(self._entree().status_code, 201)
