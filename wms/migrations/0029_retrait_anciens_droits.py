"""Retrait des cases « cabines » et « référentiel », reportées par 0028.

Une migration à part : le report et le retrait des colonnes ne partagent pas la
même transaction. Revenir en arrière recrée les deux colonnes, vides ; c'est le
retour de 0028 qui les recoche.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("wms", "0028_droits_a_cocher"),
    ]

    operations = [
        migrations.RemoveField(model_name="utilisateur", name="droit_cab"),
        migrations.RemoveField(model_name="utilisateur", name="droit_ref"),
    ]
