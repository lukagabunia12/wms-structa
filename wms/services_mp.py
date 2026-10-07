"""Matières premières — le passage obligé de toute écriture sur le stock MP.

Vitrages et cartons se rangent sur des emplacements MP, à trois places :
gauche, milieu, droite. Toute entrée et toute sortie passe par ce module, qui
écrit le `MouvementMP` dans la même transaction : un chiffre de stock qui
change sans ligne au journal est un chiffre que personne ne sait expliquer.

Règles portées ici :
- un emplacement range des cabines OU une famille de MP, jamais les deux ;
- un code ne se range que sur un emplacement de sa famille — et, si
  l'emplacement est réservé à certains codes, que s'il en fait partie ;
- un code d'ancienne génération s'entre seulement après confirmation ;
- une place condamnée ou un emplacement hors service ne reçoivent rien ;
- on ne sort ni ne déplace jamais plus que ce qui est là.

Le réglage des emplacements — ce qu'ils rangent, les codes qu'ils acceptent —
et celui des seuils d'alerte vivent aussi ici : ils ne se décident qu'en
regardant le stock. Les alertes de la cloche se calculent ici, une fois.
"""
import hashlib
import logging
import re

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, F, Max, OuterRef, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import (ArticleMP, Cabine, Emplacement, MouvementMP, Occupation,
                     PlaceCondamnee, StockMP, normaliser_code_mp)

logger = logging.getLogger(__name__)


class ErreurMP(ValidationError):
    """Refus lisible : la vue le rend en 400, avec son message."""


PLACES = [code for code, _ in StockMP.PLACES]
NOMS_PLACES = {"G": "gauche", "M": "milieu", "D": "droite"}
#: Au-delà, c'est une faute de frappe (un zéro de trop) plutôt qu'une livraison.
QUANTITE_MAX = 100_000

FAMILLE_LIBELLE = {ArticleMP.VITRAGE: "vitrages", ArticleMP.CARTON: "cartons"}


def _nom(utilisateur):
    if not utilisateur or not getattr(utilisateur, "pk", None):
        return ""
    return getattr(utilisateur, "nom", "") or utilisateur.get_username()


def libelle_usage(usage):
    """« MP · vitrages », « Cabines »… — le libellé du modèle, une seule source."""
    return dict(Emplacement.USAGES).get(usage, usage)


# --- Lecture -----------------------------------------------------------------

def ligne_publique(ligne):
    """Une ligne de stock telle que les écrans la lisent."""
    a = ligne.article
    return {
        "id": ligne.id,
        "place": ligne.place,
        "quantite": ligne.quantite,
        "article": a.id,
        "code": a.code,
        "designation": a.designation,
        "famille": a.famille,
        "ancienne_generation": a.ancienne_generation,
        "colisage": a.colisage,
        "entre_le": ligne.entre_le,
        "modifie_le": ligne.modifie_le,
    }


def contenu(emplacement):
    """Ce que porte un emplacement MP, place par place.

    Les trois places sont TOUJOURS rendues, vides comprises : devant le rack,
    « milieu : libre » est une information, une place absente de l'écran n'en
    est pas une.

    Les codes acceptés viennent avec : l'écran d'entrée les propose d'une
    touche, et une ligne posée avant la réservation est marquée
    `hors_reservation` — elle peut sortir ou changer d'emplacement, rien de ce
    code n'entrera plus ici.
    """
    lignes = list(StockMP.objects.filter(emplacement=emplacement)
                  .select_related("article").order_by("place", "article__code"))
    condamnees = {p.place: p.motif for p in emplacement.places_condamnees.all()}
    acceptes = codes_acceptes(emplacement)
    ids_acceptes = {a.pk for a in acceptes}
    places = []
    for code, libelle in StockMP.PLACES:
        ici = [{**ligne_publique(x),
                "hors_reservation": bool(ids_acceptes) and x.article_id not in ids_acceptes}
               for x in lignes if x.place == code]
        places.append({
            "code": code,
            "libelle": libelle,
            "condamnee": condamnees.get(code) or None,
            "lignes": ici,
            "quantite": sum(x["quantite"] for x in ici),
        })
    return {
        "emplacement": emplacement.id,
        "code": emplacement.code,
        "rack": emplacement.rack,
        "usage": emplacement.usage,
        "usage_libelle": libelle_usage(emplacement.usage),
        "est_mp": emplacement.est_mp,
        "famille": emplacement.usage if emplacement.est_mp else None,
        "actif": emplacement.actif,
        "motif_inactif": emplacement.motif_inactif,
        "places": places,
        "nb_lignes": len(lignes),
        "quantite": sum(x.quantite for x in lignes),
        "codes_acceptes": [article_public(a) for a in acceptes],
    }


def _rang(article, cle):
    """Où classer ce code pour ce qui a été tapé. `None` : il ne correspond pas.

    0 : le code commence par la saisie — « vitr8 » → VITR.831…
    1 : le code la contient — « 445 » → VITR.445X2072.BP
    2 : une autre référence la contient, ou c'est le n° article (« 434 »)
    3 : la désignation la contient (« quattro », « fond s »)

    La désignation vient en dernier, et seulement à partir de trois signes :
    « 44 » se trouve dans tous les vitrages (« 44/2 acoustique »), il ne doit
    pas noyer les codes qui le portent vraiment.
    """
    if article.cle.startswith(cle):
        return 0
    if cle in article.cle:
        return 1
    if article.numero and normaliser_code_mp(article.numero) == cle:
        return 2
    if any(cle in r for r in (article.cle_references or "").split("|") if r):
        return 2
    if len(cle) >= 3 and cle in normaliser_code_mp(article.designation):
        return 3
    return None


def _ordre_naturel(code):
    """VITR.831… avant VITR.1060… : les nombres se comparent comme des nombres."""
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", code)]


def _ordre_position(ligne):
    """AH500·G, AH500·M, AH500·D, puis AH510 : l'ordre du rack, de gauche à droite,
    et non celui de l'alphabet, qui mettrait la droite avant la gauche."""
    return (_ordre_naturel(ligne.emplacement.code), PLACES.index(ligne.place)
            if ligne.place in PLACES else len(PLACES))


