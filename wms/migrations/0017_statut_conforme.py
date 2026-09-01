"""« Rien à signaler » devient « Conforme ».

Seul le LIBELLÉ affiché change : le code stocké reste « libre », et rien n'est
réécrit en base. Cette migration ne touche donc aucune donnée — elle existe
parce que Django suit les `choices` d'un champ, et que la CI refuse un modèle
dont la migration manque. La jouer ou non ne change rien aux cabines déjà
enregistrées ; leur historique reste lisible mot pour mot.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wms", "0016_emplacements_multiples"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cabine",
            name="statut",
            field=models.CharField(
                choices=[
                    ("libre", "Conforme"),
                    ("quarantaine", "En quarantaine"),
                    ("envoye", "Envoyée"),
                ],
                default="libre",
                max_length=16,
            ),
        ),
    ]
