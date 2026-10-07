import logging
import re
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Count, Max, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError as ErreurAPI
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from . import (export_inventaire, export_mp, lecture_fiche, ocr_fiche, services_cabines,
               services_emplacements, services_import, services_mp)
from .models import (ArticleMP, Cabine, CabineAttendue, Emplacement, ModeleCabine,
                     MouvementCabine, MouvementMP, Occupation, StockMP)
from .permissions import EstAdministrateur
from .serializers import (CabineAttendueSerializer, CabineSerializer, EmplacementSerializer,
                          ModeleCabineSerializer, MouvementCabineSerializer,
                          OccupationSerializer)

logger = logging.getLogger(__name__)

#: Au-delà de ce délai sans le moindre mouvement, une cabine est signalée comme stagnante.
SEUIL_IMMOBILE_JOURS = 7


class EmplacementViewSet(viewsets.ModelViewSet):
    queryset = Emplacement.objects.all()
    serializer_class = EmplacementSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["code", "zone", "description"]
    ordering_fields = ["code", "rack"]
    ordering = ["code"]
    #: Un seul droit pour toutes les écritures de la vue, actions comprises :
    #: `supprimer-rack` est un POST, il est donc couvert. L'écrire ici évite
    #: qu'une action future s'ouvre par omission.
    droit_ecriture = "ref"

    def get_queryset(self):
        """Emplacements avec leurs cabines, filtrables par rack et par colonne.

        Les cabines sont préchargées : l'écran « Emplacements » afficherait sinon
        une requête par ligne. « Présentes » et non « avec une place » : en
        capacité illimitée les cabines n'ont pas de place, elles occupent tout de
        même l'emplacement.
        """
        p = self.request.query_params
        actifs = (Occupation.objects.exclude(cabine__statut=Cabine.ENVOYE)
                  .select_related("cabine"))
        qs = (Emplacement.objects
              .select_related("zone_cabine", "actif_par")
              .prefetch_related(Prefetch("occupations", queryset=actifs.order_by("place"),
                                         to_attr="occupations_actives"),
                                # Le résumé MP de chaque case du plan : une requête
                                # pour toute la liste, pas une par emplacement.
                                Prefetch("stock_mp", queryset=StockMP.objects.order_by("place"),
                                         to_attr="lignes_mp"),
                                # Les codes acceptés : idem, une requête en tout.
                                "codes_acceptes"))
        if p.get("rack"):
            qs = qs.filter(rack__iexact=p["rack"].strip())
        # `?usage=mp` : les emplacements de matières premières, toutes familles.
        usage = (p.get("usage") or "").strip()
        if usage == "mp":
            qs = qs.exclude(usage=Emplacement.CABINES)
        elif usage in dict(Emplacement.USAGES):
            qs = qs.filter(usage=usage)
        colonne = _filtre_id(p, "colonne")
        if colonne is not None:
            qs = qs.filter(colonne=colonne)
        return qs

    @action(detail=True, methods=["post"])
    def activation(self, request, pk=None):
        """Met l'emplacement en service ou hors service.

        Le corps porte `actif` (booléen) et, pour une désactivation, `motif`.
        Le service refuse tant qu'une cabine est là, et le refus la nomme.
        """
        emplacement = self.get_object()
        try:
            services_cabines.changer_activation(
                emplacement=emplacement,
                actif=bool(request.data.get("actif")),
                motif=str(request.data.get("motif") or ""),
                utilisateur=request.user)
        except services_cabines.ErreurCabine as souci:
            raise ErreurAPI(souci.messages)
        return Response(EmplacementSerializer(
            emplacement, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def place(self, request, pk=None):
        """Condamne une place, ou la rouvre.

        `{place: "G", condamnee: true, motif: "…"}` la retire du stock ;
        `{place: "G", condamnee: false}` la rouvre. Le nom de l'action est au
        singulier là où `places` est au pluriel : l'une agit sur UNE place,
        l'autre décrit l'état des deux.
        """
        emplacement = self.get_object()
        place = str(request.data.get("place") or "").strip().upper()
        try:
            if request.data.get("condamnee"):
                services_cabines.condamner_place(
                    emplacement=emplacement, place=place,
                    motif=str(request.data.get("motif") or ""),
                    utilisateur=request.user)
            else:
                services_cabines.rouvrir_place(
                    emplacement=emplacement, place=place, utilisateur=request.user)
        except services_cabines.ErreurCabine as souci:
            raise ErreurAPI(souci.messages)
        return Response(EmplacementSerializer(
            emplacement, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["get"])
    def places(self, request, pk=None):
        """Occupation des places de l'emplacement scanné.

        C'est ce que consomme l'écran de rangement : il ne propose que les places
        libres, et bloque quand elles sont prises.

        `?pour_cabine=<id>` change la réponse, et c'est nécessaire : un grand
        modèle ne se glisse pas à côté d'une autre cabine. Sans cela l'écran
        proposerait « Gauche » à une cabine qui prend l'emplacement entier, et le
        serveur refuserait au dernier moment — après que le cariste l'a posée.
        """
        emplacement = self.get_object()
        cabine = None
        demande = (request.query_params.get("pour_cabine") or "").strip()
        if demande.isdigit():
            cabine = Cabine.objects.filter(pk=int(demande)).first()
        occupees = services_cabines.occupation(emplacement)
        presentes = services_cabines.cabines_presentes(emplacement)
        # Condamnée n'est pas occupée, et l'écran doit faire la différence : une
        # place qui disparaît sans explication passe pour un défaut d'affichage,
        # et quelqu'un finit par y poser une cabine à la main.
        condamnees = services_cabines.places_condamnees(emplacement)
        return Response({
            "emplacement": emplacement.id,
            "code": emplacement.code,
            "zone": emplacement.zone_cabine.nom if emplacement.zone_cabine_id else None,
            # Un emplacement MP ne se lit pas ici : l'écran passe à son contenu MP.
            "usage": emplacement.usage,
            "usage_libelle": emplacement.get_usage_display(),
            "est_mp": emplacement.est_mp,
            "mode_places": emplacement.mode_places,
            "mode_libelle": emplacement.get_mode_places_display(),
            "illimite": emplacement.illimite,
            # Vide en capacité illimitée : il n'y a pas de place nommée à proposer.
            "places": [
                {
                    "code": code,
                    "libelle": libelle,
                    "libre": occupees[code] is None and code not in condamnees,
                    "condamnee": condamnees.get(code) or None,
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
            "actif": emplacement.actif,
            "motif_inactif": emplacement.motif_inactif,
            # Ce que l'écran doit dire de CETTE cabine, quand il en tient une.
            "pour_cabine": ({
                "id": cabine.id,
                "numero": cabine.numero,
                "modele": cabine.modele,
                "tout_l_emplacement": cabine.prend_tout_l_emplacement,
            } if cabine is not None else None),
        })

    @action(detail=False, methods=["get"])
    def pour_cabine(self, request):
        """Où peut-on ranger CETTE cabine ? Et sinon, pourquoi pas.

        L'écran de rangement listait les emplacements sans savoir quelle cabine
        il rangeait : il annonçait « Places libres : G » à un grand modèle, qui
        prend l'emplacement entier. On touchait la place, et le serveur refusait
        au dernier moment — devant le rack, la cabine déjà descendue.

        Ici, chaque emplacement répond POUR cette cabine : ses places encore
        libres, s'il peut la prendre, et sinon la raison. `proposition` désigne
        le meilleur — voir `services_cabines.emplacements_pour` pour l'ordre,
        qui n'est pas alphabétique mais celui de l'entrepôt.
        """
        demande = (request.query_params.get("cabine") or "").strip()
        cabine = (Cabine.objects.filter(pk=int(demande)).first()
                  if demande.isdigit() else None)
        if cabine is None:
            raise ErreurAPI("Indiquez la cabine à ranger : ?cabine=<id>.")
        texte = (request.query_params.get("q")
                 or request.query_params.get("search") or "")
        lignes = services_cabines.emplacements_pour(cabine, texte)
        possibles = [ligne for ligne in lignes if ligne["possible"]]
        return Response({
            "cabine": {
                "id": cabine.id,
                "numero": cabine.numero,
                "modele": cabine.modele,
                "tout_l_emplacement": cabine.prend_tout_l_emplacement,
            },
            # Le meilleur candidat, celui que propose le bouton. `null` quand
            # l'entrepôt est plein pour cette cabine — et l'écran doit alors le
            # dire, pas rester muet.
            "proposition": possibles[0]["emplacement"].id if possibles else None,
            "possibles": len(possibles),
            "emplacements": [{
                "id": ligne["emplacement"].id,
                "code": ligne["emplacement"].code,
                "zone": (ligne["emplacement"].zone_cabine.nom
                         if ligne["emplacement"].zone_cabine_id else ""),
                "mode_libelle": ligne["emplacement"].get_mode_places_display(),
                "illimite": ligne["emplacement"].illimite,
                "staging": ligne["emplacement"].staging,
                "actif": ligne["emplacement"].actif,
                "libres": ligne["libres"],
                "possible": ligne["possible"],
                "pourquoi": ligne["pourquoi"],
                "cabines": ligne["cabines"],
            } for ligne in lignes],
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
                return Response(services_emplacements.apercu_rack(**parametres))
            resultat = services_emplacements.generer_rack(
                mode_places=d.get("mode_places"), usage=d.get("usage"),
                description=(d.get("description") or "")[:255], **parametres)
        except ValidationError as e:
            return Response({"erreur": e.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(resultat, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def usage(self, request):
        """Change ce que rangent plusieurs emplacements : cabines, cartons, vitrages.

        `{ids: [...], choix: "vitrage", apercu: true}` rend le bilan sans rien
        écrire ; sans `apercu`, l'applique aux emplacements qui le peuvent. Les
        autres sont nommés, avec ce qui les retient. Droit « référentiel ».
        """
        d = request.data
        ids = d.get("ids")
        if isinstance(ids, str):
            ids = ids.split(",")
        choix = str(d.get("choix") or "").strip()
        try:
            if d.get("apercu"):
                bilan = services_mp.apercu_usage(ids, choix)
            else:
                bilan = services_mp.changer_usage(ids, choix, utilisateur=request.user)
        except ValidationError as e:
            return Response({"erreur": e.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(bilan)

    @action(detail=False, methods=["post"])
    def codes(self, request):
        """Les codes qu'acceptent un ou plusieurs emplacements MP.

        `{ids: [...], articles: [...], mode: "remplacer" | "ajouter" | "tous",
        apercu: true}` rend le bilan sans rien écrire ; sans `apercu`, l'applique
        à ceux qui le prennent. « tous » retire la réservation : l'emplacement
        accepte de nouveau toute sa famille. Droit « référentiel », comme tout
        réglage d'emplacement.
        """
        d = request.data
        ids, articles = d.get("ids"), d.get("articles")
        if isinstance(ids, str):
            ids = ids.split(",")
        mode = str(d.get("mode") or "").strip()
        try:
            if d.get("apercu"):
                bilan = services_mp.apercu_codes(ids, articles, mode)
            else:
                bilan = services_mp.regler_codes(ids, articles, mode, utilisateur=request.user)
        except ValidationError as e:
            return Response({"erreur": e.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(bilan)

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
            return Response(services_emplacements.diagnostic_rack(
                request.query_params.get("rack")))
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
            return Response(services_emplacements.diagnostic_lot(brut.split(",")))
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
            return Response(services_emplacements.supprimer_lot(
                ids, utilisateur=request.user, motif=(d.get("motif") or "")[:180]))
        except ValidationError as e:
            return Response({"erreur": e.messages}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"], url_path="supprimer-rack")
    def supprimer_rack(self, request):
        """Supprime tout un rack, ou rien. Exige le droit « référentiel »."""
        d = request.data
        try:
            return Response(services_emplacements.supprimer_rack(
                d.get("rack"), utilisateur=request.user,
                motif=(d.get("motif") or "")[:180]))
        except ValidationError as e:
            return Response({"erreur": e.messages}, status=status.HTTP_400_BAD_REQUEST)

    def perform_destroy(self, instance):
        """Suppression refusée tant que des cabines y sont rangées.

        Règle et raison dans `services_emplacements` : la base, elle, les
        détacherait en silence.
        """
        try:
            services_emplacements.supprimer_emplacement(
                instance, utilisateur=self.request.user,
                motif=(self.request.query_params.get("motif") or "")[:180])
        except ValidationError as e:
            raise ErreurAPI({"erreur": e.messages})


#: Les écritures qu'un lien, un signet ou un script peuvent porter pour « oui ».
#: `config.settings._bool` accepte les mêmes : une seule définition du vrai dans
#: tout le projet, sinon `?toutes=TRUE` marche à un endroit et pas à l'autre.
_VRAI = ("1", "true", "vrai", "oui", "yes", "on")


def _actif(params, nom):
    """Un drapeau d'URL est-il posé ? Insensible à la casse et à l'écriture."""
    return (params.get(nom) or "").strip().lower() in _VRAI


def _filtre_id(params, nom):
    """Lit un filtre d'identifiant, en 400 explicite si la valeur n'est pas numérique.

    Sans ce contrôle, `?colonne=abc` remontait en ValueError (500).
    """
    brut = params.get(nom)
    if brut is None or brut == "":
        return None
    try:
        return int(brut)
    except (TypeError, ValueError):
        raise ErreurAPI({"erreur": [f"Le filtre « {nom} » doit être un identifiant numérique."]})


class CabineViewSet(viewsets.ModelViewSet):
    """Le parc. Les cabines envoyées n'apparaissent dans les listes qu'avec
    `?toutes=1` ; leur fiche, elle, reste toujours consultable."""
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
        "ranger": "cab", "statut": "cab", "envoyer": "cab",
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
                                  self._filtrer_anciennete):
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
        # Le motif de la dernière mise en quarantaine, annoté pour TOUTE la
        # liste d'un coup. Sans lui, « En quarantaine : 3 » donne trois numéros
        # et il faut ouvrir trois fiches pour savoir ce qui bloque — ce que
        # personne ne fait devant un rack. Une sous-requête corrélée pour la
        # liste entière, et non une requête par ligne.
        quarantaine = (MouvementCabine.objects
                       .filter(cabine=OuterRef("pk"), type=MouvementCabine.STATUT,
                               statut_apres=Cabine.QUARANTAINE)
                       .order_by("-date").values("note")[:1])
        return (Cabine.objects
                .prefetch_related("occupations__emplacement__zone_cabine")
                .annotate(derniere_activite_date=Coalesce(Subquery(dernier), "date"),
                          quarantaine_motif=Subquery(quarantaine)))

    def _filtrer_archives(self, qs, p):
        """Les cabines envoyées sont archivées : elles n'encombrent pas les listes.

        Le filtre ne s'applique QU'aux listes : une cabine envoyée doit rester
        consultable en détail, sinon son historique — la raison d'être des
        archives — renverrait 404. Les archives elles-mêmes, c'est la liste
        avec `?toutes=1&statut=envoye` : un seul chemin pour un seul besoin.
        L'export suit la liste : un inventaire du stock ne compte pas ce qui
        est déjà parti.
        """
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
                             ("statut", "statut"),
                             ("type", "type_cabine"),
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
        """Où la cabine se trouve : rangée ou non, et dans quel rack.

        Les deux traversent `occupations`, d'où le `distinct()` : une cabine
        posée à deux endroits du même rack ressortirait deux fois.
        """
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

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        """L'inventaire des cabines, tel que l'écran l'affiche, en fichier Excel.

        Le point d'entrée reprend `get_queryset` et les filtres de l'écran : on
        exporte ce qu'on voit. Sans cela, il faudrait redécrire les filtres dans
        l'URL de l'export, et les deux finiraient par diverger.
        """
        cabines = self.filter_queryset(self.get_queryset())
        return export_inventaire.reponse(cabines)

    def _run(self, fn):
        """Contrat d'erreur de toute l'API : 400 {"erreur": [...]}."""
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
            # Seulement les racks qui rangent des cabines : un rack tout entier
            # passé aux matières premières n'en contiendra jamais.
            "racks": sorted(r for r in (Emplacement.objects.exclude(rack="")
                                        .filter(usage=Emplacement.CABINES).order_by()
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
        """Le journal, filtrable par type d'événement ; `?search=` fait le reste."""
        qs = MouvementCabine.objects.select_related("cabine").all()
        if self.request.query_params.get("type"):
            qs = qs.filter(type=self.request.query_params["type"])
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
        # Un fichier de production a-t-il été importé ? C'est lui qui arme la
        # règle « une cabine non annoncée ne s'enregistre pas ». Sans cette
        # information, l'écran d'entrée refuserait une saisie que le serveur
        # accepte encore — ou proposerait une saisie qu'il va refuser.
        "fichier_production": CabineAttendue.objects.exists(),
        # La forme attendue d'un chantier, écrite une fois pour toutes sur le
        # modèle. Quatre écrans annonçaient « 6 chiffres » en dur ; le jour où le
        # lot a été accepté, aucun ne l'a su et tous continuaient à refuser
        # « 251213-1 » au clavier avant même que le serveur soit consulté.
        "aide_chantier": Cabine.AIDE_CHANTIER,
        "taille_chantier": Cabine.TAILLE_CHANTIER,
        # Le motif lui-même : l'écran refuse alors une forme fautive sans
        # aller-retour, et il refuse EXACTEMENT ce que le modèle refuse. Une
        # copie écrite à la main dans le JavaScript aurait divergé au premier
        # assouplissement — c'est déjà arrivé avec « 6 chiffres ».
        "motif_chantier": Cabine.MOTIF_CHANTIER,
    })


class ModeleCabineViewSet(viewsets.GenericViewSet):
    """Les modèles de cabine et leur taille — l'écran « Modèles ».

    La liste n'est pas seulement ce qui a été enregistré : elle est complétée par
    tous les modèles VUS dans le fichier de production et dans le stock. Un
    modèle qui apparaît au prochain import se règle donc sans que personne ait à
    le créer, et sans qu'on découvre son existence le jour où une cabine ne
    rentre pas dans son emplacement.

    Deux gestes, et deux seulement : lire la liste, régler un modèle. Pas de
    fiche par modèle — l'écran n'en a pas l'usage.
    """

    queryset = ModeleCabine.objects.all()
    serializer_class = ModeleCabineSerializer
    droit_ecriture = "ref"
    pagination_class = None

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
            "emplacements_hors_regle": services_cabines.emplacements_hors_regle(),
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
def moi(request):
    """Identité et droits du compte connecté.

    Permet au front de ne pas proposer une commande que le serveur refusera : sans
    cela l'interface affiche « Créer un rack » à un opérateur sans `droit_ref`,
    qui ne découvre le refus qu'après avoir rempli le formulaire. Le `pin` n'est
    volontairement pas exposé.
    """
    u = request.user
    return Response({
        "username": u.username,
        "nom": u.nom or u.username,
        "role": u.role,
        "is_superuser": u.is_superuser,
        # Au-delà des droits fins : l'import du fichier de production n'est pas
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
    # Le journal MP dit de même toute entrée et toute sortie de matières premières.
    mp = services_mp.empreinte()
    # La cloche : le nombre d'alertes et leur empreinte, pas leur liste. Elle
    # suit aussi ce qui ne passe pas par le journal — un seuil réglé, une
    # réservation posée —, que les compteurs ci-dessus ne voient pas.
    alertes, empreinte_alertes = services_mp.empreinte_alertes()
    return Response({
        "mouvements": mouvements["total"] or 0,
        "dernier": mouvements["dernier"] or 0,
        "cabines": Cabine.objects.count(),
        "emplacements": Emplacement.objects.count(),
        "mouvements_mp": mp["total"] or 0,
        "dernier_mp": mp["dernier"] or 0,
        "alertes": alertes,
        "alertes_empreinte": empreinte_alertes,
    })


@api_view(["GET"])
def alertes(request):
    """Ce que signale la cloche, en haut à droite des écrans.

    Aujourd'hui, les matières premières : les codes sous leur seuil d'alerte,
    et les lignes posées là où leur code n'est plus accepté. La réponse est
    rangée par groupes — `type`, `titre`, `items` — pour qu'une autre sorte
    d'alerte s'y ajoute sans changer l'écran.
    """
    return Response(services_mp.alertes())


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

    @action(detail=False, methods=["get"], pagination_class=None)
    def par_semaine(self, request):
        """Annoncées et arrivées, semaine de production par semaine.

        La question à laquelle cet écran répond : « la production annoncée en
        S37 est-elle arrivée ? ». Donc « arrivées » compte les cabines ENTRÉES
        UN JOUR, celles déjà parties en chantier comprises — une cabine posée
        puis livrée est bien arrivée. Compter le stock du moment ferait baisser
        le chiffre à mesure que la production part, et la comparaison ne voudrait
        plus rien dire.

        Le lien entre les deux tables est le NUMÉRO, et lui seul : le fichier
        annonce des numéros, une cabine en stock en porte un. Une cabine créée
        hors fichier n'appartient donc à aucune semaine — elle est comptée à
        part plutôt que rattachée au hasard.

        `semaine_production` est une chaîne (« S37 »), pas une date : c'est ce
        que le classeur écrit, et le zéro de « S04 » fait que l'ordre
        alphabétique est le bon. Les lignes sans semaine sont regroupées sous
        une clé vide, en dernier, plutôt que masquées : 60 cabines sans semaine
        seraient une information sur le fichier, pas un détail à cacher.
        """
        annoncees = (CabineAttendue.objects
                     .values_list("semaine_production", "numero"))
        par_semaine = {}
        for semaine, numero in annoncees:
            par_semaine.setdefault((semaine or "").strip(), set()).add(numero)

        # Un seul aller-retour pour tous les numéros en stock : une requête par
        # semaine ferait 42 requêtes pour un écran de lecture.
        en_base = set(Cabine.objects.values_list("numero", flat=True))
        presentes = set(Occupation.objects
                        .exclude(cabine__statut=Cabine.ENVOYE)
                        .filter(emplacement__isnull=False)
                        .values_list("cabine__numero", flat=True))

        lignes = []
        for semaine in sorted(par_semaine, key=lambda s: (s == "", s)):
            numeros = par_semaine[semaine]
            arrivees = numeros & en_base
            lignes.append({
                "semaine": semaine,
                "annoncees": len(numeros),
                "arrivees": len(arrivees),
                "reste": len(numeros) - len(arrivees),
                # Secondaire, mais c'est la question suivante : parmi les
                # arrivées, combien sont encore rangées quelque part.
                "rangees": len(arrivees & presentes),
            })

        hors_fichier = len(en_base - set().union(*par_semaine.values())
                           if par_semaine else en_base)
        return Response({
            "semaines": lignes,
            "annoncees": sum(x["annoncees"] for x in lignes),
            "arrivees": sum(x["arrivees"] for x in lignes),
            "hors_fichier": hors_fichier,
        })

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


def _entier(brut):
    """Un identifiant entier, ou `None`. Les chiffres 0 à 9 seulement :
    `isdigit()` accepte « ² », que `int()` refuse ensuite — une erreur 500."""
    texte = str(brut if brut is not None else "").strip()
    return int(texte) if re.fullmatch(r"[0-9]+", texte) else None


class MatieresPremieresViewSet(viewsets.ViewSet):
    """Matières premières : vitrages et cartons, emplacement par emplacement.

    Toutes les routes sont sous `/api/mp/`. La lecture est ouverte à tout
    compte ; les gestes sur le stock — entrer, sortir, changer d'emplacement —
    exigent la case « matières premières ». Régler un seuil d'alerte est un
    réglage de la base des codes, pas un geste de poste : il demande le
    référentiel. Les règles vivent dans `services_mp`, la vue ne fait que
    traduire les refus en réponses 400.
    """

    droit_ecriture = "mp"
    #: Les exceptions au droit de la vue. Toute autre écriture reste sous
    #: `droit_ecriture` — voir `DroitWMS.droit_requis`.
    droits_par_action = {"seuils": "ref"}

    @staticmethod
    def _400(e):
        return Response({"erreur": e.messages}, status=status.HTTP_400_BAD_REQUEST)

    @staticmethod
    def _emplacement(params):
        """L'emplacement visé, par identifiant ou par le code lu sur l'étiquette."""
        brut_id = str(params.get("id") or params.get("emplacement") or "").strip()
        code = re.sub(r"^LOC:", "", str(params.get("code") or "").strip(), flags=re.I).strip().upper()
        if _entier(brut_id) is not None:
            e = Emplacement.objects.filter(pk=_entier(brut_id)).first()
        elif code:
            e = Emplacement.objects.filter(code=code).first()
        else:
            raise ErreurAPI({"erreur": ["Indiquez l'emplacement : ?id= ou ?code=."]})
        if e is None:
            raise ErreurAPI({"erreur": [
                f"Aucun emplacement ne porte le code « {code or brut_id} »."]})
        return e

    @action(detail=False, methods=["get"])
    def emplacement(self, request):
        """Ce que porte un emplacement MP, place par place.

        Un emplacement de cabines répond aussi, avec `est_mp: false` et la
        phrase à afficher : l'écran le dit sur la vidéo, au moment du scan.
        """
        e = self._emplacement(request.query_params)
        reponse = services_mp.contenu(e)
        reponse["refus"] = services_mp.refus_emplacement(e) if not e.est_mp else ""
        return Response(reponse)

    @action(detail=False, methods=["get"])
    def suggestions(self, request):
        """Les codes qui ressemblent à la saisie : « vitr.8 » → VITR.831…, VITR.814…

        `?emplacement=<id>` : seulement ceux qu'il accepte, s'il est réservé.
        """
        p = request.query_params
        famille = (p.get("famille") or "").strip()
        if famille and famille not in dict(ArticleMP.FAMILLES):
            raise ErreurAPI({"erreur": [f"Famille inconnue : « {famille} »."]})
        emplacement = None
        if str(p.get("emplacement") or "").strip():
            emplacement = self._emplacement({"id": p.get("emplacement")})
        return Response(services_mp.suggerer(p.get("q") or "", famille=famille or None,
                                             emplacement=emplacement))

    @staticmethod
    def _filtres(p):
        return {
            "texte": p.get("q") or p.get("search") or "",
            "famille": (p.get("famille") or "").strip(),
            "fournisseur": (p.get("fournisseur") or "").strip(),
            "rack": (p.get("rack") or "").strip(),
            "generation": (p.get("generation") or "").strip(),
            "sous_seuil": _actif(p, "sous_seuil"),
            "tous": _actif(p, "tous"),
            "tri": (p.get("tri") or "code").strip(),
        }

    @action(detail=False, methods=["get"])
    def stock(self, request):
        """Le stock par code, avec ses positions. Toute la liste : elle est courte."""
        return Response(services_mp.stock(**self._filtres(request.query_params)))

    @action(detail=False, methods=["get"])
    def export(self, request):
        """Le stock affiché, en fichier pour Excel : une ligne par position."""
        return export_mp.reponse(services_mp.stock(**self._filtres(request.query_params)))

    @action(detail=False, methods=["get"])
    def filtres(self, request):
        return Response(services_mp.compteurs())

    @action(detail=False, methods=["get"])
    def article(self, request):
        brut = str(request.query_params.get("id") or "").strip()
        article = ArticleMP.objects.filter(pk=_entier(brut)).first() if _entier(brut) else None
        if article is None:
            raise ErreurAPI({"erreur": ["Code introuvable dans la base MP."]})
        return Response(services_mp.detail_article(article))

    @action(detail=False, methods=["get"])
    def journal(self, request):
        """Le journal MP, paginé comme celui des cabines."""
        p = request.query_params
        qs = MouvementMP.objects.all()
        if p.get("type") in dict(MouvementMP.TYPES):
            qs = qs.filter(type=p["type"])
        terme = (p.get("search") or "").strip()
        if terme:
            cle = re.sub(r"[^0-9A-Za-z]", "", terme)
            # Un changement d'emplacement se retrouve par son départ comme par
            # son arrivée : « AH500 » doit montrer ce qui en est parti.
            filtre = (Q(article_code__icontains=terme) | Q(position__icontains=terme)
                      | Q(origine__icontains=terme)
                      | Q(utilisateur_nom__icontains=terme) | Q(note__icontains=terme))
            if cle:
                filtre |= Q(article__cle__icontains=cle.upper())
            qs = qs.filter(filtre)
        if _entier(p.get("article")) is not None:
            qs = qs.filter(article_id=_entier(p.get("article")))
        page = self.paginator.paginate_queryset(qs, request, view=self)
        return self.paginator.get_paginated_response(
            [services_mp.mouvement_public(m) for m in page])

    @property
    def paginator(self):
        if not hasattr(self, "_paginateur"):
            from rest_framework.pagination import PageNumberPagination
            self._paginateur = PageNumberPagination()
        return self._paginateur

    @action(detail=False, methods=["post"])
    def entrer(self, request):
        """Entre du stock : `{emplacement, place, article, quantite, ancienne_confirmee}`.

        `article` est l'identifiant choisi dans les suggestions — ou, à défaut, le
        code exact. Un code approchant n'est jamais deviné : la saisie se choisit
        dans la liste, c'est ce qui garde la base propre.
        """
        d = request.data
        e = self._emplacement(d)
        brut = str(d.get("article") or "").strip()
        article = (ArticleMP.objects.filter(pk=_entier(brut)).first() if _entier(brut) is not None
                   else ArticleMP.objects.filter(code=brut.upper()).first() if brut else None)
        if article is None:
            return Response({"erreur": [
                "Choisis le code dans la liste proposée : il doit exister dans la base MP."]},
                status=status.HTTP_400_BAD_REQUEST)
        try:
            ligne = services_mp.entrer(
                emplacement=e, place=d.get("place"), article=article,
                quantite=d.get("quantite"), utilisateur=request.user,
                ancienne_confirmee=str(d.get("ancienne_confirmee", "")).lower() in _VRAI,
                note=str(d.get("note") or "")[:255])
        except ValidationError as err:
            return self._400(err)
        return Response({"ligne": services_mp.ligne_publique(ligne),
                         "emplacement": services_mp.contenu(ligne.emplacement)},
                        status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def sortir(self, request):
        """Sort du stock : `{ligne, quantite}` — sans quantité, toute la ligne."""
        d = request.data
        ligne = _entier(d.get("ligne"))
        if ligne is None:
            return Response({"erreur": ["Quelle ligne de stock sortir ?"]},
                            status=status.HTTP_400_BAD_REQUEST)
        emplacement_id, article_id = (StockMP.objects.filter(pk=ligne)
                                      .values_list("emplacement_id", "article_id").first()
                                      or (None, None))
        try:
            reste = services_mp.sortir(ligne=ligne, quantite=d.get("quantite"),
                                       utilisateur=request.user,
                                       note=str(d.get("note") or "")[:255])
        except ValidationError as err:
            return self._400(err)
        emplacement = Emplacement.objects.get(pk=emplacement_id)
        # Ce qu'il reste du code, partout : la phrase de réussite dit tout de
        # suite qu'il vient de passer sous son seuil d'alerte.
        return Response({"reste": reste, "emplacement": services_mp.contenu(emplacement),
                         "article": services_mp.etat_du_code(ArticleMP.objects.get(pk=article_id))})

    @action(detail=False, methods=["post"])
    def deplacer(self, request):
        """Change d'emplacement : `{lignes: [{ligne, quantite}], emplacement | code, place}`.

        Une ligne sans quantité part entière. Tout passe, ou rien : la réponse
        400 nomme la ligne qui bloque. La réponse rend le contenu des deux
        bouts — l'écran redessine le départ, et propose d'ouvrir l'arrivée.
        """
        d = request.data
        vers = self._emplacement({"id": d.get("emplacement"), "code": d.get("code")})
        try:
            r = services_mp.deplacer(lignes=d.get("lignes"), vers=vers, place=d.get("place"),
                                     utilisateur=request.user,
                                     note=str(d.get("note") or "")[:255])
        except ValidationError as err:
            return self._400(err)
        return Response({
            "deplaces": r["deplaces"],
            "destination": services_mp.contenu(r["destination"]),
            "sources": [services_mp.contenu(e) for e in r["sources"]],
        })

    @action(detail=False, methods=["post"])
    def seuils(self, request):
        """Le même seuil d'alerte pour un ou plusieurs codes : `{articles: [...], seuil}`.

        `seuil` vide ou 0 : plus d'alerte pour ces codes. Droit « référentiel ».
        """
        d = request.data
        try:
            r = services_mp.regler_seuils(d.get("articles"), d.get("seuil"),
                                          utilisateur=request.user)
        except ValidationError as err:
            return self._400(err)
        return Response(r)
