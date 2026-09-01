"""Retrait du statut « Levée de quarantaine », et deux nouveaux types de cabine.

Une quarantaine levée rend la cabine conforme : « Rien à signaler » dit exactement
cela. Garder un troisième statut n'ajoutait aucune information sur l'état de la
cabine et laissait des cabines saines marquées d'un libellé alarmant. Le passage
par la quarantaine reste tracé dans le journal, avec son motif et sa date — c'est
là qu'on va le chercher, pas dans le statut courant.

Les cabines actuellement en « levee » deviennent donc « libre ».

Le retour arrière ne peut pas rétablir la distinction : rien, dans une cabine
« libre », ne dit si elle est passée par la quarantaine. La fonction inverse ne
fait donc rien, plutôt que de deviner.
"""
from django.db import migrations, models


def levee_vers_libre(apps, schema_editor):
    Cabine = apps.get_model("wms", "Cabine")
    Cabine.objects.filter(statut="levee").update(statut="libre")


def retour_impossible(apps, schema_editor):
    """Aucune donnée ne permet de retrouver quelles cabines étaient « levee »."""


class Migration(migrations.Migration):

    dependencies = [("wms", "0013_statuts_cabine")]

    operations = [
        migrations.RunPython(levee_vers_libre, retour_impossible),
        migrations.AlterField(
            model_name="cabine",
            name="statut",
            field=models.CharField(
                choices=[("libre", "Rien à signaler"), ("quarantaine", "En quarantaine"),
                         ("envoye", "Envoyée")],
                default="libre", max_length=16),
        ),
        migrations.AlterField(
            model_name="cabine",
            name="type_cabine",
            field=models.CharField(
                choices=[("normale", "Normale"), ("express", "Express"),
                         ("salon", "Salon"), ("occasion", "Occasion")],
                default="normale", max_length=16, verbose_name="type"),
        ),
    ]
