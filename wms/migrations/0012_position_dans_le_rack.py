"""Position physique d'un emplacement : rack, colonne, niveau.

Renseignés par le générateur de racks. Ils permettent d'imprimer les étiquettes
« par colonne » ou « par rack » sans redécouper le code à coups d'expressions
régulières — un découpage qui casserait à la première convention un peu
différente. Vides pour les emplacements créés à l'unité, qui s'impriment seuls.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("wms", "0011_journal_correction_et_suppression")]

    operations = [
        migrations.AddField(
            model_name="emplacement",
            name="rack",
            field=models.CharField(blank=True, default="", max_length=32, verbose_name="rack"),
        ),
        migrations.AddField(
            model_name="emplacement",
            name="colonne",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="colonne"),
        ),
        migrations.AddField(
            model_name="emplacement",
            name="niveau",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="niveau"),
        ),
        migrations.AddIndex(
            model_name="emplacement",
            index=models.Index(fields=["rack", "colonne", "niveau"],
                               name="emplacement_position_idx"),
        ),
    ]
