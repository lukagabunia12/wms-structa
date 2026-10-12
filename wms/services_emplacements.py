"""Le référentiel des emplacements : créer un rack, supprimer un emplacement,
une sélection ou un rack entier.

Tout ce qui crée ou supprime des emplacements en nombre passe par ici ; la vue
ne fait que traduire les refus en réponses 400. Ce qui arrive aux CABINES —
ranger, déplacer, envoyer, condamner une place, mettre un emplacement hors
service — vit dans `services_cabines`.
"""
import logging
import re

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count

from .models import Cabine, Emplacement, Occupation, StockMP

logger = logging.getLogger(__name__)


class ErreurEmplacement(ValidationError):
    """Refus lisible : la vue le rend en 400, avec son message."""


# --- Suppression : un emplacement, une sélection, un rack --------------------
#
# Deux obstacles : des cabines rangées, du stock MP posé. `Occupation.emplacement`
# est en SET_NULL, donc la base ne remonterait aucune erreur — elle détacherait
# les cabines en silence, et le parc se retrouverait « non rangé » sans la
# moindre trace. C'est le cas le plus dangereux, et le plus discret. Le stock
# MP, lui, est en PROTECT : la base refuserait, mais par une erreur brute.
#
# Le passé, lui, ne s'y oppose pas : le journal des cabines recopie le code de
# l'emplacement en toutes lettres, il reste lisible une fois l'emplacement
# supprimé.

def _cabines_rangees(emplacements):
    """{id d'emplacement: nombre de cabines rangées}, en UNE requête.

    Ce sont les OCCUPATIONS qui tiennent une place : une cabine peut n'en
    avoir qu'une ici, ou deux. On compte des cabines, pas des occupations.
    """
    lignes = (Occupation.objects
              .filter(emplacement__in=emplacements)
              .exclude(cabine__statut=Cabine.ENVOYE)
              .values("emplacement_id")
              .annotate(n=Count("cabine", distinct=True)))
    return {ligne["emplacement_id"]: ligne["n"] for ligne in lignes}


def _lignes_mp(emplacements):
    """{id d'emplacement: lignes de stock MP}, en UNE requête.

    Le stock MP est en PROTECT : la base refuserait l'effacement par une erreur
    brute. On le dit avant, en clair, comme pour les cabines.
    """
    lignes = (StockMP.objects.filter(emplacement__in=emplacements)
              .values("emplacement_id").annotate(n=Count("id")))
    return {ligne["emplacement_id"]: ligne["n"] for ligne in lignes}


def _refus(emplacement, cabines, lignes_mp=0):
    if cabines:
        return (f"{cabines} cabine(s) sont rangées sur {emplacement.code} : "
                "déplacez-les ou envoyez-les avant de supprimer l'emplacement.")
    if lignes_mp:
        return (f"{lignes_mp} ligne(s) de stock MP sont posées sur {emplacement.code} : "
                "sortez-les avant de supprimer l'emplacement.")
    return ""


def diagnostic_suppression(emplacement):
    """Pourquoi cet emplacement ne peut pas être supprimé — "" s'il le peut."""
    return _refus(emplacement, _cabines_rangees([emplacement]).get(emplacement.pk, 0),
                  _lignes_mp([emplacement]).get(emplacement.pk, 0))


def _bilan(liste):
    """Ce que la suppression de `liste` effacerait, et ce qui s'y oppose.

    Rendu AVANT toute écriture, pour que l'écran montre les conséquences au
    lieu de les découvrir à la première erreur.
    """
    par_emplacement = _cabines_rangees(liste)
    mp = _lignes_mp(liste)
    bloquants = [{"code": e.code,
                  "message": _refus(e, par_emplacement.get(e.pk, 0), mp.get(e.pk, 0))}
                 for e in liste if par_emplacement.get(e.pk) or mp.get(e.pk)]
    # Recompté sur l'ensemble : une cabine posée sur deux emplacements de la
    # sélection est UNE cabine, pas deux.
    cabines = (Cabine.objects.filter(occupations__emplacement__in=liste)
               .exclude(statut=Cabine.ENVOYE).distinct().count()) if bloquants else 0
    return {
        "emplacements": len(liste),
        "codes": [e.code for e in liste],
        "cabines": cabines,
        "lignes_mp": sum(mp.values()),
        "bloquants": bloquants,
        "supprimable": not bloquants,
    }


