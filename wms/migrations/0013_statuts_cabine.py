"""Le statut d'une cabine ne dit plus où elle est.

« Rangé » et « Non rangé » ont été demandés comme statuts. Ils n'en sont pas :
ils se déduisent de l'emplacement, et les stocker en double laisserait apparaître
une cabine marquée « Rangé » qui n'est nulle part — sans qu'on sache laquelle des
deux informations croire. Ils sont donc calculés (`Cabine.rangee`), et le statut
ne garde que ce qu'aucune autre donnée ne dit : quarantaine, levée, envoi.

« Chargé » disparaît au passage : la cabine chargée est prête à partir sans l'être
encore, ce que « Levée de quarantaine » couvre déjà. Les rares cabines à ce statut
y sont basculées plutôt qu'abandonnées à une valeur qui n'existe plus.
"""
from django.db import migrations, models


def charge_vers_levee(apps, schema_editor):
    apps.get_model("wms", "Cabine").objects.filter(statut="charge").update(statut="levee")


def levee_vers_charge(apps, schema_editor):
    """Retour arrière : on ne sait pas distinguer les cabines converties des autres.

    Rien n'est reconverti — remettre toutes les « levée » en « chargé » inventerait
    un état que la plupart n'ont jamais eu. La marche arrière rétablit le choix,
    pas l'histoire.
    """
    return


class Migration(migrations.Migration):

    dependencies = [("wms", "0012_position_dans_le_rack")]

    operations = [
        migrations.RunPython(charge_vers_levee, levee_vers_charge),
        migrations.AlterField(
            model_name="cabine",
            name="statut",
            field=models.CharField(
                choices=[("libre", "Rien à signaler"), ("quarantaine", "En quarantaine"),
                         ("levee", "Levée de quarantaine"), ("envoye", "Envoyée")],
                default="libre", max_length=16),
        ),
    ]
