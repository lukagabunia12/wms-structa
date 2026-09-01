"""Sonde de supervision.

C'est ce point que surveillent le redémarrage automatique du service et la
sonde du reverse-proxy : il doit répondre sans compte, et ne rien divulguer.
"""
from unittest import mock

from rest_framework.test import APITestCase

from wms.models import Utilisateur


class SanteTest(APITestCase):
    def test_repond_sans_authentification(self):
        """Un outil de supervision n'a pas de compte."""
        r = self.client.get("/api/sante/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, {"service": "ok", "base": "ok", "migrations": "ok"})

    def test_ne_divulgue_rien(self):
        """Ni version, ni chemin, ni hôte de base : la sonde est publique."""
        contenu = self.client.get("/api/sante/").content.decode().lower()
        for indiscret in ["django", "postgres", "sqlite", "/", "password", "secret"]:
            self.assertNotIn(indiscret, contenu)

    def test_503_si_la_base_ne_repond_pas(self):
        """503 et non 500 : c'est le code que les sondes savent interpréter."""
        with mock.patch("django.db.connection.cursor", side_effect=Exception("boum")):
            r = self.client.get("/api/sante/")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.data["base"], "injoignable")

    def test_503_si_des_migrations_manquent(self):
        """Schéma en retard sur le code : à dire avant l'incident, pas après."""
        with mock.patch("django.db.migrations.executor.MigrationExecutor.migration_plan",
                        return_value=[("wms", "0099_imaginaire")]):
            r = self.client.get("/api/sante/")
        self.assertEqual(r.status_code, 503)
        self.assertIn("1", r.data["migrations"])

    def test_le_reste_de_l_api_demande_toujours_un_compte(self):
        """La sonde ouverte ne doit pas avoir ouvert le reste au passage."""
        self.assertIn(self.client.get("/api/emplacements/").status_code, (401, 403))
        Utilisateur.objects.create_user(username="x", password="motdepasse123")
        self.assertIn(self.client.get("/api/cabines/").status_code, (401, 403))