def _supprimer(liste, utilisateur, motif):
    """Efface, et laisse une ligne au journal du serveur.

    Les emplacements n'ont pas de journal à eux : sans cette ligne, « où est
    passé le rack AC ? » n'aurait que la mémoire de quelqu'un pour réponse.
    WARNING et non INFO : c'est le niveau que le serveur garde en production.
    """
    codes = [e.code for e in liste]
    Emplacement.objects.filter(pk__in=[e.pk for e in liste]).delete()
    logger.warning("Emplacement(s) supprimé(s) par %s : %s%s", utilisateur or "?",
                   ", ".join(codes), f" — {motif}" if motif else "")


@transaction.atomic
def supprimer_emplacement(emplacement, *, utilisateur=None, motif=""):
    """Supprime un emplacement vide. Lève ErreurEmplacement sinon.

    L'emplacement est verrouillé avant le contrôle : une cabine rangée ici
    par un autre poste entre le contrôle et l'effacement serait détachée en
    silence — exactement ce que le contrôle empêche.
    """
    emplacement = Emplacement.objects.select_for_update().filter(pk=emplacement.pk).first()
    if emplacement is None:
        raise ErreurEmplacement("Cet emplacement vient d'être supprimé depuis un autre poste.")
    refus = diagnostic_suppression(emplacement)
    if refus:
        raise ErreurEmplacement(refus)
    _supprimer([emplacement], utilisateur, motif)


def emplacements_du_rack(rack):
    """Les emplacements d'un rack, dans l'ordre du plan."""
    return (Emplacement.objects.filter(rack=(rack or "").strip())
            .order_by("colonne", "niveau", "code"))


def _rack(rack, verrouiller=False):
    rack = (rack or "").strip()
    if not rack:
        raise ErreurEmplacement("Indiquez le rack à supprimer.")
    requete = emplacements_du_rack(rack)
    liste = list(requete.select_for_update() if verrouiller else requete)
    if not liste:
        raise ErreurEmplacement(f"Aucun emplacement ne porte le rack « {rack} ».")
    return rack, liste


def diagnostic_rack(rack):
    """Ce que la suppression du rack effacerait, et ce qui l'empêche.

    Un rack se supprime d'un geste : c'est précisément pourquoi il faut voir
    ce qu'il contient avant de l'engager.
    """
    rack, liste = _rack(rack)
    return {"rack": rack, **_bilan(liste)}


@transaction.atomic
def supprimer_rack(rack, *, utilisateur=None, motif=""):
    """Supprime tous les emplacements d'un rack, ou aucun.

    La transaction est le point important : supprimer la moitié d'un rack
    laisserait un plan à trous que personne ne saurait reconstituer. Si un
    seul emplacement résiste, rien n'est écrit.
    """
    rack, liste = _rack(rack, verrouiller=True)
    etat = _bilan(liste)
    if etat["bloquants"]:
        premier = etat["bloquants"][0]
        raise ErreurEmplacement(
            f"{len(etat['bloquants'])} emplacement(s) du rack « {rack} » ne peuvent "
            f"pas être supprimés. Premier : {premier['code']} — {premier['message']}")
    _supprimer(liste, utilisateur, motif or f"suppression du rack {rack}")
    return {"rack": rack, "supprimes": etat["emplacements"], "codes": etat["codes"]}


#: Garde-fou de la sélection multiple. Deux cents cases cochées à la main, c'est
#: déjà plus qu'un rack entier ; au-delà, c'est une erreur de manipulation.
LOT_MAX = 200


def _emplacements_du_lot(ids, verrouiller=False):
    """Les emplacements d'une sélection, triés par code, ou une erreur lisible."""
    try:
        numeros = list(dict.fromkeys(int(str(i).strip()) for i in (ids or []) if str(i).strip()))
    except (TypeError, ValueError):
        raise ErreurEmplacement("Sélection illisible : elle contient autre chose que des identifiants.")
    if not numeros:
        raise ErreurEmplacement("Aucun emplacement sélectionné.")
    if len(numeros) > LOT_MAX:
        raise ErreurEmplacement(f"{len(numeros)} emplacements sélectionnés : {LOT_MAX} au plus "
                                "à la fois. Passez par la suppression du rack si c'est tout un rack.")
    requete = Emplacement.objects.filter(pk__in=numeros).order_by("code")
    liste = list(requete.select_for_update() if verrouiller else requete)
    manquants = len(numeros) - len(liste)
    if manquants:
        # Deux opérateurs sur le même rack : l'autre a pu supprimer entre-temps.
        # Le dire vaut mieux que supprimer « ce qui reste » sans prévenir.
        raise ErreurEmplacement(f"{manquants} emplacement(s) de la sélection n'existent plus. "
                                "Rouvrez le rack pour repartir de ce qui est là.")
    return liste


