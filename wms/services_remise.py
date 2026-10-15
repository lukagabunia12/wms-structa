"""Repartir de zéro : remettre l'outil à neuf, en tout ou en partie.

L'écran (administration → Repartir de zéro) coche tout par défaut : l'outil
revient à son état d'installation, et il ne reste que les comptes. On décoche
ce qu'on veut garder. Six parties, chacune décrite par ce qu'elle efface — et
par ce qu'elle emporte avec elle : le plan de l'entrepôt ne s'efface pas en
gardant les cabines qui y sont rangées.

« À neuf » veut dire exactement ce que l'installation écrit : les 45 codes MP
de la migration 0026 et les six grands modèles de la 0020, lus dans ces
migrations elles-mêmes. Une copie ici divergerait au premier ajout. (Une
migration qui sèmerait d'autres données devra être ajoutée à `_semis`.)

La sauvegarde est écrite AVANT le premier effacement, dans la même transaction :
si elle échoue, rien n'est effacé. Elle contient tout ce qui part ou change, et
se recharge avec `manage.py loaddata` — juste après, avant toute nouvelle
saisie. Les codes MP et les modèles d'origine sont remis en place SUR leurs
lignes existantes plutôt que recréés : le fichier les retrouve à leur
identifiant, et un rechargement ne bute pas sur un code en double.

Les comptes restent toujours : sans eux, personne ne pourrait se reconnecter
pour constater le résultat. Ils se gèrent dans l'administration, « Utilisateurs ».
"""
import importlib
import logging
from pathlib import Path

from django.conf import settings
from django.core import serializers
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from . import services_mp
from .models import (ArticleMP, Cabine, CabineAttendue, Emplacement, ModeleCabine,
                     MouvementCabine, MouvementMP, Occupation, PlaceCondamnee, StockMP,
                     Utilisateur, Zone)

logger = logging.getLogger(__name__)

#: Où atterrissent les sauvegardes. À la racine du projet et non dans un dossier
#: temporaire : c'est un fichier qu'on doit retrouver six mois plus tard.
DOSSIER_SAUVEGARDES = "sauvegardes"

CABINES, MP, PRODUCTION, PLAN, MODELES, CODES_MP = (
    "cabines", "mp", "production", "plan", "modeles", "codes_mp")

#: (clé, titre, ce qu'elle efface) — dans l'ordre de l'écran.
PARTIES = [
    (CABINES, "Les cabines",
     "Toutes les cabines, leurs positions et leur journal."),
    (MP, "Les matières premières",
     "Le stock des vitrages et des cartons, et son journal."),
    (PRODUCTION, "Le fichier de production",
     "Les cabines annoncées par la production : le fichier sera à réimporter. "
     "D'ici là, une cabine entre en stock par saisie libre."),
    (PLAN, "Le plan de l'entrepôt",
     "Les emplacements et les racks, les zones, les places condamnées, les codes "
     "acceptés. Les étiquettes QR déjà collées ne mènent plus nulle part tant que les "
     "emplacements ne sont pas recréés avec les mêmes codes."),
    (MODELES, "Les tailles des modèles de cabine",
     "Les réglages de l'écran « Modèles de cabine » : retour aux six grands modèles "
     "d'origine."),
    (CODES_MP, "La base des codes MP",
     "Retour aux codes livrés : les codes ajoutés depuis sont retirés, les seuils "
     "d'alerte et les fiches reprennent leurs valeurs d'origine."),
]
CLES = [cle for cle, _, _ in PARTIES]
TITRES = {cle: titre for cle, titre, _ in PARTIES}

#: Ce qu'une partie emporte avec elle, et pourquoi.
EXIGE = {
    PLAN: {CABINES: "des cabines y sont rangées",
           MP: "du stock MP y est posé"},
    CODES_MP: {MP: "le stock MP cite ces codes"},
}

#: Les champs d'un code MP que l'installation écrit — ceux qu'on remet.
CHAMPS_LIVRES = ("famille", "designation", "fournisseur", "numero", "references",
                 "colisage", "seuil_reappro", "ancienne_generation")


# --- Ce que l'installation sème -------------------------------------------------

def _semis():
    """`(codes, grands)` : les codes MP livrés, par code, et les grands modèles
    d'origine, par clé — lus dans les migrations qui les sèment."""
    base_mp = importlib.import_module("wms.migrations.0026_base_mp")
    modeles = importlib.import_module("wms.migrations.0020_modeles_et_deux_places")
    codes = {" ".join(ligne["code"].split()).upper(): ligne for ligne in base_mp._lignes()}
    grands = {ModeleCabine.normaliser(nom): " ".join(nom.split())
              for nom in modeles.GRANDS_AU_DEPART}
    return codes, grands


