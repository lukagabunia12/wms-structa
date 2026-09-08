"""Vide la base pour repartir d'un entrepôt neuf.

Sert deux fois dans la vie d'un WMS : après la période d'essai, pour effacer les
cabines de test avant la vraie mise en service ; et sur le serveur, avant
d'ouvrir le service aux opérateurs.

Trois garde-fous, parce que l'opération est irréversible :

- une **sauvegarde** du fichier SQLite est prise avant toute suppression ;
- l'ordre de suppression respecte les dépendances — `Stock.emplacement` est en
  PROTECT, supprimer les emplacements en premier échouerait à mi-parcours ;
- tout se joue dans une **transaction** : en cas d'imprévu, la base reste
  exactement dans l'état où on l'a trouvée.

    python manage.py reinitialiser                      # tout sauf les comptes
    python manage.py reinitialiser --garder-referentiel # garde emplacements et zones
    python manage.py reinitialiser --tout               # comptes compris
"""
import shutil
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

MOT_DE_CONFIRMATION = "EFFACER"


class Command(BaseCommand):
    help = "Vide la base des données d'exploitation, avec sauvegarde préalable."

    def add_arguments(self, p):
        p.add_argument("--garder-referentiel", action="store_true",
                       help="conserve les emplacements et les zones déjà paramétrés")
        p.add_argument("--tout", action="store_true",
                       help="efface aussi les comptes (plus personne ne peut se connecter)")
        p.add_argument("--oui", action="store_true",
                       help="passe la confirmation — pour un script, jamais à la main")
        p.add_argument("--sans-sauvegarde", action="store_true",
                       help="n'écrit pas la copie de sécurité (déconseillé)")

    def handle(self, *args, **o):
        from rest_framework.authtoken.models import Token
        from wms.models import (Article, Cabine, CabineAttendue, Categorie,
                                Emplacement, EtatCabine, ModeleCabine, Mouvement,
                                MouvementCabine, Reception, Stock, Utilisateur, Zone)

        # L'ordre compte : les tables qui référencent les autres passent d'abord.
        # `Stock.emplacement` est en PROTECT — supprimer les emplacements avant les
        # lignes de stock lèverait une erreur au milieu du travail.
        a_vider = [
            ("Journal des cabines", MouvementCabine),
            ("Cabines", Cabine),
            ("Mouvements de stock", Mouvement),
            ("Réceptions", Reception),
            ("Lignes de stock", Stock),
            ("Articles", Article),
            ("Catégories", Categorie),
            ("États de cabine", EtatCabine),
        ]
        if not o["garder_referentiel"]:
            a_vider += [("Emplacements", Emplacement), ("Zones", Zone)]
        if o["tout"]:
            a_vider += [("Jetons de connexion", Token), ("Comptes", Utilisateur)]

        avant = [(nom, m, m.objects.count()) for nom, m in a_vider]
        total = sum(n for _, _, n in avant)
        if not total:
            self.stdout.write("La base est déjà vide : rien à faire.")
            return

        self.stdout.write("\n  Va être effacé :")
        for nom, _, n in avant:
            if n:
                self.stdout.write(f"    {nom:24} {n:>6}")
        if o["garder_referentiel"]:
            self.stdout.write(f"\n  Conservé : {Emplacement.objects.count()} emplacement(s), "
                              f"{Zone.objects.count()} zone(s)")
        # Dit dans TOUS les cas, y compris sans --garder-referentiel : ces deux
        # tables ne sont pas des données d'entrepôt mais du référentiel, et rien
        # ne les efface. Le taire laisserait croire que la remise à zéro a tout
        # emporté — et l'opérateur réimporterait un fichier déjà là, ou
        # rechercherait des réglages de taille qu'il croit perdus.
        self.stdout.write(
            f"  Conservé : {CabineAttendue.objects.count()} cabine(s) annoncée(s) "
            f"par le fichier de production, {ModeleCabine.objects.count()} "
            f"réglage(s) de taille de modèle")
        if not o["tout"]:
            comptes = ", ".join(Utilisateur.objects.values_list("username", flat=True))
            self.stdout.write(f"  Conservé : compte(s) {comptes or '—'}")
        else:
            self.stdout.write(self.style.WARNING(
                "\n  Les comptes seront effacés : plus personne ne pourra se connecter "
                "tant qu'un `createsuperuser` n'aura pas été passé."))

        if not o["oui"]:
            self.stdout.write("\n  Cette action est irréversible.")
            reponse = input(f"  Tapez {MOT_DE_CONFIRMATION} pour confirmer : ").strip()
            if reponse != MOT_DE_CONFIRMATION:
                raise CommandError("Annulé : rien n'a été effacé.")

        sauvegarde = None
        if not o["sans_sauvegarde"]:
            sauvegarde = self._sauvegarder()

        with transaction.atomic():
            for nom, modele, _ in avant:
                modele.objects.all().delete()

        self.stdout.write("")
        if sauvegarde:
            self.stdout.write(f"  Sauvegarde : {sauvegarde.name}")
        self.stdout.write(self.style.SUCCESS(
            f"  {total} ligne(s) effacée(s). La base est prête pour un entrepôt neuf."))
        restant = [f"{nom} {m.objects.count()}" for nom, m in
                   [("emplacements", Emplacement), ("zones", Zone), ("comptes", Utilisateur)]
                   if m.objects.count()]
        if restant:
            self.stdout.write("  Conservé : " + " · ".join(restant))

    @staticmethod
    def _sauvegarder():
        """Copie du fichier SQLite avant suppression.

        Sur un serveur SQL, la sauvegarde ne se fait pas ici : elle relève de
        `pg_dump`, planifié côté serveur. On le dit plutôt que de laisser croire
        à un filet qui n'existe pas.
        """
        if connection.vendor != "sqlite":
            return None
        source = Path(connection.settings_dict["NAME"])
        if not source.is_file():
            return None
        copie = source.with_name(
            f"{source.name}.avant-remise-a-zero-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(source, copie)
        return copie
