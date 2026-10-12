"""Le frein aux essais de mot de passe.

Avant lui, `/api/token/` acceptait des milliers d'essais à la suite — la vue de
DRF ignore le quota anonyme — et l'administration n'avait aucune limite. Ce
qu'on vérifie : le frein arrête la devinette, il ne bloque pas un collègue sur
un autre téléphone, il ne bloque jamais tout l'entrepôt d'un coup, et il dit
combien de temps attendre.
"""
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

from wms.admin import valeurs_profil
from wms.models import Utilisateur

PROFIL_CARISTE = valeurs_profil("cariste")


@override_settings(CONNEXION_ESSAIS_PAR_COMPTE=5, CONNEXION_ESSAIS_PAR_ADRESSE=8,
                   CONNEXION_FENETRE_MINUTES=15)
class FreinConnexionTest(APITestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.mdp = "motdepasse123"
        Utilisateur.objects.create_user(username="enzo", password=self.mdp, **PROFIL_CARISTE)

    def tenter(self, nom="enzo", mdp=None, ip="192.168.0.50"):
        return self.client.post("/api/token/", {"username": nom, "password": mdp or self.mdp},
                                format="json", REMOTE_ADDR=ip)

    def test_apres_trop_d_echecs_meme_le_bon_mot_de_passe_attend(self):
        for _ in range(5):
            self.assertEqual(self.tenter(mdp="faux").status_code, 400)
        r = self.tenter()
        self.assertEqual(r.status_code, 429)
        self.assertIn("Réessayez dans 15 minutes", r.data["detail"])
        self.assertTrue(r.has_header("Retry-After"))

    def test_un_autre_telephone_n_est_pas_bloque(self):
        for _ in range(5):
            self.tenter(mdp="faux")
        self.assertEqual(self.tenter(ip="192.168.0.51").status_code, 200)

    def test_une_reussite_remet_le_compteur_du_compte_a_zero(self):
        for _ in range(4):
            self.tenter(mdp="faux")
        self.assertEqual(self.tenter().status_code, 200)
        # Sans remise à zéro, 4 + 3 échecs dépasseraient les 5 permis au compte.
        # (Le compteur de l'adresse, lui, n'est jamais remis à zéro : 7 sur 8.)
        for _ in range(3):
            self.assertEqual(self.tenter(mdp="faux").status_code, 400)
        self.assertEqual(self.tenter().status_code, 200)

    def test_on_n_essaie_pas_cent_comptes_depuis_la_meme_adresse(self):
        for i in range(8):
            self.tenter(nom=f"inconnu{i}", mdp="faux")
        self.assertEqual(self.tenter().status_code, 429)

    def test_la_machine_elle_meme_ne_bloque_jamais_tout_l_entrepot(self):
        """Derrière un proxy mal réglé, tous les téléphones arrivent de
        127.0.0.1 : un compteur par adresse bloquerait tout le monde."""
        for i in range(20):
            self.tenter(nom=f"inconnu{i}", mdp="faux", ip="127.0.0.1")
        self.assertEqual(self.tenter(ip="127.0.0.1").status_code, 200)

    def test_l_administration_dit_pourquoi(self):
        Utilisateur.objects.create_superuser("chef", "chef@exemple.fr", "motdepasse-123")
        for _ in range(5):
            self.client.post("/admin/login/", {"username": "chef", "password": "faux"},
                             REMOTE_ADDR="192.168.0.60")
        r = self.client.post("/admin/login/?next=/admin/",
                             {"username": "chef", "password": "motdepasse-123"},
                             REMOTE_ADDR="192.168.0.60")
        self.assertEqual(r.status_code, 200)       # pas de redirection : refusé
        self.assertContains(r, "Trop d&#x27;essais de connexion")

    def test_un_corps_qui_n_est_pas_un_objet_ne_fait_pas_d_erreur_500(self):
        r = self.client.post("/api/token/", ["enzo"], format="json", REMOTE_ADDR="192.168.0.50")
        self.assertEqual(r.status_code, 400)
