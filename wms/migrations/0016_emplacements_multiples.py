"""Une cabine occupe UN emplacement, parfois plusieurs — rien n'est déclaré.

La version précédente demandait le nombre de colis à la création. C'était une
question de trop : on ne sait pas avant de décharger si une cabine tiendra en un
ou deux endroits, et l'annoncer à l'avance faisait passer pour « incomplète »
une cabine parfaitement rangée.

Le modèle devient donc : une cabine est rangée dès qu'elle occupe un
emplacement, et le cariste en ajoute un s'il en trouve un second.

`Colis` devient `Occupation` — c'est un emplacement occupé, pas un paquet.
La table est RENOMMÉE, pas recréée : aucune position n'est perdue.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wms", "0015_colis_position_par_colis"),
    ]

    operations = [
        # Les contraintes portent le nom du modèle : on les retire avant de
        # renommer, on les repose après. Un `RenameModel` seul les laisserait
        # sous leur ancien nom en base.
        migrations.RemoveConstraint(
            model_name="colis", name="colis_numerote_une_fois_par_cabine"),
        migrations.RemoveConstraint(
            model_name="colis", name="place_occupee_par_un_seul_colis"),

        # RENOMMAGE, pas suppression-recréation : les lignes existantes suivent.
        migrations.RenameModel(old_name="Colis", new_name="Occupation"),

        migrations.AlterModelOptions(
            name="occupation",
            options={
                "ordering": ["cabine", "numero"],
                "verbose_name": "emplacement occupé",
                "verbose_name_plural": "emplacements occupés",
            },
        ),
        # `related_name` ne touche pas la base : c'est le nom Python de la
        # relation inverse (`cabine.occupations`).
        migrations.AlterField(
            model_name="occupation",
            name="cabine",
            field=models.ForeignKey(on_delete=models.CASCADE,
                                    related_name="occupations", to="wms.cabine"),
        ),
        migrations.AlterField(
            model_name="occupation",
            name="emplacement",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL,
                                    related_name="occupations", to="wms.emplacement"),
        ),
        migrations.AlterField(
            model_name="occupation",
            name="numero",
            field=models.PositiveSmallIntegerField(default=1, verbose_name="n°"),
        ),
        migrations.AddConstraint(
            model_name="occupation",
            constraint=models.UniqueConstraint(
                fields=("cabine", "numero"),
                name="occupation_numerotee_une_fois_par_cabine"),
        ),
        migrations.AddConstraint(
            model_name="occupation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("emplacement__isnull", False),
                                   models.Q(("place", ""), _negated=True)),
                fields=("emplacement", "place"),
                name="place_occupee_par_une_seule_cabine"),
        ),

        # Le nombre annoncé disparaît : il n'est plus déclaré nulle part.
        migrations.RemoveField(model_name="cabine", name="nb_colis"),
    ]
