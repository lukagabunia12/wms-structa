"""Gestion du référentiel des emplacements : création, modification, suppression.

Ces règles n'existaient nulle part avant : l'interface ne proposait pas de
supprimer, et l'API ne contrôlait que le stock. Or `Cabine.emplacement` et
`Zone` sont en SET_NULL — une suppression « réussie » pouvait détacher tout un
rack de cabines sans le moindre message.
"""
from rest_framework.test import APITestCase

from wms import services
from wms.models import (Article, Cabine, Emplacement, Mouvement, Stock,
                        Utilisateur, Zone)


class BaseEmplacement(APITestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create_user(
            username="chef", password="motdepasse123", role=Utilisateur.ADMIN)
        self.client.force_authenticate(user=self.admin)
        self.emp = Emplacement.objects.create(code="C001")


class SuppressionEmplacementTest(BaseEmplacement):
    def test_emplacement_neuf_se_supprime(self):
        r = self.client.delete(f"/api/emplacements/{self.emp.id}/")
        self.assertEqual(r.status_code, 204, getattr(r, "data", None))
        self.assertFalse(Emplacement.objects.filter(pk=self.emp.pk).exists())

    def test_refus_si_des_cabines_y_sont_rangees(self):
        """Le cas le plus dangereux : SET_NULL les aurait détachées en silence."""
        cabine = Cabine.objects.create(numero="26_01_01", chantier="000123")
        services_ranger(cabine, self.emp)
        r = self.client.delete(f"/api/emplacements/{self.emp.id}/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cabine", " ".join(r.data["erreur"]).lower())
        cabine.refresh_from_db()
        self.assertEqual(cabine.emplacement_id, self.emp.pk)

    def test_refus_si_du_stock_est_present(self):
        article = Article.objects.create(ref="A1", designation="Vis")
        services.entree(article=article, emplacement=self.emp, qte=5)
        r = self.client.delete(f"/api/emplacements/{self.emp.id}/")
        self.assertEqual(r.status_code, 400)
        message = " ".join(r.data["erreur"]).lower()
        self.assertIn("stock", message)
        self.assertIn("a1 (5)", message)   # ce qui bloque est nommé, pas seulement compté

    def test_ligne_de_stock_a_zero_ne_bloque_pas(self):
        """Un emplacement vidé restait indélébile à cause du PROTECT sur Stock."""
        article = Article.objects.create(ref="A2", designation="Écrou")
        Stock.objects.create(article=article, emplacement=self.emp, qte=0)
        r = self.client.delete(f"/api/emplacements/{self.emp.id}/")
        self.assertEqual(r.status_code, 204, getattr(r, "data", None))
        self.assertFalse(Stock.objects.filter(emplacement_id=self.emp.pk).exists())

    def test_historique_bloque_mais_reste_forcable(self):
        article = Article.objects.create(ref="A3", designation="Boulon")
        services.entree(article=article, emplacement=self.emp, qte=2)
        services.sortie(article=article, emplacement=self.emp, qte=2)

        refus = self.client.delete(f"/api/emplacements/{self.emp.id}/")
        self.assertEqual(refus.status_code, 400)
        self.assertIn("historique", " ".join(refus.data["erreur"]).lower())

        force = self.client.delete(f"/api/emplacements/{self.emp.id}/?force=1")
        self.assertEqual(force.status_code, 204, getattr(force, "data", None))
        # L'historique survit : seule la référence à l'emplacement est perdue.
        self.assertEqual(Mouvement.objects.count(), 2)
        self.assertIsNone(Mouvement.objects.first().emplacement_id)

    def test_force_ne_leve_pas_le_blocage_des_cabines(self):
        """`force` couvre la perte de traçabilité, jamais la perte de marchandise."""
        cabine = Cabine.objects.create(numero="26_01_02", chantier="000124")
        services_ranger(cabine, self.emp)
        r = self.client.delete(f"/api/emplacements/{self.emp.id}/?force=1")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Emplacement.objects.filter(pk=self.emp.pk).exists())

    def test_lecture_seule_ne_peut_pas_supprimer(self):
        lecteur = Utilisateur.objects.create_user(
            username="obs", password="motdepasse123", role=Utilisateur.LECTURE)
        self.client.force_authenticate(user=lecteur)
        r = self.client.delete(f"/api/emplacements/{self.emp.id}/")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Emplacement.objects.filter(pk=self.emp.pk).exists())


