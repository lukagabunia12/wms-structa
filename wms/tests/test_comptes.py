"""Les comptes et leurs droits, dans l'administration Django.

L'application n'a pas d'écran de gestion des comptes : ils se créent dans
`/admin/`. Ces tests fixent ce qui doit y être atteignable en UN écran — les
cases à cocher, une par geste —, parce qu'un compte créé sans droit ne peut
rien faire, et que le défaut se découvre sur le téléphone du cariste, pas dans
l'administration.
"""
from django.contrib.admin.sites import site
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase

from wms.admin import PROFILS, FiltreDroit, valeurs_profil
from wms.models import Utilisateur


def champs_de(fieldsets):
    return [c for _, section in fieldsets for c in section["fields"]]


class FicheDuCompteTest(TestCase):
    def setUp(self):
        self.admin_vue = site._registry[Utilisateur]

    def test_le_formulaire_de_creation_porte_toutes_les_cases(self):
        """Sans cela, créer un cariste demande deux écrans — et on oublie le second."""
        champs = champs_de(self.admin_vue.add_fieldsets)
        for attendu in ["nom", "role"] + [f"droit_{d}" for d in Utilisateur.DROITS]:
            self.assertIn(attendu, champs)

    def test_la_fiche_montre_chaque_case_une_fois_dans_l_ordre(self):
        """Une case affichée sans droit derrière, ou un droit sans case, c'est la
        dérive qu'on a déjà connue : cinq cases qui ne commandaient plus rien."""
        cases = [c.removeprefix("droit_") for c in champs_de(self.admin_vue.fieldsets)
                 if c.startswith("droit_")]
        self.assertEqual(cases, Utilisateur.DROITS)

    def test_les_cases_sont_groupees_comme_la_fiche_les_annonce(self):
        titres = [titre for titre, section in self.admin_vue.fieldsets
                  if any(c.startswith("droit_") for c in section["fields"])]
        self.assertEqual(titres, ["Droits — cabines", "Droits — fichier de production",
                                  "Droits — matières premières",
                                  "Droits — emplacements, racks et modèles"])

    def test_creer_et_supprimer_est_une_case_a_part(self):
        """La demande d'origine : un opérateur règle les emplacements, les met
        hors service, condamne une place — sans pouvoir en créer ni en supprimer."""
        self.assertIn("empl_creer", Utilisateur.DROITS)
        u = Utilisateur.objects.create_user(
            username="op", password="motdepasse123", role=Utilisateur.OPERATEUR,
            droit_empl_regler=True, droit_empl_service=True)
        self.assertTrue(u.peut("empl_regler"))
        self.assertTrue(u.peut("empl_service"))
        self.assertFalse(u.peut("empl_creer"))

    def test_chaque_case_porte_un_nom_et_une_explication(self):
        for d in Utilisateur.DROITS:
            with self.subTest(droit=d):
                champ = Utilisateur._meta.get_field(f"droit_{d}")
                self.assertTrue(champ.verbose_name)
                self.assertEqual(Utilisateur.libelle_droit(d), str(champ.verbose_name))
                self.assertFalse(champ.default, "aucune case cochée d'office")

    def test_un_droit_inconnu_vaut_non(self):
        """Une faute de frappe dans une vue ferme le geste au lieu de l'ouvrir."""
        chef = Utilisateur.objects.create_user(username="chef", password="motdepasse123",
                                               role=Utilisateur.ADMIN)
        self.assertFalse(chef.peut("cab_rangre"))
        self.assertEqual(Utilisateur.libelle_droit("cab_rangre"), "cab_rangre")


class RolesTest(TestCase):
    def test_lecture_seule_l_emporte_sur_les_cases_cochees(self):
        """Le piège : cocher des cases sur un compte en lecture seule ne donne rien."""
        u = Utilisateur.objects.create_user(
            username="c6", password="motdepasse123", role=Utilisateur.LECTURE,
            **{f"droit_{d}": True for d in Utilisateur.DROITS})
        self.assertFalse(any(u.droits_effectifs().values()))
        self.assertEqual(site._registry[Utilisateur].profil(u), "Lecture seule")

    def test_l_administrateur_a_toutes_les_cases_sans_en_cocher_aucune(self):
        u = Utilisateur.objects.create_user(username="chef", password="motdepasse123",
                                            role=Utilisateur.ADMIN)
        self.assertTrue(all(u.droits_effectifs().values()))
        self.assertEqual(set(u.droits_effectifs()), set(Utilisateur.DROITS))

    def test_un_operateur_n_a_que_ses_cases(self):
        u = Utilisateur.objects.create_user(username="op", password="motdepasse123",
                                            role=Utilisateur.OPERATEUR,
                                            droit_cab_ranger=True, droit_mp_seuils=True)
        self.assertEqual({d for d, oui in u.droits_effectifs().items() if oui},
                         {"cab_ranger", "mp_seuils"})


