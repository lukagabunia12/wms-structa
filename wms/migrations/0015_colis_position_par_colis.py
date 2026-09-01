"""La position quitte la cabine pour le colis.

Une cabine arrive en un ou plusieurs colis, rangés là où il reste de la place —
pas forcément ensemble. Tant que `emplacement` et `place` vivaient sur la cabine,
il n'y avait de place que pour une adresse.

Cette migration ne perd RIEN : chaque cabine existante reçoit son colis n° 1, qui
reprend exactement l'emplacement et la place qu'elle occupait. Une cabine à un
seul colis se comporte donc après comme avant.
"""

import django.db.models.deletion
from django.db import migrations, models


def cabines_vers_colis(apps, schema_editor):
    """Un colis n° 1 par cabine, portant sa position actuelle."""
    Cabine = apps.get_model("wms", "Cabine")
    Colis = apps.get_model("wms", "Colis")
    Colis.objects.bulk_create([
        Colis(cabine_id=c.pk, numero=1, libelle="",
              emplacement_id=c.emplacement_id, place=c.place or "")
        for c in Cabine.objects.all().only("pk", "emplacement_id", "place")
    ])


def colis_vers_cabines(apps, schema_editor):
    """Retour en arrière : la position du colis n° 1 remonte sur la cabine.

    Les colis suivants seraient perdus — c'est inévitable, la cabine n'a qu'une
    position. On ne fait donc marche arrière qu'avant d'avoir saisi le deuxième
    colis de quoi que ce soit.
    """
    Cabine = apps.get_model("wms", "Cabine")
    Colis = apps.get_model("wms", "Colis")
    for colis in Colis.objects.filter(numero=1).only("cabine_id", "emplacement_id", "place"):
        Cabine.objects.filter(pk=colis.cabine_id).update(
            emplacement_id=colis.emplacement_id, place=colis.place or "")


class Migration(migrations.Migration):

    dependencies = [
        ("wms", "0014_statut_levee_retire_types_cabine"),
    ]

    operations = [
        migrations.CreateModel(
            name="Colis",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "numero",
                    models.PositiveSmallIntegerField(
                        default=1, verbose_name="n° de colis"
                    ),
                ),
                (
                    "libelle",
                    models.CharField(
                        blank=True, default="", max_length=60, verbose_name="contenu"
                    ),
                ),
                (
                    "place",
                    models.CharField(
                        blank=True,
                        choices=[("G", "Gauche"), ("M", "Milieu"), ("D", "Droite")],
                        default="",
                        max_length=1,
                        verbose_name="place",
                    ),
                ),
            ],
            options={
                "verbose_name": "colis",
                "verbose_name_plural": "colis",
                "ordering": ["cabine", "numero"],
            },
        ),
        migrations.AddField(
            model_name="cabine",
            name="nb_colis",
            field=models.PositiveSmallIntegerField(
                default=1, verbose_name="nombre de colis"
            ),
        ),
        migrations.AddField(
            model_name="colis",
            name="cabine",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="colis",
                to="wms.cabine",
            ),
        ),
        migrations.AddField(
            model_name="colis",
            name="emplacement",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="colis",
                to="wms.emplacement",
            ),
        ),
        migrations.AddConstraint(
            model_name="colis",
            constraint=models.UniqueConstraint(
                fields=("cabine", "numero"), name="colis_numerote_une_fois_par_cabine"
            ),
        ),
        migrations.AddConstraint(
            model_name="colis",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("emplacement__isnull", False),
                    models.Q(("place", ""), _negated=True),
                ),
                fields=("emplacement", "place"),
                name="place_occupee_par_un_seul_colis",
            ),
        ),
        # Les positions sont recopiées AVANT que les champs ne disparaissent.
        migrations.RunPython(cabines_vers_colis, colis_vers_cabines),
        migrations.RemoveConstraint(
            model_name="cabine",
            name="place_occupee_par_une_seule_cabine",
        ),
        migrations.RemoveField(
            model_name="cabine",
            name="emplacement",
        ),
        migrations.RemoveField(
            model_name="cabine",
            name="place",
        ),
    ]
