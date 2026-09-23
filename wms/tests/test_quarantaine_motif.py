"""Le motif de quarantaine doit se lire, pas se chercher.

Le motif est écrit au journal — c'est la bonne place : il en faut un par
changement, pas un seul champ écrasé à chaque fois. Mais il n'était QUE là.
Pour savoir ce qui bloque une cabine, il fallait ouvrir sa fiche, dérouler
l'historique et repérer la bonne ligne parmi les entrées, les retraits et les
changements de statut. Devant un rack, personne ne le fait.

Ce que le champ `quarantaine` doit garantir, et qui est vérifié ici :

- sur la fiche : le motif, la date, et qui a posé la quarantaine ;
- dans la LISTE (« En quarantaine : 3 ») : le motif sur chaque ligne, sans
  qu'une liste de cinquante cabines coûte cinquante requêtes — c'est le
  comptage de requêtes plus bas, et c'est lui qui empêchera qu'on
  « simplifie » un jour l'annotation en une boucle ;
- une fois la quarantaine LEVÉE, le motif reste lisible : « pourquoi cette
  cabine a-t-elle été bloquée le mois dernier ? » se demande aussi, et la levée
  ne doit pas effacer la raison.
"""
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from wms import services_cabines
from wms.models import (Cabine, CabineAttendue, Emplacement, ModeleCabine,
                        Utilisateur, Zone)


class BaseQuarantaine(APITestCase):
    def setUp(self):
        self.user = Utilisateur.objects.create_user(
            username="op", password="secret123", role=Utilisateur.ADMIN, nom="Luka G.")
        self.client.force_authenticate(user=self.user)
        self.zone = Zone.objects.create(nom="Rack A", ordre=1)
        self.emp = Emplacement.objects.create(code="C001", zone_cabine=self.zone)
        ModeleCabine.objects.update_or_create(
            cle="DUO", defaults={"nom": "DUO", "grand": False})

    def cabine(self, numero="00_00_01"):
        CabineAttendue.objects.create(numero=numero, modele="DUO", chantier="000123")
        return services_cabines.creer_cabine(
            numero=numero, chantier="000123", modele="DUO", utilisateur=self.user)

    def bloquer(self, cabine, motif):
        services_cabines.changer_statut(cabine=cabine, statut=Cabine.QUARANTAINE,
                                        utilisateur=self.user, motif=motif)

    def fiche(self, cabine):
        r = self.client.get(f"/api/cabines/{cabine.id}/")
        self.assertEqual(r.status_code, 200)
        return r.data


class MotifSurLaFicheTest(BaseQuarantaine):
    def test_la_fiche_dit_pourquoi_quand_et_par_qui(self):
        cab = self.cabine()
        self.bloquer(cab, "rayure sur la paroi gauche")

        quarantaine = self.fiche(cab)["quarantaine"]
        self.assertEqual(quarantaine["motif"], "rayure sur la paroi gauche")
        self.assertTrue(quarantaine["active"])
        self.assertEqual(quarantaine["par"], "Luka G.")
        self.assertIsNotNone(quarantaine["date"])

    def test_une_cabine_jamais_bloquee_n_a_pas_de_bloc(self):
        """Sinon la fiche porterait un cadre vide, et on le lirait comme un défaut."""
        self.assertIsNone(self.fiche(self.cabine())["quarantaine"])

    def test_apres_la_levee_le_motif_reste_lisible(self):
        cab = self.cabine()
        self.bloquer(cab, "joint de porte à remplacer")
        services_cabines.changer_statut(
            cabine=cab, statut=Cabine.LIBRE, utilisateur=self.user,
            motif="joint remplacé, contrôle refait")

        quarantaine = self.fiche(cab)["quarantaine"]
        # Le motif rendu est celui de la MISE en quarantaine, pas celui de la
        # levée : c'est le défaut qu'on cherche des semaines plus tard.
        self.assertEqual(quarantaine["motif"], "joint de porte à remplacer")
        self.assertFalse(quarantaine["active"])

    def test_la_derniere_quarantaine_l_emporte(self):
        """Une cabine peut retomber en quarantaine : c'est le motif courant qui compte."""
        cab = self.cabine()
        for motif in ("rayure sur la paroi", "fuite au robinet"):
            self.bloquer(cab, motif)
            services_cabines.changer_statut(cabine=cab, statut=Cabine.LIBRE,
                                            utilisateur=self.user)
        self.bloquer(cab, "vitre fêlée")
        self.assertEqual(self.fiche(cab)["quarantaine"]["motif"], "vitre fêlée")

    def test_le_motif_survit_a_la_suppression_du_compte(self):
        """« par » est recopié à l'écriture : un compte supprimé n'efface pas qui a fait quoi."""
        cab = self.cabine()
        self.bloquer(cab, "panneau enfoncé")
        autre = Utilisateur.objects.create_user(
            username="chef", password="secret123", role=Utilisateur.ADMIN)
        self.client.force_authenticate(user=autre)
        self.user.delete()

        quarantaine = self.fiche(cab)["quarantaine"]
        self.assertEqual(quarantaine["motif"], "panneau enfoncé")
        self.assertEqual(quarantaine["par"], "Luka G.")


class MotifDansLaListeTest(BaseQuarantaine):
    def bloquer_plusieurs(self, depuis, jusqu_a):
        """Des cabines bloquées, chacune avec SON motif — pas le même partout."""
        attendus = {}
        for i in range(depuis, jusqu_a):
            cab = self.cabine(numero=f"00_00_{i:02d}")
            self.bloquer(cab, f"défaut n°{i}")
            attendus[cab.numero] = f"défaut n°{i}"
        return attendus

    def test_la_liste_porte_le_motif_de_chaque_cabine(self):
        attendus = self.bloquer_plusieurs(1, 4)
        r = self.client.get("/api/cabines/?statut=quarantaine")
        self.assertEqual(r.status_code, 200)
        lus = {c["numero"]: c["quarantaine"]["motif"] for c in r.data["results"]}
        self.assertEqual(lus, attendus)

    def test_une_cabine_conforme_n_a_rien_a_montrer_dans_la_liste(self):
        self.cabine()
        r = self.client.get("/api/cabines/")
        self.assertIsNone(r.data["results"][0]["quarantaine"])

    def test_la_liste_ne_coute_pas_une_requete_par_cabine(self):
        """Le contrôle qui protège l'annotation.

        Le motif se lit dans le journal : la façon naïve est une requête par
        ligne, et une liste de cinquante cabines devient injouable sur le
        réseau de l'entrepôt. Une sous-requête corrélée le rend en une fois — et
        ce comptage est là pour qu'une « simplification » future s'en souvienne.
        """
        self.bloquer_plusieurs(1, 4)
        avec_trois = self._requetes_pour_la_liste()
        self.bloquer_plusieurs(4, 12)
        self.assertEqual(self._requetes_pour_la_liste(), avec_trois,
                         "le nombre de requêtes suit le nombre de cabines : "
                         "l'annotation a été remplacée par une boucle")

    def _requetes_pour_la_liste(self):
        with CaptureQueriesContext(connection) as capture:
            r = self.client.get("/api/cabines/?statut=quarantaine")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.data["results"])
        return len(capture.captured_queries)