class ColonneDroitsTest(TestCase):
    def setUp(self):
        self.admin_vue = site._registry[Utilisateur]

    def test_le_nom_du_profil_quand_les_cases_en_forment_un(self):
        cas = [
            ("c1", valeurs_profil("cariste"), "Cariste"),
            ("c2", valeurs_profil("cariste_mp"), "Cariste + MP"),
            ("c3", valeurs_profil("mp"), "Matières premières"),
            ("c4", valeurs_profil("gestionnaire"), "Gestionnaire"),
            ("c5", {"role": Utilisateur.ADMIN}, "Administrateur — tout"),
            ("c6", valeurs_profil("lecture"), "Lecture seule"),
            ("c7", {"role": Utilisateur.OPERATEUR}, "Aucun droit"),
        ]
        for nom, champs, attendu in cas:
            with self.subTest(compte=nom):
                u = Utilisateur.objects.create_user(username=nom, password="motdepasse123",
                                                    **champs)
                self.assertEqual(self.admin_vue.profil(u), attendu)

    def test_sur_mesure_dit_quelles_cases(self):
        u = Utilisateur.objects.create_user(
            username="sm", password="motdepasse123", role=Utilisateur.OPERATEUR,
            droit_cab_ranger=True, droit_empl_service=True)
        self.assertEqual(self.admin_vue.profil(u), "Sur mesure : ranger, mise en service")

    def test_les_comptes_d_avant_gardent_leur_nom_de_profil(self):
        """La migration 0028 reporte « cabines » sur les quatre cases des
        cabines : un ancien cariste doit rester « Cariste » dans la liste."""
        self.assertEqual(PROFILS["cariste"][2],
                         {"cab_ranger", "cab_statut", "cab_envoyer", "cab_corriger"})


