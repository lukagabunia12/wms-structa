"""Les familles de matières premières deviennent une table, et un emplacement MP
en accepte plusieurs.

Avant : un emplacement rangeait « des vitrages » OU « des cartons » — l'usage
portait la famille. Désormais l'usage dit « cabines » ou « matières
premières », et les familles acceptées sont une liste (vide : toutes).

Chaque emplacement de vitrages devient un emplacement MP qui n'accepte que les
vitrages ; de même pour les cartons. Ses codes acceptés restent : ils sont de
sa famille. Rien ne bouge sur le terrain, rien ne change dans ce qui entre où.
"""

import django.core.validators
from django.db import migrations, models


LIVREES = [
    # code, nom, pluriel, exemple de recherche, couleur, ordre
    ("vitrage", "Vitrage", "Vitrages", "Ex. vitr.445 ou 445", "#24657C", 1),
    ("carton", "Carton", "Cartons", "Ex. C8.FD ou ESS 1 F", "#7A5524", 2),
]


def semer_familles(apps, schema_editor):
    FamilleMP = apps.get_model("wms", "FamilleMP")
    ArticleMP = apps.get_model("wms", "ArticleMP")
    MouvementMP = apps.get_model("wms", "MouvementMP")
    for code, nom, pluriel, exemple, couleur, ordre in LIVREES:
        FamilleMP.objects.get_or_create(code=code, defaults={
            "nom": nom, "pluriel": pluriel, "exemple": exemple, "couleur": couleur,
            "ordre": ordre})
    # Une famille écrite dans la base sans être livrée : elle reçoit sa ligne,
    # plutôt que de laisser des codes MP orphelins.
    connues = set(FamilleMP.objects.values_list("code", flat=True))
    for code in (set(ArticleMP.objects.values_list("famille", flat=True))
                 | set(MouvementMP.objects.values_list("famille", flat=True))) - connues:
        if code:
            FamilleMP.objects.create(code=code, nom=code.capitalize(),
                                     pluriel=code.capitalize() + "s", ordre=99)


def usages_en_familles(apps, schema_editor):
    Emplacement = apps.get_model("wms", "Emplacement")
    FamilleMP = apps.get_model("wms", "FamilleMP")
    familles = {f.code: f for f in FamilleMP.objects.all()}
    for e in Emplacement.objects.exclude(usage__in=["cabines", "mp"]):
        famille = familles.get(e.usage)
        e.usage = "mp"
        e.save(update_fields=["usage"])
        if famille is not None:
            e.familles.set([famille])


def familles_en_usages(apps, schema_editor):
    """Retour arrière : une famille par emplacement, comme avant. Un emplacement
    qui en acceptait plusieurs — ou toutes — prend celle de son stock, à défaut
    la première."""
    Emplacement = apps.get_model("wms", "Emplacement")
    StockMP = apps.get_model("wms", "StockMP")
    for e in Emplacement.objects.filter(usage="mp"):
        codes = sorted(e.familles.values_list("code", flat=True))
        if len(codes) != 1:
            ligne = (StockMP.objects.filter(emplacement=e).select_related("article")
                     .order_by("pk").first())
            codes = [ligne.article.famille] if ligne else (codes or ["vitrage"])
        e.usage = codes[0]
        e.save(update_fields=["usage"])


class Migration(migrations.Migration):

    dependencies = [
        ("wms", "0030_groupes"),
    ]

    operations = [
        migrations.CreateModel(
            name="FamilleMP",
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
                    models.SlugField(
                        help_text="Court, en minuscules, sans espace ni accent : « quincaillerie ». Il ne change plus une fois créé : le stock et le journal le citent.",
                        max_length=16,
                        unique=True,
                        verbose_name="code",
                    ),
                ),
                (
                    "nom",
                    models.CharField(
                        help_text="Au singulier : « Vitrage ».",
                        max_length=60,
                        verbose_name="nom",
                    ),
                ),
                (
                    "pluriel",
                    models.CharField(
                        help_text="« Vitrages ». Il sert aux titres et aux quantités : « 3 vitrages ».",
                        max_length=60,
                        verbose_name="au pluriel",
                    ),
                ),
                (
                    "exemple",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Écrit en gris dans le champ de recherche : « Ex. vitr.445 ou 445 ».",
                        max_length=80,
                        verbose_name="exemple de recherche",
                    ),
                ),
                (
                    "couleur",
                    models.CharField(
                        default="#5B6B7A",
                        help_text="La couleur de sa pastille, sur le plan des racks et dans les listes.",
                        max_length=7,
                        validators=[
                            django.core.validators.RegexValidator(
                                "^#[0-9A-Fa-f]{6}$", "Une couleur au format #RRVVBB."
                            )
                        ],
                    ),
                ),
                (
                    "ordre",
                    models.PositiveIntegerField(
                        default=0, verbose_name="ordre d'affichage"
                    ),
                ),
                (
                    "actif",
                    models.BooleanField(
                        default=True,
                        help_text="Décochée : elle n'est plus proposée pour un nouveau code. Ce qui existe reste, et se range comme avant.",
                        verbose_name="active",
                    ),
                ),
            ],
            options={
                "verbose_name": "famille MP",
                "verbose_name_plural": "familles MP",
                "ordering": ["ordre", "nom"],
            },
        ),
        migrations.RunPython(semer_familles, migrations.RunPython.noop),
        migrations.AddField(
            model_name="emplacement",
            name="familles",
            field=models.ManyToManyField(
                blank=True,
                help_text="Vide : toutes les familles de matières premières. Sinon, seules celles-ci y entrent.",
                related_name="emplacements",
                to="wms.famillemp",
                verbose_name="familles acceptées",
            ),
        ),
        migrations.RunPython(usages_en_familles, familles_en_usages),
        migrations.AlterField(
            model_name="articlemp",
            name="famille",
            field=models.CharField(
                help_text="Le code d'une famille MP.", max_length=16
            ),
        ),
        migrations.AlterField(
            model_name="emplacement",
            name="codes_acceptes",
            field=models.ManyToManyField(
                blank=True,
                help_text="Vide : tous les codes de ses familles. Sinon, seuls ces codes y entrent.",
                related_name="emplacements_reserves",
                to="wms.articlemp",
                verbose_name="codes acceptés",
            ),
        ),
        migrations.AlterField(
            model_name="emplacement",
            name="usage",
            field=models.CharField(
                choices=[("cabines", "Cabines"), ("mp", "Matières premières")],
                db_index=True,
                default="cabines",
                max_length=16,
                verbose_name="ce qu'il range",
            ),
        ),
        migrations.AlterField(
            model_name="mouvementmp",
            name="famille",
            field=models.CharField(max_length=16),
        ),
    ]
