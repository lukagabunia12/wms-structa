"""Matières premières : régler, alerter, déplacer.

- `Emplacement.codes_acceptes` : un emplacement MP peut être réservé à un ou
  plusieurs codes. Vide, il accepte tous ceux de sa famille, comme avant ;
- le « seuil de réappro » s'appelle désormais seuil d'alerte : c'est lui que
  la cloche des écrans surveille. Le champ garde son nom en base ;
- le journal MP connaît le changement d'emplacement, en UNE ligne : d'où
  (`origine`, `reste_origine`) et vers où (`position`, `reste`).

Aucune donnée n'est réécrite : les emplacements restent ouverts à toute leur
famille, les seuils gardent leur valeur.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wms", "0026_base_mp"),
    ]

    operations = [
        migrations.AddField(
            model_name="emplacement",
            name="codes_acceptes",
            field=models.ManyToManyField(
                blank=True,
                help_text="Vide : tous les codes de sa famille. Sinon, seuls ces codes y entrent.",
                related_name="emplacements_reserves",
                to="wms.articlemp",
                verbose_name="codes acceptés",
            ),
        ),
        migrations.AddField(
            model_name="mouvementmp",
            name="origine",
            field=models.CharField(
                blank=True, default="", max_length=80, verbose_name="depuis"
            ),
        ),
        migrations.AddField(
            model_name="mouvementmp",
            name="reste_origine",
            field=models.PositiveIntegerField(
                blank=True, null=True, verbose_name="reste au départ"
            ),
        ),
        migrations.AlterField(
            model_name="articlemp",
            name="seuil_reappro",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Alerte quand le stock total du code passe en dessous. Vide : pas d'alerte.",
                null=True,
                verbose_name="seuil d'alerte",
            ),
        ),
        migrations.AlterField(
            model_name="mouvementmp",
            name="type",
            field=models.CharField(
                choices=[
                    ("entree", "Entrée"),
                    ("sortie", "Sortie"),
                    ("transfert", "Changement d'emplacement"),
                ],
                max_length=16,
            ),
        ),
    ]
