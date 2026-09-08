import logging
import re
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db.models import (Count, IntegerField, Max, OuterRef, Prefetch, Q,
                              Subquery, Sum)
from django.db.models.functions import Coalesce
from django.db.models.deletion import ProtectedError
import time
from django.conf import settings
from django.shortcuts import render
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError as ErreurAPI
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from . import (export_inventaire, lecture_fiche, ocr_fiche, services, services_cabines,
               services_import)
from .models import (Article, Cabine, CabineAttendue, Categorie, Occupation,
                     Emplacement, EtatCabine, ModeleCabine, Mouvement, MouvementCabine,
                     Reception, Stock, Zone)
from .permissions import EstAdministrateur
from .serializers import (ArticleSerializer, CabineAttendueSerializer, CabineSerializer,
                          OccupationSerializer, CategorieSerializer,
                          EmplacementSerializer, EtatCabineSerializer,
                          ModeleCabineSerializer, MouvementCabineSerializer,
                          MouvementSerializer, ReceptionSerializer, StockSerializer,
                          ZoneSerializer)

logger = logging.getLogger(__name__)

#: Au-delà de ce délai sans le moindre mouvement, une cabine est signalée comme stagnante.
SEUIL_IMMOBILE_JOURS = 7


class CategorieViewSet(viewsets.ModelViewSet):
    queryset = Categorie.objects.all()
    serializer_class = CategorieSerializer
    droit_ecriture = "ref"


