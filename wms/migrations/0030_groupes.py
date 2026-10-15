"""Les groupes de comptes : les cases du WMS, réglées une fois pour toute une équipe.

Les anciens profils (« Cariste », « Gestionnaire »…) n'étaient que des actions
qui recopiaient des cases sur chaque fiche. Ils deviennent des groupes, et un
compte dont les cases forment EXACTEMENT un profil est rangé dans le groupe
correspondant, ses cases personnelles vidées : ses droits effectifs ne changent
pas d'une case. Les autres comptes gardent leurs cases telles quelles.

Les profils sont recopiés ici, pas importés : une migration doit rejouer le
même résultat dans un an, quel que soit le code de l'administration alors.
"""

import django.db.models.deletion
from django.db import migrations, models


CABINES = ["cab_ranger", "cab_statut", "cab_envoyer", "cab_corriger"]
GROUPES = [
    ("Caristes", "Entrer, ranger, sortir les cabines.", CABINES),
    ("Caristes + MP", "Les cabines, et les matières premières.", CABINES + ["mp"]),
    ("Matières premières", "Entrer, sortir et déplacer les matières premières.", ["mp"]),
    ("Gestionnaires",
     "Tout le quotidien, réglages compris — sans créer d'emplacements ni importer "
     "le fichier de production.",
     CABINES + ["mp", "mp_seuils", "empl_service", "empl_regler", "modeles"]),
]
DROITS = ["cab_ranger", "cab_statut", "cab_envoyer", "cab_corriger", "production",
          "hors_fichier", "mp", "mp_seuils", "empl_service", "empl_regler", "empl_creer",
          "modeles"]


def creer_groupes(apps, schema_editor):
    Groupe = apps.get_model("wms", "Groupe")
    Utilisateur = apps.get_model("wms", "Utilisateur")
    for nom, description, cases in GROUPES:
        groupe, _ = Groupe.objects.get_or_create(
            nom=nom, defaults={"description": description,
                               **{f"droit_{d}": d in cases for d in DROITS}})
        for u in Utilisateur.objects.filter(role="operateur", is_superuser=False,
                                            groupe__isnull=True):
            if {d for d in DROITS if getattr(u, f"droit_{d}")} == set(cases):
                u.groupe = groupe
                for d in DROITS:
                    setattr(u, f"droit_{d}", False)
                u.save(update_fields=["groupe"] + [f"droit_{d}" for d in DROITS])


def rendre_les_cases(apps, schema_editor):
    """Retour arrière : chaque compte reprend sur sa fiche les cases de son groupe."""
    Utilisateur = apps.get_model("wms", "Utilisateur")
    for u in Utilisateur.objects.exclude(groupe=None).select_related("groupe"):
        for d in DROITS:
            if getattr(u.groupe, f"droit_{d}"):
                setattr(u, f"droit_{d}", True)
        u.save()


class Migration(migrations.Migration):

    dependencies = [
        ("wms", "0029_retrait_anciens_droits"),
    ]

    operations = [
        migrations.CreateModel(
            name="Groupe",
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
                    "droit_cab_ranger",
                    models.BooleanField(
                        default=False,
                        help_text="Enregistrer une cabine annoncée par le fichier de production, la ranger, la déplacer, lui ajouter un emplacement.",
                        verbose_name="entrer et ranger des cabines",
                    ),
                ),
                (
                    "droit_cab_statut",
                    models.BooleanField(
                        default=False,
                        help_text="La mettre en quarantaine, lever la quarantaine. Sans cette case, la question « quel est son état ? » qui suit un rangement est sautée.",
                        verbose_name="changer le statut d'une cabine",
                    ),
                ),
                (
                    "droit_cab_envoyer",
                    models.BooleanField(
                        default=False,
                        help_text="Les envoyer sur chantier (en leur affectant le n° de chantier), et remettre en stock une cabine revenue.",
                        verbose_name="sortir des cabines de l'entrepôt",
                    ),
                ),
                (
                    "droit_cab_corriger",
                    models.BooleanField(
                        default=False,
                        help_text="Changer le numéro, le chantier, le modèle d'une cabine mal saisie, ou la supprimer.",
                        verbose_name="corriger ou supprimer une fiche cabine",
                    ),
                ),
                (
                    "droit_production",
                    models.BooleanField(
                        default=False,
                        help_text="Remplacer la liste des cabines annoncées par la production (écran « Fichier de production »).",
                        verbose_name="importer le fichier de production",
                    ),
                ),
                (
                    "droit_hors_fichier",
                    models.BooleanField(
                        default=False,
                        help_text="Avec un motif, écrit au journal. Demande aussi « entrer et ranger des cabines ».",
                        verbose_name="enregistrer une cabine absente du fichier de production",
                    ),
                ),
                (
                    "droit_mp",
                    models.BooleanField(
                        default=False,
                        help_text="Vitrages et cartons : entrée, sortie, changement d'emplacement.",
                        verbose_name="entrer, sortir et déplacer des matières premières",
                    ),
                ),
                (
                    "droit_mp_seuils",
                    models.BooleanField(
                        default=False,
                        help_text="Le stock sous lequel la cloche signale un code à recommander.",
                        verbose_name="régler les seuils d'alerte MP",
                    ),
                ),
                (
                    "droit_empl_service",
                    models.BooleanField(
                        default=False,
                        help_text="Mettre un emplacement hors service ou le remettre en service ; condamner une place ou la rouvrir.",
                        verbose_name="mettre hors service, condamner une place",
                    ),
                ),
                (
                    "droit_empl_regler",
                    models.BooleanField(
                        default=False,
                        help_text="Leur code, ce qu'ils rangent (cabines, cartons, vitrages), les codes MP qu'ils acceptent, leur description.",
                        verbose_name="régler les emplacements",
                    ),
                ),
                (
                    "droit_empl_creer",
                    models.BooleanField(
                        default=False,
                        help_text="Un emplacement ne se supprime de toute façon pas tant qu'une cabine ou du stock MP y est posé.",
                        verbose_name="créer et supprimer des emplacements et des racks",
                    ),
                ),
                (
                    "droit_modeles",
                    models.BooleanField(
                        default=False,
                        help_text="Grand modèle — il prend tout l'emplacement — ou non.",
                        verbose_name="régler la taille des modèles de cabine",
                    ),
                ),
                ("nom", models.CharField(max_length=80, unique=True)),
                (
                    "description",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "modifie_le",
                    models.DateTimeField(auto_now=True, verbose_name="modifié le"),
                ),
            ],
            options={
                "verbose_name": "groupe",
                "verbose_name_plural": "groupes",
                "ordering": ["nom"],
            },
        ),
        migrations.AddField(
            model_name="utilisateur",
            name="groupe",
            field=models.ForeignKey(
                blank=True,
                help_text="Ses droits viennent du groupe. Les cases cochées plus bas s'y ajoutent : ce sont ses droits en plus.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="membres",
                to="wms.groupe",
            ),
        ),
        migrations.RunPython(creer_groupes, rendre_les_cases),
    ]
