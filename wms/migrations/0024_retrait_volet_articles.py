"""Retrait du volet « articles » : catégories, articles, stock, mouvements,
réceptions et états de cabine. Aucun écran ne s'en servait plus ; leur contenu
a été sauvegardé par la migration précédente.

Au passage :
- les cinq cases de droits qui ne commandaient plus rien (mouvements,
  correction de mouvement, inventaire, données, appro) quittent la fiche
  utilisateur ;
- le champ « code-barres » des emplacements, jamais utilisé, disparaît ;
- une zone ne se supprime plus tant que des emplacements y sont rattachés.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wms", "0023_sauvegarde_volet_articles"),
    ]

    operations = [
        # Les tables sont supprimées entières, celles qui en référencent
        # d'autres d'abord. Retirer leurs colonnes une à une, comme le propose
        # `makemigrations`, échoue sur SQLite : la reconstruction de la table
        # emporte une contrainte d'unicité qui cite encore la colonne retirée.
        migrations.DeleteModel(name="Stock"),
        migrations.DeleteModel(name="Mouvement"),
        migrations.DeleteModel(name="Reception"),
        migrations.DeleteModel(name="Article"),
        migrations.DeleteModel(name="Categorie"),
        migrations.DeleteModel(name="EtatCabine"),
        migrations.RemoveField(model_name="emplacement", name="code_barre"),
        migrations.RemoveField(model_name="utilisateur", name="droit_appro"),
        migrations.RemoveField(model_name="utilisateur", name="droit_data"),
        migrations.RemoveField(model_name="utilisateur", name="droit_inv"),
        migrations.RemoveField(model_name="utilisateur", name="droit_mvt"),
        migrations.RemoveField(model_name="utilisateur", name="droit_mvt_corr"),
        migrations.AlterField(
            model_name="emplacement",
            name="zone_cabine",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="emplacements",
                to="wms.zone",
                verbose_name="zone de cabines",
            ),
        ),
    ]