class ProfilsPretsAEmploiTest(TestCase):
    """Les actions de la liste des comptes : un profil d'un geste, pour plusieurs."""

    def setUp(self):
        self.admin_vue = site._registry[Utilisateur]
        # Superutilisateur : la gestion des comptes, dans l'administration, suit
        # les permissions de Django — le rôle WMS n'y suffit pas.
        self.chef = Utilisateur.objects.create_user(
            username="chef", password="motdepasse123", role=Utilisateur.ADMIN,
            is_staff=True, is_superuser=True)

    def appliquer(self, action, queryset):
        requete = RequestFactory().post("/admin/wms/utilisateur/")
        requete.user = self.chef
        requete.session = {}
        requete._messages = FallbackStorage(requete)
        getattr(self.admin_vue, action)(requete, queryset)
        return [str(m) for m in requete._messages]

    def test_un_profil_fixe_toutes_les_cases(self):
        """Passer un gestionnaire en cariste lui RETIRE le reste : une action qui
        ne ferait que cocher laisserait ses droits d'avant, sans le dire."""
        u = Utilisateur.objects.create_user(username="g", password="motdepasse123",
                                            **valeurs_profil("gestionnaire"))
        self.appliquer("profil_cariste", Utilisateur.objects.filter(pk=u.pk))
        u.refresh_from_db()
        self.assertEqual({d for d, oui in u.droits_effectifs().items() if oui},
                         PROFILS["cariste"][2])
        self.assertEqual(self.admin_vue.profil(u), "Cariste")

    def test_plusieurs_comptes_d_un_coup(self):
        for i in range(3):
            Utilisateur.objects.create_user(username=f"n{i}", password="motdepasse123")
        messages = self.appliquer("profil_cariste_mp",
                                  Utilisateur.objects.filter(username__startswith="n"))
        for u in Utilisateur.objects.filter(username__startswith="n"):
            self.assertEqual(self.admin_vue.profil(u), "Cariste + MP")
        self.assertIn("3 compte(s)", messages[0])

    def test_le_gestionnaire_ne_cree_ni_ne_supprime_d_emplacement(self):
        """Ni le fichier de production : ces cases se cochent à la main."""
        droits = PROFILS["gestionnaire"][2]
        self.assertNotIn("empl_creer", droits)
        self.assertNotIn("production", droits)
        self.assertNotIn("hors_fichier", droits)
        self.assertTrue({"empl_regler", "empl_service", "modeles", "mp_seuils"} <= droits)

    def test_un_administrateur_coche_par_megarde_reste_administrateur(self):
        op = Utilisateur.objects.create_user(username="op", password="motdepasse123")
        messages = self.appliquer(
            "profil_lecture", Utilisateur.objects.filter(pk__in=[op.pk, self.chef.pk]))
        self.chef.refresh_from_db()
        op.refresh_from_db()
        self.assertEqual(self.chef.role, Utilisateur.ADMIN)
        self.assertEqual(op.role, Utilisateur.LECTURE)
        self.assertIn("1 administrateur(s) laissé(s) tel(s) quel(s)", messages[0])

    def test_un_compte_qui_consulte_ne_se_donne_pas_de_droits(self):
        """Django propose les actions à qui peut seulement consulter la liste,
        sauf si elles exigent la permission de modifier. Sans cela, un compte
        en lecture se passait lui-même en gestionnaire."""
        from django.contrib.auth.models import Permission
        lecteur = Utilisateur.objects.create_user(
            username="lect", password="motdepasse123", role=Utilisateur.LECTURE,
            is_staff=True)
        lecteur.user_permissions.set(Permission.objects.filter(codename="view_utilisateur"))
        self.client.force_login(lecteur)
        r = self.client.post("/admin/wms/utilisateur/", {
            "action": "profil_gestionnaire", "_selected_action": [lecteur.pk], "index": 0})
        self.assertIn(r.status_code, (200, 302))
        lecteur.refresh_from_db()
        self.assertEqual(lecteur.role, Utilisateur.LECTURE)
        self.assertFalse(any(getattr(lecteur, f"droit_{d}") for d in Utilisateur.DROITS))
        # Et l'action ne lui est même pas proposée.
        actions = self.admin_vue.get_actions(type("R", (), {"user": lecteur, "GET": {}})())
        self.assertNotIn("profil_gestionnaire", actions)

    def test_le_filtre_par_droit_compte_les_roles(self):
        """« Qui peut créer des emplacements ? » : les administrateurs aussi, la
        lecture seule jamais — même cochée."""
        Utilisateur.objects.create_user(username="op", password="motdepasse123",
                                        role=Utilisateur.OPERATEUR, droit_empl_creer=True)
        Utilisateur.objects.create_user(username="sans", password="motdepasse123",
                                        role=Utilisateur.OPERATEUR)
        Utilisateur.objects.create_user(username="lect", password="motdepasse123",
                                        role=Utilisateur.LECTURE, droit_empl_creer=True)
        filtre = FiltreDroit(None, {"droit": ["empl_creer"]}, Utilisateur, self.admin_vue)
        noms = set(filtre.queryset(None, Utilisateur.objects.all())
                   .values_list("username", flat=True))
        self.assertEqual(noms, {"op", "chef"})

    def test_la_page_de_creation_s_ouvre(self):
        self.client.force_login(self.chef)
        r = self.client.get("/admin/wms/utilisateur/add/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Créer et supprimer des emplacements et des racks")
        self.assertContains(r, "Droits — emplacements, racks et modèles")

    def test_la_fiche_d_un_compte_enregistre_les_cases(self):
        op = Utilisateur.objects.create_user(username="op", password="motdepasse123")
        self.client.force_login(self.chef)
        r = self.client.get(f"/admin/wms/utilisateur/{op.pk}/change/")
        self.assertEqual(r.status_code, 200)
        formulaire = r.context["adminform"].form
        donnees = {nom: valeur for nom, valeur in formulaire.initial.items()
                   if valeur is not None and not isinstance(valeur, (list, bool))}
        donnees.update({"username": "op", "role": Utilisateur.OPERATEUR,
                        "date_joined_0": "2026-10-07", "date_joined_1": "08:00:00",
                        "droit_empl_service": "on", "droit_mp": "on", "is_active": "on"})
        donnees.pop("password", None)
        r = self.client.post(f"/admin/wms/utilisateur/{op.pk}/change/", donnees)
        self.assertEqual(r.status_code, 302, getattr(r, "context", {}) and
                         r.context["adminform"].form.errors)
        op.refresh_from_db()
        self.assertEqual({d for d, oui in op.droits_effectifs().items() if oui},
                         {"empl_service", "mp"})