def suggerer(texte, famille=None, limite=12, emplacement=None):
    """Les codes de la base qui ressemblent à ce qui a été tapé, les plus sûrs d'abord.

    Le classement se fait ici et non en base : quelques dizaines de codes, et
    une règle de pertinence qu'un `LIKE` ne sait pas exprimer. Les codes
    d'ancienne génération restent proposés — il reste du stock à ranger —,
    mais APRÈS ceux d'aujourd'hui à pertinence égale : celui qu'on cherche le
    plus souvent est l'actuel.

    Avec `emplacement`, seuls les codes qu'il accepte sont proposés : choisir
    dans la liste un code que le serveur refusera ensuite est un aller-retour
    pour rien, devant le rack.

    Chaque code dit aussi où il a une place réservée (`reserve_sur`) : à
    l'entrée, c'est la réponse à « où est-ce que je le pose ? ».
    """
    cle = normaliser_code_mp(texte)
    if not cle:
        return []
    qs = ArticleMP.objects.filter(actif=True)
    if famille:
        qs = qs.filter(famille=famille)
    if emplacement is not None:
        acceptes = codes_acceptes(emplacement)
        if acceptes:
            qs = qs.filter(pk__in=[a.pk for a in acceptes])
    trouves = []
    for article in qs:
        rang = _rang(article, cle)
        if rang is not None:
            trouves.append((rang, article.ancienne_generation,
                            _ordre_naturel(article.code), article))
    trouves.sort(key=lambda t: t[:3])
    articles = [t[3] for t in trouves[:limite]]
    stock = dict(StockMP.objects.filter(article__in=articles)
                 .values("article").annotate(q=Sum("quantite"))
                 .values_list("article", "q"))
    reserves = _reserves_de(articles)
    return [{**article_public(a, en_stock=stock.get(a.id, 0)),
             "reserve_sur": reserves.get(a.id, [])} for a in articles]


def _reserves_de(articles):
    """{id du code: [codes des emplacements qui lui sont réservés]}, en une requête."""
    liaison = Emplacement.codes_acceptes.through
    resultat = {}
    for article_id, code in (liaison.objects.filter(articlemp_id__in=[a.pk for a in articles])
                             .values_list("articlemp_id", "emplacement__code")):
        resultat.setdefault(article_id, []).append(code)
    return {k: sorted(v, key=_ordre_naturel) for k, v in resultat.items()}


def article_public(article, en_stock=None):
    return {
        "id": article.id,
        "code": article.code,
        "famille": article.famille,
        "famille_libelle": article.get_famille_display(),
        "designation": article.designation,
        "fournisseur": article.fournisseur,
        "numero": article.numero,
        "references": article.references,
        "colisage": article.colisage,
        "seuil_reappro": article.seuil_reappro,
        "ancienne_generation": article.ancienne_generation,
        "actif": article.actif,
        "en_stock": en_stock,
    }


def sous_le_seuil(article, total):
    """Le code est-il sous son seuil d'alerte ? Jamais pour une ancienne
    génération : on l'écoule, on ne la recommande pas.

    Un code sans seuil n'est jamais « sous le seuil » — on ne sait pas. Le
    seuil se franchit EN DESSOUS : 20 en stock pour un seuil de 20 ne
    déclenche rien, 19 si. C'est la phrase de l'écran de réglage.
    """
    return bool(article.actif and not article.ancienne_generation
                and article.seuil_reappro and (total or 0) < article.seuil_reappro)


#: Les tris de la liste de stock : clé d'URL → libellé et clé de tri.
TRIS = {
    "code": "Code",
    "quantite": "Quantité, la plus forte d'abord",
    "recent": "Dernier mouvement",
}


def stock(*, texte="", famille="", fournisseur="", rack="", generation="",
          sous_seuil=False, tous=False, tri="code"):
    """Le stock MP par code : combien, et où. C'est la liste du Parc « MP ».

    Une ligne par code, avec ses positions : la question posée est « où sont
    les VITR.445 et combien en reste-t-il ? », pas « que porte AH120 ? » —
    celle-là se pose en scannant l'emplacement.

    `texte` cherche dans les codes, les références, les désignations ET les
    emplacements : « AH12 » rend ce qui est rangé en AH12x. Deux requêtes,
    quelle que soit la taille de la base.
    """
    cle = normaliser_code_mp(texte)
    articles = ArticleMP.objects.all()
    if famille:
        articles = articles.filter(famille=famille)
    if fournisseur:
        articles = articles.filter(fournisseur__iexact=fournisseur)
    if generation == "ancienne":
        articles = articles.filter(ancienne_generation=True)
    elif generation == "actuelle":
        articles = articles.filter(ancienne_generation=False)

    lignes = (StockMP.objects.filter(article__in=articles)
              .select_related("emplacement", "article")
              .order_by("emplacement__code", "place"))
    if rack:
        lignes = lignes.filter(emplacement__rack__iexact=rack.strip())
    par_article = {}
    for ligne in sorted(lignes, key=_ordre_position):
        par_article.setdefault(ligne.article_id, []).append(ligne)

    # Un code sans stock n'apparaît que si on le demande : toute la base, ou ce
    # qui est sous le seuil — un code à zéro est le premier à recommander.
    montrer_vides = (tous or sous_seuil) and not rack
    resultat = []
    for article in articles:
        ici = par_article.get(article.id, [])
        if not ici and not montrer_vides:
            continue
        if cle:
            rang = _rang(article, cle)
            dans_emplacement = any(cle in normaliser_code_mp(x.emplacement.code) for x in ici)
            if rang is None and not dans_emplacement:
                continue
        total = sum(x.quantite for x in ici)
        bas = sous_le_seuil(article, total)
        if sous_seuil and not bas:
            continue
        resultat.append({
            **article_public(article, en_stock=total),
            "sous_seuil": bas,
            "dernier_mouvement": max((x.modifie_le for x in ici), default=None),
            "positions": [{
                "ligne": x.id,
                "emplacement": x.emplacement_id,
                "code_emplacement": x.emplacement.code,
                "place": x.place,
                "position": x.position,
                "quantite": x.quantite,
            } for x in ici],
        })

    if tri == "quantite":
        resultat.sort(key=lambda a: (-(a["en_stock"] or 0), _ordre_naturel(a["code"])))
    elif tri == "recent":
        resultat.sort(key=lambda a: (a["dernier_mouvement"] is None,
                                     -(a["dernier_mouvement"].timestamp()
                                       if a["dernier_mouvement"] else 0)))
    else:
        resultat.sort(key=lambda a: (a["famille"] != ArticleMP.VITRAGE,
                                     _ordre_naturel(a["code"])))
    return resultat


