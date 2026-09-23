"""Deux caristes, la même place, la même seconde.

`ranger()` contrôle que la place est libre, puis écrit. Entre les deux, une
autre transaction peut s'y glisser : `select_for_update()` ne l'empêche pas,
puisqu'il n'y a pas encore de ligne à verrouiller.

Ce qui est vérifié ici, et dans cet ordre :

1. la DONNÉE est protégée — la base refuse elle-même deux cabines sur une même
   place. C'est la garantie qui compte, et elle ne dépend d'aucun contrôle
   applicatif ;
2. l'OPÉRATEUR reçoit une phrase, pas une erreur serveur. La contrainte violée
   remontait en `IntegrityError`, que la vue ne traduit pas : devant son rack,
   le cariste lisait une erreur brute au lieu de « la place vient d'être prise ».

Le second essai force l'échec de la contrainte au moment de l'écriture plutôt
que de simuler une vraie concurrence : deux fils d'exécution sur une base
d'essai ne prouveraient rien de reproductible. Ce qu'on vérifie est la
TRADUCTION de l'échec, et elle se teste exactement ainsi.
"""
from unittest import mock

from django.db import IntegrityError, transaction
from django.db.utils import IntegrityError as ErreurIntegrite
from rest_framework.test import APITestCase

from wms import services_cabines
from wms.models import (Cabine, CabineAttendue, Emplacement, ModeleCabine,
                        Occupation, Utilisateur, Zone)


class CourseSurUnePlaceTest(APITestCase):
    def setUp(self):
        self.user = Utilisateur.objects.create_user(
            username="op", password="secret123", role=Utilisateur.ADMIN, nom="Luka G.")
        self.client.force_authenticate(user=self.user)
        self.zone = Zone.objects.create(nom="Rack A", ordre=1)
        self.emp = Emplacement.objects.create(code="A001", zone_cabine=self.zone)
        ModeleCabine.objects.update_or_create(
            cle="DUO", defaults={"nom": "DUO", "grand": False})

    def cabine(self, numero):
        CabineAttendue.objects.create(numero=numero, modele="DUO", chantier="000123")
        return services_cabines.creer_cabine(
            numero=numero, chantier="000123", modele="DUO", utilisateur=self.user)

    def test_la_base_refuse_elle_meme_deux_cabines_sur_une_place(self):
        """La garantie de fond : elle ne dépend d'aucun contrôle applicatif."""
        une = self.cabine("00_00_01")
        deux = self.cabine("00_00_02")
        services_cabines.ranger(cabine=une, emplacement=self.emp,
                                place=Occupation.GAUCHE, utilisateur=self.user)
        occupation = deux.occupations.first()
        occupation.emplacement = self.emp
        occupation.place = Occupation.GAUCHE
        with self.assertRaises(ErreurIntegrite):
            with transaction.atomic():
                occupation.save(update_fields=["emplacement", "place"])

    def test_la_place_prise_entre_temps_donne_une_phrase_pas_une_erreur_500(self):
        cabine = self.cabine("00_00_03")
        vrai_save = Occupation.save

        def save_qui_perd_la_course(self, *args, **kwargs):
            # La place a été prise juste après le contrôle : c'est ce que la
            # base répond, et c'est ce que le service doit savoir traduire.
            if kwargs.get("update_fields") == ["emplacement", "place"]:
                raise IntegrityError(
                    'UNIQUE constraint failed: place_occupee_par_une_seule_cabine')
            return vrai_save(self, *args, **kwargs)

        with mock.patch.object(Occupation, "save", save_qui_perd_la_course):
            with self.assertRaises(services_cabines.ErreurCabine) as bilan:
                services_cabines.ranger(cabine=cabine, emplacement=self.emp,
                                        place=Occupation.GAUCHE, utilisateur=self.user)
        message = " ".join(bilan.exception.messages)
        self.assertIn("vient d'être prise", message)
        self.assertIn("A001", message, "le message doit nommer l'emplacement")
        # Et rien n'a été écrit : ni rangement, ni ligne de journal.
        cabine.refresh_from_db()
        self.assertEqual(cabine.position, "")

    def test_l_api_repond_400_et_non_500(self):
        """Ce que voit le cariste : un message, dans le même format que les autres refus."""
        cabine = self.cabine("00_00_04")
        vrai_save = Occupation.save

        def save_qui_perd_la_course(self, *args, **kwargs):
            if kwargs.get("update_fields") == ["emplacement", "place"]:
                raise IntegrityError("UNIQUE constraint failed")
            return vrai_save(self, *args, **kwargs)

        with mock.patch.object(Occupation, "save", save_qui_perd_la_course):
            r = self.client.post(f"/api/cabines/{cabine.id}/ranger/",
                                 {"emplacement": self.emp.id,
                                  "place": Occupation.GAUCHE}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("vient d'être prise", " ".join(r.data["erreur"]))
        self.assertEqual(Cabine.objects.get(pk=cabine.pk).position, "")