def _reservations_qui_tombent(codes):
    """{id d'emplacement: (code, codes qui tombent, codes qui restent)} — ce que
    la remise des codes ferait aux réservations d'un plan gardé : un code
    retiré, ou revenu à une famille que l'emplacement n'accepte pas, n'y est
    plus accepté."""
    lien = Emplacement.codes_acceptes.through
    familles = _familles_par_emplacement()
    touches = {}
    for emplacement, code_emp, code in lien.objects.values_list(
            "emplacement_id", "emplacement__code", "articlemp__code"):
        _, tombent, restent = touches.setdefault(emplacement, (code_emp, [], []))
        siennes = familles.get(emplacement)
        (tombent if code not in codes or (siennes and codes[code]["famille"] not in siennes)
         else restent).append(code)
    return {pk: v for pk, v in touches.items() if v[1]}


def _familles_par_emplacement():
    """{id d'emplacement: {codes de familles acceptées}} — absents : toutes."""
    resultat = {}
    for e_id, code in Emplacement.familles.through.objects.values_list(
            "emplacement_id", "famillemp__code"):
        resultat.setdefault(e_id, set()).add(code)
    return resultat


def _differe(article, ligne):
    """Le code a-t-il changé depuis l'installation ?"""
    return (not article.actif) or any(getattr(article, champ) != ligne[champ]
                                      for champ in CHAMPS_LIVRES)


# --- Ce qui partirait -----------------------------------------------------------

def etat():
    """Ce que chaque partie effacerait ou changerait, compté maintenant.

    Une seule définition, pour que l'écran annonce exactement ce que
    l'opération fera ensuite. Deux comptages écrits à deux endroits finissent
    par diverger, et c'est l'écran qui aurait tort au pire moment.
    """
    codes, grands = _semis()
    articles = list(ArticleMP.objects.all())
    presents = {a.code for a in articles}
    modeles = list(ModeleCabine.objects.all())
    cles_modeles = {m.cle for m in modeles}
    reservations = _reservations_qui_tombent(codes)
    return {
        CABINES: {
            "cabines": Cabine.objects.count(),
            "rangees": (Occupation.objects.filter(emplacement__isnull=False)
                        .order_by().values("cabine").distinct().count()),
            "journal": MouvementCabine.objects.count(),
        },
        MP: {"lignes": StockMP.objects.count(), "journal": MouvementMP.objects.count()},
        PRODUCTION: {"attendues": CabineAttendue.objects.count()},
        PLAN: {
            "emplacements": Emplacement.objects.count(),
            # `.order_by()` vide : le tri par défaut ajouterait le code au
            # DISTINCT, et chaque emplacement compterait pour un rack.
            "racks": (Emplacement.objects.exclude(rack="").order_by()
                      .values("rack").distinct().count()),
            "zones": Zone.objects.count(),
            "places_condamnees": PlaceCondamnee.objects.count(),
            "reserves": (Emplacement.objects.filter(codes_acceptes__isnull=False)
                         .distinct().count()),
        },
        MODELES: {
            "regles": len(modeles),
            "origine": len(grands),
            "changes": (sum(1 for m in modeles if m.cle not in grands or not m.grand)
                        + len(set(grands) - cles_modeles)),
        },
        CODES_MP: {
            "codes": len(articles),
            "livres": len(codes),
            # Si le plan est gardé : les emplacements qui perdent un code réservé,
            # et ceux qui n'en gardent aucun — ils accepteront alors tous les
            # codes de leurs familles.
            "reservations": sorted(v[0] for v in reservations.values()),
            "sans_reservation": sorted(v[0] for v in reservations.values() if not v[2]),
            "ajoutes": sum(1 for a in articles if a.code not in codes),
            "modifies": sum(1 for a in articles
                            if a.code in codes and _differe(a, codes[a.code])),
            "manquants": len(set(codes) - presents),
        },
        "comptes": Utilisateur.objects.count(),
    }


def _nombre(n):
    """1 940 et non 1940 : l'espace des milliers, comme on l'écrit en France."""
    return f"{n:,}".replace(",", " ")


#: Les mots comptés au féminin : « aucune cabine », mais « aucun code ».
FEMININS = {"cabine", "ligne", "zone", "place condamnée", "cabine annoncée"}


def _compte(n, singulier, pluriel=None):
    if n == 0:
        return f"{'aucune' if singulier in FEMININS else 'aucun'} {singulier}"
    return f"{_nombre(n)} {singulier if n == 1 else (pluriel or singulier + 's')}"