def compteurs():
    """Les chiffres du haut de l'écran MP, et les listes de ses filtres."""
    par_famille = {f: {"codes": 0, "quantite": 0} for f, _ in ArticleMP.FAMILLES}
    for ligne in (StockMP.objects.values("article__famille")
                  .annotate(codes=Count("article", distinct=True), q=Sum("quantite"))):
        par_famille[ligne["article__famille"]] = {"codes": ligne["codes"],
                                                  "quantite": ligne["q"] or 0}
    totaux = dict(StockMP.objects.values("article").annotate(q=Sum("quantite"))
                  .values_list("article", "q"))
    sous_seuil = 0
    anciennes = 0
    for a in ArticleMP.objects.filter(Q(pk__in=totaux.keys()) | Q(seuil_reappro__isnull=False)):
        total = totaux.get(a.id, 0)
        if sous_le_seuil(a, total):
            sous_seuil += 1
        if a.ancienne_generation and total:
            anciennes += 1
    return {
        "familles": par_famille,
        "ancienne_generation": anciennes,
        "sous_seuil": sous_seuil,
        # `.order_by()` vide n'est pas décoratif : le tri par défaut du modèle
        # entrerait dans le DISTINCT, et chaque rack reviendrait une fois par
        # emplacement.
        "fournisseurs": sorted(f for f in ArticleMP.objects.exclude(fournisseur="")
                               .order_by().values_list("fournisseur", flat=True)
                               .distinct() if f),
        "racks": sorted(r for r in Emplacement.objects.exclude(usage=Emplacement.CABINES)
                        .exclude(rack="").order_by().values_list("rack", flat=True)
                        .distinct() if r),
        "emplacements_mp": Emplacement.objects.exclude(usage=Emplacement.CABINES).count(),
        "tris": [{"code": c, "libelle": libelle} for c, libelle in TRIS.items()],
    }


def detail_article(article, mouvements=12):
    """La fiche d'un code : sa base, ses positions, ses derniers mouvements."""
    lignes = sorted(StockMP.objects.filter(article=article).select_related("emplacement"),
                    key=_ordre_position)
    total = sum(x.quantite for x in lignes)
    reserves = list(article.emplacements_reserves.order_by().values("id", "code"))
    return {
        **article_public(article, en_stock=total),
        "sous_seuil": sous_le_seuil(article, total),
        "positions": [{
            "ligne": x.id, "emplacement": x.emplacement_id,
            "code_emplacement": x.emplacement.code, "place": x.place,
            "position": x.position, "quantite": x.quantite,
            "entre_le": x.entre_le, "modifie_le": x.modifie_le,
        } for x in lignes],
        # Les emplacements réservés à ce code : où il est ATTENDU, qu'il y soit
        # ou non. Avec ses positions, la fiche répond à « où est-il ? » et à
        # « où doit-il aller ? ».
        "reserve_sur": sorted(reserves, key=lambda e: _ordre_naturel(e["code"])),
        "mouvements": [mouvement_public(m) for m in
                       MouvementMP.objects.filter(article=article)[:mouvements]],
    }


def mouvement_public(m):
    return {
        "id": m.id, "date": m.date, "type": m.type, "type_libelle": m.get_type_display(),
        "article": m.article_id, "code": m.article_code, "famille": m.famille,
        "emplacement": m.emplacement_id, "position": m.position,
        "quantite": m.quantite, "reste": m.reste,
        "origine": m.origine, "reste_origine": m.reste_origine,
        "utilisateur_nom": m.utilisateur_nom, "note": m.note,
    }


# --- Écriture ----------------------------------------------------------------

def _quantite(brut):
    """Une quantité entière et positive, ou un refus qui dit laquelle on attend."""
    texte = str(brut if brut is not None else "").strip().replace(" ", "")
    if not texte:
        raise ErreurMP("Indique la quantité.")
    # Des chiffres de 0 à 9, et eux seuls : `isdigit()` accepte aussi « ² »,
    # que `int()` refuse ensuite — une erreur 500 au lieu d'un refus lisible.
    if not re.fullmatch(r"[0-9]+", texte):
        raise ErreurMP(f"Quantité « {brut} » illisible : un nombre entier de pièces, "
                       "sans virgule.")
    n = int(texte)
    if n < 1:
        raise ErreurMP("La quantité doit être d'au moins 1.")
    if n > QUANTITE_MAX:
        raise ErreurMP(f"{n} pièces d'un coup : c'est sûrement une faute de frappe "
                       f"({QUANTITE_MAX} au plus).")
    return n


def _tracer(type, *, article, emplacement, place, quantite, reste, utilisateur, note="",
            origine="", reste_origine=None):
    return MouvementMP.objects.create(
        type=type, article=article, article_code=article.code, famille=article.famille,
        emplacement=emplacement, position=f"{emplacement.code}·{place}",
        quantite=quantite, reste=reste, origine=origine, reste_origine=reste_origine,
        utilisateur=utilisateur if getattr(utilisateur, "pk", None) else None,
        utilisateur_nom=_nom(utilisateur), note=(note or "").strip()[:255])


def codes_acceptes(emplacement):
    """Les codes qu'accepte cet emplacement, dans l'ordre naturel — [] : tous
    ceux de sa famille. Lit le préchargement de la vue quand il existe."""
    return sorted(emplacement.codes_acceptes.all(), key=lambda a: _ordre_naturel(a.code))


def liste_codes(codes, combien=3):
    """« VITR.445, VITR.470 et 2 autres » : assez pour reconnaître, pas un roman."""
    codes = list(codes)
    if len(codes) <= 1:
        return "".join(codes)
    if len(codes) <= combien:
        return f"{', '.join(codes[:-1])} et {codes[-1]}"
    reste = len(codes) - combien
    return f"{', '.join(codes[:combien])} et {reste} autre{'s' if reste > 1 else ''}"


def refus_code(emplacement, article, acceptes=None):
    """Pourquoi ce code n'entre pas ici à cause de la réservation — "" s'il entre.

    Séparé de `refus_emplacement` : un emplacement réservé reste un emplacement
    où l'on PEUT entrer ; c'est ce code-là qui n'y va pas, et le message dit
    lesquels y vont.
    """
    if acceptes is None:
        acceptes = codes_acceptes(emplacement)
    if not acceptes or any(a.pk == article.pk for a in acceptes):
        return ""
    return (f"{emplacement.code} est réservé à {liste_codes(a.code for a in acceptes)} : "
            f"{article.code} n'y entre pas. Choisis un autre emplacement, ou fais régler "
            "ses codes acceptés.")


def refus_emplacement(emplacement, famille=None):
    """Pourquoi on ne peut rien entrer ici — "" si on le peut.

    Écrit une fois, ici : l'écran l'affiche sur la vidéo au moment du scan, et
    le serveur le redit si l'écran l'a manqué.
    """
    if not emplacement.est_mp:
        return (f"{emplacement.code} range des cabines : on n'y pose pas de matières "
                "premières. Pour le changer, Emplacements → l'emplacement → réglages.")
    if not emplacement.actif:
        motif = f" : {emplacement.motif_inactif}" if emplacement.motif_inactif else ""
        return f"{emplacement.code} est hors service{motif}."
    if famille and famille != emplacement.usage:
        return (f"{emplacement.code} range des {FAMILLE_LIBELLE[emplacement.usage]} : "
                f"un {dict(ArticleMP.FAMILLES)[famille].lower()} n'y va pas.")
    return ""