class EmplacementViewSet(viewsets.ModelViewSet):
    queryset = Emplacement.objects.all()
    serializer_class = EmplacementSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["code", "zone", "description"]
    ordering_fields = ["code", "zone_cabine__nom", "occupees", "rack"]
    ordering = ["code"]
    #: Un seul droit pour toutes les écritures de la vue, actions comprises :
    #: `supprimer-rack` est un POST, il est donc couvert. L'écrire ici évite
    #: qu'une action future s'ouvre par omission.
    droit_ecriture = "ref"

    def get_queryset(self):
        """Emplacements avec leurs cabines, filtrables par cabine, chantier ou statut.

        Les cabines sont préchargées : l'écran « Emplacements » afficherait sinon une
        requête par ligne. Le compte de places occupées passe par une sous-requête et
        non par un Count sur la jointure, sinon les filtres portant sur `cabines__*`
        restreindraient aussi le comptage.
        """
        p = self.request.query_params
        # « Présentes » et non « avec une place » : en capacité illimitée les
        # cabines n'ont pas de place, elles occupent tout de même l'emplacement.
        actifs = (Occupation.objects.exclude(cabine__statut=Cabine.ENVOYE)
                  .select_related("cabine"))
        occupees = (actifs.filter(emplacement=OuterRef("pk"))
                    .order_by().values("emplacement")
                    .annotate(n=Count("pk")).values("n"))
        qs = (Emplacement.objects
              .select_related("zone_cabine")
              .prefetch_related(Prefetch("occupations", queryset=actifs.order_by("place"),
                                         to_attr="occupations_actives"))
              .annotate(occupees=Coalesce(Subquery(occupees, output_field=IntegerField()), 0)))

        zone = _filtre_id(p, "zone")
        if zone is not None:
            qs = qs.filter(zone_cabine_id=zone)
        if _actif(p, "sans_zone"):
            qs = qs.filter(zone_cabine__isnull=True)

        # Réunis dans un SEUL filter() : trois .filter() enchaînés créeraient trois
        # jointures indépendantes et retiendraient un emplacement dont une cabine porte
        # le bon chantier et une autre le bon statut, sans qu'aucune n'ait les deux.
        surCabine = Q()
        for param, lookup in (("cabine", "occupations__cabine__numero__icontains"),
                              ("chantier", "occupations__cabine__chantier__icontains"),
                              ("statut", "occupations__cabine__statut"),
                              ("type", "occupations__cabine__type_cabine")):
            if p.get(param):
                surCabine &= Q(**{lookup: p[param]})
        if surCabine:
            qs = qs.filter(surCabine & ~Q(occupations__cabine__statut=Cabine.ENVOYE)).distinct()

        if p.get("mode"):
            qs = qs.filter(mode_places=p["mode"])
        if p.get("rack"):
            qs = qs.filter(rack__iexact=p["rack"].strip())
        colonne = _filtre_id(p, "colonne")
        if colonne is not None:
            qs = qs.filter(colonne=colonne)

        occupation = p.get("occupation")
        total_places = len(Cabine.PLACES)
        if occupation == "libre":
            qs = qs.filter(occupees=0)
        elif occupation == "complet":
            # Un emplacement illimité n'est jamais complet.
            qs = qs.filter(mode_places=Emplacement.GD, occupees__gte=total_places)
        elif occupation == "partiel":
            qs = qs.filter(occupees__gt=0).exclude(
                Q(mode_places=Emplacement.GD) & Q(occupees__gte=total_places))
        return qs

    @action(detail=True, methods=["get"])
    def places(self, request, pk=None):
        """Occupation des places de l'emplacement scanné.

        C'est ce que consomme l'écran de rangement : il ne propose que les places
        libres, et bloque quand elles sont prises.

        `?pour_cabine=<id>` change la réponse, et c'est nécessaire : un grand
        modèle ne se glisse pas à côté d'une autre cabine. Sans cela l'écran
        proposerait « Gauche » à une cabine qui prend la travée entière, et le
        serveur refuserait au dernier moment — après que le cariste l'a posée.

        Le paramètre ne s'appelle pas `cabine` : ce nom est déjà celui du filtre
        de la LISTE des emplacements (« ceux qui portent telle cabine »), lu par
        le même `get_queryset()`. Un `?cabine=12` sur cette action-ci filtrait
        donc l'emplacement lui-même, et la fiche répondait 404.
        """
        emplacement = self.get_object()
        cabine = None
        demande = (request.query_params.get("pour_cabine") or "").strip()
        if demande.isdigit():
            cabine = Cabine.objects.filter(pk=int(demande)).first()
        occupees = services_cabines.occupation(emplacement)
        presentes = services_cabines.cabines_presentes(emplacement)
        return Response({
            "emplacement": emplacement.id,
            "code": emplacement.code,
            "zone": emplacement.zone_cabine.nom if emplacement.zone_cabine_id else None,
            "mode_places": emplacement.mode_places,
            "mode_libelle": emplacement.get_mode_places_display(),
            "illimite": emplacement.illimite,
            # Vide en capacité illimitée : il n'y a pas de place nommée à proposer.
            "places": [
                {
                    "code": code,
                    "libelle": libelle,
                    "libre": occupees[code] is None,
                    "cabine": (CabineSerializer(occupees[code].cabine).data
                               if occupees[code] is not None else None),
                    # Lequel de ses emplacements, quand la cabine en occupe plusieurs.
                    "occupation": (OccupationSerializer(occupees[code]).data
                                   if occupees[code] is not None else None),
                }
                for code, libelle in Cabine.PLACES
            ] if not emplacement.illimite else [],
            "cabines": CabineSerializer(presentes, many=True).data,
            "nb_cabines": presentes.count(),
            "libres": services_cabines.places_libres(emplacement, cabine),
            "complet": services_cabines.est_complet(emplacement, cabine),
            # Ce que l'écran doit dire de CETTE cabine, quand il en tient une.
            "pour_cabine": ({
                "id": cabine.id,
                "numero": cabine.numero,
                "modele": cabine.modele,
                "toute_la_travee": cabine.prend_toute_la_travee,
            } if cabine is not None else None),
        })

    @action(detail=False, methods=["post"])
    def generer(self, request):
        """Crée un rack entier — ou en donne l'aperçu, sans rien écrire.

        `apercu: true` renvoie exactement les mêmes codes que la création, calculés
        par le même code : l'opérateur valide donc ce qu'il a réellement lu.
        """
        d = request.data
        parametres = {
            "prefixe": d.get("prefixe"),
            "debut": d.get("debut"),
            "pas": d.get("pas", 10),
            "colonnes": d.get("colonnes"),
            "niveaux": d.get("niveaux", 1),
            "separateur": d.get("separateur", ""),
        }
        try:
            if d.get("apercu"):
                return Response(services.apercu_rack(**parametres))
            zone = None
            if d.get("zone_cabine"):
                zone = self._zone_requise(d.get("zone_cabine"))
            resultat = services.generer_rack(
                zone_cabine=zone, mode_places=d.get("mode_places"),
                description=(d.get("description") or "")[:255], **parametres)
        except ValidationError as e:
            return Response({"erreur": e.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(resultat, status=status.HTTP_201_CREATED)

    @staticmethod
    def _zone_requise(brut):
        try:
            return Zone.objects.get(pk=brut)
        except (Zone.DoesNotExist, ValueError, TypeError):
            raise ErreurAPI({"erreur": [f"Zone introuvable : « {brut} »."]})

    @action(detail=False, methods=["get"])
    def racks(self, request):
        """Inventaire des racks : ce que l'écran d'impression propose à imprimer."""
        lignes = (Emplacement.objects.exclude(rack="")
                  .values("rack")
                  .annotate(colonnes=Count("colonne", distinct=True),
                            niveaux=Count("niveau", distinct=True),
                            emplacements=Count("pk"))
                  .order_by("rack"))
        # `liste_colonnes` et non `colonnes` : cette dernière porte déjà le compte
        # calculé au-dessus, et l'écrasement passerait inaperçu côté écran.
        bornes = {}
        for e in Emplacement.objects.exclude(rack="").order_by("rack", "colonne", "niveau"):
            b = bornes.setdefault(e.rack, {"premier": e.code, "dernier": e.code,
                                           "liste_colonnes": []})
            b["dernier"] = e.code
            if e.colonne is not None and e.colonne not in b["liste_colonnes"]:
                b["liste_colonnes"].append(e.colonne)
        return Response([{**ligne, **bornes.get(ligne["rack"], {})} for ligne in lignes])

    @action(detail=False, methods=["get"], url_path="rack-diagnostic")
    def rack_diagnostic(self, request):
        """Ce que la suppression d'un rack effacerait — sans rien écrire.

        En lecture, donc ouvert à tout compte authentifié : voir les conséquences
        d'une suppression n'est pas la faire, et l'écran doit pouvoir les montrer
        avant de proposer le bouton.
        """
        try:
            return Response(services.diagnostic_rack(request.query_params.get("rack"),
                                                     request.user))
        except ValidationError as e:
            return Response({"erreur": e.messages}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["get"], url_path="lot-diagnostic")
    def lot_diagnostic(self, request):
        """Ce que la suppression d'une sélection effacerait — sans rien écrire.

        Les identifiants arrivent en une liste séparée par des virgules :
        `?ids=12,13,14`. En lecture, donc ouvert comme `rack-diagnostic` — voir
        les conséquences d'une suppression n'est pas la faire.
        """
        brut = request.query_params.get("ids") or ""
        try:
            return Response(services.diagnostic_lot(brut.split(","), request.user))
        except ValidationError as e:
            return Response({"erreur": e.messages}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"], url_path="supprimer-lot")
    def supprimer_lot(self, request):
        """Supprime une sélection d'emplacements, ou aucun. Droit « référentiel »."""
        d = request.data
        ids = d.get("ids")
        if isinstance(ids, str):
            ids = ids.split(",")
        try:
            resultat = services.supprimer_lot(
                ids,
                force=bool(d.get("force")),
                utilisateur=request.user,
                motif=(d.get("motif") or "")[:180])
        except ValidationError as e:
            return Response({"erreur": e.messages}, status=status.HTTP_400_BAD_REQUEST)
        except ProtectedError:
            return Response({"erreur": ["Un emplacement de la sélection est encore référencé."]},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(resultat)

    @action(detail=False, methods=["post"], url_path="supprimer-rack")
    def supprimer_rack(self, request):
        """Supprime tout un rack, ou rien. Exige le droit « référentiel »."""
        d = request.data
        try:
            resultat = services.supprimer_rack(
                d.get("rack"),
                force=bool(d.get("force")),
                utilisateur=request.user,
                motif=(d.get("motif") or "")[:180])
        except ValidationError as e:
            return Response({"erreur": e.messages}, status=status.HTTP_400_BAD_REQUEST)
        except ProtectedError:
            return Response({"erreur": ["Un emplacement du rack est encore référencé."]},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(resultat)

    def perform_destroy(self, instance):
        """Suppression sécurisée — règles dans `services.diagnostic_suppression`.

        Trois garde-fous : cabines rangées (SET_NULL les aurait détachées en
        silence), stock non nul, présence dans l'historique. `?force=1` lève
        ceux que `services.suppression_forcable` autorise pour ce compte : la
        suppression avec stock est réservée aux administrateurs, celle des
        cabines rangées n'est ouverte à personne.
        """
        force = _actif(self.request.query_params, "force")
        motif = (self.request.query_params.get("motif") or "")[:180]
        try:
            services.supprimer_emplacement(instance, force=force,
                                           utilisateur=self.request.user, motif=motif)
        except ValidationError as e:
            raise ErreurAPI({"erreur": e.messages})
        except ProtectedError:
            raise ErreurAPI({"erreur": [
                "Impossible de supprimer cet emplacement : il est encore référencé."
            ]})


class ArticleViewSet(viewsets.ModelViewSet):
    queryset = Article.objects.select_related("categorie", "emplacement_defaut").all()
    serializer_class = ArticleSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["ref", "ean", "designation"]
    ordering_fields = ["ref", "designation", "total_stock"]
    # Sans ordre explicite, l'annotation `Sum` pose un GROUP BY : Django écarte alors
    # l'ordre par défaut du modèle et la pagination ne garantit plus la composition
    # des pages (un article pouvait apparaître deux fois, un autre jamais).
    ordering = ["ref"]
    droit_ecriture = "ref"

    def get_queryset(self):
        """Le total de stock est agrégé en base plutôt que reconstitué par le client.

        L'écran « Stock » a besoin de la quantité totale par article : sans cette
        annotation, il faudrait télécharger toutes les lignes de stock et les
        additionner côté navigateur.
        """
        return (Article.objects
                .select_related("categorie", "emplacement_defaut")
                .annotate(
                    total_stock=Sum("lignes_stock__qte"),
                    nb_emplacements=Count("lignes_stock",
                                          filter=Q(lignes_stock__qte__gt=0), distinct=True),
                ))

    def perform_create(self, serializer):
        if not serializer.validated_data.get("ref"):
            serializer.save(ref=services.generer_ref(serializer.validated_data.get("categorie")))
        else:
            serializer.save()


#: Les écritures qu'un lien, un signet ou un script peuvent porter pour « oui ».
#: `config.settings._bool` accepte les mêmes : une seule définition du vrai dans
#: tout le projet, sinon `?toutes=TRUE` marche à un endroit et pas à l'autre.
_VRAI = ("1", "true", "vrai", "oui", "yes", "on")


def _actif(params, nom):
    """Un drapeau d'URL est-il posé ? Insensible à la casse et à l'écriture."""
    return (params.get(nom) or "").strip().lower() in _VRAI


def _filtre_id(params, nom):
    """Lit un filtre d'identifiant, en 400 explicite si la valeur n'est pas numérique.

    Sans ce contrôle, `?article=abc` remontait en ValueError (500).
    """
    brut = params.get(nom)
    if brut is None or brut == "":
        return None
    try:
        return int(brut)
    except (TypeError, ValueError):
        raise ErreurAPI({"erreur": [f"Le filtre « {nom} » doit être un identifiant numérique."]})


class StockViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StockSerializer

    def get_queryset(self):
        qs = Stock.objects.select_related("article", "emplacement").all()
        a = _filtre_id(self.request.query_params, "article")
        e = _filtre_id(self.request.query_params, "emplacement")
        if a is not None:
            qs = qs.filter(article_id=a)
        if e is not None:
            qs = qs.filter(emplacement_id=e)
        return qs


class MouvementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MouvementSerializer

    def get_queryset(self):
        qs = Mouvement.objects.select_related("article", "emplacement").all()
        a = _filtre_id(self.request.query_params, "article")
        if a is not None:
            qs = qs.filter(article_id=a)
        return qs


class ReceptionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Reception.objects.select_related("article", "emplacement").all()
    serializer_class = ReceptionSerializer


class EtatCabineViewSet(viewsets.ModelViewSet):
    queryset = EtatCabine.objects.all()
    serializer_class = EtatCabineSerializer
    droit_ecriture = "cab"


class ZoneViewSet(viewsets.ModelViewSet):
    """Zones de cabines : « À ranger », « Sortie prod », « Attente départ »…"""
    queryset = Zone.objects.all()
    serializer_class = ZoneSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["nom", "description"]
    ordering_fields = ["ordre", "nom"]
    droit_ecriture = "cab"

    def perform_destroy(self, instance):
        """Refuse de supprimer une zone encore rattachée à des emplacements.

        `Emplacement.zone_cabine` est en SET_NULL : la suppression ne remontait
        aucune erreur, elle « débranchait » les emplacements en silence. Le suivi
        du processus les reclassait alors tous en simple rangement, sans que
        personne ne comprenne pourquoi l'étape « attente de départ » s'était vidée.
        """
        rattaches = instance.emplacements.count()
        if rattaches:
            raise ErreurAPI({"erreur": [
                f"{rattaches} emplacement(s) sont rattachés à la zone « {instance.nom} ». "
                "Rattachez-les à une autre zone avant de la supprimer — ou désactivez "
                "simplement celle-ci."
            ]})
        instance.delete()


class CabineViewSet(viewsets.ModelViewSet):
    """Cabines actives par défaut ; les cabines envoyées sont dans /archives/."""
    queryset = Cabine.objects.prefetch_related(
        "occupations__emplacement__zone_cabine").all()
    serializer_class = CabineSerializer
    # La recherche libre est traitée dans `get_queryset` : « 260347 » doit
    # ramener la cabine 26_03_47, ce que `SearchFilter` ne sait pas faire.
    filter_backends = [OrderingFilter]
    ordering_fields = ["numero", "chantier", "date", "statut", "modele",
                       "type_cabine", "derniere_activite_date"]
    droits_par_action = {
        "create": "cab", "update": "cab", "partial_update": "cab", "destroy": "cab",
        "ranger": "cab", "sortir": "cab", "statut": "cab", "envoyer": "cab",
        "chantier": "cab", "reprendre": "cab",
    }

    def get_queryset(self):
        """Le parc, filtré par ce que l'écran demande.

        Le corps est découpé par question posée — archives, recherche libre,
        égalités simples, position dans l'entrepôt, ancienneté. Chaque filtre
        garde la raison d'être écrite au-dessus de lui ; c'est ce qui permet de
        les relire un par un plutôt que d'affronter cent lignes d'affilée.
        """
        qs = self._parc_annote()
        p = self.request.query_params
        for etape_de_filtrage in (self._filtrer_archives, self._filtrer_recherche,
                                  self._filtrer_egalites, self._filtrer_position,
                                  self._filtrer_anciennete, self._filtrer_etape_processus):
            qs = etape_de_filtrage(qs, p)
        return qs

    @staticmethod
    def _parc_annote():
        """Le parc, prêt à filtrer.

        `derniere_activite_date` est annotée ici une fois pour toutes : sans
        elle, chaque ligne d'une liste redemanderait son historique.
        """
        dernier = (MouvementCabine.objects.filter(cabine=OuterRef("pk"))
                   .order_by("-date").values("date")[:1])
        return (Cabine.objects
                .prefetch_related("occupations__emplacement__zone_cabine")
                .annotate(derniere_activite_date=Coalesce(Subquery(dernier), "date")))

    def _filtrer_archives(self, qs, p):
        """Les cabines envoyées sont archivées : elles n'encombrent pas les listes.

        Le filtre ne s'applique QU'aux listes : une cabine envoyée doit rester
        consultable en détail, sinon son historique — la raison d'être des
        archives — renverrait 404.
        """
        if self.action == "archives" or _actif(p, "archivees"):
            return qs.filter(statut=Cabine.ENVOYE)
        # L'export suit la liste : un inventaire du stock ne compte pas ce qui
        # est déjà parti. Le détail d'une cabine, lui, reste toujours lisible.
        if self.action in ("list", "export") and not _actif(p, "toutes"):
            return qs.exclude(statut=Cabine.ENVOYE)
        return qs

    @staticmethod
    def _filtrer_recherche(qs, p):
        """Recherche libre du bandeau « Parc » : n°, chantier et modèle à la fois.

        Six chiffres d'affilée sont ambigus — c'est aussi bien un n° de chantier
        qu'un n° de cabine tapé sans ses tirets bas. On répond aux deux plutôt
        que de ne rien ramener : sur ce champ-là, le masque XX_XX_XX ne peut pas
        être imposé, puisqu'on y cherche aussi un chantier et un modèle.
        """
        terme = (p.get("search") or "").strip()
        if not terme:
            return qs
        filtre = (Q(numero__icontains=terme) | Q(chantier__icontains=terme)
                  | Q(modele__icontains=terme))
        chiffres = re.sub(r"\D", "", terme)
        if len(chiffres) == 6 and not re.search(r"[A-Za-z]", terme):
            filtre |= Q(numero__icontains="{}_{}_{}".format(
                chiffres[:2], chiffres[2:4], chiffres[4:6]))
        return qs.filter(filtre)

    @staticmethod
    def _filtrer_egalites(qs, p):
        """Les filtres qui portent sur un champ de la cabine elle-même."""
        for param, champ in [("numero", "numero__icontains"),
                             ("chantier", "chantier__icontains"),
                             ("statut", "statut"),
                             ("type", "type_cabine"),
                             ("modele", "modele__icontains"),
                             # Valeur choisie dans une liste déroulante : elle est
                             # complète, donc exacte. « contient » y répondrait à
                             # côté — le modèle « Duo 120 » ramènerait aussi les
                             # « Duo 1200 », et l'écran annoncerait un compte faux.
                             ("chantier_exact", "chantier"),
                             ("modele_exact", "modele")]:
            if p.get(param):
                qs = qs.filter(**{champ: p[param]})
        if _actif(p, "sans_chantier"):
            qs = qs.filter(chantier="")
        # Relecture d'une poignée de cabines dont on connaît déjà les identifiants :
        # sert aux « Consultées récemment » du scanner, qui vivaient dans le
        # navigateur et affichaient donc des cabines supprimées, parties, ou
        # portant un libellé de statut d'avant son renommage.
        if p.get("ids"):
            try:
                ids = [int(x) for x in p["ids"].split(",") if x.strip()][:50]
            except (TypeError, ValueError):
                raise ErreurAPI({"erreur": [
                    "Le filtre « ids » attend des identifiants numériques séparés par des virgules."]})
            qs = qs.filter(pk__in=ids)
        return qs

    @staticmethod
    def _filtrer_position(qs, p):
        """Où la cabine se trouve : zone, emplacement, rack, rangée ou non.

        Tous traversent `occupations`, d'où le `distinct()` : une cabine posée à
        deux endroits du même rack ressortirait deux fois.
        """
        zone = _filtre_id(p, "zone")
        if zone is not None:
            qs = qs.filter(occupations__emplacement__zone_cabine_id=zone).distinct()
        emplacement = _filtre_id(p, "emplacement")
        if emplacement is not None:
            qs = qs.filter(occupations__emplacement_id=emplacement).distinct()
        # « Rangée » = elle occupe au moins un emplacement. Rien n'est déclaré à
        # l'avance : une cabine qui tient à deux endroits n'est pas « incomplète »,
        # elle est rangée à deux endroits.
        if p.get("rangee") == "0":
            qs = qs.exclude(occupations__emplacement__isnull=False).distinct()
        elif p.get("rangee") == "1":
            qs = qs.filter(occupations__emplacement__isnull=False).distinct()
        # Le rack est la maille de rangement réelle : « toutes les cabines du rack
        # AC » ne se posait qu'emplacement par emplacement, soit une trentaine de
        # requêtes.
        if p.get("rack"):
            qs = qs.filter(occupations__emplacement__rack__iexact=p["rack"].strip()).distinct()
        return qs

    @staticmethod
    def _filtrer_anciennete(qs, p):
        """Immobiles : rien ne leur est arrivé depuis N jours.

        S'appuie sur `derniere_activite_date`, annotée par `_parc_annote`.
        """
        jours = p.get("immobile")
        if jours in (None, ""):
            return qs
        try:
            seuil = int(jours)
        except (TypeError, ValueError):
            raise ErreurAPI({"erreur": [
                "Le filtre « immobile » se donne en nombre de jours."]})
        return qs.filter(derniere_activite_date__lt=timezone.now() - timedelta(days=seuil))

    def _filtrer_etape_processus(self, qs, p):
        etape = p.get("etape")
        if not etape:
            return qs
        # Le filtre traverse les occupations : une cabine rangée deux fois dans
        # la même zone ressortirait deux fois sans `distinct()`.
        return qs.filter(self._filtre_etape(etape)).distinct()

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        """L'inventaire des cabines, tel que l'écran l'affiche, en fichier Excel.

        Le point d'entrée reprend `get_queryset` et les filtres de l'écran : on
        exporte ce qu'on voit. Sans cela, il faudrait redécrire les filtres dans
        l'URL de l'export, et les deux finiraient par diverger.
        """
        cabines = self.filter_queryset(self.get_queryset())
        return export_inventaire.reponse(cabines)

    @staticmethod
    def _filtre_etape(etape):
        """Traduit une étape de processus en conditions sur statut et rôle de zone.

        L'étape est calculée (jamais stockée) : le filtre reproduit donc la même
        logique de priorité que `Cabine.etape`, le statut d'abord.
        """
        conforme = Q(statut__in=[Cabine.LIBRE])
        if etape == "envoyee":
            return Q(statut=Cabine.ENVOYE)
        if etape == "quarantaine":
            return Q(statut=Cabine.QUARANTAINE)
        if etape == "envoi":
            return conforme & Q(occupations__emplacement__zone_cabine__role=Zone.ENVOI)
        if etape == "production":
            return conforme & (Q(occupations__emplacement__isnull=True)
                               | Q(occupations__emplacement__zone_cabine__role=Zone.PRODUCTION))
        if etape == "rangement":
            # Un emplacement sans zone compte comme du rangement : `role` valant NULL,
            # un simple ~Q(role__in=…) l'exclurait (NOT NULL vaut NULL en SQL).
            return (conforme & Q(occupations__emplacement__isnull=False)
                    & (Q(occupations__emplacement__zone_cabine__isnull=True)
                       | ~Q(occupations__emplacement__zone_cabine__role__in=[Zone.ENVOI, Zone.PRODUCTION])))
        return Q()

    def _run(self, fn):
        """Même contrat d'erreur que les opérations de stock : 400 {"erreur": [...]}."""
        try:
            return Response(CabineSerializer(fn()).data)
        except ValidationError as e:
            return Response({"erreur": e.messages}, status=status.HTTP_400_BAD_REQUEST)

    def perform_update(self, serializer):
        """Une correction de fiche passe par le service, comme toute autre écriture.

        Sans cela, un PATCH direct changeait le numéro d'une cabine sans laisser la
        moindre trace : le journal continuait d'afficher l'ancien numéro sur les
        mouvements passés, et rien n'expliquait la différence.
        """
        try:
            serializer.instance = services_cabines.corriger_fiche(
                cabine=serializer.instance, utilisateur=self.request.user,
                **serializer.validated_data)
        except ValidationError as e:
            raise ErreurAPI({"erreur": e.messages})

    def perform_destroy(self, instance):
        """Suppression d'une cabine mal saisie — règles dans services_cabines.

        Trois situations appellent une confirmation supplémentaire (`?force=1`) :
        cabine envoyée, cabine rangée quelque part, cabine ayant déjà un historique.
        Aucune n'est bloquante : supprimer une saisie erronée est l'intention même.
        """
        force = _actif(self.request.query_params, "force")
        motif = (self.request.query_params.get("motif") or "")[:255]
        try:
            services_cabines.supprimer_cabine(
                cabine=instance, utilisateur=self.request.user, force=force, motif=motif)
        except ValidationError as e:
            raise ErreurAPI({"erreur": e.messages})

    def perform_create(self, serializer):
        # Passe par le service pour que la création soit journalisée, et pour que
        # la règle du fichier de production s'applique — une cabine que la
        # production n'annonce pas ne s'enregistre pas ici.
        d = serializer.validated_data
        try:
            cabine = services_cabines.creer_cabine(
                numero=d.get("numero"), chantier=d.get("chantier", ""),
                type_cabine=d.get("type_cabine", Cabine.NORMALE),
                modele=d.get("modele", ""), utilisateur=self.request.user,
                # Motif d'une création hors fichier. Hors du serializer à dessein :
                # ce n'est pas un champ de la cabine, c'est la raison d'un geste.
                motif_hors_fichier=str(self.request.data.get("motif_hors_fichier") or ""),
                **{c: d.get(c, "") for c in services_cabines.CHAMPS_FICHE})
        except ValidationError as e:
            # `ErreurCabine` est une ValidationError de Django, pas de DRF : sans
            # cette conversion elle remonterait en 500 au lieu d'un 400 lisible.
            raise ErreurAPI({"erreur": e.messages})
        serializer.instance = cabine

    @action(detail=False, methods=["post"], url_path="lire-fiche")
    def lire_fiche(self, request):
        """Photo de la fiche cabine → champs extraits. Ne crée rien.

        L'opérateur envoie la photo, le serveur reconnaît le texte puis l'analyse.
        Le formulaire est ensuite pré-rempli et **relu** avant enregistrement : la
        reconnaissance peut confondre 0 et O, rien ne part en base à l'aveugle.
        """
        fichier = request.FILES.get("photo")
        if fichier is None:
            return Response({"erreur": ["Aucune photo reçue."]},
                            status=status.HTTP_400_BAD_REQUEST)
        if fichier.size > 12 * 1024 * 1024:
            return Response({"erreur": ["Photo trop lourde (12 Mo maximum)."]},
                            status=status.HTTP_400_BAD_REQUEST)
        if not ocr_fiche.disponible():
            return Response({"erreur": [
                "Reconnaissance de texte indisponible sur le serveur : installez "
                "requirements-ocr.txt, puis redémarrez."]},
                status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            texte = ocr_fiche.lire_image(fichier.read())
        except Exception as e:
            return Response({"erreur": [f"Lecture impossible : {e}"]},
                            status=status.HTTP_400_BAD_REQUEST)
        if not texte.strip():
            return Response({"erreur": [
                "Aucun texte lisible sur la photo. Reprends-la à plat, cadrée sur le "
                "tableau et bien éclairée."]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self._depuis_texte(texte))

    @action(detail=False, methods=["post"], url_path="analyser-fiche")
    def analyser_fiche(self, request):
        """Extrait les champs d'une fiche cabine depuis le texte reconnu par l'OCR.

        Ne crée rien : l'écran pré-remplit le formulaire avec ce qui a été lu, et
        l'opérateur confirme. L'OCR confond notamment 0/O et 1/I — sur un n° de
        commande ou une référence de cabine, aucune écriture ne se fait à l'aveugle.
        """
        texte = request.data.get("texte") or ""
        if not isinstance(texte, str) or not texte.strip():
            return Response({"erreur": ["Aucun texte à analyser."]},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(self._depuis_texte(texte))

    @staticmethod
    def _depuis_texte(texte):
        """Analyse le texte et signale une cabine déjà connue, pour éviter un doublon."""
        champs, manquants = lecture_fiche.analyser(texte)
        existante = None
        if champs.get("numero"):
            cabine = Cabine.objects.filter(numero=champs["numero"]).first()
            if cabine:
                existante = CabineSerializer(cabine).data
        return {"champs": champs, "manquants": manquants,
                "cabine_existante": existante, "texte": texte}

    @action(detail=False, methods=["get"])
    def filtres(self, request):
        """Ce qui existe vraiment dans le parc, pour alimenter les listes déroulantes.

        Une liste déroulante remplie à la main ment dès la première cabine d'un
        nouveau chantier : on propose donc les valeurs réellement présentes en base.
        Les compteurs accompagnent les filtres rapides — « Non rangées (12) » —
        parce qu'un filtre dont on ignore le rendement ne se clique pas.

        Les cabines envoyées sont hors du parc : elles ne remplissent pas les
        listes et ne sont comptées que pour dire combien il y en a.
        """
        dernier = (MouvementCabine.objects.filter(cabine=OuterRef("pk"))
                   .order_by("-date").values("date")[:1])
        parc = (Cabine.objects
                .annotate(derniere_activite_date=Coalesce(Subquery(dernier), "date"))
                .exclude(statut=Cabine.ENVOYE))
        limite = timezone.now() - timedelta(days=SEUIL_IMMOBILE_JOURS)

        # `.order_by()` vide n'est pas décoratif : le tri par défaut du modèle
        # ajoute ses colonnes au SELECT, et le DISTINCT porte alors sur le couple
        # (chantier, date) — la liste rendait trois fois le même chantier.
        def distinctes(champ):
            return sorted(
            v for v in (parc.exclude(**{champ: ""}).exclude(**{champ + "__isnull": True})
                        .order_by().values_list(champ, flat=True).distinct()) if v)

        return Response({
            "chantiers": distinctes("chantier"),
            "modeles": distinctes("modele"),
            # Les racks viennent du référentiel, pas des cabines : un rack vidé
            # doit rester proposé, sinon on ne peut plus vérifier qu'il est vide.
            "racks": sorted(r for r in (Emplacement.objects.exclude(rack="").order_by()
                                        .values_list("rack", flat=True).distinct()) if r),
            "seuil_immobile_jours": SEUIL_IMMOBILE_JOURS,
            "compteurs": {
                "total": parc.count(),
                "non_rangees": parc.filter(occupations__emplacement__isnull=True).distinct().count(),
                "quarantaine": parc.filter(statut=Cabine.QUARANTAINE).count(),
                "sans_chantier": parc.filter(chantier="").count(),
                "immobiles": parc.filter(derniere_activite_date__lt=limite).count(),
                "envoyees": Cabine.objects.filter(statut=Cabine.ENVOYE).count(),
            },
        })

    @action(detail=False, methods=["get"])
    def archives(self, request):
        """Cabines envoyées — le « fichier à part » demandé."""
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(CabineSerializer(page, many=True).data)

    @action(detail=True, methods=["get"])
    def historique(self, request, pk=None):
        mouvements = services_cabines.historique(self.get_object())
        return Response(MouvementCabineSerializer(mouvements, many=True).data)

    def _occupation_optionnelle(self, cabine, brut):
        """Résout l'emplacement visé. Absent : le service choisit lui-même."""
        if brut in (None, ""):
            return None
        occupation = cabine.occupations.filter(pk=brut).first()
        if occupation is None:
            raise ErreurAPI({"erreur": [
                "Cet emplacement n'appartient pas à cette cabine."]})
        return occupation

    @action(detail=True, methods=["post"])
    def ranger(self, request, pk=None):
        d = request.data
        cabine = self.get_object()

        def go():
            emplacement = self._emplacement_requis(d.get("emplacement"))
            return services_cabines.ranger(
                cabine=cabine, emplacement=emplacement,
                place=(d.get("place") or "").strip().upper(),
                occupation=self._occupation_optionnelle(cabine, d.get("occupation")),
                # `ajouter` : un emplacement DE PLUS, sans libérer le premier.
                ajouter=str(d.get("ajouter", "")).lower() in ("1", "true"),
                utilisateur=request.user)
        return self._run(go)

    @action(detail=True, methods=["post"])
    def sortir(self, request, pk=None):
        cabine = self.get_object()
        return self._run(lambda: services_cabines.sortir_de_l_emplacement(
            cabine=cabine, utilisateur=request.user,
            occupation=self._occupation_optionnelle(
                cabine, request.data.get("occupation")),
            note=(request.data.get("note") or "")[:255]))

    @action(detail=True, methods=["post"])
    def statut(self, request, pk=None):
        return self._run(lambda: services_cabines.changer_statut(
            cabine=self.get_object(), statut=(request.data.get("statut") or "").strip(),
            utilisateur=request.user, motif=(request.data.get("motif") or "")[:255]))

    @action(detail=True, methods=["post"])
    def envoyer(self, request, pk=None):
        return self._run(lambda: services_cabines.envoyer(
            cabine=self.get_object(), utilisateur=request.user,
            note=(request.data.get("note") or "")[:255]))

    @action(detail=True, methods=["post"])
    def reprendre(self, request, pk=None):
        """Remet en stock une cabine envoyée — l'inverse d'`envoyer`.

        Même droit que le reste (« cabines ») : c'est une correction de terrain,
        pas une opération d'administration. L'écran demande confirmation ; le
        journal garde l'envoi ET le retour.
        """
        return self._run(lambda: services_cabines.reprendre(
            cabine=self.get_object(), utilisateur=request.user,
            motif=(request.data.get("motif") or "")[:255]))

    @action(detail=True, methods=["post"])
    def chantier(self, request, pk=None):
        return self._run(lambda: services_cabines.affecter_chantier(
            cabine=self.get_object(), chantier=request.data.get("chantier"),
            utilisateur=request.user))

    @staticmethod
    def _emplacement_requis(brut):
        if brut is None or brut == "":
            raise ValidationError("Le champ « emplacement » est obligatoire.")
        try:
            return Emplacement.objects.select_related("zone_cabine").get(pk=brut)
        except (Emplacement.DoesNotExist, ValueError, TypeError, ValidationError):
            raise ValidationError(f"Emplacement introuvable : « {brut} ».")


class MouvementCabineViewSet(viewsets.ReadOnlyModelViewSet):
    """Journal de vie des cabines — lecture seule, y compris pour un administrateur."""
    serializer_class = MouvementCabineSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["cabine_numero", "chantier", "utilisateur_nom", "note"]
    ordering_fields = ["date", "cabine_numero"]

    def get_queryset(self):
        qs = MouvementCabine.objects.select_related("cabine").all()
        p = self.request.query_params
        cabine = _filtre_id(p, "cabine")
        if cabine is not None:
            qs = qs.filter(cabine_id=cabine)
        if p.get("numero"):
            qs = qs.filter(cabine_numero__icontains=p["numero"])
        if p.get("chantier"):
            qs = qs.filter(chantier__icontains=p["chantier"])
        if p.get("type"):
            qs = qs.filter(type=p["type"])
        return qs


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def referentiels_cabine(request):
    """Listes de choix figées, pour que le front ne les recopie pas en dur."""
    return Response({
        "statuts": [{"code": code, "libelle": libelle} for code, libelle in Cabine.STATUTS],
        "types": [{"code": code, "libelle": libelle} for code, libelle in Cabine.TYPES],
        "places": [{"code": code, "libelle": libelle} for code, libelle in Cabine.PLACES],
        "types_mouvement": [{"code": code, "libelle": libelle} for code, libelle in MouvementCabine.TYPES],
        "etapes": [{"code": code, "libelle": libelle} for code, libelle in Cabine.ETAPES],
        "roles_zone": [{"code": code, "libelle": libelle} for code, libelle in Zone.ROLES],
        "modes_places": [{"code": code, "libelle": libelle} for code, libelle in Emplacement.MODES_PLACES],
        # Un fichier de production a-t-il été importé ? C'est lui qui arme la
        # règle « une cabine non annoncée ne s'enregistre pas ». Sans cette
        # information, l'écran d'entrée refuserait une saisie que le serveur
        # accepte encore — ou proposerait une saisie qu'il va refuser.
        "fichier_production": CabineAttendue.objects.exists(),
        # La forme attendue d'un chantier, écrite une fois pour toutes sur le
        # modèle. Quatre écrans annonçaient « 6 chiffres » en dur ; le jour où le
        # lot a été accepté, aucun ne l'a su et tous continuaient à refuser
        # « 251213-1 » au clavier avant même que le serveur soit consulté.
        # Les grands modèles, pour que l'écran puisse le dire AVANT le scan de
        # l'emplacement : « cette cabine prendra toute la travée ».
        "grands_modeles": sorted(ModeleCabine.objects.filter(grand=True)
                                 .values_list("nom", flat=True)),
        "aide_chantier": Cabine.AIDE_CHANTIER,
        "taille_chantier": Cabine.TAILLE_CHANTIER,
        # Le motif lui-même : l'écran refuse alors une forme fautive sans
        # aller-retour, et il refuse EXACTEMENT ce que le modèle refuse. Une
        # copie écrite à la main dans le JavaScript aurait divergé au premier
        # assouplissement — c'est déjà arrivé avec « 6 chiffres ».
        "motif_chantier": Cabine.MOTIF_CHANTIER,
    })


class ModeleCabineViewSet(viewsets.ModelViewSet):
    """Les modèles de cabine et leur taille — l'écran « Modèles ».

    La liste n'est pas seulement ce qui a été enregistré : elle est complétée par
    tous les modèles VUS dans le fichier de production et dans le stock. Un
    modèle qui apparaît au prochain import se règle donc sans que personne ait à
    le créer, et sans qu'on découvre son existence le jour où une cabine ne
    rentre pas dans sa travée.
    """

    queryset = ModeleCabine.objects.all()
    serializer_class = ModeleCabineSerializer
    droit_ecriture = "ref"
    pagination_class = None
    lookup_field = "pk"

    def list(self, request, *args, **kwargs):
        """Les modèles enregistrés, plus ceux que les données montrent."""
        vus = _modeles_vus()
        connus = {m.cle: m for m in ModeleCabine.objects.select_related("modifie_par")}
        lignes = []
        for cle, infos in sorted(vus.items(), key=lambda kv: kv[1]["nom"]):
            enregistre = connus.pop(cle, None)
            lignes.append({
                "id": enregistre.id if enregistre else None,
                "nom": enregistre.nom if enregistre else infos["nom"],
                "cle": cle,
                "grand": bool(enregistre and enregistre.grand),
                "regle": enregistre is not None,
                "regle_par": (getattr(enregistre.modifie_par, "nom", "")
                              if enregistre and enregistre.modifie_par_id else ""),
                "nb_attendues": infos["attendues"],
                "nb_en_stock": infos["stock"],
            })
        # Un modèle réglé qui n'apparaît plus dans aucune donnée reste montré :
        # « COLLAB » a été déclaré grand modèle avant sa première cabine, et le
        # faire disparaître de l'écran l'aurait fait ressaisir.
        for cle, m in sorted(connus.items(), key=lambda kv: kv[1].nom):
            lignes.append({
                "id": m.id, "nom": m.nom, "cle": cle, "grand": m.grand, "regle": True,
                "regle_par": (getattr(m.modifie_par, "nom", "")
                              if m.modifie_par_id else ""),
                "nb_attendues": 0, "nb_en_stock": 0,
            })
        return Response({
            "modeles": lignes,
            "nb_grands": sum(1 for ligne in lignes if ligne["grand"]),
            # Ce que le dernier reclassement a laissé derrière lui.
            "travees_hors_regle": services_cabines.travees_hors_regle(),
        })

    @action(detail=False, methods=["post"])
    def regler(self, request):
        """Pose la taille d'un modèle, en le créant au besoin.

        Un POST par bascule, sur la CLÉ et non sur un identifiant : l'écran
        affiche des modèles qui n'ont pas encore de ligne en base, et exiger une
        création préalable aurait demandé deux appels pour une seule touche.
        """
        nom = " ".join(str(request.data.get("nom") or "").split())
        if not nom:
            raise ErreurAPI("Quel modèle ?")
        grand = bool(request.data.get("grand"))
        cle = ModeleCabine.normaliser(nom)
        modele, _ = ModeleCabine.objects.update_or_create(
            cle=cle, defaults={"nom": nom, "grand": grand,
                               "modifie_par": request.user})
        return Response(ModeleCabineSerializer(modele).data)


def _modeles_vus():
    """Tous les modèles que les données connaissent, avec leurs volumes.

    Deux sources : le fichier de production (ce qui va arriver) et le stock (ce
    qui est là). Un modèle présent seulement en stock — importé avant que le
    fichier existe, ou créé hors fichier — doit se régler lui aussi.
    """
    vus = {}

    def ajouter(nom, champ):
        cle = ModeleCabine.normaliser(nom)
        if not cle:
            return
        entree = vus.setdefault(cle, {"nom": " ".join(str(nom).split()),
                                      "attendues": 0, "stock": 0})
        entree[champ] += 1

    for nom in CabineAttendue.objects.values_list("modele", flat=True):
        ajouter(nom, "attendues")
    for nom in Cabine.objects.exclude(statut=Cabine.ENVOYE).values_list("modele", flat=True):
        ajouter(nom, "stock")
    return vus


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def suivi_processus(request):
    """Avancement du parc dans le processus : combien de cabines à chaque étape.

    Répond au besoin de suivre le flux de bout en bout — production, quarantaine,
    rangement, attente de départ, envoi — et de repérer ce qui stagne.
    """
    dernier = (MouvementCabine.objects.filter(cabine=OuterRef("pk"))
               .order_by("-date").values("date")[:1])
    base = (Cabine.objects
            .prefetch_related("occupations__emplacement__zone_cabine")
            .annotate(derniere_activite_date=Coalesce(Subquery(dernier), "date")))
    limite = timezone.now() - timedelta(days=SEUIL_IMMOBILE_JOURS)

    etapes = []
    for code, libelle in Cabine.ETAPES:
        lot = base.filter(CabineViewSet._filtre_etape(code))
        etapes.append({
            "code": code,
            "libelle": libelle,
            "total": lot.count(),
            # Les cabines envoyées sont sorties : leur ancienneté n'a plus de sens.
            "immobiles": (0 if code == "envoyee"
                          else lot.filter(derniere_activite_date__lt=limite).count()),
        })

    stagnantes = [c for c in base.exclude(statut=Cabine.ENVOYE)
                  .filter(derniere_activite_date__lt=limite)
                  .order_by("derniere_activite_date")[:20]]
    return Response({
        "seuil_jours": SEUIL_IMMOBILE_JOURS,
        "etapes": etapes,
        "en_stock": base.exclude(statut=Cabine.ENVOYE).count(),
        "stagnantes": CabineSerializer(stagnantes, many=True).data,
    })


class OperationsViewSet(viewsets.ViewSet):
    """Opérations métier de stock (voir wms/services.py)."""

    droits_par_action = {
        "entree": "mvt",
        "sortie": "mvt",
        "reception": "mvt",
        "transfert": "mvt",
        "ajustement": "inv",
        "contre_passer": "mvt_corr",
    }

    def _objet(self, modele, data, champ, libelle):
        """Résout une clé étrangère du corps de la requête en erreurs 400 explicites.

        `get_object_or_404(pk=…)` renvoyait un 404 au message technique anglais quand le
        champ était absent, et remontait en ValueError (500) sur un identifiant non
        numérique.
        """
        brut = data.get(champ)
        if brut is None or brut == "":
            raise ErreurAPI({"erreur": [f"Le champ « {libelle} » est obligatoire."]})
        try:
            return modele.objects.get(pk=brut)
        except (modele.DoesNotExist, ValueError, TypeError, ValidationError):
            raise ErreurAPI({"erreur": [f"{libelle.capitalize()} introuvable : « {brut} »."]})

    def _article(self, data):
        return self._objet(Article, data, "article", "article")

    def _emplacement(self, data, champ="emplacement", libelle="emplacement"):
        return self._objet(Emplacement, data, champ, libelle)

    def _texte(self, data, champ, longueur_max=255):
        """Les CharField ne sont pas contrôlés par SQLite : on borne ici."""
        valeur = data.get(champ) or ""
        if not isinstance(valeur, str):
            valeur = str(valeur)
        valeur = valeur.strip()
        if len(valeur) > longueur_max:
            raise ErreurAPI({"erreur": [
                f"Le champ « {champ} » dépasse {longueur_max} caractères."
            ]})
        return valeur

    def _run(self, fn):
        try:
            return Response(fn(), status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({"erreur": e.messages}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def entree(self, request):
        d = request.data
        return self._run(lambda: MouvementSerializer(services.entree(
            article=self._article(d), emplacement=self._emplacement(d),
            qte=d.get("qte"), utilisateur=request.user,
            note=self._texte(d, "note"), commande=self._texte(d, "commande", 64))).data)

    @action(detail=False, methods=["post"])
    def sortie(self, request):
        d = request.data
        return self._run(lambda: MouvementSerializer(services.sortie(
            article=self._article(d), emplacement=self._emplacement(d),
            qte=d.get("qte"), utilisateur=request.user,
            note=self._texte(d, "note"), commande=self._texte(d, "commande", 64))).data)

    @action(detail=False, methods=["post"])
    def ajustement(self, request):
        d = request.data
        return self._run(lambda: MouvementSerializer(services.ajustement(
            article=self._article(d), emplacement=self._emplacement(d),
            qte=d.get("qte"), utilisateur=request.user,
            note=self._texte(d, "note"))).data)

    @action(detail=False, methods=["post"])
    def transfert(self, request):
        d = request.data

        def go():
            mv_out, mv_in = services.transfert(
                article=self._article(d),
                source=self._emplacement(d, "source", "emplacement source"),
                destination=self._emplacement(d, "destination", "emplacement de destination"),
                qte=d.get("qte"), utilisateur=request.user,
                commande=self._texte(d, "commande", 64))
            return {"sortie": MouvementSerializer(mv_out).data,
                    "entree": MouvementSerializer(mv_in).data}
        return self._run(go)

    @action(detail=False, methods=["post"])
    def reception(self, request):
        d = request.data

        def go():
            emplacement = self._emplacement(d)
            mv, rec = services.receptionner(
                article=self._article(d), emplacement=emplacement,
                qte=d.get("qte"), utilisateur=request.user,
                commande=self._texte(d, "commande", 64),
                commentaire=self._texte(d, "commentaire"),
                # Déduit de l'emplacement, jamais du client : le drapeau envoyé par le
                # front pouvait marquer « à ranger » une réception déposée dans un
                # emplacement normal (et la chaîne "false" valait True).
                staging=emplacement.staging)
            return {"mouvement": MouvementSerializer(mv).data,
                    "reception": ReceptionSerializer(rec).data}
        return self._run(go)

    @action(detail=False, methods=["post"], url_path="contre-passer")
    def contre_passer(self, request):
        d = request.data

        def go():
            mouvement = self._objet(Mouvement, d, "mouvement", "mouvement")
            if mouvement.article_id is None or mouvement.emplacement_id is None:
                raise ErreurAPI({"erreur": [
                    "Impossible de contre-passer ce mouvement : l'article ou "
                    "l'emplacement d'origine a été supprimé."
                ]})
            return MouvementSerializer(
                services.contre_passer(mouvement, utilisateur=request.user)).data
        return self._run(go)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def moi(request):
    """Identité et droits du compte connecté.

    Permet au front de ne pas proposer une commande que le serveur refusera : sans
    cela l'interface affiche « Créer une référence » à un opérateur sans `droit_ref`,
    qui ne découvre le refus qu'après avoir rempli le formulaire. Le `pin` n'est
    volontairement pas exposé.
    """
    u = request.user
    return Response({
        "username": u.username,
        "nom": u.nom or u.username,
        "role": u.role,
        "is_superuser": u.is_superuser,
        # Au-delà des 7 droits fins : l'import du fichier de production n'est pas
        # une case à cocher. Le front en a besoin pour ne pas proposer un écran
        # que le serveur refusera.
        "administrateur": u.est_administrateur,
        "droits": u.droits_effectifs(),
    })


@api_view(["GET"])
def pouls(request):
    """Empreinte de l'activité : trois entiers, rien de plus.

    Plusieurs personnes travaillent sur le même stock ; un écran ouvert depuis
    dix minutes ment. Les écrans interrogent donc ce point toutes les dix
    secondes pour savoir s'il s'est passé quelque chose — et ne redessinent que
    si c'est le cas. Trois `COUNT` valent mieux qu'une page de JSON rechargée
    en boucle pour rien.

    Le journal des mouvements suffit à détecter rangements, sorties et
    changements de statut ; les deux autres compteurs rattrapent les créations
    et les suppressions, qui ne passent pas toujours par lui.
    """
    mouvements = MouvementCabine.objects.aggregate(dernier=Max("id"), total=Count("id"))
    return Response({
        "mouvements": mouvements["total"] or 0,
        "dernier": mouvements["dernier"] or 0,
        "cabines": Cabine.objects.count(),
        "emplacements": Emplacement.objects.count(),
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def sante(request):
    """État du service — le point que la supervision interroge.

    Ouvert sans authentification : un outil de supervision n'a pas de compte, et
    la réponse ne divulgue rien (ni version, ni chemin, ni configuration). Elle
    dit seulement si la base répond et si le schéma est à jour.

    Répond 200 tant que tout va bien, 503 sinon : c'est ce code que surveillent
    les redémarrages automatiques et les sondes d'un reverse-proxy.
    """
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    etat = {"service": "ok", "base": "ok", "migrations": "ok"}
    code = status.HTTP_200_OK
    try:
        with connection.cursor() as curseur:
            curseur.execute("SELECT 1")
            curseur.fetchone()
    except Exception:
        # Le détail de l'erreur part au journal, pas sur le réseau : un message
        # de connexion contient l'hôte, le port et parfois l'utilisateur.
        logger.exception("Sonde de santé : base injoignable")
        etat["base"] = "injoignable"
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        try:
            executeur = MigrationExecutor(connection)
            restantes = executeur.migration_plan(
                executeur.loader.graph.leaf_nodes())
            if restantes:
                # Schéma en retard sur le code : les écritures peuvent tomber sur
                # une colonne absente. Mieux vaut le dire avant l'incident.
                etat["migrations"] = f"{len(restantes)} en attente"
                code = status.HTTP_503_SERVICE_UNAVAILABLE
        except Exception:
            logger.exception("Sonde de santé : plan de migration illisible")
            etat["migrations"] = "inconnu"
            code = status.HTTP_503_SERVICE_UNAVAILABLE

    return Response(etat, status=code)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tableau_de_bord(request):
    # Toutes les zones de staging, pas seulement la première trouvée.
    a_ranger = Stock.objects.filter(emplacement__staging=True).aggregate(t=Sum("qte"))["t"] or 0
    # Note : le total d'alerte inclut volontairement le stock en zone « à ranger ».
    # C'est le comportement de référence de la maquette (`totalStock` sommait toutes les
    # lignes de stock de l'article, staging compris) — la marchandise est physiquement là.
    totals = {r["article"]: (r["t"] or 0) for r in Stock.objects.values("article").annotate(t=Sum("qte"))}
    bas = []
    for art in Article.objects.filter(statut=Article.ACTIF):
        tot = totals.get(art.id, 0)
        if art.stock_min and tot < art.stock_min:
            bas.append({"ref": art.ref, "designation": art.designation,
                        "stock": float(tot), "min": float(art.stock_min)})
    bas = sorted(bas, key=lambda x: x["stock"])[:50]
    derniers = [{
        "date": m.date.isoformat(), "type": m.get_type_display(),
        "article": m.article.ref if m.article else "?",
        "emplacement": m.emplacement.code if m.emplacement else "?",
        "qte": float(m.qte), "note": m.note,
    } for m in Mouvement.objects.select_related("article", "emplacement")[:12]]
    return Response({
        "references": Article.objects.count(), "emplacements": Emplacement.objects.count(),
        "mouvements": Mouvement.objects.count(), "receptions": Reception.objects.count(),
        "a_ranger": float(a_ranger), "stock_bas": bas, "derniers_mouvements": derniers,
    })


#: Les deux bibliothèques front (lecture de QR à la caméra, génération des
#: étiquettes). Servies en local si elles ont été téléchargées une fois
#: (`python manage.py telecharger_libs`), sinon depuis le CDN.
_VENDOR = Path(__file__).resolve().parent / "static" / "app" / "vendor"
LIBS_FRONT = ("html5-qrcode.min.js", "qrcode.min.js")


def app_index(request):
    """Sert l'interface opérateur.

    `v` sert d'anti-cache : calculé sur la date des fichiers et non sur l'heure
    courante, sinon le navigateur retéléchargeait 130 Ko de CSS + JS à **chaque**
    ouverture — sensible sur le Wi-Fi d'un entrepôt et en 4G.
    """
    statiques = Path(__file__).resolve().parent / "static" / "app"
    try:
        version = int(max(f.stat().st_mtime for f in statiques.glob("*.js"))) + int(
            max((f.stat().st_mtime for f in statiques.glob("*.css")), default=0))
    except ValueError:  # pragma: no cover - dossier statique absent
        version = int(time.time())
    return render(request, "app.html", {
        "v": version,
        # Vrai seulement si les DEUX fichiers sont là : un mélange local/CDN
        # échouerait à moitié, sans message clair pour l'opérateur.
        "libs_locales": all((_VENDOR / nom).is_file() for nom in LIBS_FRONT),
        # Campagne de test : de quoi pré-remplir l'écran de connexion. Vide
        # en dehors des campagnes — voir ACCES_TEST dans les réglages.
        "acces_test": settings.ACCES_TEST,
    })


class CabineAttendueViewSet(viewsets.ReadOnlyModelViewSet):
    """Les cabines annoncées par la production, et l'import du fichier.

    Cette table ne dit pas ce qui est en stock : elle dit ce qu'on attend. À
    l'entrée, l'opérateur saisit le numéro et tout se pré-remplit — c'est la
    raison d'être de l'écran, et pourquoi la lecture est ouverte à tout compte.

    L'écriture, elle, ne passe que par les deux actions d'import, réservées aux
    administrateurs : un fichier réécrit les caractéristiques de milliers de
    cabines d'un coup. Aucune création ni modification à l'unité n'est exposée —
    la source est le fichier, et lui seul, sans quoi la table divergerait de la
    production sans que personne ne sache laquelle des deux croire.
    """

    queryset = CabineAttendue.objects.select_related("importe_par").all()
    serializer_class = CabineAttendueSerializer
    permission_classes = [EstAdministrateur]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["numero", "num_unique", "chantier", "chantier_brut", "client",
                     "revendeur", "modele", "gamme"]
    ordering_fields = ["numero", "chantier", "semaine_production", "importe_le"]
    #: Le numéro porte des tirets bas : sans cette expression, le routeur de DRF
    #: ne reconnaît pas « /cabines-attendues/26_02_49/ » et rend un 404 muet.
    lookup_field = "numero"
    lookup_value_regex = r"[0-9_]+"

    #: 10 Mo : le fichier de production en fait un demi aujourd'hui, et grossit
    #: d'une semaine à l'autre. Au-delà, ce n'est plus lui.
    TAILLE_MAX = 10 * 1024 * 1024

    def _fichier(self, request):
        fichier = request.FILES.get("fichier")
        if fichier is None:
            raise ErreurAPI({"erreur": [
                "Aucun fichier reçu. Choisissez le fichier Excel de production."]})
        if fichier.size > self.TAILLE_MAX:
            raise ErreurAPI({"erreur": [
                f"Fichier trop lourd ({fichier.size // (1024 * 1024)} Mo). "
                "10 Mo au maximum."]})
        if not fichier.name.lower().endswith((".xlsx", ".xlsm")):
            raise ErreurAPI({"erreur": [
                f"« {fichier.name} » n'est pas un classeur Excel. Attendu : .xlsx. "
                "Un .xls ou un .csv doit d'abord être enregistré au format .xlsx."]})
        return fichier

    @action(detail=False, methods=["post"])
    def analyser(self, request):
        """Ce qu'un import ferait, sans rien écrire.

        Personne ne devrait découvrir qu'un fichier était le mauvais après
        l'avoir importé : l'écran montre d'abord ce compte, et n'écrit qu'après
        confirmation.
        """
        fichier = self._fichier(request)
        try:
            rapport = services_import.analyser(fichier, nom=fichier.name)
        except services_import.ErreurImport as e:
            raise ErreurAPI({"erreur": [str(e)]})
        return Response(services_import.rapport_public(rapport))

    @action(detail=False, methods=["post"])
    def importer(self, request):
        """Applique le fichier. Tout ou rien."""
        fichier = self._fichier(request)
        try:
            rapport = services_import.importer(
                fichier, utilisateur=request.user, nom=fichier.name)
        except services_import.ErreurImport as e:
            raise ErreurAPI({"erreur": [str(e)]})
        logger.info("Import cabines attendues par %s : %s ligne(s) retenue(s), "
                    "%s refusee(s), fichier %s",
                    request.user, rapport["retenues"], len(rapport["erreurs"]),
                    rapport["fichier"])
        return Response(rapport)
