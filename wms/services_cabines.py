"""Moteur métier des cabines — passage obligé, comme services.py l'est pour le stock.

Toute écriture sur une `Cabine` passe par ce module : il applique les règles et écrit
le `MouvementCabine` correspondant dans la même transaction. Écrire `Cabine` en direct
laisserait une cabine sans trace de son déplacement, alors que l'historique « par qui,
quand » est précisément ce que l'exploitation demande.

Règles portées ici :
- une place (emplacement × G/M/D) ne porte qu'une cabine ;
- une cabine envoyée est sortie de l'entrepôt : plus aucun mouvement possible ;
- la sortie d'emplacement et l'envoi exigent un n° de chantier, y compris pour une
  cabine express — c'est la seule contrainte qu'express ne relâche pas.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Cabine, MouvementCabine, Occupation


class ErreurCabine(ValidationError):
    pass


PLACES = [c for c, _ in Cabine.PLACES]


def _nom(utilisateur):
    if not utilisateur or not getattr(utilisateur, "pk", None):
        return ""
    return getattr(utilisateur, "nom", "") or utilisateur.get_username()


def _libelle(emplacement, place):
    """« Zone / A001·G » — recopié dans l'historique pour survivre aux suppressions."""
    if not emplacement:
        return ""
    zone = emplacement.zone_cabine.nom if emplacement.zone_cabine_id else ""
    position = f"{emplacement.code}·{place}" if place else emplacement.code
    return f"{zone} / {position}" if zone else position


def _tracer(cabine, type, utilisateur=None, depuis="", vers="",
            statut_avant="", statut_apres="", note=""):
    return MouvementCabine.objects.create(
        cabine=cabine, cabine_numero=cabine.numero, chantier=cabine.chantier,
        type=type, utilisateur=utilisateur if getattr(utilisateur, "pk", None) else None,
        utilisateur_nom=_nom(utilisateur), depuis=depuis, vers=vers,
        statut_avant=statut_avant, statut_apres=statut_apres, note=note,
    )


def _rafraichir(cabine):
    """Vide les caches de relations avant de rendre la cabine à l'appelant.

    La vue charge les cabines avec `prefetch_related("occupations…")` : après
    avoir rangé, `cabine.occupations.all()` rendait encore la liste d'AVANT, et
    la réponse HTTP annonçait donc l'ancienne position. `refresh_from_db()` sans
    argument vide ce cache — c'est ce qu'il fait de documenté.
    """
    cabine.refresh_from_db()
    return cabine


def _refuser_si_envoyee(cabine):
    if cabine.envoyee:
        raise ErreurCabine(
            f"La cabine {cabine.numero} est envoyée : elle est archivée et ne peut plus bouger.")


def occupations_presentes(emplacement):
    """Occupations réelles de cet emplacement, quel que soit son mode.

    Une cabine peut occuper cette travée et se prolonger trois travées plus loin :
    ce sont les occupations qu'on compte, pas les cabines.
    """
    return (Occupation.objects.filter(emplacement=emplacement)
            .exclude(cabine__statut=Cabine.ENVOYE)
            .select_related("cabine", "emplacement", "emplacement__zone_cabine")
            .order_by("place", "cabine__numero", "numero"))


def cabines_presentes(emplacement):
    """Cabines occupant au moins une place ici. Sans doublon, ordre stable."""
    return (Cabine.objects.filter(occupations__emplacement=emplacement)
            .exclude(statut=Cabine.ENVOYE)
            .prefetch_related("occupations__emplacement")
            .distinct().order_by("numero"))


def places_libres(emplacement):
    """Places G/M/D encore disponibles, dans l'ordre. Vide si capacité illimitée."""
    if emplacement.illimite:
        return []
    prises = set(occupations_presentes(emplacement).exclude(place="")
                 .values_list("place", flat=True))
    return [p for p in PLACES if p not in prises]


def est_complet(emplacement):
    """Un emplacement à capacité illimitée n'est jamais complet."""
    return False if emplacement.illimite else not places_libres(emplacement)


def occupation(emplacement):
    """État des trois places : {'G': occupation|None, 'M': …, 'D': …}.

    Vide pour un emplacement à capacité illimitée : il n'a pas de place nommée,
    ses occupants se lisent par `occupations_presentes()`.
    """
    if emplacement.illimite:
        return {}
    etat = {p: None for p in PLACES}
    for occupation in occupations_presentes(emplacement).exclude(place=""):
        etat[occupation.place] = occupation
    return etat