def _verrouiller_emplacement(pk):
    """Le verrou de l'emplacement, posé AVANT celui d'une ligne de stock.

    Toujours dans cet ordre — emplacement, puis ligne —, pour l'entrée comme pour
    la sortie : deux gestes simultanés sur le même emplacement s'attendent l'un
    l'autre au lieu de se bloquer mutuellement (PostgreSQL annulerait alors
    l'un des deux, et le cariste verrait une erreur sans rapport).
    """
    return Emplacement.objects.select_for_update().filter(pk=pk).first()


def _ligne_verrouillee(**critere):
    """Une ligne de stock, verrouillée SEULE.

    `of=("self",)` : sans lui, PostgreSQL verrouille aussi les lignes jointes —
    l'emplacement et le code, par le tri par défaut de `StockMP` — et deux
    gestes croisés sur le même code s'interbloquent. Sans effet sur SQLite, qui
    n'a pas de verrou de ligne.
    """
    return (StockMP.objects.select_for_update(of=("self",))
            .filter(**critere).order_by("pk").first())


@transaction.atomic
def entrer(*, emplacement, place, article, quantite, utilisateur=None,
           ancienne_confirmee=False, note=""):
    """Pose `quantite` pièces de `article` sur une place. Rend la ligne de stock.

    Le même code déjà présent sur la même place voit sa quantité augmenter : une
    deuxième palette posée sur la première ne crée pas une deuxième ligne.
    """
    # Verrou sur l'emplacement : deux entrées simultanées sur la même place
    # s'écrivent l'une après l'autre, sans se marcher dessus.
    emplacement = _verrouiller_emplacement(getattr(emplacement, "pk", emplacement))
    if emplacement is None:
        raise ErreurMP("Cet emplacement vient d'être supprimé depuis un autre poste.")
    refus = refus_emplacement(emplacement, article.famille) or refus_code(emplacement, article)
    if refus:
        raise ErreurMP(refus)
    place = str(place or "").strip().upper()
    if place not in PLACES:
        raise ErreurMP("Touche la place où tu poses : gauche, milieu ou droite.")
    if not article.actif:
        raise ErreurMP(f"{article.code} n'est plus actif dans la base : il ne s'entre plus.")
    condamnee = (PlaceCondamnee.objects.filter(emplacement=emplacement, place=place)
                 .values_list("motif", flat=True).first())
    if condamnee is not None:
        raise ErreurMP(f"La place {NOMS_PLACES[place]} de {emplacement.code} est "
                       f"condamnée : {condamnee}. Choisis une autre place.")
    n = _quantite(quantite)
    if article.ancienne_generation and not ancienne_confirmee:
        raise ErreurMP(f"{article.code} est une ANCIENNE GÉNÉRATION. Confirme que tu "
                       "veux vraiment l'entrer.")

    ligne = _ligne_verrouillee(emplacement=emplacement, place=place, article=article)
    if ligne is None:
        try:
            with transaction.atomic():
                ligne = StockMP.objects.create(emplacement=emplacement, place=place,
                                               article=article, quantite=n)
        except IntegrityError:
            # Créée par un autre poste entre la lecture et l'écriture : on ajoute.
            ligne = _ligne_verrouillee(emplacement=emplacement, place=place, article=article)
            ligne.quantite += n
            ligne.save(update_fields=["quantite", "modifie_le"])
    else:
        ligne.quantite += n
        ligne.save(update_fields=["quantite", "modifie_le"])

    if article.ancienne_generation:
        note = " — ".join(x for x in ["ancienne génération confirmée", (note or "").strip()] if x)
    _tracer(MouvementMP.ENTREE, article=article, emplacement=emplacement, place=place,
            quantite=n, reste=ligne.quantite, utilisateur=utilisateur, note=note)
    return ligne


@transaction.atomic
def sortir(*, ligne, quantite=None, utilisateur=None, note=""):
    """Retire des pièces d'une ligne de stock. Sans quantité : tout.

    Rend ce qui reste à cette place pour ce code (0 quand la ligne disparaît).
    """
    identifiant = getattr(ligne, "pk", ligne)
    emplacement_id = (StockMP.objects.filter(pk=identifiant)
                      .values_list("emplacement_id", flat=True).first())
    if emplacement_id is not None:
        _verrouiller_emplacement(emplacement_id)
    ligne = _ligne_verrouillee(pk=identifiant)
    if ligne is None:
        raise ErreurMP("Cette ligne de stock n'existe plus : elle vient sans doute "
                       "d'être sortie depuis un autre poste. Rafraîchis l'écran.")
    tout = quantite in (None, "", "tout")
    n = ligne.quantite if tout else _quantite(quantite)
    if n > ligne.quantite:
        raise ErreurMP(f"Il n'y a que {ligne.quantite} {ligne.article.code} en "
                       f"{ligne.position} : impossible d'en sortir {n}.")
    reste = ligne.quantite - n
    article, emplacement, place = ligne.article, ligne.emplacement, ligne.place
    if reste:
        ligne.quantite = reste
        ligne.save(update_fields=["quantite", "modifie_le"])
    else:
        ligne.delete()
    _tracer(MouvementMP.SORTIE, article=article, emplacement=emplacement, place=place,
            quantite=n, reste=reste, utilisateur=utilisateur, note=note)
    return reste


def etat_du_code(article):
    """Le total en stock d'un code et sa position face au seuil d'alerte.

    Rendu après une sortie : celui qui vient de prendre la dernière palette
    doit l'apprendre tout de suite, pas en ouvrant la cloche demain.
    """
    total = StockMP.objects.filter(article=article).aggregate(t=Sum("quantite"))["t"] or 0
    return {"id": article.id, "code": article.code, "famille": article.famille,
            "en_stock": total, "seuil": article.seuil_reappro,
            "sous_seuil": sous_le_seuil(article, total)}


# --- Changer d'emplacement ----------------------------------------------------
#
# Sortir puis rentrer une palette pour la déplacer laissait au journal une
# sortie et une entrée : la palette déplacée comptait comme consommée, et
# l'opérateur tapait deux fois ce que le WMS savait déjà. Ici, c'est un geste.

#: Au-delà, ce n'est plus un déplacement de palettes mais une réorganisation :
#: elle se fait emplacement par emplacement, en voyant ce qui part.
DEPLACEMENT_MAX = 50