def diagnostic_lot(ids):
    """Ce que la suppression d'une sélection effacerait, et ce qui l'empêche."""
    return _bilan(_emplacements_du_lot(ids))


@transaction.atomic
def supprimer_lot(ids, *, utilisateur=None, motif=""):
    """Supprime toute la sélection, ou aucun de ses emplacements.

    Tout ou rien, comme pour un rack, et pour la même raison : une sélection
    dont la moitié disparaît laisse l'opérateur sans savoir laquelle. Si un
    seul emplacement résiste, rien n'est écrit et le premier obstacle est nommé.
    """
    liste = _emplacements_du_lot(ids, verrouiller=True)
    etat = _bilan(liste)
    if etat["bloquants"]:
        premier = etat["bloquants"][0]
        raise ErreurEmplacement(
            f"{len(etat['bloquants'])} emplacement(s) de la sélection ne peuvent pas être "
            f"supprimés. Premier : {premier['code']} — {premier['message']}")
    _supprimer(liste, utilisateur, motif)
    return {"supprimes": etat["emplacements"], "codes": etat["codes"]}


# --- Génération d'un rack entier --------------------------------------------
#: Garde-fou : une faute de frappe sur le nombre de colonnes (10 → 1000) créerait
#: des milliers de lignes qu'il faudrait ensuite supprimer une par une.
GENERATION_MAX = 500
COLONNES_MAX, NIVEAUX_MAX, PAS_MAX = 300, 26, 10000
#: Bornes des colonnes de la base : `rack` en 32 caractères, `colonne` en entier.
RACK_MAX, COLONNE_MAX = 32, 2_147_483_647


def _entier(valeur, nom, mini, maxi):
    try:
        n = int(str(valeur).strip())
    except (TypeError, ValueError):
        raise ErreurEmplacement(f"« {nom} » doit être un nombre entier.")
    if not (mini <= n <= maxi):
        raise ErreurEmplacement(f"« {nom} » doit être compris entre {mini} et {maxi}.")
    return n


def codes_de_rack(*, prefixe, debut, pas=10, colonnes, niveaux=1, separateur=""):
    """Les codes d'un rack, dans l'ordre physique : colonne par colonne, de bas en haut.

    Convention retenue — celle de l'exploitation : le **niveau s'ajoute au numéro
    de colonne**. Rack « AC », première colonne 550, pas de 10, 3 niveaux :

        AC550 AC551 AC552 · AC560 AC561 AC562 · … · AC640 AC641 AC642

    Le nombre de chiffres est repris de la saisie : « 050 » garde son zéro de tête,
    « 50 » n'en gagne pas. D'où un `debut` reçu en texte et non en nombre.

    Renvoie ``[{"code", "colonne", "niveau"}, …]``.
    """
    prefixe = (prefixe or "").strip().upper()
    if not prefixe:
        raise ErreurEmplacement("Le préfixe du rack est obligatoire (ex. AC).")
    # Le préfixe devient le nom du rack, limité à 32 caractères en base.
    # SQLite l'ignore ; PostgreSQL refuse — en erreur 500, le jour même de la
    # mise en service.
    if len(prefixe) > RACK_MAX:
        raise ErreurEmplacement(f"Le préfixe du rack tient en {RACK_MAX} caractères au plus.")
    separateur = (separateur or "").strip()

    brut = str(debut if debut is not None else "").strip()
    # Les chiffres 0 à 9 seulement : `isdigit()` accepte « ² » (la touche à
    # gauche du 1 sur un clavier français), que `int()` refuse ensuite — une
    # erreur 500 à chaque frappe, l'aperçu se recalculant à chaque touche.
    if not re.fullmatch(r"[0-9]+", brut):
        raise ErreurEmplacement("Le numéro de la première colonne doit être un nombre "
                                "(ex. 550, ou 050 pour garder le zéro).")
    largeur = len(brut)
    premier = int(brut)

    colonnes = _entier(colonnes, "nombre de colonnes", 1, COLONNES_MAX)
    niveaux = _entier(niveaux, "nombre de niveaux", 1, NIVEAUX_MAX)
    pas = _entier(pas, "pas entre colonnes", 1, PAS_MAX)

    # Le niveau s'ajoute au numéro de colonne : avec un pas de 2 et 3 niveaux, la
    # colonne 550 produirait 550/551/552 et la suivante 552 — deux emplacements
    # différents porteraient le même code, et l'un écraserait l'autre.
    if niveaux > pas:
        raise ErreurEmplacement(
            f"Avec un pas de {pas}, il ne peut pas y avoir {niveaux} niveaux : les "
            f"codes d'une colonne déborderaient sur la suivante. Augmentez le pas "
            f"(au moins {niveaux}) ou réduisez le nombre de niveaux.")

    # La colonne est un entier en base (2 147 483 647 au plus sur PostgreSQL).
    if premier + (colonnes - 1) * pas + niveaux > COLONNE_MAX:
        raise ErreurEmplacement(
            f"Numéros de colonne trop grands : la dernière dépasserait {COLONNE_MAX}.")

    total = colonnes * niveaux
    if total > GENERATION_MAX:
        raise ErreurEmplacement(
            f"{colonnes} colonnes × {niveaux} niveaux = {total} emplacements, au-delà "
            f"de la limite de {GENERATION_MAX} par création. Découpez le rack en "
            "plusieurs tranches.")

    liste = []
    for c in range(colonnes):
        base = premier + c * pas
        for n in range(niveaux):
            liste.append({
                "code": f"{prefixe}{separateur}{base + n:0{largeur}d}",
                "colonne": base,
                "niveau": n,
            })

    trop_long = next((x["code"] for x in liste if len(x["code"]) > 64), None)
    if trop_long:
        raise ErreurEmplacement(f"Le code « {trop_long} » dépasse 64 caractères.")
    return liste