#: Champs repris de la fiche papier : informatifs, sans règle logistique attachée.
CHAMPS_FICHE = ["revendeur", "client", "tissu_bk", "tissu_aq", "fond_cabine"]


@transaction.atomic
def creer_cabine(*, numero, chantier="", type_cabine=Cabine.NORMALE, modele="",
                 statut=Cabine.LIBRE, utilisateur=None, **fiche):
    cabine = Cabine(numero=(numero or "").strip(), chantier=(chantier or "").strip(),
                    type_cabine=type_cabine, modele=modele, statut=statut,
                    statut_date=timezone.now(), utilisateur=utilisateur)
    for champ in CHAMPS_FICHE:
        if fiche.get(champ):
            setattr(cabine, champ, str(fiche[champ]).strip()[:120])
    cabine.save()   # crée aussi la ligne d'occupation n° 1, vide (invariant)
    _tracer(cabine, MouvementCabine.CREATION, utilisateur,
            statut_apres=cabine.statut, note=cabine.get_type_cabine_display())
    return cabine


@transaction.atomic
def occupation_a_remplir(cabine):
    """Ligne d'occupation encore vide, s'il y en a une.

    Une cabine neuve en a exactement une : c'est là que sa première position
    s'écrit. Une cabine déjà rangée n'en a aucune — ajouter un emplacement en
    crée alors une nouvelle.
    """
    libres = cabine.occupations_libres
    return libres[0] if libres else None


def _occupation_de(cabine, occupation=None, ajouter=False):
    """Résout la ligne où écrire la position.

    Trois cas, dans cet ordre :

    - une occupation est nommée : c'est un DÉPLACEMENT de celle-là ;
    - `ajouter` : on en crée une nouvelle, même si la cabine est déjà rangée.
      C'est le cas « elle tient à deux endroits » — le plus rare, mais celui
      qu'il ne faut surtout pas confondre avec un déplacement, sous peine de
      libérer une place où la cabine se trouve encore ;
    - sinon : la première ligne vide, ou — s'il n'y en a plus — la dernière
      occupée, ce qui revient à déplacer la cabine. C'est le comportement de
      toujours pour une cabine à un seul emplacement.
    """
    if occupation is not None:
        if occupation.cabine_id != cabine.pk:
            raise ErreurCabine("Cet emplacement n'appartient pas à cette cabine.")
        return occupation
    if ajouter:
        prochain = (cabine.occupations.order_by("-numero")
                    .values_list("numero", flat=True).first() or 0) + 1
        return Occupation.objects.create(cabine=cabine, numero=prochain)
    tous = list(cabine.occupations.order_by("numero"))
    if not tous:
        # Cabine antérieure au modèle, ou créée hors service : on la remet d'aplomb.
        return Occupation.objects.create(cabine=cabine, numero=1)
    return occupation_a_remplir(cabine) or tous[-1]


@transaction.atomic
def ranger(*, cabine, emplacement, place="", occupation=None, ajouter=False,
           utilisateur=None):
    """Range la cabine sur l'emplacement.

    Le mode de l'emplacement commande : « gmd » exige une place G/M/D libre,
    « illimite » n'en accepte aucune et ne limite pas le nombre de cabines.

    Sans précision, une cabine déjà rangée est DÉPLACÉE — le comportement de
    toujours. `ajouter=True` lui donne un emplacement DE PLUS, sans libérer le
    premier : c'est le cas de la cabine qui ne tient pas dans une seule travée.
    """
    _refuser_si_envoyee(cabine)
    if not emplacement.actif:
        raise ErreurCabine(f"L'emplacement {emplacement.code} est inactif.")

    cible = _occupation_de(cabine, occupation, ajouter=ajouter)
    place = (place or "").strip().upper()
    if emplacement.illimite:
        if place:
            raise ErreurCabine(
                f"L'emplacement {emplacement.code} est à capacité illimitée : "
                "il ne se range pas par place G/M/D.")
    else:
        if place not in PLACES:
            raise ErreurCabine(f"Place inconnue : « {place} ». Attendu G, M ou D.")

    if cible.emplacement_id == emplacement.pk and cible.place == place:
        raise ErreurCabine("La cabine est déjà à cet emplacement." if emplacement.illimite
                           else "La cabine est déjà à cette place.")

    if not emplacement.illimite:
        occupant = (Occupation.objects.select_for_update()
                    .filter(emplacement=emplacement, place=place)
                    .exclude(cabine__statut=Cabine.ENVOYE).exclude(pk=cible.pk)
                    .select_related("cabine").first())
        if occupant:
            raise ErreurCabine(
                f"La place {place} de {emplacement.code} est déjà occupée par la "
                f"cabine {occupant.cabine.numero}.")

    avant = _libelle(cible.emplacement, cible.place)
    etait_range = bool(cible.emplacement_id)
    cible.emplacement = emplacement
    cible.place = place
    cible.save(update_fields=["emplacement", "place"])
    apres = _libelle(emplacement, place)
    # Un emplacement AJOUTÉ n'est pas un transfert : rien n'a été libéré.
    _tracer(cabine, MouvementCabine.TRANSFERT if etait_range else MouvementCabine.RANGEMENT,
            utilisateur, depuis=avant, vers=apres,
            note=("emplacement supplémentaire" if ajouter and not etait_range else ""))
    return _rafraichir(cabine)


