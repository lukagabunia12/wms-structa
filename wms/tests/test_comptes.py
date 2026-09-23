"""Création des comptes, dans l'administration Django.

L'application n'a pas d'écran de gestion des comptes : ils se créent dans
`/admin/`. Ces tests fixent ce qui doit y être atteignable en UN écran, parce
qu'un compte créé sans le droit « cabines » ne peut rien faire — et que le
défaut se découvre sur le téléphone du cariste, pas dans l'administration.
"""
from django.contrib.admin.sites import site
from django.test import TestCase

from wms.admin import PROFIL_CARISTE, PROFIL_GESTIONNAIRE
from wms.models import Utilisateur


class AdministrationDesComptesTest(TestCase):
    def setUp(self):
        self.admin_vue = site._registry[Utilisateur]

    def test_le_formulaire_de_creation_porte_le_droit_cabines(self):
        """Sans cela, créer un cariste demande deux écrans — et on oublie le second."""
        champs = []
        for _, section in self.admin_vue.add_fieldsets:
            champs.extend(section["fields"])
        for attendu in ("nom", "role", "droit_cab", "droit_ref"):
            self.assertIn(attendu, champs)

    def test_la_fiche_ne_montre_que_les_droits_qui_commandent_quelque_chose(self):
        """Cinq cases (mouvements, inventaire, appro…) ne commandaient plus rien
        depuis le retrait du volet articles : on les cochait sans effet."""
        champs = [c for _, section in self.admin_vue.fieldsets for c in section["fields"]]
        self.assertEqual([c for c in champs if c.startswith("droit_")], ["droit_cab", "droit_ref"])

    def test_profil_affiche_ce_que_la_personne_verra(self):
        cas = [
            (dict(username="c1", role=Utilisateur.OPERATEUR, droit_cab=True), "Cariste"),
            (dict(username="c2", role=Utilisateur.OPERATEUR, droit_cab=True,
                  droit_ref=True), "Gestionnaire"),
            (dict(username="c3", role=Utilisateur.ADMIN), "Administrateur"),
            (dict(username="c4", role=Utilisateur.LECTURE), "Lecture seule"),
            (dict(username="c5", role=Utilisateur.OPERATEUR), "Aucun droit"),
        ]
        for champs, attendu in cas:
            with self.subTest(compte=champs["username"]):
                u = Utilisateur.objects.create_user(password="motdepasse123", **champs)
                self.assertEqual(self.admin_vue.profil(u), attendu)

    def test_lecture_seule_l_emporte_sur_les_cases_cochees(self):
        """Le piège : cocher « cabines » sur un compte en lecture seule ne donne rien."""
        u = Utilisateur.objects.create_user(username="c6", password="motdepasse123",
                                            role=Utilisateur.LECTURE, droit_cab=True)
        self.assertFalse(u.droits_effectifs()["cab"])
        self.assertEqual(self.admin_vue.profil(u), "Lecture seule")

    def test_action_groupee_cariste(self):
        for i in range(3):
            Utilisateur.objects.create_user(username=f"n{i}", password="motdepasse123")
        Utilisateur.objects.filter(username__startswith="n").update(**PROFIL_CARISTE)
        for u in Utilisateur.objects.filter(username__startswith="n"):
            self.assertEqual(self.admin_vue.profil(u), "Cariste")

    def test_action_groupee_gestionnaire(self):
        u = Utilisateur.objects.create_user(username="g1", password="motdepasse123")
        Utilisateur.objects.filter(pk=u.pk).update(**PROFIL_GESTIONNAIRE)
        u.refresh_from_db()
        self.assertEqual(self.admin_vue.profil(u), "Gestionnaire")

    def test_un_cariste_n_a_pas_le_referentiel(self):
        """Ce que « Cariste » veut dire, noir sur blanc."""
        u = Utilisateur.objects.create_user(username="c7", password="motdepasse123",
                                            **PROFIL_CARISTE)
        self.assertEqual(u.droits_effectifs(), {"cab": True, "ref": False})
