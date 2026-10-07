"""Une case, un geste : chaque case ouvre le sien, et aucune autre ne l'ouvre.

La demande d'origine : « Je ne veux pas qu'il puisse créer ou supprimer les
emplacements » — d'un opérateur à qui l'on confie pourtant les réglages, la
mise hors service et les places condamnées. Les trois cases d'avant ouvraient
chacune un bloc entier ; il fallait pouvoir « donner les autorisations en
souplesse, en cochant les cases de ce qu'il peut faire ».

Ce fichier vérifie la correspondance geste par geste, dans les deux sens :

- un opérateur qui n'a QUE la case du geste passe le contrôle des droits (il
  peut encore être refusé pour une autre raison — un 400 —, jamais par un 403) ;
- un opérateur qui a TOUTES les autres cases est refusé (403), et le refus
  nomme la case qui manque.

`StructureTest` relie le tableau à l'API : toute écriture exposée par le
routeur (actions standard et @action autres que GET) doit y figurer avec sa
case — ou dans `SANS_CASE`, avec la raison —, chaque vue doit exiger la case
du tableau, et chaque case doit commander au moins un geste.
"""
import itertools

from rest_framework.test import APIClient, APITestCase

from wms import services_cabines, services_mp
from wms.models import ArticleMP, Cabine, Emplacement, Utilisateur
from wms.permissions import DroitWMS
from wms.urls import router

COMPTEUR = itertools.count(10)


class Monde:
    """Fabrique des objets neufs pour chaque essai : un geste réussi peut
    supprimer ou envoyer ce qu'il touche, le suivant ne doit pas en hériter."""

    def __init__(self, auteur):
        self.auteur = auteur

    def n(self):
        return next(COMPTEUR)

    def emplacement(self):
        return Emplacement.objects.create(code=f"T{self.n()}")

    def emplacement_mp(self):
        return Emplacement.objects.create(code=f"V{self.n()}", usage=Emplacement.MP_VITRAGE)

    def article(self):
        return ArticleMP.objects.get(code="VITR.470X2072.BP")

    def numero(self):
        k = self.n()
        return f"77_{k // 100 % 100:02d}_{k % 100:02d}"

    def cabine(self):
        # Aucun fichier de production dans ces essais : la saisie est libre.
        return services_cabines.creer_cabine(numero=self.numero(), chantier="000111",
                                             utilisateur=self.auteur)

    def cabine_envoyee(self):
        c = self.cabine()
        return services_cabines.envoyer(cabine=c, utilisateur=self.auteur, note="départ")

    def ligne_mp(self):
        return services_mp.entrer(emplacement=self.emplacement_mp(), place="G",
                                  article=self.article(), quantite=5, utilisateur=self.auteur)