@transaction.atomic
def sortir_de_l_emplacement(*, cabine, occupation=None, utilisateur=None, note=""):
    """Libère la place occupée par la cabine.

    Exige un n° de chantier pour TOUS les types, y compris ceux qui peuvent
    circuler sans (express, salon, occasion) : c'est la règle explicite du métier
    (« on ne doit pas pouvoir sortir sans attribuer un numéro de chantier »).
    L'exemption vaut pour entrer en stock, jamais pour en sortir.
    """
    _refuser_si_envoyee(cabine)
    poses = cabine.emplacements_occupes
    if not poses:
        raise ErreurCabine(f"La cabine {cabine.numero} n'est rangée nulle part.")
    if not cabine.chantier:
        raise ErreurCabine(
            "Affectez un n° de chantier à cette cabine avant de la sortir de son emplacement.")

    # Sans précision on libère TOUS les emplacements. Sortir une cabine à moitié
    # sans le dire laisserait une place réservée par un morceau qu'on croit parti.
    cibles = [occupation] if occupation is not None else poses
    for cible in cibles:
        if cible.cabine_id != cabine.pk:
            raise ErreurCabine("Cet emplacement n'appartient pas à cette cabine.")
        if not cible.emplacement_id:
            continue
        depuis = _libelle(cible.emplacement, cible.place)
        cible.emplacement = None
        cible.place = ""
        cible.save(update_fields=["emplacement", "place"])
        _tracer(cabine, MouvementCabine.RETRAIT, utilisateur, depuis=depuis, note=note)
    return _rafraichir(cabine)


@transaction.atomic
def changer_statut(*, cabine, statut, utilisateur=None, motif=""):
    """Change le statut. Aucun ordre imposé entre Libre / Quarantaine / Levée / Chargé.

    Les transitions ne sont volontairement pas contraintes : toute cabine ne passe pas
    par la quarantaine, et bloquer un enchaînement légitime arrêterait la production.
    Seul l'envoi est verrouillé (terminal, et il exige un chantier).

    `motif` est facultatif — jamais bloquant au poste — mais consigné dans l'historique :
    c'est lui qui explique pourquoi une quarantaine a été posée puis levée.
    """
    _refuser_si_envoyee(cabine)
    valides = [c for c, _ in Cabine.STATUTS]
    if statut not in valides:
        raise ErreurCabine(f"Statut inconnu : « {statut} ».")
    if statut == Cabine.ENVOYE:
        return envoyer(cabine=cabine, utilisateur=utilisateur, note=motif)
    if statut == cabine.statut:
        raise ErreurCabine(f"La cabine est déjà au statut « {cabine.get_statut_display()} ».")

    avant = cabine.statut
    cabine.statut = statut
    cabine.statut_date = timezone.now()
    cabine.save(update_fields=["statut", "statut_date"])
    _tracer(cabine, MouvementCabine.STATUT, utilisateur,
            statut_avant=avant, statut_apres=statut, note=(motif or "")[:255])
    return cabine