def _demandes(lignes):
    """[{ligne, quantite}] lu depuis l'API → [(id, quantité brute)], sans doublon."""
    if not isinstance(lignes, (list, tuple)):
        raise ErreurMP("Indique les lignes à déplacer.")
    demandes, vues = [], set()
    for brut in lignes:
        if isinstance(brut, dict):
            ident, quantite = brut.get("ligne"), brut.get("quantite")
        else:
            ident, quantite = brut, None
        texte = str(ident if ident is not None else "").strip()
        if not re.fullmatch(r"[0-9]+", texte):
            raise ErreurMP("Sélection illisible : une des lignes n'est pas un identifiant.")
        if int(texte) in vues:
            raise ErreurMP("La même ligne apparaît deux fois dans la demande : rafraîchis "
                           "l'écran et recommence.")
        vues.add(int(texte))
        demandes.append((int(texte), quantite))
    if not demandes:
        raise ErreurMP("Touche au moins une ligne à déplacer.")
    if len(demandes) > DEPLACEMENT_MAX:
        raise ErreurMP(f"{len(demandes)} lignes d'un coup : {DEPLACEMENT_MAX} au plus.")
    return demandes


@transaction.atomic
def deplacer(*, lignes, vers, place, utilisateur=None, note=""):
    """Change d'emplacement une ou plusieurs lignes de stock, en un seul geste.

    `lignes` : `[{"ligne": id, "quantite": n}]` — sans quantité, toute la
    ligne ; avec, une partie seulement (la palette entamée qu'on sépare).
    `vers` et `place` : où tout arrive.

    TOUT OU RIEN : si une seule ligne ne peut pas aller là — mauvaise famille,
    code non accepté, quantité de trop —, rien ne bouge, et le message dit
    laquelle. Une moitié de déplacement laisserait l'opérateur devant deux
    emplacements sans savoir ce qui a suivi.

    Verrous : tous les emplacements concernés d'abord, dans l'ordre de leur
    code — celui des autres gestes en nombre —, puis les lignes de stock.
    Deux déplacements croisés entre les mêmes emplacements s'attendent l'un
    l'autre au lieu de s'interbloquer.

    Une ancienne génération se déplace sans confirmation : elle est déjà là,
    personne ne la choisit par erreur dans une liste.
    """
    demandes = _demandes(lignes)
    ids = [i for i, _ in demandes]
    sources = dict(StockMP.objects.filter(pk__in=ids).values_list("pk", "emplacement_id"))
    vers_id = getattr(vers, "pk", vers)
    verrous = {e.pk: e for e in Emplacement.objects.select_for_update()
               .filter(pk__in=set(sources.values()) | {vers_id}).order_by("code")}
    destination = verrous.get(vers_id)
    if destination is None:
        raise ErreurMP("L'emplacement d'arrivée n'existe plus : il vient sans doute d'être "
                       "supprimé depuis un autre poste.")
    stock = {x.pk: x for x in StockMP.objects.select_for_update(of=("self",))
             .filter(pk__in=ids).select_related("article", "emplacement").order_by("pk")}
    if len(stock) != len(ids):
        raise ErreurMP("Une des lignes à déplacer n'existe plus : elle vient sans doute "
                       "d'être sortie depuis un autre poste. Rafraîchis l'écran.")
    place = str(place or "").strip().upper()
    if place not in PLACES:
        raise ErreurMP("Touche la place d'arrivée : gauche, milieu ou droite.")
    condamnee = (PlaceCondamnee.objects.filter(emplacement=destination, place=place)
                 .values_list("motif", flat=True).first())
    if condamnee is not None:
        raise ErreurMP(f"La place {NOMS_PLACES[place]} de {destination.code} est "
                       f"condamnée : {condamnee}. Choisis une autre place.")

    acceptes = codes_acceptes(destination)
    plan = []
    for ident, brut in demandes:
        ligne = stock[ident]
        refus = (refus_emplacement(destination, ligne.article.famille)
                 or refus_code(destination, ligne.article, acceptes))
        if refus:
            raise ErreurMP(refus)
        if ligne.emplacement_id == destination.pk and ligne.place == place:
            raise ErreurMP(f"{ligne.article.code} est déjà en {destination.code}·{place} : "
                           "choisis une autre place ou un autre emplacement.")
        n = ligne.quantite if brut in (None, "", "tout") else _quantite(brut)
        if n > ligne.quantite:
            raise ErreurMP(f"Il n'y a que {ligne.quantite} {ligne.article.code} en "
                           f"{ligne.position} : impossible d'en déplacer {n}.")
        plan.append((ligne, n))

    arrivees, faits = {}, []
    for ligne, n in plan:
        article, origine = ligne.article, ligne.position
        reste_origine = ligne.quantite - n
        if reste_origine:
            ligne.quantite = reste_origine
            ligne.save(update_fields=["quantite", "modifie_le"])
        else:
            ligne.delete()
        cible = arrivees.get(article.pk) or _ligne_verrouillee(
            emplacement=destination, place=place, article=article)
        if cible is None:
            try:
                with transaction.atomic():
                    cible = StockMP.objects.create(emplacement=destination, place=place,
                                                   article=article, quantite=n)
            except IntegrityError:
                cible = _ligne_verrouillee(emplacement=destination, place=place,
                                           article=article)
                cible.quantite += n
                cible.save(update_fields=["quantite", "modifie_le"])
        else:
            cible.quantite += n
            cible.save(update_fields=["quantite", "modifie_le"])
        arrivees[article.pk] = cible
        _tracer(MouvementMP.TRANSFERT, article=article, emplacement=destination, place=place,
                quantite=n, reste=cible.quantite, utilisateur=utilisateur, note=note,
                origine=origine, reste_origine=reste_origine)
        faits.append({"code": article.code, "famille": article.famille, "quantite": n,
                      "origine": origine, "reste_origine": reste_origine,
                      "destination": f"{destination.code}·{place}",
                      "reste": cible.quantite})
    return {"deplaces": faits, "destination": destination,
            "sources": sorted({verrous[sources[i]] for i in ids}, key=lambda e: e.code)}


# --- Usage des emplacements ---------------------------------------------------
#
# « Ce que range cet emplacement » se règle en nombre — un rack entier, une
# colonne, le niveau du sol où se posent les chevalets — et pas seulement à
# l'unité. Les quatre choix possibles, et ce qu'ils écrivent :

CHOIX_USAGE = {
    "cabines-gd": (Emplacement.CABINES, Emplacement.GD),
    "cabines-illimite": (Emplacement.CABINES, Emplacement.ILLIMITE),
    "carton": (Emplacement.MP_CARTON, None),
    "vitrage": (Emplacement.MP_VITRAGE, None),
}
LIBELLES_CHOIX = {
    "cabines-gd": "Cabines — 2 places",
    "cabines-illimite": "Cabines — capacité illimitée",
    "carton": "MP — cartons",
    "vitrage": "MP — vitrages",
}
#: Une génération de rack va jusqu'à 500 emplacements : un rack entier doit
#: pouvoir changer d'usage d'un geste.
USAGE_LOT_MAX = 500