def _detail(cle, e):
    """Ce que la partie touche, en une ligne lisible."""
    d = e[cle]
    if cle == CABINES:
        if not d["cabines"] and not d["journal"]:
            return "Rien à effacer (aucune cabine)."
        rangees = f", dont {_nombre(d['rangees'])} rangée{'s' if d['rangees'] > 1 else ''}" \
            if d["rangees"] else ""
        return (f"{_compte(d['cabines'], 'cabine')}{rangees} · "
                f"{_compte(d['journal'], 'ligne')} de journal.")
    if cle == MP:
        if not d["lignes"] and not d["journal"]:
            return "Rien à effacer (aucun stock MP)."
        return (f"{_compte(d['lignes'], 'ligne')} de stock · "
                f"{_compte(d['journal'], 'ligne')} de journal MP.")
    if cle == PRODUCTION:
        if not d["attendues"]:
            return "Rien à effacer (aucun fichier importé)."
        return f"{_compte(d['attendues'], 'cabine annoncée', 'cabines annoncées')}."
    if cle == PLAN:
        if not d["emplacements"] and not d["zones"]:
            return "Rien à effacer (aucun emplacement)."
        morceaux = [_compte(d["emplacements"], "emplacement")]
        if d["racks"]:
            morceaux[0] += f" en {_compte(d['racks'], 'rack')}"
        morceaux.append(_compte(d["zones"], "zone"))
        if d["places_condamnees"]:
            morceaux.append(_compte(d["places_condamnees"], "place condamnée",
                                    "places condamnées"))
        if d["reserves"]:
            morceaux.append(f"{_compte(d['reserves'], 'emplacement')} "
                            f"réservé{'s' if d['reserves'] > 1 else ''} à certains codes")
        return " · ".join(morceaux) + "."
    if cle == MODELES:
        if not d["changes"]:
            return (f"{_compte(d['regles'], 'modèle réglé', 'modèles réglés')}, "
                    "tels qu'à l'installation — rien ne changera.")
        plusieurs = d["changes"] > 1
        return (f"{_compte(d['regles'], 'modèle réglé', 'modèles réglés')} · "
                f"{_compte(d['changes'], 'réglage')} fait{'s' if plusieurs else ''} depuis "
                f"l'installation {'reviennent' if plusieurs else 'revient'} à l'origine.")
    if cle == CODES_MP:
        changes = []
        if d["ajoutes"]:
            changes.append(f"{_compte(d['ajoutes'], 'code ajouté', 'codes ajoutés')} "
                           "depuis l'installation, retiré" + ("s" if d["ajoutes"] > 1 else ""))
        if d["modifies"]:
            changes.append(f"{_compte(d['modifies'], 'code modifié', 'codes modifiés')}, "
                           "remis comme livré" + ("s" if d["modifies"] > 1 else ""))
        if d["manquants"]:
            changes.append(f"{_compte(d['manquants'], 'code livré', 'codes livrés')} "
                           "manquant" + ("s" if d["manquants"] > 1 else "") + ", remis")
        if not changes:
            return f"{_compte(d['codes'], 'code')}, tels que livrés — rien ne changera."
        phrase = f"{_compte(d['codes'], 'code')} · " + " · ".join(changes) + "."
        if d["reservations"]:
            # Ne vaut que si le plan reste : effacé, il emporte ses réservations.
            touches, vides = d["reservations"], d["sans_reservation"]
            phrase += (f" Si le plan est gardé, {services_mp.liste_codes(touches)} "
                       f"perd{'ent' if len(touches) > 1 else ''} un code réservé")
            if len(vides) > 1:
                phrase += (f" ; {services_mp.liste_codes(vides)} n'en gardent aucun et "
                           "accepteront tous les codes de leurs familles")
            elif vides:
                phrase += (f" ; {services_mp.liste_codes(vides)} n'en garde aucun et "
                           "acceptera tous les codes de ses familles")
            phrase += "."
        return phrase
    raise KeyError(cle)


def _minuscule(texte):
    """« Les cabines » → « les cabines », sans toucher au reste : « MP » reste « MP »."""
    return texte[:1].lower() + texte[1:]