#: (geste, case exigée, action de l'API, requête). L'action est
#: (préfixe du routeur, nom de l'action) ; la requête est construite sur des
#: objets neufs.
GESTES = [
    # Emplacements, racks et modèles
    ("créer un emplacement", "empl_creer", ("emplacements", "create"),
     lambda m: ("post", "/api/emplacements/", {"code": f"N{m.n()}"})),
    ("supprimer un emplacement", "empl_creer", ("emplacements", "destroy"),
     lambda m: ("delete", f"/api/emplacements/{m.emplacement().id}/", None)),
    ("créer un rack", "empl_creer", ("emplacements", "generer"),
     lambda m: ("post", "/api/emplacements/generer/",
                {"prefixe": f"R{m.n()}", "debut": 10, "colonnes": 2, "apercu": True})),
    ("supprimer une sélection", "empl_creer", ("emplacements", "supprimer_lot"),
     lambda m: ("post", "/api/emplacements/supprimer-lot/", {"ids": [m.emplacement().id]})),
    ("supprimer un rack", "empl_creer", ("emplacements", "supprimer_rack"),
     lambda m: ("post", "/api/emplacements/supprimer-rack/", {"rack": "QQ"})),
    ("régler un emplacement", "empl_regler", ("emplacements", "partial_update"),
     lambda m: ("patch", f"/api/emplacements/{m.emplacement().id}/", {"description": "x"})),
    ("régler un emplacement en entier", "empl_regler", ("emplacements", "update"),
     lambda m: ("put", f"/api/emplacements/{m.emplacement().id}/", {"code": f"P{m.n()}"})),
    ("ce que rangent des emplacements", "empl_regler", ("emplacements", "usage"),
     lambda m: ("post", "/api/emplacements/usage/",
                {"ids": [m.emplacement().id], "choix": "vitrage", "apercu": True})),
    ("les codes acceptés", "empl_regler", ("emplacements", "codes"),
     lambda m: ("post", "/api/emplacements/codes/",
                {"ids": [m.emplacement_mp().id], "articles": [m.article().id],
                 "mode": "remplacer", "apercu": True})),
    ("mettre hors service", "empl_service", ("emplacements", "activation"),
     lambda m: ("post", f"/api/emplacements/{m.emplacement().id}/activation/",
                {"actif": False, "motif": "rack démonté"})),
    ("condamner une place", "empl_service", ("emplacements", "place"),
     lambda m: ("post", f"/api/emplacements/{m.emplacement().id}/place/",
                {"place": "G", "condamnee": True, "motif": "pilier"})),
    ("régler un modèle", "modeles", ("modeles-cabine", "regler"),
     lambda m: ("post", "/api/modeles-cabine/regler/", {"nom": "DUO", "grand": True})),
    # Cabines
    ("entrer une cabine", "cab_ranger", ("cabines", "create"),
     lambda m: ("post", "/api/cabines/", {"numero": m.numero(), "chantier": "000111"})),
    ("ranger une cabine", "cab_ranger", ("cabines", "ranger"),
     lambda m: ("post", f"/api/cabines/{m.cabine().id}/ranger/",
                {"emplacement": m.emplacement().id, "place": "G"})),
    ("changer le statut", "cab_statut", ("cabines", "statut"),
     lambda m: ("post", f"/api/cabines/{m.cabine().id}/statut/",
                {"statut": Cabine.QUARANTAINE, "motif": "rayure"})),
    ("affecter un chantier", "cab_envoyer", ("cabines", "chantier"),
     lambda m: ("post", f"/api/cabines/{m.cabine().id}/chantier/", {"chantier": "000222"})),
    ("envoyer une cabine", "cab_envoyer", ("cabines", "envoyer"),
     lambda m: ("post", f"/api/cabines/{m.cabine().id}/envoyer/", {"note": "départ"})),
    ("remettre en stock", "cab_envoyer", ("cabines", "reprendre"),
     lambda m: ("post", f"/api/cabines/{m.cabine_envoyee().id}/reprendre/", {})),
    ("corriger une fiche", "cab_corriger", ("cabines", "partial_update"),
     lambda m: ("patch", f"/api/cabines/{m.cabine().id}/", {"modele": "DUO"})),
    ("corriger une fiche en entier", "cab_corriger", ("cabines", "update"),
     lambda m: ("put", f"/api/cabines/{m.cabine().id}/",
                {"numero": m.numero(), "chantier": "000111"})),
    ("supprimer une cabine", "cab_corriger", ("cabines", "destroy"),
     lambda m: ("delete", f"/api/cabines/{m.cabine().id}/?force=1", None)),
    # Fichier de production — sans fichier joint : le refus de droit passe avant.
    ("analyser le fichier de production", "production", ("cabines-attendues", "analyser"),
     lambda m: ("post", "/api/cabines-attendues/analyser/", {})),
    ("importer le fichier de production", "production", ("cabines-attendues", "importer"),
     lambda m: ("post", "/api/cabines-attendues/importer/", {})),
    # Matières premières
    ("entrer des MP", "mp", ("mp", "entrer"),
     lambda m: ("post", "/api/mp/entrer/", {"emplacement": m.emplacement_mp().id, "place": "G",
                                            "article": m.article().id, "quantite": 1})),
    ("sortir des MP", "mp", ("mp", "sortir"),
     lambda m: ("post", "/api/mp/sortir/", {"ligne": m.ligne_mp().id, "quantite": 1})),
    ("déplacer des MP", "mp", ("mp", "deplacer"),
     lambda m: ("post", "/api/mp/deplacer/",
                {"lignes": [{"ligne": m.ligne_mp().id, "quantite": 1}],
                 "emplacement": m.emplacement_mp().id, "place": "D"})),
    ("régler les seuils d'alerte", "mp_seuils", ("mp", "seuils"),
     lambda m: ("post", "/api/mp/seuils/", {"articles": [m.article().id], "seuil": 5})),
]

