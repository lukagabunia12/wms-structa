"""Le coût d'un écran ne doit pas suivre le nombre de lignes qu'il affiche.

Un écran qui interroge la base une fois par ligne marche parfaitement sur les
neuf cabines d'une base d'essai, et devient injouable sur les deux mille du
parc réel — au poste, sur le Wi-Fi de l'entrepôt, avec un téléphone. Le défaut
n'apparaît jamais en développement : il apparaît le jour de la mise en service.

Ces contrôles ne fixent aucun nombre absolu — il changerait à chaque
`select_related` ajouté, et on finirait par le mettre à jour sans réfléchir.
Ils vérifient la seule chose qui compte : que le nombre de requêtes soit le
MÊME avec dix lignes qu'avec une. Une boucle qui interroge la base le fait
grandir, et le contrôle tombe.

Trois écrans sont protégés ici parce qu'ils sont les trois plus ouverts de la
journée : le parc, les emplacements, et le journal.
"""
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from wms import services_cabines
from wms.models import (Cabine, CabineAttendue, Emplacement, ModeleCabine,
                        Occupation, Utilisateur, Zone)


class CoutDesEcransTest(APITestCase):
    def setUp(self):
        self.user = Utilisateur.objects.create_user(
            username="op", password="secret123", role=Utilisateur.ADMIN, nom="Luka G.")
        self.client.force_authenticate(user=self.user)
        self.zone = Zone.objects.create(nom="Rack A", ordre=1)
        ModeleCabine.objects.update_or_create(
            cle="DUO", defaults={"nom": "DUO", "grand": False})
        self.cree = 0

    def peupler(self, combien):
        """Des cabines rangées, avec journal : le cas coûteux, pas le cas vide."""
        for _ in range(combien):
            self.cree += 1
            numero = f"00_00_{self.cree:03d}"
            emplacement = Emplacement.objects.create(
                code=f"E{self.cree:03d}", zone_cabine=self.zone)
            CabineAttendue.objects.create(numero=numero, modele="DUO",
                                          chantier="000123")
            cabine = services_cabines.creer_cabine(
                numero=numero, chantier="000123", modele="DUO",
                utilisateur=self.user)
            services_cabines.ranger(cabine=cabine, emplacement=emplacement,
                                    place=Occupation.GAUCHE, utilisateur=self.user)
            services_cabines.changer_statut(
                cabine=cabine, statut=Cabine.QUARANTAINE, utilisateur=self.user,
                motif="rayure sur la paroi")

    def requetes(self, url):
        with CaptureQueriesContext(connection) as capture:
            reponse = self.client.get(url)
            self.assertEqual(reponse.status_code, 200, url)
        return len(capture.captured_queries)

    def verifier(self, url, ecran):
        self.peupler(2)
        avec_deux = self.requetes(url)
        self.peupler(10)
        avec_douze = self.requetes(url)
        self.assertEqual(
            avec_douze, avec_deux,
            f"{ecran} : {avec_deux} requêtes pour 2 cabines, {avec_douze} pour 12. "
            "Le coût suit le nombre de lignes — il y a une requête par ligne "
            "quelque part.")

    def test_le_parc_ne_coute_pas_une_requete_par_cabine(self):
        self.verifier("/api/cabines/?page=1", "Parc des cabines")

    def test_les_emplacements_ne_coutent_pas_une_requete_par_emplacement(self):
        self.verifier("/api/emplacements/?page=1", "Emplacements")

    def test_le_journal_ne_coute_pas_une_requete_par_mouvement(self):
        self.verifier("/api/mouvements-cabine/?page=1", "Journal")

    def test_le_stock_mp_ne_coute_pas_une_requete_par_code(self):
        """Le Parc côté MP : deux requêtes, quelle que soit la base des codes."""
        from wms import services_mp
        from wms.models import ArticleMP

        vitrages = [Emplacement.objects.create(code=f"V{i:03d}", usage=Emplacement.MP_VITRAGE)
                    for i in range(12)]
        codes = list(ArticleMP.objects.filter(famille=ArticleMP.VITRAGE, ancienne_generation=False))

        def poser(combien):
            for i in range(combien):
                services_mp.entrer(emplacement=vitrages[i], place="G", article=codes[i],
                                   quantite=5, utilisateur=self.user)

        poser(2)
        avec_deux = self.requetes("/api/mp/stock/")
        poser(10)
        self.assertEqual(self.requetes("/api/mp/stock/"), avec_deux,
                         "le coût du stock MP suit le nombre de codes en stock")

    def test_la_proposition_d_emplacement_ne_suit_pas_l_entrepot(self):
        """L'écran le plus utilisé : il relit tout l'entrepôt à chaque appel."""
        self.peupler(2)
        cabine = Cabine.objects.exclude(statut=Cabine.ENVOYE).first()
        url = f"/api/emplacements/pour_cabine/?cabine={cabine.id}"
        avec_deux = self.requetes(url)
        self.peupler(10)
        self.assertEqual(self.requetes(url), avec_deux,
                         "le coût de la proposition suit la taille de l'entrepôt")
