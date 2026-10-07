"""Reprise des données de SQLite vers un serveur SQL — en deux temps.

Le risque d'une reprise n'est pas qu'elle échoue : c'est qu'elle réussisse **à
moitié**. Une contrainte qui saute au milieu du chargement laisse une base
crédible mais amputée, et personne ne s'en aperçoit avant le jour où une cabine
manque à l'appel.

D'où le manifeste : l'export compte les lignes de chaque table et les inscrit à
côté des données. L'import recompte après chargement et **refuse de valider** si
un seul écart apparaît. Tout se joue dans une transaction : en cas d'écart, la
base cible reste vide plutôt que d'être à moitié remplie.

    # 1. sur l'ancienne configuration (SQLite)
    python manage.py reprise_sql exporter --vers reprise/

    # 2. basculer .env sur le serveur SQL, puis
    python manage.py migrate
    python manage.py reprise_sql importer --depuis reprise/
"""
import json
from pathlib import Path

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction

#: Tables gérées par Django lui-même. Les types de contenu et les permissions
#: sont recréés par `migrate` sur la base cible : les réimporter provoque des
#: doublons de clé, l'erreur classique d'une reprise Django.
EXCLUES = ["contenttypes", "auth.Permission", "admin.logentry", "sessions.session"]

#: Lignes qu'une migration crée d'elle-même sur une base neuve. Deux
#: conséquences, et les deux comptent :
#:
#: - elles ne font pas d'une base « déjà peuplée ». Sans cette liste, une base
#:   fraîchement migrée porte les six grands modèles semés par 0020, et l'import
#:   refusait la reprise en annonçant une base non vide — exactement quand elle
#:   devait marcher, le jour d'une remise en service ;
#: - elles sont retirées AVANT le chargement. Les mêmes modèles arrivent dans le
#:   fichier, et `ModeleCabine.cle` est unique : deux lignes « QUATTRO » de clés
#:   primaires différentes se heurteraient, et la reprise échouerait à moitié
#:   faite si elle n'était pas dans une transaction.
#:
#: La base des codes MP (vitrages, cartons), semée par 0026, suit la même règle :
#: `ArticleMP.code` est unique, et le stock qui la cite arrive dans le fichier.
SEMEES_PAR_MIGRATION = ["wms.modelecabine", "wms.articlemp"]

FICHIER_DONNEES = "donnees.json"
FICHIER_MANIFESTE = "manifeste.json"


def _comptages():
    """Nombre de lignes par modèle repris, dans un ordre stable."""
    exclus = {e.lower() for e in EXCLUES}
    resultat = {}
    for modele in apps.get_models():
        # Un modèle mandataire (`proxy`) partage la table de son modèle concret :
        # le compter comptabiliserait deux fois les mêmes lignes, et le manifeste
        # annoncerait un total qui ne correspond à rien.
        if modele._meta.proxy:
            continue
        etiquette = f"{modele._meta.app_label}.{modele._meta.model_name}"
        if etiquette in exclus or modele._meta.app_label in exclus:
            continue
        resultat[etiquette] = modele.objects.count()
    return dict(sorted(resultat.items()))


def modeles_a_recaler():
    """Modèles dont la séquence d'auto-incrément doit être recalée après import.

    `include_auto_created=True` est le point clé : les tables de liaison
    ManyToMany (`wms_utilisateur_groups`, `wms_utilisateur_user_permissions`)
    sont créées par Django et **absentes de `get_models()` par défaut**. Leur
    séquence n'était donc jamais recalée, et la première association après la
    reprise tombait en « duplicate key » — reproduit sur PostgreSQL 16. Django
    ne les rattrape pas non plus : son `sequence_reset_sql` ne parcourt que
    `local_fields`, jamais les tables de liaison.

    Le filtre est celui du manifeste, pas `app_label == "wms"` : on recale ce
    qu'on importe. `auth.Group` en fait partie, et était lui aussi oublié.
    """
    exclus = {e.lower() for e in EXCLUES}
    return [
        m for m in apps.get_models(include_auto_created=True)
        if not m._meta.proxy
        and f"{m._meta.app_label}.{m._meta.model_name}" not in exclus
        and m._meta.app_label not in exclus
    ]


