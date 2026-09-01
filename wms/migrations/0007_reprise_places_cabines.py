"""Attribue une place aux cabines reprises qui occupent un emplacement sans place.

L'ancien modèle n'avait pas la notion de place : une cabine pointait un emplacement,
sans position dedans. Après la reprise `0004`, ces cabines se retrouvent donc sur un
emplacement en mode « 3 places » avec `place = ""` — un état que le modèle actuel
interdit, et qui affiche « 1/3 occupé » tout en annonçant les trois places libres.

Choix retenu : la travée est une information réelle, on la conserve ; la position dans
la travée est inconnue, on prend la première place libre et on l'inscrit dans
l'historique comme étant à vérifier. Si la travée est déjà pleine, la cabine est
détachée plutôt que d'écraser une position connue.
"""
from django.db import migrations

PLACES = ["G", "M", "D"]
NOTE = "Place attribuée automatiquement à la reprise — à vérifier sur le terrain"


def attribuer(apps, schema_editor):
    Cabine = apps.get_model("wms", "Cabine")
    MouvementCabine = apps.get_model("wms", "MouvementCabine")

    a_traiter = (Cabine.objects.filter(place="", emplacement__isnull=False)
                 .exclude(statut="envoye")
                 .select_related("emplacement")
                 .order_by("emplacement_id", "id"))

    for cabine in a_traiter:
        emplacement = cabine.emplacement
        if emplacement.mode_places != "gmd":
            continue  # capacité illimitée : l'absence de place est normale
        prises = set(Cabine.objects
                     .filter(emplacement=emplacement)
                     .exclude(statut="envoye").exclude(place="")
                     .values_list("place", flat=True))
        libres = [p for p in PLACES if p not in prises]
        if libres:
            cabine.place = libres[0]
            cabine.save(update_fields=["place"])
            MouvementCabine.objects.create(
                cabine=cabine, cabine_numero=cabine.numero, chantier=cabine.chantier or "",
                type="rangement", statut_apres=cabine.statut,
                vers=f"{emplacement.code}·{cabine.place}", note=NOTE)
        else:
            code = emplacement.code
            cabine.emplacement = None
            cabine.save(update_fields=["emplacement"])
            MouvementCabine.objects.create(
                cabine=cabine, cabine_numero=cabine.numero, chantier=cabine.chantier or "",
                type="retrait", statut_apres=cabine.statut, depuis=code,
                note=f"Détachée à la reprise : les 3 places de {code} étaient déjà prises")


def revenir(apps, schema_editor):
    """Retire les places attribuées automatiquement (les détachements ne se rejouent pas)."""
    Cabine = apps.get_model("wms", "Cabine")
    MouvementCabine = apps.get_model("wms", "MouvementCabine")
    numeros = list(MouvementCabine.objects.filter(note=NOTE)
                   .values_list("cabine_numero", flat=True))
    Cabine.objects.filter(numero__in=numeros).update(place="")
    MouvementCabine.objects.filter(note=NOTE).delete()


class Migration(migrations.Migration):

    dependencies = [("wms", "0006_mode_de_rangement_emplacement")]

    operations = [migrations.RunPython(attribuer, revenir)]