#: Les écritures ouvertes à tout compte, et pourquoi : elles n'écrivent rien.
SANS_CASE = {("cabines", "lire_fiche")}    # lire la photo d'une fiche


class UneCaseUnGesteTest(APITestCase):
    def setUp(self):
        self.chef = Utilisateur.objects.create_user(username="chef", password="motdepasse123",
                                                    role=Utilisateur.ADMIN)
        self.monde = Monde(self.chef)

    def client_avec(self, droits):
        u = Utilisateur.objects.create_user(
            username=f"op{next(COMPTEUR)}", password="motdepasse123",
            role=Utilisateur.OPERATEUR, **{f"droit_{d}": True for d in droits})
        client = APIClient()
        client.force_authenticate(u)
        return client

    def envoyer(self, client, geste):
        methode, url, corps = geste(self.monde)
        return getattr(client, methode)(url, corps, format="json")

    def test_la_case_seule_suffit(self):
        for nom, droit, _, geste in GESTES:
            with self.subTest(geste=nom, case=droit):
                r = self.envoyer(self.client_avec([droit]), geste)
                self.assertNotIn(r.status_code, (401, 403), getattr(r, "data", None))

    def test_toutes_les_autres_cases_ne_suffisent_pas(self):
        for nom, droit, _, geste in GESTES:
            with self.subTest(geste=nom, case=droit):
                autres = [d for d in Utilisateur.DROITS if d != droit]
                r = self.envoyer(self.client_avec(autres), geste)
                self.assertEqual(r.status_code, 403, getattr(r, "data", None))
                # Le refus nomme la case : l'administrateur sait laquelle cocher.
                self.assertIn(Utilisateur.libelle_droit(droit), str(r.data))

    def test_lire_une_fiche_n_exige_aucune_case(self):
        """Lire la photo d'une fiche n'écrit rien : même sans case, on passe le
        contrôle des droits — et c'est l'absence de photo qui est refusée."""
        r = self.client_avec([]).post("/api/cabines/lire-fiche/", {}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_un_operateur_qui_regle_ne_cree_ni_ne_supprime(self):
        """Le cas qui a tout déclenché, dit en une phrase."""
        client = self.client_avec(["empl_regler", "empl_service"])
        e = self.monde.emplacement()
        self.assertEqual(client.patch(f"/api/emplacements/{e.id}/", {"description": "allée 3"},
                                      format="json").status_code, 200)
        self.assertEqual(client.post(f"/api/emplacements/{e.id}/place/",
                                     {"place": "G", "condamnee": True, "motif": "pilier"},
                                     format="json").status_code, 200)
        self.assertEqual(client.post("/api/emplacements/", {"code": "NEUF1"},
                                     format="json").status_code, 403)
        self.assertEqual(client.delete(f"/api/emplacements/{e.id}/").status_code, 403)
        self.assertTrue(Emplacement.objects.filter(pk=e.pk).exists())


class StructureTest(APITestCase):
    """Le tableau ci-dessus et l'API ne doivent pas diverger en silence."""

    @staticmethod
    def ecritures_de_l_api():
        """(préfixe, action) de toute écriture exposée par le routeur : les
        actions standard qu'a la vue, et ses @action autres que GET."""
        ecritures = set()
        for prefixe, vue, _ in router.registry:
            for action in ("create", "update", "partial_update", "destroy"):
                if hasattr(vue, action):
                    ecritures.add((prefixe, action))
            for extra in vue.get_extra_actions():
                if set(extra.mapping) - {"get", "head", "options"}:
                    ecritures.add((prefixe, extra.__name__))
        return ecritures

    def test_toute_ecriture_de_l_api_est_au_tableau(self):
        """Une action ajoutée à l'API sans case réfléchie fait échouer ce test :
        elle entre au tableau GESTES (avec sa case), ou à SANS_CASE."""
        au_tableau = {action for _, _, action, _ in GESTES}
        self.assertEqual(self.ecritures_de_l_api(), au_tableau | SANS_CASE)

    def test_chaque_vue_exige_la_case_du_tableau(self):
        vues = {prefixe: vue for prefixe, vue, _ in router.registry}
        for nom, droit, (prefixe, action), _ in GESTES:
            with self.subTest(geste=nom):
                vue = vues[prefixe]()
                vue.action = action
                self.assertEqual(DroitWMS.droit_requis(vue), droit)
        for prefixe, action in SANS_CASE:
            vue = vues[prefixe]()
            vue.action = action
            self.assertIsNone(DroitWMS.droit_requis(vue))

    def test_chaque_case_commande_quelque_chose(self):
        """« Enregistrer une cabine absente du fichier » est vérifiée par le
        service des cabines, pas par une vue : elle est la seule exception."""
        self.assertEqual({droit for _, droit, _, _ in GESTES} | {"hors_fichier"},
                         set(Utilisateur.DROITS))

    def test_l_administrateur_passe_partout(self):
        chef = Utilisateur.objects.create_user(username="chef2", password="motdepasse123",
                                               role=Utilisateur.ADMIN)
        self.assertTrue(all(chef.peut(d) for d in Utilisateur.DROITS))


class AdministrationSuitLesCasesTest(APITestCase):
    """L'administration de Django a ses propres permissions. Pour les
    emplacements, elle exige AUSSI les cases du WMS pour créer et régler — et
    elle ne supprime rien : la suppression vit dans l'application, avec ses
    refus, sa confirmation et sa trace."""

    def equipe(self, permissions, **cases):
        from django.contrib.auth.models import Permission
        u = Utilisateur.objects.create_user(
            username=f"eq{next(COMPTEUR)}", password="motdepasse123",
            role=Utilisateur.OPERATEUR, is_staff=True, **{f"droit_{c}": True for c in cases})
        u.user_permissions.set(Permission.objects.filter(
            content_type__app_label="wms", codename__in=permissions))
        self.client.force_login(u)
        return u

    def test_sans_la_case_les_permissions_django_ne_suffisent_pas(self):
        self.equipe(["add_emplacement", "change_emplacement", "delete_emplacement",
                     "view_emplacement"], empl_regler=True)
        e = Emplacement.objects.create(code="ADM1")
        self.assertEqual(self.client.get("/admin/wms/emplacement/add/").status_code, 403)
        self.assertEqual(self.client.post(f"/admin/wms/emplacement/{e.pk}/delete/",
                                          {"post": "yes"}).status_code, 403)
        self.assertTrue(Emplacement.objects.filter(pk=e.pk).exists())

    def test_l_administration_ne_supprime_aucun_emplacement(self):
        """Superutilisateur compris : la suppression de Django contournait les
        refus de l'application et détachait en silence les cabines rangées."""
        chef = Utilisateur.objects.create_user(
            username="chef3", password="motdepasse123", role=Utilisateur.ADMIN,
            is_staff=True, is_superuser=True)
        self.client.force_login(chef)
        vide = Emplacement.objects.create(code="ADM2")
        occupe = Emplacement.objects.create(code="ADM3")
        c = services_cabines.creer_cabine(numero="66_00_01", chantier="000111",
                                          utilisateur=chef)
        services_cabines.ranger(cabine=c, emplacement=occupe, place="G", utilisateur=chef)
        for e in (vide, occupe):
            self.assertEqual(self.client.post(f"/admin/wms/emplacement/{e.pk}/delete/",
                                              {"post": "yes"}).status_code, 403)
        r = self.client.post("/admin/wms/emplacement/", {
            "action": "delete_selected", "_selected_action": [vide.pk, occupe.pk],
            "post": "yes"})
        self.assertIn(r.status_code, (200, 302))
        self.assertEqual(Emplacement.objects.filter(pk__in=[vide.pk, occupe.pk]).count(), 2)
        self.assertEqual(self.client.get("/admin/wms/emplacement/add/").status_code, 200,
                         "créer reste possible pour qui a la case")

    def test_regler_dans_l_administration_demande_la_case(self):
        self.equipe(["change_emplacement", "view_emplacement"], empl_creer=True)
        e = Emplacement.objects.create(code="ADM4")
        r = self.client.post(f"/admin/wms/emplacement/{e.pk}/change/",
                             {"code": "ADM4", "usage": "cabines", "mode_places": "gd"})
        self.assertEqual(r.status_code, 403, "consultation seule sans « régler »")