class SuppressionAvecStockTest(BaseEmplacement):
    """Vider un emplacement demande les écrans Sortie / Transfert, qui appartiennent
    au volet articles archivé : sans cette porte réservée aux administrateurs, un
    emplacement portant du stock est définitivement indélébile depuis l'interface."""

    def setUp(self):
        super().setUp()
        self.article = Article.objects.create(ref="V0001", designation="Vis M6")
        services.entree(article=self.article, emplacement=self.emp, qte=12,
                        utilisateur=self.admin)

    def _operateur(self):
        operateur = Utilisateur.objects.create_user(
            username="poste", password="motdepasse123",
            role=Utilisateur.OPERATEUR, droit_ref=True, droit_mvt=True)
        self.client.force_authenticate(user=operateur)
        return operateur

    def test_un_operateur_ne_peut_pas_forcer(self):
        self._operateur()
        r = self.client.delete(f"/api/emplacements/{self.emp.id}/?force=1&motif=essai")
        self.assertEqual(r.status_code, 400)
        self.assertIn("administrateur", " ".join(r.data["erreur"]))
        self.assertTrue(Emplacement.objects.filter(pk=self.emp.pk).exists())

    def test_un_administrateur_peut_forcer(self):
        r = self.client.delete(
            f"/api/emplacements/{self.emp.id}/?force=1&motif=travée+démontée")
        self.assertEqual(r.status_code, 204, getattr(r, "data", None))
        self.assertFalse(Emplacement.objects.filter(pk=self.emp.pk).exists())
        self.assertFalse(Stock.objects.filter(emplacement_id=self.emp.pk).exists())

    def test_le_stock_sort_par_un_mouvement_et_non_en_douce(self):
        """Invariant du projet : la vérité du stock est le journal des mouvements.

        Supprimer les lignes de `Stock` en direct ferait disparaître 12 vis des
        totaux sans la moindre écriture, et `recalculer_stock()` ne pourrait rien
        reconstituer.
        """
        self.client.delete(f"/api/emplacements/{self.emp.id}/?force=1&motif=travée+démontée")
        sortie = Mouvement.objects.filter(type=Mouvement.SORTIE).first()
        self.assertIsNotNone(sortie)
        self.assertEqual(sortie.qte, 12)
        self.assertEqual(sortie.article_id, self.article.pk)
        self.assertEqual(sortie.utilisateur_id, self.admin.pk)
        self.assertIn("travée démontée", sortie.note)
        self.assertIn("C001", sortie.note)

    def test_sans_force_meme_un_administrateur_est_arrete(self):
        """Le droit d'y aller ne dispense pas de le dire explicitement."""
        r = self.client.delete(f"/api/emplacements/{self.emp.id}/")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Emplacement.objects.filter(pk=self.emp.pk).exists())

    def test_le_message_dit_a_chacun_ce_qu_il_peut_faire(self):
        fiche_admin = self.client.get(f"/api/emplacements/{self.emp.id}/").data["suppression"]
        self.assertTrue(fiche_admin["forcable"])
        self.assertTrue(fiche_admin["reserve_admin"])
        self.assertIn("En tant qu'administrateur", fiche_admin["message"])
        self.assertEqual(fiche_admin["stock"],
                         [{"ref": "V0001", "designation": "Vis M6", "qte": 12.0}])

        self._operateur()
        fiche_op = self.client.get(f"/api/emplacements/{self.emp.id}/").data["suppression"]
        self.assertFalse(fiche_op["forcable"])
        self.assertIn("demandez à un administrateur", fiche_op["message"])

    def test_les_cabines_restent_infranchissables_meme_pour_un_admin(self):
        """Sortir une cabine est à un clic sur l'écran de l'emplacement : aucune
        raison d'ouvrir une porte qui rendrait le parc « non rangé » sans trace."""
        vide = Emplacement.objects.create(code="D001")
        cabine = Cabine.objects.create(numero="26_02_01", chantier="000200")
        services_ranger(cabine, vide)
        r = self.client.delete(f"/api/emplacements/{vide.id}/?force=1&motif=peu+importe")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Emplacement.objects.filter(pk=vide.pk).exists())