def choix_de(emplacement):
    """Le choix d'usage qui décrit l'emplacement tel qu'il est."""
    if emplacement.est_mp:
        return emplacement.usage
    return "cabines-illimite" if emplacement.illimite else "cabines-gd"


def _emplacements(ids, verrouiller=False):
    try:
        numeros = list(dict.fromkeys(int(str(i).strip()) for i in (ids or [])
                                     if str(i).strip()))
    except (TypeError, ValueError):
        raise ErreurMP("Sélection illisible : elle contient autre chose que des identifiants.")
    if not numeros:
        raise ErreurMP("Aucun emplacement sélectionné.")
    if len(numeros) > USAGE_LOT_MAX:
        raise ErreurMP(f"{len(numeros)} emplacements sélectionnés : {USAGE_LOT_MAX} au plus "
                       "à la fois.")
    requete = Emplacement.objects.filter(pk__in=numeros).order_by("code")
    liste = list(requete.select_for_update() if verrouiller else requete)
    if len(liste) != len(numeros):
        raise ErreurMP(f"{len(numeros) - len(liste)} emplacement(s) de la sélection "
                       "n'existent plus. Rouvrez le rack pour repartir de ce qui est là.")
    return liste


def bilan_usage(liste, choix):
    """Ce que le changement ferait à chaque emplacement — sans rien écrire.

    Trois issues par emplacement : il change, il est déjà ainsi, ou quelque
    chose l'en empêche. Ce qui empêche est toujours ce qui est POSÉ dessus : le
    WMS ne déplace ni une cabine ni une palette tout seul, il dit lesquelles
    sont à sortir d'abord.
    """
    if choix not in CHOIX_USAGE:
        raise ErreurMP(f"Usage inconnu : « {choix} ».")
    usage, mode = CHOIX_USAGE[choix]
    ids = [e.pk for e in liste]
    cabines = dict(Occupation.objects.filter(emplacement_id__in=ids)
                   .exclude(cabine__statut=Cabine.ENVOYE)
                   .values("emplacement_id")
                   .annotate(n=Count("cabine", distinct=True))
                   .values_list("emplacement_id", "n"))
    lignes_mp = dict(StockMP.objects.filter(emplacement_id__in=ids)
                     .values("emplacement_id").annotate(n=Count("id"))
                     .values_list("emplacement_id", "n"))
    milieu_condamne = set(PlaceCondamnee.objects.filter(emplacement_id__in=ids, place="M")
                          .values_list("emplacement_id", flat=True))

    changes, deja, bloques = [], [], []
    for e in liste:
        if choix_de(e) == choix:
            deja.append(e)
            continue
        n_cab, n_mp = cabines.get(e.pk, 0), lignes_mp.get(e.pk, 0)
        message = ""
        if n_cab:
            message = (f"{n_cab} cabine(s) y sont rangées : sortez-les ou déplacez-les "
                       "d'abord.")
        elif n_mp:
            message = (f"{n_mp} ligne(s) de stock MP y sont posées : sortez-les "
                       "d'abord.")
        elif usage == Emplacement.CABINES and e.pk in milieu_condamne:
            message = ("la place du milieu est condamnée, et elle n'existe pas pour des "
                       "cabines : remettez-la en service d'abord.")
        if message:
            bloques.append({"id": e.pk, "code": e.code, "message": message})
        else:
            changes.append(e)
    return {
        "choix": choix,
        "libelle": LIBELLES_CHOIX[choix],
        "total": len(liste),
        "changes": [e.code for e in changes],
        "ids_changes": [e.pk for e in changes],
        "deja": [e.code for e in deja],
        "bloques": bloques,
    }


def apercu_usage(ids, choix):
    return bilan_usage(_emplacements(ids), choix)


@transaction.atomic
def changer_usage(ids, choix, *, utilisateur=None):
    """Applique l'usage aux emplacements qui le peuvent, et dit ce qu'il en est des autres.

    Pas « tout ou rien » ici, à la différence d'une suppression : passer le
    niveau du sol d'un rack aux vitrages alors qu'une cabine y attend encore
    ne doit pas obliger à décocher sa case à la main. Les emplacements bloqués
    sont NOMMÉS dans la réponse — l'écran les a montrés avant le geste, et les
    redit après.
    """
    liste = _emplacements(ids, verrouiller=True)
    bilan = bilan_usage(liste, choix)
    usage, mode = CHOIX_USAGE[choix]
    valeurs = {"usage": usage}
    if mode:
        valeurs["mode_places"] = mode
    if bilan["ids_changes"]:
        # Les codes acceptés appartiennent à l'ancienne famille : ils ne
        # veulent plus rien dire, ils partent avec elle.
        oublier_codes([e.pk for e in liste if e.pk in bilan["ids_changes"]
                       and e.usage != usage])
        Emplacement.objects.filter(pk__in=bilan["ids_changes"]).update(**valeurs)
        # Les emplacements n'ont pas de journal à eux : sans cette ligne,
        # « depuis quand AH ne prend plus de cabines ? » n'aurait pas de réponse.
        logger.warning("Usage des emplacements changé par %s : %s → %s",
                       _nom(utilisateur) or "?", ", ".join(bilan["changes"]),
                       bilan["libelle"])
    return bilan


def refus_changement_usage(emplacement, choix):
    """Pour la fiche d'un emplacement : "" si le changement passe, sinon pourquoi."""
    bilan = bilan_usage([emplacement], choix)
    return bilan["bloques"][0]["message"] if bilan["bloques"] else ""


def stock_de_l_emplacement(emplacement_ids):
    """{id d'emplacement: nombre de lignes de stock MP}, en UNE requête."""
    return dict(StockMP.objects.filter(emplacement_id__in=emplacement_ids)
                .values("emplacement_id").annotate(n=Count("id"))
                .values_list("emplacement_id", "n"))


# --- Codes acceptés : réserver un emplacement à certains codes ----------------
#
# « Le sol de AH ne prend que les VITR.445 et les VITR.470 » : un emplacement MP
# accepte par défaut toute sa famille, et se réserve, si besoin, à un ou
# plusieurs codes. Comme l'usage, le réglage se fait à l'unité — la fiche de
# l'emplacement — ou en nombre — une sélection dans le plan d'un rack. Une
# réservation n'est jamais un déplacement : ce qui est déjà posé reste là, et
# la réponse le nomme.

MODES_CODES = {
    "remplacer": "réservés à ces codes",
    "ajouter": "codes ajoutés à leur réservation",
    "tous": "ouverts à tous les codes de leur famille",
}


