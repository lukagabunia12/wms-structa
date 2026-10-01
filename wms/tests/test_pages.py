"""Tests de bout en bout des pages servies (interface et administration)."""
import json
import os
import struct
from pathlib import Path
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


STATIQUES = Path(__file__).resolve().parents[1] / "static" / "app"


def _taille_png(chemin):
    """Largeur et hauteur lues dans l'en-tête PNG — sans dépendre de Pillow."""
    entete = chemin.read_bytes()[:24]
    assert entete[:8] == b"\x89PNG\r\n\x1a\n", f"{chemin.name} n'est pas un PNG"
    return struct.unpack(">II", entete[16:24])


class RaccourciTelephoneTest(TestCase):
    """Ce qu'il faut pour que l'icône posée sur l'écran d'accueil soit la bonne.

    Une icône manquante ne casse rien à l'écran : le téléphone pose alors une
    capture de la page, ou un « S » générique. C'est pour cela qu'un test la
    guette — personne ne le verrait avant d'équiper vingt téléphones.
    """

    def setUp(self):
        self.manifeste = json.loads((STATIQUES / "manifest.webmanifest").read_text("utf-8"))

    def test_la_page_annonce_le_manifeste_et_l_icone_iphone(self):
        html = self.client.get("/").content.decode()
        self.assertIn("app/manifest.webmanifest", html)
        self.assertIn('rel="apple-touch-icon"', html)
        self.assertIn('name="apple-mobile-web-app-title" content="WMS Structa"', html)

    def test_le_manifeste_ouvre_le_wms_en_plein_ecran(self):
        self.assertEqual(self.manifeste["start_url"], "/")
        self.assertEqual(self.manifeste["scope"], "/")
        self.assertEqual(self.manifeste["display"], "standalone")
        self.assertEqual(self.manifeste["name"], "WMS Structa")

    def test_chaque_icone_existe_a_la_taille_annoncee(self):
        for icone in self.manifeste["icons"]:
            with self.subTest(icone=icone["src"]):
                fichier = STATIQUES / Path(icone["src"]).name
                self.assertTrue(fichier.is_file(), f"{icone['src']} introuvable")
                largeur, hauteur = map(int, icone["sizes"].split("x"))
                self.assertEqual(_taille_png(fichier), (largeur, hauteur))

    def test_android_a_une_icone_decoupable(self):
        """Sans icône « maskable », Android réduit le logo dans une pastille blanche."""
        tailles = {i["sizes"] for i in self.manifeste["icons"] if i.get("purpose") == "maskable"}
        self.assertIn("512x512", tailles)

    def test_l_icone_iphone_fait_180_pixels(self):
        self.assertEqual(_taille_png(STATIQUES / "apple-touch-icon.png"), (180, 180))

    def test_le_manifeste_est_servi(self):
        r = self.client.get("/static/app/manifest.webmanifest")
        self.assertEqual(r.status_code, 200)
        contenu = b"".join(r.streaming_content) if r.streaming else r.content
        self.assertEqual(json.loads(contenu)["short_name"], "WMS Structa")
