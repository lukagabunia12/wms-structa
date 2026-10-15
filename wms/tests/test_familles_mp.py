"""Les familles de matières premières : une table, réglée dans l'administration.

La demande : un emplacement qui prend cartons ET vitrages, et demain d'autres
familles — quincaillerie, profilés — sans toucher au code de l'application.
"""
import importlib

from django.apps import apps
from django.contrib.admin.sites import site
from django.test import TestCase
from rest_framework.test import APITestCase

from wms import services_mp
from wms.models import ArticleMP, Emplacement, FamilleMP, StockMP, Utilisateur


class FamillesLivreesTest(TestCase):
    def test_vitrage_et_carton_sont_livrees(self):
        self.assertEqual(list(FamilleMP.objects.values_list("code", flat=True)),
                         ["vitrage", "carton"])
        self.assertEqual(services_mp.libelle_usage(
            Emplacement.objects.create(code="X1", usage="vitrage")), "MP · vitrages")

    def test_la_migration_traduit_les_anciens_usages(self):
        """Un emplacement « vitrage » devient « MP, vitrages seulement » ; ses codes
        réservés restent. Rien ne change dans ce qui entre où."""
        migration = importlib.import_module("wms.migrations.0031_familles_mp")
        e = Emplacement.objects.create(code="AH500")
        v470 = ArticleMP.objects.get(code="VITR.470X2072.BP")
        e.codes_acceptes.set([v470])
        Emplacement.objects.filter(pk=e.pk).update(usage="vitrage")   # l'état d'avant
        migration.usages_en_familles(apps, None)
        e = Emplacement.objects.get(pk=e.pk)
        self.assertEqual((e.usage, e.codes_familles()), (Emplacement.MP, ["vitrage"]))
        self.assertEqual(list(e.codes_acceptes.all()), [v470])


class NouvelleFamilleTest(APITestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create_user(
            username="chef", password="motdepasse123", role=Utilisateur.ADMIN,
            is_staff=True, is_superuser=True)
        self.client.force_authenticate(self.admin)
        self.quinc = FamilleMP.objects.create(code="quincaillerie", nom="Quincaillerie",
                                              pluriel="Quincailleries", couleur="#6B4FA0",
                                              ordre=3)
        self.vis = ArticleMP.objects.create(code="VIS.6X40", famille="quincaillerie")

    def test_l_ecran_la_recoit(self):
        r = self.client.get("/api/mp/familles/")
        self.assertEqual([f["code"] for f in r.data], ["vitrage", "carton", "quincaillerie"])
        self.assertEqual(r.data[2]["couleur"], "#6B4FA0")
        filtres = self.client.get("/api/mp/filtres/").data
        self.assertIn("quincaillerie", filtres["familles"])

    def test_un_emplacement_pour_elle_seule(self):
        e = Emplacement.objects.create(code="Q1", usage=Emplacement.MP)
        e.familles.set([self.quinc])
        services_mp.entrer(emplacement=e, place="G", article=self.vis, quantite=100)
        with self.assertRaisesMessage(services_mp.ErreurMP, "n'accepte que les quincailleries"):
            services_mp.entrer(emplacement=e, place="G", quantite=1,
                               article=ArticleMP.objects.get(code="VITR.470X2072.BP"))
        self.assertEqual(StockMP.objects.get(emplacement=e).quantite, 100)

    def test_les_suggestions_la_connaissent(self):
        r = self.client.get("/api/mp/suggestions/", {"famille": "quincaillerie", "q": "vis"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([a["code"] for a in r.data], ["VIS.6X40"])
        self.assertEqual(r.data[0]["famille_libelle"], "Quincaillerie")
        r = self.client.get("/api/mp/suggestions/", {"famille": "verre", "q": "vis"})
        self.assertEqual(r.status_code, 400)

    def test_un_code_d_une_famille_inconnue_est_refuse(self):
        from django.core.exceptions import ValidationError
        a = ArticleMP(code="X.1", famille="inconnue")
        with self.assertRaises(ValidationError):
            a.full_clean()

    def test_une_famille_citee_ne_se_supprime_pas(self):
        vue = site._registry[FamilleMP]
        requete = type("R", (), {"user": self.admin})()
        self.assertFalse(vue.has_delete_permission(requete, self.quinc))
        libre = FamilleMP.objects.create(code="profile", nom="Profilé", pluriel="Profilés")
        self.assertTrue(vue.has_delete_permission(requete, libre))

    def test_les_pages_de_l_administration(self):
        self.client.force_login(self.admin)
        r = self.client.get("/admin/wms/famillemp/")
        self.assertContains(r, "Quincaillerie")
        r = self.client.get(f"/admin/wms/famillemp/{self.quinc.pk}/change/")
        self.assertEqual(r.status_code, 200)
        # Le code se lit, il ne se change plus.
        self.assertNotContains(r, 'name="code"')
        r = self.client.get("/admin/wms/articlemp/add/")
        self.assertContains(r, '<option value="quincaillerie">Quincaillerie</option>')
        r = self.client.post("/admin/wms/famillemp/add/", {
            "nom": "Profilé", "pluriel": "Profilés", "code": "profile", "exemple": "",
            "couleur": "#336699", "ordre": 4, "actif": "on"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(FamilleMP.objects.filter(code="profile").exists())

    def test_la_liste_des_codes_reste_modifiable(self):
        """Le seuil se règle depuis la liste : le choix de famille, déclaré sur la
        fiche, n'y est pas exigé."""
        self.client.force_login(self.admin)
        r = self.client.get("/admin/wms/articlemp/", {"famille": "quincaillerie"})
        self.assertContains(r, "VIS.6X40")
        r = self.client.post("/admin/wms/articlemp/?famille=quincaillerie", {
            "form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
            "form-0-id": str(self.vis.pk), "form-0-seuil_reappro": "50",
            "form-0-actif": "on", "_save": "Enregistrer"})
        self.assertIn(r.status_code, (200, 302))
        self.vis.refresh_from_db()
        self.assertEqual(self.vis.seuil_reappro, 50)
