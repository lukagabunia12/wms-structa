"""Matières premières : vitrages et cartons.

- la base des codes éléments (`ArticleMP`), le stock place par place
  (`StockMP`) et le journal (`MouvementMP`) ;
- `Emplacement.usage` : un emplacement range des cabines, ou une famille de
  matières premières — jamais les deux ;
- la case « matières premières » des comptes ;
- « Milieu » devient condamnable, pour les seuls emplacements MP qui ont trois
  places.

La base est remplie par la migration suivante, séparée pour que le schéma et
les données se rejouent chacun dans sa transaction.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wms", "0024_retrait_volet_articles"),
    ]

    operations = [
        migrations.CreateModel(
            name="ArticleMP",
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
                    "code",
                    models.CharField(
                        max_length=64, unique=True, verbose_name="code élément"
                    ),
                ),
                (
                    "famille",
                    models.CharField(
                        choices=[("vitrage", "Vitrage"), ("carton", "Carton")],
                        max_length=16,
                    ),
                ),
                (
                    "designation",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=200,
                        verbose_name="désignation",
                    ),
                ),
                (
                    "fournisseur",
                    models.CharField(blank=True, default="", max_length=60),
                ),
                (
                    "numero",
                    models.CharField(
                        blank=True, default="", max_length=20, verbose_name="n° article"
                    ),
                ),
                (
                    "references",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=255,
                        verbose_name="autres références",
                    ),
                ),
                ("colisage", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "seuil_reappro",
                    models.PositiveIntegerField(
                        blank=True, null=True, verbose_name="seuil de réappro"
                    ),
                ),
                (
                    "ancienne_generation",
                    models.BooleanField(
                        default=False, verbose_name="ancienne génération"
                    ),
                ),
                ("actif", models.BooleanField(default=True)),
                (
                    "cle",
                    models.CharField(
                        db_index=True,
                        default="",
                        editable=False,
                        max_length=64,
                        verbose_name="clé de recherche",
                    ),
                ),
                (
                    "cle_references",
                    models.CharField(default="", editable=False, max_length=300),
                ),
                (
                    "modifie_le",
                    models.DateTimeField(auto_now=True, verbose_name="modifié le"),
                ),
            ],
            options={
                "verbose_name": "code MP",
                "verbose_name_plural": "codes MP (base vitrages et cartons)",
                "ordering": ["famille", "code"],
            },
        ),
        migrations.AddField(
            model_name="emplacement",
            name="usage",
            field=models.CharField(
                choices=[
                    ("cabines", "Cabines"),
                    ("carton", "MP · cartons"),
                    ("vitrage", "MP · vitrages"),
                ],
                db_index=True,
                default="cabines",
                max_length=16,
                verbose_name="ce qu'il range",
            ),
        ),
        migrations.AddField(
            model_name="utilisateur",
            name="droit_mp",
            field=models.BooleanField(default=False, verbose_name="matières premières"),
        ),
        migrations.AlterField(
            model_name="placecondamnee",
            name="place",
            field=models.CharField(
                choices=[("G", "Gauche"), ("M", "Milieu"), ("D", "Droite")],
                max_length=2,
            ),
        ),
        migrations.CreateModel(
            name="MouvementMP",
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
                ("date", models.DateTimeField(auto_now_add=True)),
                (
                    "type",
                    models.CharField(
                        choices=[("entree", "Entrée"), ("sortie", "Sortie")],
                        max_length=16,
                    ),
                ),
                (
                    "article_code",
                    models.CharField(max_length=64, verbose_name="code élément"),
                ),
                (
                    "famille",
                    models.CharField(
                        choices=[("vitrage", "Vitrage"), ("carton", "Carton")],
                        max_length=16,
                    ),
                ),
                ("position", models.CharField(max_length=80)),
                ("quantite", models.PositiveIntegerField(verbose_name="quantité")),
                (
                    "reste",
                    models.PositiveIntegerField(verbose_name="reste à cette place"),
                ),
                (
                    "utilisateur_nom",
                    models.CharField(blank=True, default="", max_length=150),
                ),
                ("note", models.CharField(blank=True, default="", max_length=255)),
                (
                    "article",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mouvements",
                        to="wms.articlemp",
                    ),
                ),
                (
                    "emplacement",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mouvements_mp",
                        to="wms.emplacement",
                    ),
                ),
                (
                    "utilisateur",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mouvements_mp",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "mouvement MP",
                "verbose_name_plural": "mouvements MP",
                "ordering": ["-date", "-id"],
            },
        ),
        migrations.CreateModel(
            name="StockMP",
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
                    "place",
                    models.CharField(
                        choices=[("G", "Gauche"), ("M", "Milieu"), ("D", "Droite")],
                        max_length=1,
                    ),
                ),
                ("quantite", models.PositiveIntegerField(verbose_name="quantité")),
                (
                    "entre_le",
                    models.DateTimeField(auto_now_add=True, verbose_name="entré le"),
                ),
                (
                    "modifie_le",
                    models.DateTimeField(
                        auto_now=True, verbose_name="dernier mouvement"
                    ),
                ),
                (
                    "article",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="stock",
                        to="wms.articlemp",
                    ),
                ),
                (
                    "emplacement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="stock_mp",
                        to="wms.emplacement",
                    ),
                ),
            ],
            options={
                "verbose_name": "ligne de stock MP",
                "verbose_name_plural": "stock MP",
                "ordering": ["emplacement__code", "place", "article__code"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("emplacement", "place", "article"),
                        name="stock_mp_un_code_par_place",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("quantite__gt", 0)),
                        name="stock_mp_quantite_positive",
                    ),
                ],
            },
        ),
    ]
