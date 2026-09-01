"""Détache les cabines déjà envoyées de leur emplacement.

`services_cabines.envoyer()` vide `emplacement` et `place` : une cabine envoyée a quitté
l'entrepôt, elle n'occupe plus rien. Les cabines reprises du modèle précédent gardaient
en revanche leur ancien emplacement, si bien que leur fiche annonçait « rangée en A001 »
alors qu'elles sont parties. Elles n'occupaient déjà aucune place (tous les calculs
excluent le statut « envoyé ») : il s'agit uniquement de rendre la donnée cohérente.
"""
from django.db import migrations


def detacher(apps, schema_editor):
    Cabine = apps.get_model("wms", "Cabine")
    (Cabine.objects.filter(statut="envoye")
     .exclude(emplacement__isnull=True, place="")
     .update(emplacement=None, place=""))


def revenir(apps, schema_editor):
    """Irréversible : l'emplacement d'origine n'est pas conservé ailleurs.

    L'historique garde la position au moment de l'envoi (`MouvementCabine.depuis`),
    mais pas de quoi reconstituer un rattachement qui n'avait plus de sens.
    """
    pass


class Migration(migrations.Migration):

    dependencies = [("wms", "0007_reprise_places_cabines")]

    operations = [migrations.RunPython(detacher, revenir)]