def _articles(ids):
    """Les codes désignés par leurs identifiants, tous existants — ou un refus."""
    if isinstance(ids, str):
        ids = ids.split(",")
    try:
        numeros = list(dict.fromkeys(int(str(i).strip()) for i in (ids or [])
                                     if str(i).strip()))
    except (TypeError, ValueError):
        raise ErreurMP("Sélection de codes illisible : elle contient autre chose que des "
                       "identifiants.")
    articles = list(ArticleMP.objects.filter(pk__in=numeros))
    if len(articles) != len(numeros):
        raise ErreurMP(f"{len(numeros) - len(articles)} code(s) de la sélection n'existent "
                       "plus dans la base MP.")
    return sorted(articles, key=lambda a: _ordre_naturel(a.code))


def _calculer_codes(liste, articles, mode):
    """Ce que le réglage ferait à chaque emplacement : (bilan public, nouvelles listes).

    Chaque emplacement prend les codes de SA famille dans la sélection : réserver
    d'un geste le niveau du sol aux VITR.445 et le niveau du dessus aux C8.FD
    est un seul réglage. Un emplacement qui n'y trouve aucun code de sa famille
    est laissé tel quel, et nommé : « remplacer par rien » voudrait dire « tout
    accepter », le contraire de ce qui était demandé.
    """
    if mode not in MODES_CODES:
        raise ErreurMP(f"Réglage inconnu : « {mode} ».")
    if mode != "tous":
        if not articles:
            raise ErreurMP("Choisis au moins un code.")
        inactifs = [a.code for a in articles if not a.actif]
        if len(inactifs) == 1:
            raise ErreurMP(f"{inactifs[0]} n'est plus actif dans la base : il ne s'entre "
                           "plus, inutile de lui réserver une place.")
        if inactifs:
            raise ErreurMP(f"{liste_codes(inactifs)} ne sont plus actifs dans la base : ils "
                           "ne s'entrent plus, inutile de leur réserver une place.")
    ids = [e.pk for e in liste]
    liaison = Emplacement.codes_acceptes.through
    avant = {}
    for e_id, a_id in liaison.objects.filter(emplacement_id__in=ids).values_list(
            "emplacement_id", "articlemp_id"):
        avant.setdefault(e_id, set()).add(a_id)
    poses = {}
    for e_id, a_id, code in StockMP.objects.filter(emplacement_id__in=ids).values_list(
            "emplacement_id", "article_id", "article__code"):
        poses.setdefault(e_id, {})[a_id] = code

    changes, deja, bloques, hors, nouvelles = [], [], [], [], {}
    for e in liste:
        if not e.est_mp:
            bloques.append({"id": e.pk, "code": e.code, "message": (
                "il range des cabines : les codes acceptés ne concernent que les "
                "matières premières.")})
            continue
        siens = {a.pk for a in articles if a.famille == e.usage}
        actuels = avant.get(e.pk, set())
        if mode == "tous":
            apres = set()
        elif not siens:
            bloques.append({"id": e.pk, "code": e.code, "message": (
                f"il range des {FAMILLE_LIBELLE[e.usage]} : aucun des codes choisis n'en "
                "est un.")})
            continue
        elif mode == "ajouter" and not actuels:
            # Ouvert à toute sa famille, il accepte DÉJÀ ces codes. « Ajouter »
            # ne doit pas le fermer aux autres : ce serait le contraire de ce
            # que dit le geste — « les codes déjà acceptés le restent ».
            deja.append(e.code)
            continue
        else:
            apres = siens if mode == "remplacer" else actuels | siens
        if apres == actuels:
            deja.append(e.code)
            continue
        changes.append(e)
        nouvelles[e.pk] = apres
        restants = sorted((code for a_id, code in poses.get(e.pk, {}).items()
                           if apres and a_id not in apres), key=_ordre_naturel)
        if restants:
            hors.append({"id": e.pk, "code": e.code, "codes": restants})
    bilan = {
        "mode": mode,
        "libelle": MODES_CODES[mode],
        "codes": [a.code for a in articles],
        "total": len(liste),
        "changes": [e.code for e in changes],
        "ids_changes": [e.pk for e in changes],
        "deja": deja,
        "bloques": bloques,
        # Déjà posés et plus acceptés : ils restent, peuvent sortir ou changer
        # d'emplacement — et la cloche les signale tant qu'ils sont là.
        "hors_reservation": hors,
    }
    return bilan, nouvelles


def apercu_codes(ids, articles, mode):
    return _calculer_codes(_emplacements(ids), _articles(articles) if mode != "tous" else [],
                           mode)[0]


@transaction.atomic
def regler_codes(ids, articles, mode, *, utilisateur=None):
    """Applique la réservation aux emplacements qui la prennent ; nomme les autres."""
    liste = _emplacements(ids, verrouiller=True)
    bilan, nouvelles = _calculer_codes(
        liste, _articles(articles) if mode != "tous" else [], mode)
    if bilan["ids_changes"]:
        liaison = Emplacement.codes_acceptes.through
        liaison.objects.filter(emplacement_id__in=bilan["ids_changes"]).delete()
        liaison.objects.bulk_create([liaison(emplacement_id=e_id, articlemp_id=a_id)
                                     for e_id, codes in nouvelles.items()
                                     for a_id in sorted(codes)])
        # Comme l'usage : pas de journal pour les emplacements, la trace va au
        # journal du serveur — « depuis quand AH500 refuse les VITR.470 ? ».
        logger.warning("Codes acceptés changés par %s : %s → %s (%s)",
                       _nom(utilisateur) or "?", ", ".join(bilan["changes"]),
                       bilan["libelle"], ", ".join(bilan["codes"]) or "tous")
    return bilan


def oublier_codes(emplacement_ids):
    """Retire la réservation de ces emplacements — leur famille vient de changer."""
    if emplacement_ids:
        Emplacement.codes_acceptes.through.objects.filter(
            emplacement_id__in=emplacement_ids).delete()


def refus_codes_famille(usage, articles):
    """Pour l'administration : "" si ces codes vont sur un emplacement de cet usage."""
    articles = list(articles)
    if not articles:
        return ""
    if usage == Emplacement.CABINES:
        return ("Un emplacement de cabines n'accepte pas de codes MP : videz « codes "
                "acceptés », ou réglez d'abord ce qu'il range.")
    autres = [a.code for a in articles if a.famille != usage]
    if autres:
        return (f"{liste_codes(autres)} ne {'sont' if len(autres) > 1 else 'est'} pas "
                f"des {FAMILLE_LIBELLE[usage]} : un emplacement « {libelle_usage(usage)} » "
                "ne peut pas les accepter.")
    return ""


# --- Seuils d'alerte ------------------------------------------------------------

