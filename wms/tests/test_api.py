"""Tests de l'API REST : authentification, identité du compte, droits."""
from rest_framework.test import APITestCase

from wms.models import Cabine, Emplacement, Utilisateur


class AuthentificationTest(APITestCase):
    def setUp(self):
        Utilisateur.objects.create_user(username="op", password="secret123")

    def test_acces_refuse_sans_authentification(self):
        r = self.client.get("/api/emplacements/")
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
        self.assertEqual(self.client.get("/api/emplacements/").status_code, 200)


class MoiTest(APITestCase):
    """L'interface a besoin des droits du compte pour ne pas proposer l'interdit."""

    def setUp(self):
        self.user = Utilisateur.objects.create_user(username="op", password="secret123",
                                                    role=Utilisateur.ADMIN)
        self.client.force_authenticate(user=self.user)

    def test_identite_et_droits(self):
        r = self.client.get("/api/moi/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["username"], "op")
        self.assertEqual(r.data["role"], Utilisateur.ADMIN)
        # Une clé par case de la fiche du compte, ni plus ni moins — toutes
        # vraies pour un administrateur.
        self.assertEqual(r.data["droits"], {d: True for d in Utilisateur.DROITS})
        # Et le nom de chaque case : l'écran dit « il te manque X » avec le mot
        # que l'administrateur cherchera sur la fiche.
        self.assertEqual(r.data["libelles_droits"]["empl_creer"],
                         "créer et supprimer des emplacements et des racks")
        self.assertEqual(set(r.data["libelles_droits"]), set(Utilisateur.DROITS))

    def test_droits_d_un_lecteur(self):
        lecteur = Utilisateur.objects.create_user(username="lect", password="secret123",
                                                  role=Utilisateur.LECTURE,
                                                  droit_cab_ranger=True, droit_mp=True)
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


class UniciteCasseTest(APITestCase):
    """Le code d'un emplacement est normalisé en MAJUSCULES *et* unique."""

    def test_code_emplacement_en_minuscules_detecte_comme_doublon(self):
        self.client.force_authenticate(user=Utilisateur.objects.create_user(
            username="chef", password="secret123", role=Utilisateur.ADMIN))
        Emplacement.objects.create(code="A001")
        self.assertEqual(self.client.post("/api/emplacements/", {"code": "a001"},
                                          format="json").status_code, 400)


class DroitsTest(APITestCase):
    """Chaque écriture exige son droit ; la lecture reste ouverte à tout compte."""

    def setUp(self):
        self.e1 = Emplacement.objects.create(code="A001")

    def _connecter(self, username, **kw):
        u = Utilisateur.objects.create_user(username=username, password="secret123", **kw)
        self.client.force_authenticate(user=u)
        return u

    def _creer_emplacement(self, code="B001"):
        return self.client.post("/api/emplacements/", {"code": code}, format="json")

    def _creer_cabine(self):
        return self.client.post("/api/cabines/", {"numero": "11_22_33", "chantier": "000111"},
                                format="json")

    def test_acces_refuse_sans_authentification(self):
        self.assertIn(self._creer_emplacement().status_code, (401, 403))

    def test_lecture_seule_ne_peut_rien_ecrire(self):
        self._connecter("lecteur", role=Utilisateur.LECTURE)
        self.assertEqual(self._creer_emplacement().status_code, 403)
        self.assertEqual(self.client.delete(f"/api/emplacements/{self.e1.id}/").status_code, 403)
        self.assertEqual(self._creer_cabine().status_code, 403)
        self.assertTrue(Emplacement.objects.filter(pk=self.e1.id).exists())
        self.assertFalse(Cabine.objects.exists())

    def test_lecture_seule_peut_consulter(self):
        self._connecter("lecteur", role=Utilisateur.LECTURE)
        self.assertEqual(self.client.get("/api/emplacements/").status_code, 200)
        self.assertEqual(self.client.get("/api/cabines/").status_code, 200)

    def test_lecture_seule_ignore_les_cases_cochees(self):
        self._connecter("lecteur", role=Utilisateur.LECTURE,
                        **{f"droit_{d}": True for d in Utilisateur.DROITS})
        self.assertEqual(self._creer_emplacement().status_code, 403)
        self.assertEqual(self._creer_cabine().status_code, 403)

    def test_creer_un_emplacement_exige_sa_case(self):
        """Régler, mettre hors service : rien de cela ne vaut créer."""
        self._connecter("op", role=Utilisateur.OPERATEUR, droit_cab_ranger=True,
                        droit_empl_regler=True, droit_empl_service=True)
        r = self._creer_emplacement()
        self.assertEqual(r.status_code, 403)
        # Le refus nomme la case qui manque.
        self.assertIn("créer et supprimer des emplacements", str(r.data))

    def test_la_case_creer_autorise_la_creation(self):
        self._connecter("op", role=Utilisateur.OPERATEUR, droit_empl_creer=True)
        self.assertEqual(self._creer_emplacement().status_code, 201)

    def test_cabines_exigent_leur_case(self):
        self._connecter("op", role=Utilisateur.OPERATEUR, droit_empl_creer=True,
                        droit_empl_regler=True)
        self.assertEqual(self._creer_cabine().status_code, 403)

    def test_une_ecriture_rattachee_a_aucune_case_est_reservee_aux_administrateurs(self):
        """Fermé par défaut : une vue qui ne dit rien de ses écritures ne les
        ouvre pas à tous les comptes. `/api/pouls/` ne se lit qu'en GET."""
        self._connecter("op", role=Utilisateur.OPERATEUR,
                        **{f"droit_{d}": True for d in Utilisateur.DROITS})
        r = self.client.post("/api/pouls/", {}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertIn("aucune case", str(r.data))
        self._connecter("chef", role=Utilisateur.ADMIN)
        self.assertEqual(self.client.post("/api/pouls/", {}, format="json").status_code, 405,
                         "l'administrateur passe le contrôle, et la méthode est refusée")

    def test_role_admin_a_tous_les_droits(self):
        self._connecter("chef", role=Utilisateur.ADMIN)
        self.assertEqual(self._creer_emplacement().status_code, 201)

    def test_superuser_a_tous_les_droits(self):
        """`createsuperuser` laisse role=operateur : sans `is_superuser` dans
        droits_effectifs(), le seul compte d'administration réel serait verrouillé."""
        u = Utilisateur.objects.create_superuser(username="boss", password="secret123", email="")
        self.assertEqual(u.role, Utilisateur.OPERATEUR)
        self.client.force_authenticate(user=u)
        self.assertEqual(self._creer_emplacement().status_code, 201)