def presenter(cochees=None, e=None):
    """Les parties, prêtes pour l'écran : titre, ce qu'elles effacent, ce
    qu'elles touchent maintenant, ce qu'elles emportent, cochée ou non."""
    e = e or etat()
    cochees = set(CLES if cochees is None else cochees)
    return [{
        "cle": cle,
        "titre": titre,
        "efface": efface,
        "detail": _detail(cle, e),
        "exige": [TITRES[autre] for autre in EXIGE.get(cle, {})],
        "exige_cles": list(EXIGE.get(cle, {})),
        "exige_phrase": (f"Emporte aussi {' et '.join(_minuscule(TITRES[a]) for a in EXIGE[cle])}."
                         if cle in EXIGE else ""),
        "cochee": cle in cochees,
    } for cle, titre, efface in PARTIES]


def controler(parties):
    """Les refus, en phrases : une partie inconnue, une partie sans ce qu'elle
    emporte, ou rien de coché. Vide : on peut y aller."""
    parties = set(parties)
    refus = [f"Partie inconnue : « {p} »." for p in sorted(parties - set(CLES))]
    if not parties:
        refus.append("Cochez au moins une partie à effacer.")
    for partie, exigences in EXIGE.items():
        if partie not in parties:
            continue
        for autre, raison in exigences.items():
            if autre not in parties:
                refus.append(f"« {TITRES[partie]} » ne s'efface pas sans « {TITRES[autre]} » "
                             f"— {raison}. Cochez les deux, ou gardez les deux.")
    return refus


# --- La sauvegarde --------------------------------------------------------------

def _emplacements_touches(codes):
    """Les emplacements gardés dont une réservation va tomber : un code retiré,
    ou qui revient à une autre famille que celle de l'emplacement."""
    return Emplacement.objects.filter(pk__in=_reservations_qui_tombent(codes))


def _a_sauvegarder(parties):
    """Tout ce qui va partir ou changer, dans l'ordre où `loaddata` doit le
    recharger : ce qui est cité avant ce qui le cite."""
    objets = []
    if CODES_MP in parties:
        objets += list(ArticleMP.objects.all())
    if PLAN in parties:
        objets += (list(Zone.objects.all()) + list(Emplacement.objects.all())
                   + list(PlaceCondamnee.objects.all()))
    elif CODES_MP in parties:
        # Le plan reste, mais des réservations vont tomber avec les codes :
        # leurs emplacements partent dans le fichier, réservations comprises.
        objets += list(_emplacements_touches(_semis()[0]))
    if MODELES in parties:
        objets += list(ModeleCabine.objects.all())
    if PRODUCTION in parties:
        objets += list(CabineAttendue.objects.all())
    if CABINES in parties:
        objets += (list(Cabine.objects.all()) + list(Occupation.objects.all())
                   + list(MouvementCabine.objects.all()))
    if MP in parties:
        objets += list(StockMP.objects.all()) + list(MouvementMP.objects.all())
    return objets


def sauvegarder(parties, dossier=None, horodatage=None):
    """Écrit tout ce que la remise à zéro va effacer ou changer. Rend le chemin.

    Le format est un export Django ordinaire : `manage.py loaddata <fichier>`
    remet tout en place. Ce n'est pas une trace pour l'archive, c'est un retour
    en arrière qui marche — et c'est la différence entre « irréversible, vous
    êtes prévenu » et « irréversible, sauf si vous rechargez ce fichier ».
    """
    racine = Path(dossier) if dossier else Path(settings.BASE_DIR) / DOSSIER_SAUVEGARDES
    racine.mkdir(parents=True, exist_ok=True)
    quand = horodatage or timezone.localtime()
    fichier = racine / f"remise-a-zero_{quand:%Y-%m-%d_%Hh%M%S}.json"
    rang = 2
    while fichier.exists():
        fichier = racine / f"remise-a-zero_{quand:%Y-%m-%d_%Hh%M%S}-{rang}.json"
        rang += 1
    # Écrite à côté, puis renommée : une écriture interrompue (disque plein)
    # ne laisse pas un fichier tronqué qui passerait pour une sauvegarde.
    partiel = fichier.with_name(fichier.name + ".partiel")
    try:
        partiel.write_text(serializers.serialize("json", _a_sauvegarder(set(parties)),
                                                 indent=1), encoding="utf-8")
        partiel.replace(fichier)
    except BaseException:
        try:
            partiel.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return fichier


# --- La remise à zéro -----------------------------------------------------------

def _remettre_modeles(grands):
    """Les six grands modèles d'origine, et eux seuls, sur leurs lignes."""
    ModeleCabine.objects.exclude(cle__in=list(grands)).delete()
    for cle, nom in grands.items():
        modele = ModeleCabine.objects.filter(cle=cle).first() or ModeleCabine()
        modele.nom, modele.grand, modele.modifie_par = nom, True, None
        modele.save()


