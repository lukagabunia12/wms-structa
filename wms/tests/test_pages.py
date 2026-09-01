"""Tests de bout en bout des pages servies (interface et administration)."""
from django.test import TestCase

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
