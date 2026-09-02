"""Tests de bout en bout des pages servies (interface et administration)."""
import os
from unittest import mock

from django.test import TestCase, override_settings

from config.settings import _acces_test
from wms.models import Utilisateur


class PagesTest(TestCase):
    def test_page_application_repond(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)

    def test_page_application_charge_les_ressources_versionnees(self):
        html = self.client.get("/").content.decode()
        self.assertIn("app/app.js", html)
        self.assertIn("app/app.css", html)
        self.assertIn("?v=", html)  # anti-cache navigateur

    def test_administration_redirige_vers_connexion(self):
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 302)

    def test_administration_accessible_a_un_admin(self):
        Utilisateur.objects.create_superuser(username="boss", password="secret123", email="")
        self.client.login(username="boss", password="secret123")
        self.assertEqual(self.client.get("/admin/").status_code, 200)


class AccesTesteursTest(TestCase):
    """Le pré-remplissage de l'écran de connexion pendant une campagne de test.

    Ce réglage écrit un mot de passe dans la page : ces tests portent d'abord sur
    ce qui ne doit PAS sortir tant que la variable d'environnement est absente.
    """

    def test_rien_dans_la_page_sans_reglage(self):
        with override_settings(ACCES_TEST=None):
            html = self.client.get("/").content.decode()
        self.assertNotIn("acces-test", html)

    def test_le_compte_est_pre_rempli_quand_le_reglage_est_la(self):
        with override_settings(ACCES_TEST={"identifiant": "TEST", "motdepasse": "secret"}):
            html = self.client.get("/").content.decode()
        self.assertIn('id="acces-test"', html)
        self.assertIn("TEST", html)
        self.assertIn("secret", html)

    def test_un_mot_de_passe_biscornu_ne_casse_pas_la_page(self):
        """Le mot de passe traverse le HTML : il est échappé, jamais interprété."""
        with override_settings(ACCES_TEST={"identifiant": "TEST",
                                           "motdepasse": '</script><b>x'}):
            html = self.client.get("/").content.decode()
        self.assertNotIn("</script><b>x", html)
        self.assertIn("\\u003C", html)

    def test_lecture_du_reglage(self):
        complet = {"identifiant": "TEST", "motdepasse": "testwms1"}
        for brut, attendu in [
            ("", None),                                # rien : cas normal
            ("TEST", None),                            # sans mot de passe : ignoré
            ("TEST:", None),
            (":testwms1", None),
            ("TEST:testwms1", complet),
            ("  TEST : testwms1  ", complet),          # espaces d'un copier-coller
            ("TEST:a:b", {"identifiant": "TEST", "motdepasse": "a:b"}),
        ]:
            with self.subTest(brut=brut), mock.patch.dict(os.environ,
                                                          {"WMS_ACCES_TEST": brut}):
                self.assertEqual(_acces_test(), attendu)
