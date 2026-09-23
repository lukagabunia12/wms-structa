"""Sauvegarde du volet « articles » avant son retrait (migration suivante).

Le contenu des catégories, articles, stock, mouvements, réceptions et états de
cabine est écrit dans `sauvegardes/articles-retires_<date>.json` — seulement
s'il y a quelque chose à sauvegarder. Rien ne disparaît sans trace.

Au passage, les emplacements créés avec l'ancien code de mode « gmd » (trois
places), que le générateur de racks écrivait encore, passent à « gd » (deux
places).

Séparée du retrait des tables pour que la lecture et la réparation se
jouent dans leur propre transaction, avant toute modification de schéma.
"""
import itertools
from pathlib import Path

from django.conf import settings
from django.core import serializers
from django.db import migrations
from django.utils import timezone

TABLES_RETIREES = ["Categorie", "Article", "Stock", "Mouvement", "Reception", "EtatCabine"]


def sauvegarder_puis_reparer(apps, schema_editor):
    modeles = [apps.get_model("wms", nom) for nom in TABLES_RETIREES]
    if any(m.objects.exists() for m in modeles):
        dossier = Path(settings.BASE_DIR) / "sauvegardes"
        dossier.mkdir(parents=True, exist_ok=True)
        fichier = dossier / f"articles-retires_{timezone.localtime():%Y-%m-%d_%Hh%M%S}.json"
        with fichier.open("w", encoding="utf-8") as sortie:
            serializers.serialize(
                "json", itertools.chain.from_iterable(m.objects.order_by("pk") for m in modeles),
                indent=2, stream=sortie)
        print(f"\n  Volet articles sauvegardé avant retrait : {fichier}")

    Emplacement = apps.get_model("wms", "Emplacement")
    Emplacement.objects.filter(mode_places="gmd").update(mode_places="gd")


class Migration(migrations.Migration):

    dependencies = [
        ("wms", "0022_places_condamnees_et_activation"),
    ]

    operations = [
        migrations.RunPython(sauvegarder_puis_reparer, migrations.RunPython.noop),
    ]
