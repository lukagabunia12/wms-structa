"""La migration 0028 reporte les trois anciennes cases sur les douze nouvelles.

Rejouée pour de vrai : la base revient à 0027, des comptes y sont créés avec
les anciennes cases, puis on avance jusqu'à 0029 — et on revient. Chaque
compte doit garder exactement ce qu'il pouvait faire, à une exception voulue :
« créer et supprimer des emplacements et des racks », que personne ne reçoit
d'office.
"""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

AVANT = [("wms", "0027_mp_reglages_alertes_deplacement")]
APRES = [("wms", "0029_retrait_anciens_droits")]
CABINES = {"cab_ranger", "cab_statut", "cab_envoyer", "cab_corriger"}


class ReportDesDroitsTest(TransactionTestCase):
    # Les codes MP et les modèles semés par les migrations reviennent après le test.
    serialized_rollback = True

    def migrer(self, cible):
        executeur = MigrationExecutor(connection)
        executeur.migrate(cible)
        return MigrationExecutor(connection).loader.project_state(cible).apps

    def tearDown(self):
        executeur = MigrationExecutor(connection)
        self.migrer(executeur.loader.graph.leaf_nodes())
        super().tearDown()

    def test_aller_et_retour(self):
        anciens = self.migrer(AVANT)
        U = anciens.get_model("wms", "Utilisateur")
        for nom, role, cab, ref, mp in [("cariste", "operateur", 1, 0, 0),
                                        ("cariste_mp", "operateur", 1, 0, 1),
                                        ("gestion", "operateur", 1, 1, 1),
                                        ("ref_seul", "operateur", 0, 1, 0),
                                        ("mp_seul", "operateur", 0, 0, 1),
                                        ("lecteur", "lecture", 1, 1, 0),
                                        ("chef", "admin", 0, 0, 0)]:
            U.objects.create(username=nom, role=role, droit_cab=bool(cab),
                             droit_ref=bool(ref), droit_mp=bool(mp))

        nouveaux = self.migrer(APRES)
        U = nouveaux.get_model("wms", "Utilisateur")
        champs = [f.name for f in U._meta.fields if f.name.startswith("droit_")]
        self.assertNotIn("droit_cab", champs)
        self.assertNotIn("droit_ref", champs)

        def cases(nom):
            u = U.objects.get(username=nom)
            return {c.removeprefix("droit_") for c in champs if getattr(u, c)}

        reglages = {"empl_service", "empl_regler", "modeles", "mp_seuils"}
        self.assertEqual(cases("cariste"), CABINES)
        self.assertEqual(cases("cariste_mp"), CABINES | {"mp"})
        self.assertEqual(cases("gestion"), CABINES | {"mp"} | reglages)
        self.assertEqual(cases("ref_seul"), reglages)
        self.assertEqual(cases("mp_seul"), {"mp"})
        # Les cases d'un compte en lecture seule sont reportées, et restent
        # sans effet tant que son rôle ne change pas.
        self.assertEqual(cases("lecteur"), CABINES | reglages)
        for nom in ("cariste", "gestion", "ref_seul", "lecteur", "chef"):
            self.assertNotIn("empl_creer", cases(nom), "personne ne la reçoit d'office")
            self.assertNotIn("production", cases(nom))
            self.assertNotIn("hors_fichier", cases(nom))

        anciens = self.migrer(AVANT)
        U = anciens.get_model("wms", "Utilisateur")
        retour = {u.username: (u.droit_cab, u.droit_ref, u.droit_mp) for u in U.objects.all()}
        self.assertEqual(retour["cariste"], (True, False, False))
        self.assertEqual(retour["gestion"], (True, True, True))
        self.assertEqual(retour["ref_seul"], (False, True, False))
        self.assertEqual(retour["mp_seul"], (False, False, True))