@transaction.atomic
def envoyer(*, cabine, utilisateur=None, note=""):
    """Envoi : irréversible. La cabine quitte l'entrepôt et rejoint les archives."""
    _refuser_si_envoyee(cabine)
    if not cabine.chantier:
        raise ErreurCabine("Affectez un n° de chantier à cette cabine avant de l'envoyer.")

    avant_statut = cabine.statut
    # `_libelle` et non `position` : le journal nomme la ZONE en plus de la
    # travée (« À ranger cabines / C001·M »). Sans elle, l'archive perd où la
    # cabine se trouvait dans l'entrepôt, pas seulement dans quel rack.
    avant_position = ", ".join(_libelle(c.emplacement, c.place)
                               for c in cabine.emplacements_occupes)
    maintenant = timezone.now()
    cabine.statut = Cabine.ENVOYE
    cabine.statut_date = maintenant
    cabine.envoi_date = maintenant
    cabine.save(update_fields=["statut", "statut_date", "envoi_date"])
    # Tous les emplacements sont libérés : la cabine part entière, y compris le
    # morceau qui dormait dans une autre travée.
    cabine.occupations.update(emplacement=None, place="")
    _tracer(cabine, MouvementCabine.ENVOI, utilisateur, depuis=avant_position,
            statut_avant=avant_statut, statut_apres=Cabine.ENVOYE, note=note)
    return _rafraichir(cabine)


@transaction.atomic
def reprendre(*, cabine, utilisateur=None, motif=""):
    """Remet en stock une cabine marquée envoyée.

    L'envoi était jusqu'ici sans retour : toute opération sur une cabine envoyée
    était refusée, et une cabine sortie par erreur — ou revenue de chantier —
    n'avait pour issue qu'une nouvelle fiche sous un autre numéro, avec deux
    historiques pour un seul objet.

    La reprise n'efface rien : l'envoi reste au journal, et le retour s'y ajoute.
    On lit donc la vie complète de la cabine, aller et retour compris.

    La cabine revient « en stock, non rangée » — pas à sa place d'avant : cette
    place a pu être réattribuée entre-temps, et c'est le rangement qui tranche.
    """
    if not cabine.envoyee:
        raise ErreurCabine(f"La cabine {cabine.numero} n'est pas envoyée.")

    maintenant = timezone.now()
    cabine.statut = Cabine.LIBRE
    cabine.statut_date = maintenant
    cabine.envoi_date = None
    cabine.save(update_fields=["statut", "statut_date", "envoi_date"])
    _tracer(cabine, MouvementCabine.STATUT, utilisateur,
            statut_avant=Cabine.ENVOYE, statut_apres=Cabine.LIBRE,
            note=(motif or "").strip() or "Retour en stock d'une cabine envoyée")
    return cabine


@transaction.atomic
def affecter_chantier(*, cabine, chantier, utilisateur=None):
    """Affecte ou corrige le n° de chantier (cas courant d'une express à sortir)."""
    _refuser_si_envoyee(cabine)
    chantier = (chantier or "").strip()
    if not chantier:
        raise ErreurCabine("Le n° de chantier est obligatoire.")
    avant = cabine.chantier
    cabine.chantier = chantier
    cabine.save(update_fields=["chantier"])
    _tracer(cabine, MouvementCabine.CORRECTION, utilisateur,
            note=f"Chantier {avant or '—'} → {chantier}")
    return cabine


def historique(cabine):
    return (MouvementCabine.objects.filter(cabine=cabine)
            .select_related("utilisateur").order_by("-date", "-id"))


# --- Correction et suppression d'une cabine ---------------------------------
#: Champs corrigeables sur une fiche, avec leur libellé pour le journal.
#: La position et le statut n'y figurent pas : ils ont leurs opérations dédiées
#: (ranger, sortir, statut, envoyer), qui écrivent chacune leur propre trace.
CHAMPS_CORRIGEABLES = {
    "numero": "n°", "chantier": "chantier", "type_cabine": "type", "modele": "modèle",
    "revendeur": "revendeur", "client": "client", "tissu_bk": "tissu BK",
    "tissu_aq": "tissu AQ", "fond_cabine": "fond de cabine",
}


