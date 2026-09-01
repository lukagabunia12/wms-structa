"""Deux types d'événement en plus au journal des cabines.

`correction` (fiche corrigée après une mauvaise saisie) et `suppression` (cabine
supprimée). La ligne de suppression est écrite juste avant que la cabine ne
disparaisse : `MouvementCabine.cabine` étant en SET_NULL, elle survit et garde le
numéro, le chantier et l'auteur — sans quoi une cabine s'évanouissait sans
explication.

Migration de choix seulement : aucune donnée existante n'est touchée.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("wms", "0010_champs_fiche_cabine")]

    operations = [
        migrations.AlterField(
            model_name="mouvementcabine",
            name="type",
            field=models.CharField(
                choices=[
                    ("creation", "Création"),
                    ("rangement", "Rangement"),
                    ("transfert", "Transfert"),
                    ("retrait", "Sortie d'emplacement"),
                    ("statut", "Changement de statut"),
                    ("envoi", "Envoi"),
                    ("correction", "Correction de fiche"),
                    ("suppression", "Suppression de la cabine"),
                ],
                max_length=16,
            ),
        ),
    ]