def apercu_rack(**parametres):
    """Les codes qui seraient créés, en signalant ceux qui existent déjà.

    Le même calcul que la création, exécuté par le **serveur** : un aperçu
    reconstitué côté navigateur pourrait diverger de ce qui est réellement écrit,
    et l'opérateur validerait alors autre chose que ce qu'il a lu.
    """
    liste = codes_de_rack(**parametres)
    connus = set(Emplacement.objects.filter(code__in=[x["code"] for x in liste])
                 .values_list("code", flat=True))
    for x in liste:
        x["existe"] = x["code"] in connus
    return {
        "codes": liste,
        "total": len(liste),
        "nouveaux": sum(1 for x in liste if not x["existe"]),
        "existants": sorted(connus),
    }


@transaction.atomic
def generer_rack(*, mode_places=None, usage=None, description="", **parametres):
    """Crée le rack. Les codes déjà pris sont laissés intacts et rapportés.

    Volontairement rejouable : ajouter un quatrième niveau à un rack existant se
    fait en relançant la même génération avec `niveaux=4` — les trois premiers
    sont reconnus et sautés, seul le nouveau est créé.
    """
    # `save()` ne contrôle pas les choix d'un champ : un mode inconnu était
    # écrit tel quel, et l'emplacement échappait ensuite à tous les filtres
    # qui distinguent « deux places » de « capacité illimitée ».
    if mode_places and mode_places not in dict(Emplacement.MODES_PLACES):
        raise ErreurEmplacement(f"Mode de rangement inconnu : « {mode_places} ».")
    # Un rack se crée directement pour les matières premières : le niveau du sol
    # des chevalets, une rangée de palettes de cartons.
    if usage and usage not in dict(Emplacement.USAGES):
        raise ErreurEmplacement(f"Usage inconnu : « {usage} ».")
    apercu = apercu_rack(**parametres)
    a_creer = [x for x in apercu["codes"] if not x["existe"]]
    prefixe = (parametres.get("prefixe") or "").strip().upper()

    # Un par un plutôt que `bulk_create` : `Emplacement.save()` normalise le code,
    # et 500 lignes au maximum dans une seule transaction ne coûtent rien.
    crees = []
    for x in a_creer:
        emplacement = Emplacement(
            code=x["code"], rack=prefixe, colonne=x["colonne"], niveau=x["niveau"],
            description=description,
            **({"mode_places": mode_places} if mode_places else {}),
            **({"usage": usage} if usage else {}),
        )
        try:
            emplacement.save()
        except IntegrityError:
            # Deux postes qui génèrent le même rack en même temps : l'aperçu ne
            # voyait pas encore le code de l'autre.
            raise ErreurEmplacement(
                f"Le code {x['code']} vient d'être créé par ailleurs. Relancez la "
                "génération : les codes déjà pris seront simplement ignorés.")
        crees.append(emplacement.code)

    return {
        "rack": prefixe,
        "crees": crees,
        "ignores": apercu["existants"],
        "total": apercu["total"],
    }