@transaction.atomic
def corriger_fiche(*, cabine, utilisateur=None, **champs):
    """Corrige les informations d'identité d'une cabine mal saisie.

    Autorisé y compris sur une cabine envoyée : une faute de frappe sur un numéro
    reste une faute de frappe une fois la cabine partie, et la corriger vaut mieux
    que supprimer une archive pour la ressaisir.

    Chaque correction est journalisée avec l'avant et l'après, champ par champ :
    sans cela, un numéro qui change du jour au lendemain n'a aucune explication.
    """
    modifs = []
    for champ, libelle in CHAMPS_CORRIGEABLES.items():
        if champ not in champs:
            continue
        nouveau = champs[champ]
        nouveau = nouveau.strip() if isinstance(nouveau, str) else nouveau
        ancien = getattr(cabine, champ)
        if nouveau == ancien:
            continue
        setattr(cabine, champ, nouveau)
        modifs.append(f"{libelle} {ancien or '—'} → {nouveau or '—'}")

    if not modifs:
        raise ErreurCabine("Aucune modification : la fiche est déjà dans cet état.")

    if "numero" in champs and Cabine.objects.filter(
            numero=cabine.numero).exclude(pk=cabine.pk).exists():
        # `numero` est unique en base : sans ce contrôle, le doublon remonte en
        # IntegrityError (500) au lieu d'un message lisible au poste.
        raise ErreurCabine(f"Le numéro {cabine.numero} est déjà porté par une autre cabine.")

    cabine.save()   # clean_fields() + clean() rejouent les formats attendus
    _tracer(cabine, MouvementCabine.CORRECTION, utilisateur, note=" ; ".join(modifs)[:255])
    return cabine


#: Motifs qui appellent une confirmation supplémentaire avant de supprimer.
#: Tous sont franchissables : supprimer une cabine mal saisie est précisément
#: l'intention. Ce que le WMS doit garantir, c'est que l'opérateur sache ce qu'il
#: efface — pas l'en empêcher.
BLOCAGE_ENVOYEE, BLOCAGE_RANGEE, BLOCAGE_HISTORIQUE = "envoyee", "rangee", "historique"


def diagnostic_suppression(cabine):
    """Que perd-on en supprimant cette cabine ? Renvoie ``(motif, message)``.

    ``(None, "")`` = la cabine vient d'être créée, n'a rien vécu et n'occupe aucune
    place : c'est le cas de la faute de frappe, la suppression est sans conséquence.
    """
    if cabine.envoyee:
        date = cabine.envoi_date.strftime("%d/%m/%Y") if cabine.envoi_date else "—"
        return BLOCAGE_ENVOYEE, (
            f"La cabine {cabine.numero} a été envoyée le {date} : elle est archivée et "
            f"rattachée au chantier {cabine.chantier or '—'}. La supprimer efface la trace "
            "de ce départ.")

    poses = cabine.emplacements_occupes
    if poses:
        ou = ", ".join(_libelle(c.emplacement, c.place) for c in poses)
        quoi = "cette place" if len(poses) == 1 else f"ces {len(poses)} places"
        return BLOCAGE_RANGEE, (
            f"La cabine {cabine.numero} est rangée en {ou}. La supprimer libérera "
            f"{quoi} : assurez-vous que la cabine n'y est physiquement plus, sinon une "
            "autre y sera rangée par-dessus.")

    # Création et corrections de fiche ne comptent pas comme du vécu : ce sont
    # précisément les traces d'une saisie en cours de rectification. Sans cette
    # exclusion, corriger une faute de frappe rendait ensuite la cabine « déjà
    # vécue » et le WMS conseillait… de corriger la fiche.
    vecu = (MouvementCabine.objects.filter(cabine=cabine)
            .exclude(type__in=[MouvementCabine.CREATION, MouvementCabine.CORRECTION])
            .count())
    if vecu:
        return BLOCAGE_HISTORIQUE, (
            f"Cette cabine a déjà vécu {vecu} événement(s) — rangements, changements de "
            "statut. Ce n'est probablement pas une simple erreur de saisie : corriger la "
            "fiche vaut mieux que la supprimer.")

    return None, ""


@transaction.atomic
def supprimer_cabine(*, cabine, utilisateur=None, force=False, motif=""):
    """Supprime une cabine créée par erreur, en laissant une trace dans le journal.

    La trace est écrite AVANT la suppression : `MouvementCabine.cabine` est en
    SET_NULL, la ligne survit donc à la disparition de la cabine, avec son numéro,
    son chantier et le nom de l'auteur recopiés. Le journal général répond ainsi à
    « où est passée la 26_03_47 ? », ce qu'une suppression muette rendait impossible.
    """
    blocage, message = diagnostic_suppression(cabine)
    if blocage and not force:
        raise ErreurCabine(message)

    numero = cabine.numero
    _tracer(cabine, MouvementCabine.SUPPRESSION, utilisateur,
            depuis=cabine.position,
            statut_avant=cabine.statut,
            note=(motif or "").strip()[:255] or "Saisie erronée")
    cabine.delete()
    return numero
