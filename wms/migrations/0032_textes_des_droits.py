"""Les explications de deux cases suivent les familles MP : « toutes les familles »
plutôt que « vitrages et cartons »."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wms", "0031_familles_mp"),
    ]

    operations = [
        migrations.AlterField(
            model_name="groupe",
            name="droit_empl_regler",
            field=models.BooleanField(
                default=False,
                help_text="Leur code, ce qu'ils rangent (cabines ou matières premières), les familles et codes MP qu'ils acceptent, leur description.",
                verbose_name="régler les emplacements",
            ),
        ),
        migrations.AlterField(
            model_name="groupe",
            name="droit_mp",
            field=models.BooleanField(
                default=False,
                help_text="Toutes les familles — vitrages, cartons… : entrée, sortie, changement d'emplacement.",
                verbose_name="entrer, sortir et déplacer des matières premières",
            ),
        ),
        migrations.AlterField(
            model_name="utilisateur",
            name="droit_empl_regler",
            field=models.BooleanField(
                default=False,
                help_text="Leur code, ce qu'ils rangent (cabines ou matières premières), les familles et codes MP qu'ils acceptent, leur description.",
                verbose_name="régler les emplacements",
            ),
        ),
        migrations.AlterField(
            model_name="utilisateur",
            name="droit_mp",
            field=models.BooleanField(
                default=False,
                help_text="Toutes les familles — vitrages, cartons… : entrée, sortie, changement d'emplacement.",
                verbose_name="entrer, sortir et déplacer des matières premières",
            ),
        ),
    ]