def _remettre_codes_mp(codes):
    """Les codes livrés, tels que livrés, sur leurs lignes ; les autres retirés.

    Le stock MP est déjà vide (`EXIGE`) : rien ne retient un code retiré. Une
    réservation qui ne tient plus — code retiré, ou revenu à une autre famille
    que celle de son emplacement — tombe avec lui : un emplacement de cartons
    n'accepte pas un vitrage.
    """
    ArticleMP.objects.exclude(code__in=list(codes)).delete()
    for code, ligne in codes.items():
        article = ArticleMP.objects.filter(code=code).first() or ArticleMP(code=code)
        for champ in CHAMPS_LIVRES:
            setattr(article, champ, ligne[champ])
        article.actif = True
        article.save()
    lien = Emplacement.codes_acceptes.through
    familles = _familles_par_emplacement()
    hors_famille = [pk for pk, famille, e_id in lien.objects.values_list(
        "pk", "articlemp__famille", "emplacement_id")
        if familles.get(e_id) and famille not in familles[e_id]]
    lien.objects.filter(pk__in=hors_famille).delete()


def _tables(parties):
    """Les tables que la remise va lire, effacer ou réécrire."""
    modeles = set()
    if CABINES in parties:
        modeles |= {Cabine, Occupation, MouvementCabine}
    if MP in parties:
        modeles |= {StockMP, MouvementMP}
    if PRODUCTION in parties:
        modeles |= {CabineAttendue}
    if PLAN in parties:
        modeles |= {Zone, Emplacement, PlaceCondamnee, Emplacement.codes_acceptes.through}
    if MODELES in parties:
        modeles |= {ModeleCabine}
    if CODES_MP in parties:
        modeles |= {ArticleMP, Emplacement, Emplacement.codes_acceptes.through}
    return sorted(m._meta.db_table for m in modeles)


def _verrouiller(parties):
    """Plus personne n'écrit dans ces tables jusqu'à la fin de la transaction.

    Sans cela, sur PostgreSQL, une cabine rangée par un poste pendant que la
    sauvegarde s'écrit serait effacée sans être dans le fichier. Les lectures
    continuent ; les écritures attendent quelques secondes, puis passent sur
    l'outil remis à zéro. SQLite (poste de développement) verrouille déjà la
    base entière à la première écriture.
    """
    if connection.vendor != "postgresql":
        return
    noms = ", ".join(connection.ops.quote_name(t) for t in _tables(parties))
    with connection.cursor() as curseur:
        # Un geste en cours a quinze secondes pour finir ; au-delà, ou si
        # PostgreSQL détecte que deux transactions s'attendent l'une l'autre,
        # la remise est annulée avant toute écriture — l'écran le dit.
        curseur.execute("SET LOCAL lock_timeout = '15s'")
        curseur.execute(f"LOCK TABLE {noms} IN EXCLUSIVE MODE")


@transaction.atomic
def remettre_a_zero(*, parties, utilisateur=None, dossier=None):
    """Efface les parties cochées, après les avoir sauvegardées. Rend le bilan.

    L'ordre suit les liens entre tables : les journaux et le stock d'abord, le
    plan ensuite — un emplacement qui porte du stock ne se supprime pas —, les
    réglages d'origine en dernier.
    """
    parties = set(parties)
    refus = controler(parties)
    if refus:
        raise ValidationError(refus)
    _verrouiller(parties)
    avant = etat()
    resume = " ; ".join(f"{_minuscule(TITRES[cle])} : {_minuscule(_detail(cle, avant))}"
                        .rstrip(".") for cle in CLES if cle in parties)
    fichier = sauvegarder(parties, dossier)
    codes, grands = _semis()

    if CABINES in parties:
        MouvementCabine.objects.all().delete()
        Cabine.objects.all().delete()          # leurs occupations partent avec elles
    if MP in parties:
        MouvementMP.objects.all().delete()
        StockMP.objects.all().delete()
    if PRODUCTION in parties:
        CabineAttendue.objects.all().delete()
    if PLAN in parties:
        # Places condamnées et réservations partent avec leurs emplacements ;
        # les zones ensuite, que plus rien ne retient.
        Emplacement.objects.all().delete()
        Zone.objects.all().delete()
    if MODELES in parties:
        _remettre_modeles(grands)
    if CODES_MP in parties:
        _remettre_codes_mp(codes)

    logger.warning("Remise à zéro par %s : %s. Sauvegarde : %s",
                   getattr(utilisateur, "username", "?"), resume, fichier)
    return {"parties": [cle for cle in CLES if cle in parties], "avant": avant,
            "resume": resume, "sauvegarde": fichier}
