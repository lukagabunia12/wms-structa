"""Les droits deviennent des cases à cocher, une par geste.

Trois cases ouvraient chacune un bloc entier — « cabines », « référentiel »,
« matières premières ». Donner à quelqu'un le droit de condamner une place lui
donnait aussi celui de supprimer un rack. Elles sont remplacées par douze cases,
une par geste (ou par famille de gestes qui vont ensemble).

Report des anciennes cases, compte par compte :

- « cabines » → entrer et ranger, changer le statut, sortir, corriger ou
  supprimer une fiche : exactement ce que la case ouvrait ;
- « référentiel » → mettre hors service et condamner une place, régler les
  emplacements, régler les modèles, régler les seuils d'alerte MP. **Pas**
  « créer et supprimer des emplacements et des racks » : c'est la demande
  qui a motivé ce découpage, et cette case se coche à la main, pour qui doit
  l'avoir ;
- « matières premières » garde son champ (`droit_mp`) et son effet ;
- les deux cases du fichier de production (l'importer, enregistrer une cabine
  qu'il n'annonce pas) étaient réservées au rôle administrateur : personne ne
  les reçoit d'office, l'administrateur les a par son rôle.

Les anciens champs sont retirés par la migration suivante, une fois les cases
reportées : deux migrations, deux transactions.
"""
from django.db import migrations, models

#: Ce que chaque ancienne case ouvre désormais. Recopié ici plutôt que lu sur le
#: modèle : une migration rejoue demain ce qu'elle fait aujourd'hui.
REPORT = {
    "droit_cab": ["droit_cab_ranger", "droit_cab_statut", "droit_cab_envoyer",
                  "droit_cab_corriger"],
    "droit_ref": ["droit_empl_service", "droit_empl_regler", "droit_modeles",
                  "droit_mp_seuils"],
}

#: Pour revenir en arrière : l'ancienne case est cochée si l'une des nouvelles
#: qu'elle couvrait l'est. « Créer et supprimer » y revient aussi : sans cela un
#: compte qui n'aurait que cette case perdrait tout au retour.
RETOUR = {
    "droit_cab": REPORT["droit_cab"],
    "droit_ref": REPORT["droit_ref"] + ["droit_empl_creer"],
}


def reporter(apps, schema_editor):
    Utilisateur = apps.get_model("wms", "Utilisateur")
    for ancienne, nouvelles in REPORT.items():
        Utilisateur.objects.filter(**{ancienne: True}).update(
            **{champ: True for champ in nouvelles})


def revenir(apps, schema_editor):
    Utilisateur = apps.get_model("wms", "Utilisateur")
    for ancienne, nouvelles in RETOUR.items():
        for champ in nouvelles:
            Utilisateur.objects.filter(**{champ: True}).update(**{ancienne: True})


def case(libelle, aide):
    return models.BooleanField(default=False, help_text=aide, verbose_name=libelle)


class Migration(migrations.Migration):

    dependencies = [
        ("wms", "0027_mp_reglages_alertes_deplacement"),
    ]

    operations = [
        # Le libellé seul : « Role » s'affichait sans accent sur la fiche.
        migrations.AlterField(
            model_name="utilisateur",
            name="role",
            field=models.CharField(
                choices=[("admin", "Administrateur"), ("operateur", "Opérateur"),
                         ("lecture", "Lecture seule")],
                default="operateur", max_length=16, verbose_name="rôle"),
        ),
        migrations.AddField(
            model_name="utilisateur",
            name="droit_cab_ranger",
            field=case("entrer et ranger des cabines",
                       "Enregistrer une cabine annoncée par le fichier de production, la "
                       "ranger, la déplacer, lui ajouter un emplacement."),
        ),
        migrations.AddField(
            model_name="utilisateur",
            name="droit_cab_statut",
            field=case("changer le statut d'une cabine",
                       "La mettre en quarantaine, lever la quarantaine. Sans cette case, "
                       "la question « quel est son état ? » qui suit un rangement est sautée."),
        ),
        migrations.AddField(
            model_name="utilisateur",
            name="droit_cab_envoyer",
            field=case("sortir des cabines de l'entrepôt",
                       "Les envoyer sur chantier (en leur affectant le n° de chantier), et "
                       "remettre en stock une cabine revenue."),
        ),
        migrations.AddField(
            model_name="utilisateur",
            name="droit_cab_corriger",
            field=case("corriger ou supprimer une fiche cabine",
                       "Changer le numéro, le chantier, le modèle d'une cabine mal saisie, "
                       "ou la supprimer."),
        ),
        migrations.AddField(
            model_name="utilisateur",
            name="droit_production",
            field=case("importer le fichier de production",
                       "Remplacer la liste des cabines annoncées par la production "
                       "(écran « Fichier de production »)."),
        ),
        migrations.AddField(
            model_name="utilisateur",
            name="droit_hors_fichier",
            field=case("enregistrer une cabine absente du fichier de production",
                       "Avec un motif, écrit au journal. Demande aussi « entrer et ranger "
                       "des cabines »."),
        ),
        migrations.AlterField(
            model_name="utilisateur",
            name="droit_mp",
            field=case("entrer, sortir et déplacer des matières premières",
                       "Vitrages et cartons : entrée, sortie, changement d'emplacement."),
        ),
        migrations.AddField(
            model_name="utilisateur",
            name="droit_mp_seuils",
            field=case("régler les seuils d'alerte MP",
                       "Le stock sous lequel la cloche signale un code à recommander."),
        ),
        migrations.AddField(
            model_name="utilisateur",
            name="droit_empl_service",
            field=case("mettre hors service, condamner une place",
                       "Mettre un emplacement hors service ou le remettre en service ; "
                       "condamner une place ou la rouvrir."),
        ),
        migrations.AddField(
            model_name="utilisateur",
            name="droit_empl_regler",
            field=case("régler les emplacements",
                       "Leur code, ce qu'ils rangent (cabines, cartons, vitrages), les codes "
                       "MP qu'ils acceptent, leur description."),
        ),
        migrations.AddField(
            model_name="utilisateur",
            name="droit_empl_creer",
            field=case("créer et supprimer des emplacements et des racks",
                       "Un emplacement ne se supprime de toute façon pas tant qu'une cabine "
                       "ou du stock MP y est posé."),
        ),
        migrations.AddField(
            model_name="utilisateur",
            name="droit_modeles",
            field=case("régler la taille des modèles de cabine",
                       "Grand modèle — il prend tout l'emplacement — ou non."),
        ),
        migrations.RunPython(reporter, revenir),
    ]
