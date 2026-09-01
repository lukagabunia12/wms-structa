"""Contrôle qu'une base SQL fraîchement reprise est réellement exploitable.

Compter les lignes ne suffit pas : une reprise peut livrer une base complète et
pourtant inutilisable, parce que les séquences d'auto-incrément sont restées à 1
et que la première création tombera en « duplicate key ». Ce défaut ne se voit
pas à la lecture — il se déclare des semaines plus tard, en production.

Ce script écrit donc pour de vrai, puis efface : une zone, un emplacement, un
groupe et son association à un compte. La table de liaison ManyToMany est
incluse à dessein : c'est celle qui était oubliée du recalage.

    python outils/verifier_bascule.py
"""
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
django.setup()

from django.contrib.auth.models import Group  # noqa: E402
from django.db import connection, transaction  # noqa: E402

from wms.models import (Article, Cabine, Emplacement, Mouvement,  # noqa: E402
                        MouvementCabine, Utilisateur, Zone)

MARQUE = "__controle_bascule__"


def etat():
    reglages = connection.settings_dict
    print(f"\n  Moteur   : {connection.vendor}")
    cible = reglages["NAME"]
    if connection.vendor != "sqlite":
        cible += f"  sur {reglages['HOST']}:{reglages['PORT'] or 5432}"
    print(f"  Base     : {cible}")
    print(f"  Contenu  : {Emplacement.objects.count()} emplacements · "
          f"{Article.objects.count()} articles · {Cabine.objects.count()} cabines · "
          f"{Mouvement.objects.count()} mouvements · "
          f"{MouvementCabine.objects.count()} événements · "
          f"{Utilisateur.objects.count()} comptes")


def essai_ecriture():
    """Crée puis efface. Tout est annulé à la fin : la base ressort intacte."""
    controles = []
    try:
        with transaction.atomic():
            zone = Zone.objects.create(nom=MARQUE, ordre=9999, actif=False)
            controles.append(("création d'une zone", zone.pk))

            empl = Emplacement.objects.create(code=MARQUE, zone="", actif=False)
            controles.append(("création d'un emplacement", empl.pk))

            # Le point sensible : la table de liaison ManyToMany est créée par
            # Django et sa séquence était oubliée du recalage. Sans le correctif,
            # cette ligne échoue en « duplicate key ».
            groupe = Group.objects.create(name=MARQUE)
            controles.append(("création d'un groupe", groupe.pk))
            compte = Utilisateur.objects.order_by("pk").first()
            if compte is None:
                raise RuntimeError("Aucun compte en base : la reprise est incomplète.")
            compte.groups.add(groupe)
            controles.append(("association compte/groupe (table de liaison)",
                              compte.groups.filter(pk=groupe.pk).count()))
            raise _Rollback()
    except _Rollback:
        pass

    for libelle, valeur in controles:
        print(f"    OK   {libelle:46} -> {valeur}")
    return len(controles)


class _Rollback(Exception):
    """Annule la transaction d'essai sans laisser de trace."""


def main():
    etat()
    print("\n  Essai d'écriture (créé puis annulé, rien ne reste) :")
    n = essai_ecriture()

    restes = (Zone.objects.filter(nom=MARQUE).count()
              + Emplacement.objects.filter(code=MARQUE).count()
              + Group.objects.filter(name=MARQUE).count())
    if restes:
        print(f"\n  ÉCHEC : {restes} ligne(s) d'essai n'ont pas été annulées.")
        return 1

    print(f"\n  {n}/4 contrôles passés, aucune trace laissée.")
    print("  La base est exploitable : les séquences sont correctes.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