class Command(BaseCommand):
    help = ("Exporte les données vers un dossier, puis les importe sur le serveur "
            "SQL en vérifiant que rien ne manque.")

    def add_arguments(self, parseur):
        parseur.add_argument("action", choices=["exporter", "importer", "verifier"])
        parseur.add_argument("--vers", default="reprise", help="dossier de sortie")
        parseur.add_argument("--depuis", default="reprise", help="dossier d'entrée")
        parseur.add_argument(
            "--sur-base-non-vide", action="store_true",
            help="autorise l'import alors que la base cible contient déjà des données")

    def handle(self, *args, **o):
        {"exporter": self.exporter, "importer": self.importer,
         "verifier": self.verifier}[o["action"]](o)

    # --- Export ------------------------------------------------------------
    def exporter(self, o):
        dossier = Path(o["vers"])
        dossier.mkdir(parents=True, exist_ok=True)
        comptes = _comptages()
        total = sum(comptes.values())
        if not total:
            raise CommandError("La base courante est vide : rien à exporter.")

        fichier = dossier / FICHIER_DONNEES
        with fichier.open("w", encoding="utf-8") as sortie:
            # Sans `--natural-*` : on veut une copie fidèle, clés primaires
            # comprises. Les clés naturelles renuméroteraient les lignes, ce qui
            # rendrait le contrôle de comptage moins parlant et casserait toute
            # référence à un identifiant. Le projet n'a aucune clé étrangère
            # générique, seul cas où les clés naturelles seraient nécessaires.
            call_command("dumpdata", *(f"--exclude={e}" for e in EXCLUES),
                         indent=2, stdout=sortie)

        (dossier / FICHIER_MANIFESTE).write_text(
            json.dumps({"moteur": connection.vendor, "comptages": comptes,
                        "total": total}, indent=2, ensure_ascii=False),
            encoding="utf-8")

        self.stdout.write(f"  source : {connection.vendor}")
        for nom, n in comptes.items():
            if n:
                self.stdout.write(f"    {nom:28} {n:>7}")
        self.stdout.write(self.style.SUCCESS(
            f"OK — {total} lignes exportées dans {dossier}/. "
            "Basculez .env sur le serveur SQL, jouez `migrate`, puis "
            f"`reprise_sql importer --depuis {dossier}`."))

    # --- Import ------------------------------------------------------------
    def importer(self, o):
        dossier = Path(o["depuis"])
        fichier, manifeste_fichier = dossier / FICHIER_DONNEES, dossier / FICHIER_MANIFESTE
        for f in (fichier, manifeste_fichier):
            if not f.is_file():
                raise CommandError(f"Fichier manquant : {f}. Lancez d'abord `exporter`.")
        manifeste = json.loads(manifeste_fichier.read_text(encoding="utf-8"))

        if connection.vendor == manifeste["moteur"] == "sqlite":
            self.stdout.write(self.style.WARNING(
                "Attention : la cible est encore SQLite. Avez-vous basculé .env ?"))

        semees = {e.lower() for e in SEMEES_PAR_MIGRATION}
        deja = {k: v for k, v in _comptages().items()
                if v and k.lower() not in semees}
        if deja and not o["sur_base_non_vide"]:
            detail = ", ".join(f"{k}={v}" for k, v in deja.items())
            raise CommandError(
                f"La base cible n'est pas vide ({detail}). Un import par-dessus des "
                "données existantes produit des doublons de clé. Repartez d'une base "
                "neuve, ou relancez avec --sur-base-non-vide si vous savez ce que "
                "vous faites.")

        # Tout dans une transaction : si le contrôle échoue, la base cible reste
        # dans l'état où on l'a trouvée — vide — plutôt qu'à moitié remplie.
        with transaction.atomic():
            # Les lignes semées par les migrations partent d'abord : celles du
            # fichier les remplacent, et une contrainte d'unicité ne doit pas
            # faire échouer une reprise pour une donnée de référence.
            for etiquette in SEMEES_PAR_MIGRATION:
                app_label, nom = etiquette.split(".")
                apps.get_model(app_label, nom).objects.all().delete()
            call_command("loaddata", str(fichier))
            ecarts = self._ecarts(manifeste["comptages"])
            if ecarts:
                for ligne in ecarts:
                    self.stderr.write(self.style.ERROR("  " + ligne))
                raise CommandError(
                    "Reprise annulée : les comptages ne correspondent pas. "
                    "Rien n'a été écrit.")
            self._recaler_sequences()

        self.stdout.write(self.style.SUCCESS(
            f"OK — {manifeste['total']} lignes reprises sur {connection.vendor}, "
            "comptages identiques à la source."))
        self.stdout.write("Vérifiez maintenant une connexion et un scan avant "
                          "d'ouvrir le service aux postes.")

    # --- Vérification seule ------------------------------------------------
    def verifier(self, o):
        manifeste_fichier = Path(o["depuis"]) / FICHIER_MANIFESTE
        if not manifeste_fichier.is_file():
            raise CommandError(f"Manifeste introuvable : {manifeste_fichier}")
        manifeste = json.loads(manifeste_fichier.read_text(encoding="utf-8"))
        ecarts = self._ecarts(manifeste["comptages"])
        if ecarts:
            for ligne in ecarts:
                self.stderr.write(self.style.ERROR("  " + ligne))
            raise CommandError("La base ne correspond pas au manifeste.")
        self.stdout.write(self.style.SUCCESS(
            f"OK — {manifeste['total']} lignes, conformes au manifeste."))

    def _ecarts(self, attendus):
        actuels = _comptages()
        return [f"{nom:28} attendu {n:>7}  trouvé {actuels.get(nom, 0):>7}"
                for nom, n in attendus.items() if actuels.get(nom, 0) != n]

    @staticmethod
    def _recaler_sequences():
        """Remet les compteurs d'auto-incrément au-dessus des clés importées.

        `loaddata` écrit les clés primaires telles quelles. Sur PostgreSQL, la
        séquence reste à 1 : la première création après la reprise réclamerait la
        clé 1, déjà prise, et tomberait en « duplicate key ». Django sait recaler,
        encore faut-il le lui demander.
        """
        if connection.vendor != "postgresql":
            return
        instructions = connection.ops.sequence_reset_sql(
            no_style(), modeles_a_recaler())
        with connection.cursor() as curseur:
            for sql in instructions:
                curseur.execute(sql)
