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
from wms.models import Groupe, Utilisateur


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

    def test_ce_que_dit_la_colonne_selon_le_compte(self):
        caristes = Groupe.objects.get(nom="Caristes")
        cas = [
            ("c1", {"groupe": caristes}, "Ceux du groupe"),
            ("c2", {"groupe": caristes, "droit_mp_seuils": True}, "Ceux du groupe + seuils MP"),
            # Une case que le groupe donne déjà n'est pas « en plus ».
            ("c3", {"groupe": caristes, "droit_cab_ranger": True}, "Ceux du groupe"),
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


class ActionsDeLaListeTest(TestCase):
    """Les actions de la liste des comptes : un groupe d'un geste, pour plusieurs."""

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

    def action_groupe(self, nom):
        groupe = Groupe.objects.get(nom=nom)
        return f"groupe_{groupe.pk}", groupe

    def appliquer_groupe(self, nom, queryset):
        cle, _ = self.action_groupe(nom)
        requete = RequestFactory().post("/admin/wms/utilisateur/")
        requete.user = self.chef
        requete.session = {}
        requete._messages = FallbackStorage(requete)
        fonction = self.admin_vue.get_actions(requete)[cle][0]
        fonction(self.admin_vue, requete, queryset)
        return [str(m) for m in requete._messages]

    def test_un_groupe_remplace_toutes_les_cases(self):
        """Passer un gestionnaire chez les caristes lui RETIRE le reste : une
        action qui garderait ses cases laisserait ses droits d'avant, sans le dire."""
        u = Utilisateur.objects.create_user(username="g", password="motdepasse123",
                                            **valeurs_profil("gestionnaire"))
        self.appliquer_groupe("Caristes", Utilisateur.objects.filter(pk=u.pk))
        u.refresh_from_db()
        self.assertEqual(u.groupe.nom, "Caristes")
        self.assertEqual(u.cases_cochees(), [])
        self.assertEqual({d for d, oui in u.droits_effectifs().items() if oui},
                         PROFILS["cariste"][2])
        self.assertEqual(self.admin_vue.profil(u), "Ceux du groupe")

    def test_plusieurs_comptes_d_un_coup(self):
        for i in range(3):
            Utilisateur.objects.create_user(username=f"n{i}", password="motdepasse123",
                                            role=Utilisateur.LECTURE)
        messages = self.appliquer_groupe("Caristes + MP",
                                         Utilisateur.objects.filter(username__startswith="n"))
        for u in Utilisateur.objects.filter(username__startswith="n"):
            self.assertEqual(u.groupe.nom, "Caristes + MP")
            # Ranger dans un groupe, c'est vouloir qu'il agisse : il quitte la lecture.
            self.assertEqual(u.role, Utilisateur.OPERATEUR)
            self.assertTrue(u.peut("mp"))
        self.assertIn("3 compte(s)", messages[0])

    def test_chaque_groupe_a_son_action(self):
        requete = type("R", (), {"user": self.chef, "GET": {}})()
        nouveau = Groupe.objects.create(nom="Réception MP", droit_mp=True)
        libelles = {v[2] for v in self.admin_vue.get_actions(requete).values()}
        self.assertIn("Mettre dans le groupe « Réception MP »", libelles)
        self.assertIn("Mettre dans le groupe « Caristes »", libelles)
        nouveau.delete()

    def test_retirer_du_groupe_garde_les_droits_en_plus(self):
        u = Utilisateur.objects.create_user(
            username="r", password="motdepasse123",
            groupe=Groupe.objects.get(nom="Caristes"), droit_mp_seuils=True)
        self.appliquer("retirer_du_groupe", Utilisateur.objects.filter(pk=u.pk))
        u.refresh_from_db()
        self.assertIsNone(u.groupe)
        self.assertEqual({d for d, oui in u.droits_effectifs().items() if oui}, {"mp_seuils"})

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
        cle = f"groupe_{Groupe.objects.get(nom='Gestionnaires').pk}"
        r = self.client.post("/admin/wms/utilisateur/", {
            "action": cle, "_selected_action": [lecteur.pk], "index": 0})
        self.assertIn(r.status_code, (200, 302))
        lecteur.refresh_from_db()
        self.assertEqual(lecteur.role, Utilisateur.LECTURE)
        self.assertFalse(any(getattr(lecteur, f"droit_{d}") for d in Utilisateur.DROITS))
        # Et l'action ne lui est même pas proposée.
        actions = self.admin_vue.get_actions(type("R", (), {"user": lecteur, "GET": {}})())
        self.assertNotIn(cle, actions)
        self.assertNotIn("profil_lecture", actions)

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


class GroupesTest(TestCase):
    """Un groupe porte les cases d'une équipe ; la fiche du compte, ses exceptions."""

    def setUp(self):
        self.chef = Utilisateur.objects.create_user(
            username="chef", password="motdepasse123", role=Utilisateur.ADMIN,
            is_staff=True, is_superuser=True)
        self.equipe = Groupe.objects.create(nom="Équipe test", droit_cab_ranger=True,
                                            droit_mp=True)

    def test_le_compte_a_les_droits_du_groupe_plus_les_siens(self):
        u = Utilisateur.objects.create_user(username="u", password="motdepasse123",
                                            groupe=self.equipe, droit_mp_seuils=True)
        self.assertEqual({d for d, oui in u.droits_effectifs().items() if oui},
                         {"cab_ranger", "mp", "mp_seuils"})
        self.assertEqual(u.droits_en_plus(), ["mp_seuils"])

    def test_une_case_changee_sur_le_groupe_vaut_pour_tous_ses_membres(self):
        a = Utilisateur.objects.create_user(username="a", password="motdepasse123",
                                            groupe=self.equipe)
        b = Utilisateur.objects.create_user(username="b", password="motdepasse123",
                                            groupe=self.equipe, droit_mp=True)
        self.equipe.droit_mp = False
        self.equipe.save()
        a = Utilisateur.objects.get(pk=a.pk)
        b = Utilisateur.objects.get(pk=b.pk)
        self.assertFalse(a.peut("mp"))
        self.assertTrue(b.peut("mp"), "son exception lui reste")

    def test_la_lecture_seule_l_emporte_sur_le_groupe(self):
        u = Utilisateur.objects.create_user(username="l", password="motdepasse123",
                                            role=Utilisateur.LECTURE, groupe=self.equipe)
        self.assertFalse(any(u.droits_effectifs().values()))

    def test_le_filtre_par_droit_voit_les_droits_du_groupe(self):
        Utilisateur.objects.create_user(username="membre", password="motdepasse123",
                                        groupe=self.equipe)
        Utilisateur.objects.create_user(username="seul", password="motdepasse123")
        admin_vue = site._registry[Utilisateur]
        filtre = FiltreDroit(None, {"droit": ["mp"]}, Utilisateur, admin_vue)
        noms = set(filtre.queryset(None, Utilisateur.objects.all())
                   .values_list("username", flat=True))
        self.assertEqual(noms, {"membre", "chef"})

    def test_un_groupe_qui_a_des_membres_ne_se_supprime_pas(self):
        from django.db.models import ProtectedError
        Utilisateur.objects.create_user(username="m", password="motdepasse123",
                                        groupe=self.equipe)
        with self.assertRaises(ProtectedError):
            self.equipe.delete()

    def test_la_fiche_du_groupe_a_les_cases_de_la_fiche_du_compte(self):
        """Mêmes cases, même ordre, mêmes sections : c'est la demande."""
        vue_groupe = site._registry[Groupe]
        vue_compte = site._registry[Utilisateur]
        sections = [(titre, s["fields"]) for titre, s in vue_groupe.fieldsets
                    if any(c.startswith("droit_") for c in s["fields"])]
        attendues = [(titre, s["fields"]) for titre, s in vue_compte.fieldsets
                     if any(c.startswith("droit_") for c in s["fields"])]
        self.assertEqual(sections, attendues)

    def test_les_pages_des_groupes_s_ouvrent_en_francais(self):
        Utilisateur.objects.create_user(username="m", password="motdepasse123",
                                        nom="Martin", groupe=self.equipe)
        self.client.force_login(self.chef)
        r = self.client.get("/admin/wms/groupe/")
        self.assertContains(r, "Équipe test")
        self.assertContains(r, "ranger, MP")
        r = self.client.get(f"/admin/wms/groupe/{self.equipe.pk}/change/")
        self.assertContains(r, "Entrer et ranger des cabines")
        self.assertContains(r, "m (Martin)")
        self.assertEqual(self.client.get("/admin/wms/groupe/add/").status_code, 200)

    def test_un_groupe_se_cree_depuis_l_administration(self):
        self.client.force_login(self.chef)
        r = self.client.post("/admin/wms/groupe/add/", {
            "nom": "Réception MP", "description": "", "droit_mp": "on"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Groupe.objects.get(nom="Réception MP").cases_cochees(), ["mp"])

    def test_les_groupes_de_django_ne_sont_plus_au_menu(self):
        """Deux « Groupes » dans le menu, l'un en anglais : le mauvais était
        choisi une fois sur deux."""
        from django.contrib.auth.models import Group
        self.assertNotIn(Group, site._registry)
        vue = site._registry[Utilisateur]
        champs = [c for _, s in vue.fieldsets for c in s["fields"]]
        self.assertNotIn("groups", champs)
        self.assertIn("groupe", champs)

    def test_les_permissions_de_django_sont_dites_en_francais(self):
        from django.contrib.auth.models import Permission

        from wms.admin import libelle_permission
        p = Permission.objects.get(codename="change_cabine")
        self.assertEqual(libelle_permission(p), "Cabines — modifier")

    def test_la_fiche_du_compte_dit_ce_que_le_groupe_donne(self):
        u = Utilisateur.objects.create_user(username="u", password="motdepasse123",
                                            groupe=self.equipe)
        texte = site._registry[Utilisateur].droits_recus(u)
        self.assertIn("Équipe test", texte)
        self.assertIn("entrer et ranger des cabines", texte)

    def test_la_migration_range_les_comptes_qui_avaient_un_profil(self):
        """Ses droits effectifs ne changent pas d'une case ; un compte sur mesure
        n'est pas touché."""
        import importlib

        from django.apps import apps
        migration = importlib.import_module("wms.migrations.0030_groupes")
        cariste = Utilisateur.objects.create_user(username="ca", password="motdepasse123",
                                                  **valeurs_profil("cariste"))
        sur_mesure = Utilisateur.objects.create_user(username="sm", password="motdepasse123",
                                                     droit_cab_ranger=True, droit_mp=True)
        avant = {u.pk: u.droits_effectifs() for u in (cariste, sur_mesure)}
        migration.creer_groupes(apps, None)
        cariste = Utilisateur.objects.get(pk=cariste.pk)
        sur_mesure = Utilisateur.objects.get(pk=sur_mesure.pk)
        self.assertEqual(cariste.groupe.nom, "Caristes")
        self.assertEqual(cariste.cases_cochees(), [])
        self.assertIsNone(sur_mesure.groupe)
        for u in (cariste, sur_mesure):
            self.assertEqual(u.droits_effectifs(), avant[u.pk])
