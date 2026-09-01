"""Reprise des cabines existantes vers le nouveau jeu de statuts.

L'ancien modèle portait deux informations séparées : `etat`, un libellé libre issu de la
maquette (« Quarantaine »…), et `statut` valant "" ou "sortie". Le nouveau modèle a un
seul `statut` parmi Libre / Quarantaine / Levée de quarantaine / Chargé / Envoyé.

Sans cette reprise, une cabine réellement en quarantaine repasserait silencieusement à
« Libre » — l'inverse de ce que la quarantaine protège.
"""
from django.db import migrations


def _statut_depuis_etat(libelle):
    """Traduit un libellé libre de la maquette vers un statut du nouveau modèle."""
    t = (libelle or "").strip().lower()
    if not t:
        return "libre"
    if "lev" in t:            # « levée de quarantaine », « levee »
        return "levee"
    if "quarantaine" in t:
        return "quarantaine"
    if "charg" in t:          # « chargé », « charge »
        return "charge"
    if "envoy" in t:
        return "envoye"
    return "libre"


def reprendre(apps, schema_editor):
    Cabine = apps.get_model("wms", "Cabine")
    MouvementCabine = apps.get_model("wms", "MouvementCabine")

    for cabine in Cabine.objects.all():
        ancien_etat = cabine.etat or ""
        if (cabine.statut or "") == "sortie":
            cabine.statut = "envoye"
            cabine.envoi_date = cabine.sortie_date or cabine.date
        else:
            cabine.statut = _statut_depuis_etat(ancien_etat)
        cabine.statut_date = cabine.etat_date or cabine.date
        cabine.save(update_fields=["statut", "statut_date", "envoi_date"])

        # Une entrée d'historique pour que la fiche ne soit pas vide dès la reprise.
        # La date est celle de la migration : `date` est en auto_now_add.
        MouvementCabine.objects.create(
            cabine=cabine, cabine_numero=cabine.numero, chantier=cabine.chantier or "",
            type="creation", statut_apres=cabine.statut,
            note=f"Reprise du modèle précédent (état d'origine : {ancien_etat or '—'})",
        )


def revenir(apps, schema_editor):
    """Retour arrière : on remet `statut` dans son ancienne forme ("" ou "sortie")."""
    Cabine = apps.get_model("wms", "Cabine")
    MouvementCabine = apps.get_model("wms", "MouvementCabine")
    MouvementCabine.objects.filter(type="creation",
                                   note__startswith="Reprise du modèle précédent").delete()
    for cabine in Cabine.objects.all():
        cabine.statut = "sortie" if cabine.statut == "envoye" else ""
        cabine.save(update_fields=["statut"])


class Migration(migrations.Migration):

    dependencies = [("wms", "0003_cabines_zones_et_historique")]

    operations = [migrations.RunPython(reprendre, revenir)]
