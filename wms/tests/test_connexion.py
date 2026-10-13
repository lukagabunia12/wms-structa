"""Connexion à l'application : ce qui doit passer, ce qui doit être refusé.

Ces tests viennent d'un échec réel : un compte fraîchement créé répondait
« identifiants incorrects » sans qu'on sache pourquoi. Trois causes étaient
possibles et se ressemblaient toutes à l'écran.
"""
from rest_framework.test import APITestCase

from wms.admin import valeurs_profil
from wms.models import Utilisateur

PROFIL_CARISTE = valeurs_profil("cariste")


class ConnexionTest(APITestCase):
    def setUp(self):
        self.mdp = "motdepasse123"
        self.u = Utilisateur.objects.create_user(username="enzo", password=self.mdp,
                                                 **PROFIL_CARISTE)

    def tenter(self, nom, mdp=None):
        return self.client.post("/api/token/",
                                {"username": nom, "password": mdp or self.mdp},
                                format="json")

    def test_connexion_normale(self):
        r = self.tenter("enzo")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.assertIn("token", r.data)

    def test_majuscule_du_clavier_de_telephone(self):
        """LE cas qui a fait échouer une mise en service : « Enzo » pour « enzo »."""
        for saisi in ("Enzo", "ENZO", "eNzO"):
            with self.subTest(saisi=saisi):
                self.assertEqual(self.tenter(saisi).status_code, 200)

    def test_espaces_autour_de_l_identifiant(self):
        self.assertEqual(self.tenter("  enzo  ").status_code, 200)

    def test_mot_de_passe_reste_sensible_a_la_casse(self):
        """La tolérance porte sur l'identifiant, JAMAIS sur le mot de passe."""
        self.assertEqual(self.tenter("enzo", self.mdp.upper()).status_code, 400)

    def test_mauvais_mot_de_passe_refuse(self):
        self.assertEqual(self.tenter("enzo", "autre-chose").status_code, 400)

    def test_compte_desactive_refuse(self):
        self.u.is_active = False
        self.u.save()
        self.assertEqual(self.tenter("enzo").status_code, 400)

    def test_compte_sans_mot_de_passe_utilisable_refuse(self):
        """Le piège de l'administration : « Aucun mot de passe » se coche sans y penser."""
        u = Utilisateur.objects.create(username="fantome", **PROFIL_CARISTE)
        u.set_unusable_password()
        u.save()
        self.assertEqual(self.tenter("fantome").status_code, 400)

    def test_identifiant_inconnu_refuse(self):
        self.assertEqual(self.tenter("personne").status_code, 400)

    def test_ambiguite_de_casse_refusee_sauf_correspondance_exacte(self):
        """Deux comptes qui ne diffèrent que par la casse : on ne devine pas."""
        Utilisateur.objects.create_user(username="Enzo", password="unautremdp456",
                                        **PROFIL_CARISTE)
        # Chacun se connecte avec SON orthographe exacte…
        self.assertEqual(self.tenter("enzo", self.mdp).status_code, 200)
        self.assertEqual(self.tenter("Enzo", "unautremdp456").status_code, 200)
        # …mais une orthographe qui ne correspond à aucun des deux est refusée,
        # plutôt que d'en choisir un au hasard.
        self.assertEqual(self.tenter("ENZO", self.mdp).status_code, 400)

    def test_un_compte_sans_droit_peut_se_connecter(self):
        """Il se connecte, et ne voit aucune action : c'est le comportement voulu.

        Le refuser à la connexion enverrait chercher un problème de mot de passe
        là où il n'y a qu'une case à cocher.
        """
        Utilisateur.objects.create_user(username="vide", password=self.mdp)
        self.assertEqual(self.tenter("vide").status_code, 200)


class ConnexionAvecSessionAdminTest(APITestCase):
    """Vu sur le serveur : connectée à /admin/ dans le même navigateur, la
    responsable ne pouvait plus se connecter à l'application — « 403 », à
    chaque essai. Le cookie de session de l'administration faisait passer la
    page de connexion par l'authentification de session de DRF, qui exige alors
    le jeton CSRF que l'application n'envoie pas (elle travaille par jeton)."""

    def test_une_session_admin_ouverte_n_empeche_pas_la_connexion(self):
        from rest_framework.test import APIClient
        admin = Utilisateur.objects.create_superuser(username="structa", password="x-admin-1",
                                                     email="")
        Utilisateur.objects.create_user(username="enzo", password="motdepasse123",
                                        **PROFIL_CARISTE)
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(admin)
        r = client.post("/api/token/", {"username": "enzo", "password": "motdepasse123"},
                        format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.assertIn("token", r.data)