class DiagnostiqueExposeTest(BaseEmplacement):
    """La fiche annonce ce qui bloquera AVANT que l'opérateur ne clique."""

    def test_fiche_dit_que_la_suppression_est_possible(self):
        r = self.client.get(f"/api/emplacements/{self.emp.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["suppression"]["possible"])
        self.assertFalse(r.data["suppression"]["forcable"])

    def test_fiche_explique_le_blocage(self):
        cabine = Cabine.objects.create(numero="26_01_03", chantier="000125")
        services_ranger(cabine, self.emp)
        r = self.client.get(f"/api/emplacements/{self.emp.id}/")
        self.assertFalse(r.data["suppression"]["possible"])
        self.assertEqual(r.data["suppression"]["motif"], services.BLOCAGE_CABINES)
        self.assertFalse(r.data["suppression"]["forcable"])

    def test_la_liste_ne_paie_pas_le_diagnostic(self):
        """3 comptages par ligne × 50 lignes : l'info n'a de sens que sur la fiche."""
        r = self.client.get("/api/emplacements/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data["results"][0]["suppression"])


class ContratApiTest(BaseEmplacement):
    """Les clés annoncées sont toujours là, même quand la relation est nulle."""

    def test_zone_nulle_donne_null_et_pas_une_cle_absente(self):
        """DRF retire la clé (SkipField) quand la source traverse un None : le champ
        `zone_cabine_nom` disparaissait de la réponse pour tout emplacement sans
        zone — c'est-à-dire les cinq du poste."""
        for url in (f"/api/emplacements/{self.emp.id}/", "/api/emplacements/"):
            r = self.client.get(url)
            ligne = r.data if "results" not in r.data else r.data["results"][0]
            self.assertIn("zone_cabine_nom", ligne, url)
            self.assertIsNone(ligne["zone_cabine_nom"], url)

    def test_mouvement_orphelin_garde_ses_cles(self):
        from wms import services
        article = Article.objects.create(ref="A9", designation="Vis")
        services.entree(article=article, emplacement=self.emp, qte=1)
        article.delete()          # SET_NULL : le mouvement survit sans son article
        ligne = self.client.get("/api/mouvements/").data["results"][0]
        self.assertIn("article_ref", ligne)
        self.assertIsNone(ligne["article_ref"])


class ModificationEmplacementTest(BaseEmplacement):
    def test_renommer_normalise_en_majuscules(self):
        r = self.client.patch(f"/api/emplacements/{self.emp.id}/", {"code": "d012"},
                              format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.code, "D012")

    def test_code_en_doublon_refuse_avec_un_message(self):
        Emplacement.objects.create(code="D012")
        r = self.client.patch(f"/api/emplacements/{self.emp.id}/", {"code": "d012"},
                              format="json")
        self.assertEqual(r.status_code, 400)

    def test_tous_les_champs_de_la_fiche_sont_modifiables(self):
        """Aucun des trois anciens formulaires ne les proposait tous."""
        zone = Zone.objects.create(nom="Attente départ", role=Zone.ENVOI)
        r = self.client.patch(f"/api/emplacements/{self.emp.id}/", {
            "code": "C001", "zone_cabine": zone.id, "mode_places": Emplacement.ILLIMITE,
            "description": "rack du fond", "staging": True, "actif": False,
        }, format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.zone_cabine_id, zone.id)
        self.assertEqual(self.emp.mode_places, Emplacement.ILLIMITE)
        self.assertEqual(self.emp.description, "rack du fond")
        self.assertTrue(self.emp.staging)
        self.assertFalse(self.emp.actif)

    def test_emplacement_inactif_refuse_les_rangements(self):
        self.client.patch(f"/api/emplacements/{self.emp.id}/", {"actif": False},
                          format="json")
        cabine = Cabine.objects.create(numero="26_01_04", chantier="000126")
        r = self.client.post(f"/api/cabines/{cabine.id}/ranger/",
                             {"emplacement": self.emp.id, "place": "G"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("inactif", " ".join(r.data["erreur"]).lower())


class SuppressionZoneTest(BaseEmplacement):
    def test_zone_vide_se_supprime(self):
        zone = Zone.objects.create(nom="Provisoire")
        r = self.client.delete(f"/api/zones/{zone.id}/")
        self.assertEqual(r.status_code, 204, getattr(r, "data", None))

    def test_zone_rattachee_a_des_emplacements_est_protegee(self):
        """SET_NULL débranchait les emplacements sans rien dire, et le suivi du
        processus reclassait tout le parc en simple rangement."""
        zone = Zone.objects.create(nom="Attente départ", role=Zone.ENVOI)
        self.emp.zone_cabine = zone
        self.emp.save()
        r = self.client.delete(f"/api/zones/{zone.id}/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("emplacement", " ".join(r.data["erreur"]).lower())
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.zone_cabine_id, zone.id)


class SuppressionRackTest(BaseEmplacement):
    """Supprimer un rack entier — l'opération la plus destructrice de l'écran.

    Ce qui compte ici n'est pas qu'elle marche, c'est qu'elle soit ENTIÈRE ou
    NULLE. Un rack à moitié supprimé laisse un plan à trous que personne ne sait
    reconstituer, et la panne se découvre des jours plus tard, devant le rack.
    """

    def setUp(self):
        super().setUp()
        services.generer_rack(prefixe="AC", debut=550, pas=10, colonnes=3, niveaux=2)
        self.codes = sorted(Emplacement.objects.filter(rack="AC").values_list("code", flat=True))
        self.assertEqual(len(self.codes), 6)

    def test_diagnostic_annonce_ce_qui_sera_efface(self):
        r = self.client.get("/api/emplacements/rack-diagnostic/?rack=AC")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.assertEqual(r.data["emplacements"], 6)
        self.assertEqual(r.data["cabines"], 0)
        self.assertTrue(r.data["supprimable"])
        self.assertEqual(sorted(r.data["codes"]), self.codes)

    def test_rack_vide_se_supprime_entierement(self):
        r = self.client.post("/api/emplacements/supprimer-rack/", {"rack": "AC"}, format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.assertEqual(r.data["supprimes"], 6)
        self.assertEqual(Emplacement.objects.filter(rack="AC").count(), 0)

    def test_refus_si_une_seule_cabine_est_rangee(self):
        cabine = Cabine.objects.create(numero="26_01_02", chantier="000123")
        vise = Emplacement.objects.get(code=self.codes[3])
        services_ranger(cabine, vise)

        diag = self.client.get("/api/emplacements/rack-diagnostic/?rack=AC")
        self.assertFalse(diag.data["supprimable"])
        self.assertEqual(diag.data["cabines"], 1)

        r = self.client.post("/api/emplacements/supprimer-rack/", {"rack": "AC"}, format="json")
        self.assertEqual(r.status_code, 400)
        # LE point du test : les cinq emplacements libres sont intacts eux aussi.
        self.assertEqual(Emplacement.objects.filter(rack="AC").count(), 6)
        cabine.refresh_from_db()
        self.assertEqual(cabine.emplacement_id, vise.pk)

    def test_le_forcage_ne_leve_jamais_le_blocage_des_cabines(self):
        cabine = Cabine.objects.create(numero="26_01_03", chantier="000123")
        services_ranger(cabine, Emplacement.objects.get(code=self.codes[0]))
        r = self.client.post("/api/emplacements/supprimer-rack/",
                             {"rack": "AC", "force": True}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Emplacement.objects.filter(rack="AC").count(), 6)

    def test_rack_inconnu_refuse(self):
        r = self.client.post("/api/emplacements/supprimer-rack/", {"rack": "ZZ"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_rack_vide_de_nom_refuse(self):
        """Sans ce garde-fou, un rack vide viserait tous les emplacements isolés."""
        isole = Emplacement.objects.create(code="ISOLE")
        r = self.client.post("/api/emplacements/supprimer-rack/", {"rack": ""}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Emplacement.objects.filter(pk=isole.pk).exists())

    def test_droit_referentiel_exige(self):
        operateur = Utilisateur.objects.create_user(
            username="cariste", password="motdepasse123",
            role=Utilisateur.OPERATEUR, droit_cab=True)
        self.client.force_authenticate(user=operateur)
        r = self.client.post("/api/emplacements/supprimer-rack/", {"rack": "AC"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Emplacement.objects.filter(rack="AC").count(), 6)


def services_ranger(cabine, emplacement, place="G"):
    from wms import services_cabines

    return services_cabines.ranger(cabine=cabine, emplacement=emplacement, place=place)