def _seuil(brut):
    """Un seuil lisible : un entier, ou rien. Zéro vaut « pas de seuil »."""
    texte = str(brut if brut is not None else "").strip().replace(" ", "")
    if texte.lower() in ("", "aucun", "none", "null"):
        return None
    if not re.fullmatch(r"[0-9]+", texte):
        raise ErreurMP(f"Seuil « {brut} » illisible : un nombre entier de pièces, ou rien "
                       "pour ne pas avoir d'alerte.")
    n = int(texte)
    if n > QUANTITE_MAX:
        raise ErreurMP(f"Un seuil de {n} pièces : c'est sûrement une faute de frappe "
                       f"({QUANTITE_MAX} au plus).")
    return n or None


@transaction.atomic
def regler_seuils(articles, seuil, *, utilisateur=None):
    """Le même seuil d'alerte pour un ou plusieurs codes. `None` : plus d'alerte.

    Rend aussi les codes pour lesquels le seuil n'aura PAS d'effet — ancienne
    génération ou code retiré : ils ne déclenchent jamais d'alerte, et le
    dire évite d'attendre une alerte qui ne viendra pas.
    """
    liste = _articles(articles)
    if not liste:
        raise ErreurMP("Choisis au moins un code.")
    valeur = _seuil(seuil)
    ArticleMP.objects.filter(pk__in=[a.pk for a in liste]).update(
        seuil_reappro=valeur, modifie_le=timezone.now())
    codes = [a.code for a in liste]
    logger.warning("Seuil d'alerte réglé par %s : %s → %s", _nom(utilisateur) or "?",
                   ", ".join(codes), valeur if valeur is not None else "aucun")
    return {
        "seuil": valeur,
        "codes": codes,
        "nombre": len(codes),
        "sans_effet": [a.code for a in liste
                       if valeur and (a.ancienne_generation or not a.actif)],
    }


# --- Alertes : ce que la cloche signale -----------------------------------------
#
# Deux sortes, chacune avec un geste au bout :
# - un code SOUS SON SEUIL d'alerte — il faut en recommander ;
# - une ligne posée sur un emplacement qui ne l'ACCEPTE PLUS — elle est à
#   déplacer. Elle y était avant la réservation, ou quelqu'un l'y a posée à la
#   main en contournant l'écran.
# Le pouls des écrans n'en lit qu'une empreinte ; la liste se lit à l'ouverture.

def _requete_sous_seuil():
    total = Coalesce(Sum("stock__quantite"), 0)
    return (ArticleMP.objects.filter(actif=True, ancienne_generation=False,
                                     seuil_reappro__gt=0)
            .annotate(total=total).filter(total__lt=F("seuil_reappro")).order_by())


def _requete_hors_reservation():
    liaison = Emplacement.codes_acceptes.through.objects
    reserve = Exists(liaison.filter(emplacement_id=OuterRef("emplacement_id")))
    accepte = Exists(liaison.filter(emplacement_id=OuterRef("emplacement_id"),
                                    articlemp_id=OuterRef("article_id")))
    return StockMP.objects.filter(reserve).exclude(accepte).order_by()


def _empreinte(sous_seuil, hors):
    """(nombre, empreinte) d'un ensemble d'alertes.

    `sous_seuil` : des triplets (code, total, seuil) ; `hors` : des paires
    (ligne, quantité). L'empreinte change dès que l'ENSEMBLE change — une
    alerte qui se règle pendant qu'une autre naît laisse le nombre identique,
    pas l'empreinte — et aussi quand ce qu'une alerte DIT change : un code
    qui passe de 8 à 0 sous son seuil devient plus urgent, et les autres
    postes doivent le voir remonter en tête.
    """
    cles = sorted([f"s{a}:{t}:{seuil}" for a, t, seuil in sous_seuil]
                  + [f"h{x}:{q}" for x, q in hors])
    if not cles:
        return 0, ""
    return len(cles), hashlib.blake2s("|".join(cles).encode(), digest_size=6).hexdigest()


def empreinte_alertes():
    """(nombre, empreinte) des alertes, en deux requêtes : ce que lit le pouls."""
    return _empreinte(_requete_sous_seuil().values_list("pk", "total", "seuil_reappro"),
                      _requete_hors_reservation().values_list("pk", "quantite"))


def alertes():
    """Les alertes en cours, regroupées, les plus urgentes d'abord.

    Sous le seuil : un code à zéro passe avant un code à moitié de son seuil,
    lui-même avant un code juste en dessous. Chaque alerte porte une `cle`
    stable : l'écran s'en sert pour distinguer les nouvelles de celles déjà
    vues.
    """
    seuils = []
    for a in _requete_sous_seuil():
        seuils.append({
            "cle": f"seuil:{a.pk}", "article": a.pk, "code": a.code, "famille": a.famille,
            "designation": a.designation, "en_stock": a.total, "seuil": a.seuil_reappro,
        })
    seuils.sort(key=lambda x: (x["en_stock"] / x["seuil"], _ordre_naturel(x["code"])))

    hors = []
    lignes = list(_requete_hors_reservation().select_related("article", "emplacement"))
    acceptes = {}
    if lignes:
        for e_id, code in (Emplacement.codes_acceptes.through.objects
                           .filter(emplacement_id__in={x.emplacement_id for x in lignes})
                           .values_list("emplacement_id", "articlemp__code")):
            acceptes.setdefault(e_id, []).append(code)
    for x in sorted(lignes, key=_ordre_position):
        hors.append({
            "cle": f"hors:{x.pk}", "ligne": x.pk, "article": x.article_id,
            "code": x.article.code, "famille": x.article.famille,
            "emplacement": x.emplacement_id, "code_emplacement": x.emplacement.code,
            "place": x.place, "position": x.position, "quantite": x.quantite,
            "acceptes": sorted(acceptes.get(x.emplacement_id, []), key=_ordre_naturel),
        })

    groupes = []
    if seuils:
        groupes.append({"type": "seuil", "titre": "Sous le seuil d'alerte", "items": seuils})
    if hors:
        groupes.append({"type": "hors_reservation",
                        "titre": "Posés là où ils ne sont plus acceptés", "items": hors})
    # Calculée sur CETTE liste, pas relue : le nombre affiché et les lignes
    # montrées ne peuvent pas se contredire.
    total, cle = _empreinte([(x["article"], x["en_stock"], x["seuil"]) for x in seuils],
                            [(x["ligne"], x["quantite"]) for x in hors])
    return {"total": total, "empreinte": cle, "groupes": groupes}


def empreinte():
    """Ce que le pouls des écrans regarde : le journal MP, en une requête."""
    return MouvementMP.objects.aggregate(total=Count("id"), dernier=Max("id"))
