"""Moteur métier des mouvements de stock — cœur du WMS.

Toutes les écritures de stock passent par ici. `Stock` est un cache : il est
maintenu en transaction à chaque mouvement, et reconstructible via `recalculer_stock()`.
"""
import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Article, Emplacement, Mouvement, Reception, Stock


class ErreurStock(ValidationError):
    pass


#: Le schéma stocke 3 décimales (Mouvement.qte / Stock.qte). Au-delà, la valeur serait
#: tronquée silencieusement : on la refuse plutôt que de fausser le stock.
DECIMALES_MAX = 3

#: max_digits des colonnes de quantité. SQLite n'impose PAS ce gabarit et Django ne le
#: valide pas au save() : une quantité démesurée (« 1e40 », 17 chiffres saisis par erreur)
#: était écrite en base, après quoi toute relecture ORM de la colonne levait
#: InvalidOperation — /api/stock/, /api/mouvements/ et le tableau de bord tombaient en 500
#: définitivement, sans correction possible par l'API. D'où ce contrôle en amont.
CHIFFRES_MAX = 14
ENTIERS_MAX = CHIFFRES_MAX - DECIMALES_MAX

#: Forme acceptée pour une quantité : un nombre décimal simple, point comme séparateur.
#: Refuse volontairement "1,5" (virgule ambiguë : séparateur décimal ou de milliers ?),
#: "1e3" (notation scientifique) et toute saisie non numérique.
_NOMBRE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _dec(v):
    """Convertit une quantité en Decimal, ou lève ErreurStock (→ 400 côté API).

    Sans ce garde-fou, une saisie invalide remonte en decimal.InvalidOperation,
    que la couche API ne rattrape pas : l'opérateur reçoit une erreur 500.
    """
    if isinstance(v, Decimal):
        d = v
    elif isinstance(v, bool):
        raise ErreurStock("Quantité invalide.")
    elif isinstance(v, int):
        d = Decimal(v)
    else:
        if v is None:
            raise ErreurStock("La quantité est obligatoire.")
        texte = str(v).strip()
        if not texte:
            raise ErreurStock("La quantité est obligatoire.")
        if not _NOMBRE.match(texte):
            raise ErreurStock(
                f"Quantité invalide : « {v} ». Attendu un nombre, "
                "avec le point comme séparateur décimal."
            )
        d = Decimal(texte)
    if not d.is_finite():
        raise ErreurStock("Quantité invalide.")
    if -d.as_tuple().exponent > DECIMALES_MAX:
        raise ErreurStock(
            f"La quantité ne peut pas avoir plus de {DECIMALES_MAX} décimales "
            f"(reçu : {v})."
        )
    if max(0, d.adjusted() + 1) > ENTIERS_MAX:
        raise ErreurStock(
            f"Quantité hors limites : au maximum {ENTIERS_MAX} chiffres avant la virgule "
            f"(reçu : {v})."
        )
    return d


def _ligne(article, emplacement):
    obj, _ = Stock.objects.select_for_update().get_or_create(
        article=article, emplacement=emplacement, defaults={"qte": Decimal("0")}
    )
    return obj


@transaction.atomic
def appliquer_mouvement(*, article, emplacement, type, qte, utilisateur=None, note="",
                        commande="", annulation=False, mouvement_source=None):
    qte = _dec(qte)
    if type in (Mouvement.ENTREE, Mouvement.SORTIE) and qte <= 0:
        raise ErreurStock("La quantité doit être strictement positive.")
    if type == Mouvement.AJUSTEMENT and qte < 0:
        raise ErreurStock("La quantité d'ajustement ne peut pas être négative.")

    ligne = _ligne(article, emplacement)
    if type == Mouvement.ENTREE:
        ligne.qte = ligne.qte + qte
    elif type == Mouvement.SORTIE:
        if ligne.qte < qte:
            raise ErreurStock(f"Stock insuffisant ({ligne.qte} disponible).")
        ligne.qte = ligne.qte - qte
    elif type == Mouvement.AJUSTEMENT:
        ligne.qte = qte
    else:
        raise ErreurStock("Type de mouvement inconnu.")
    ligne.save(update_fields=["qte"])

    return Mouvement.objects.create(
        type=type, article=article, emplacement=emplacement, qte=qte,
        utilisateur=utilisateur, note=note, commande=commande,
        annulation=annulation, mouvement_source=mouvement_source,
    )


def entree(**kw):
    return appliquer_mouvement(type=Mouvement.ENTREE, **kw)


def sortie(**kw):
    return appliquer_mouvement(type=Mouvement.SORTIE, **kw)


def ajustement(**kw):
    return appliquer_mouvement(type=Mouvement.AJUSTEMENT, **kw)


@transaction.atomic
def transfert(*, article, source, destination, qte, utilisateur=None, commande=""):
    if source == destination:
        raise ErreurStock("Source et destination identiques.")
    mv_out = sortie(article=article, emplacement=source, qte=qte, utilisateur=utilisateur,
                    note=f"Transfert vers {destination.code}", commande=commande)
    mv_in = entree(article=article, emplacement=destination, qte=qte, utilisateur=utilisateur,
                   note=f"Transfert depuis {source.code}", commande=commande)
    return mv_out, mv_in


@transaction.atomic
def contre_passer(mouvement, utilisateur=None):
    if mouvement.type == Mouvement.AJUSTEMENT:
        raise ErreurStock("Impossible de contre-passer un ajustement.")
    if mouvement.annule:
        raise ErreurStock("Mouvement déjà annulé.")
    if mouvement.annulation:
        # Sinon on rétablit l'effet du mouvement d'origine tout en le laissant marqué
        # « annulé » : l'historique deviendrait incohérent. Pour refaire l'opération,
        # il faut saisir un nouveau mouvement.
        raise ErreurStock(
            "Un mouvement d'annulation ne peut pas être contre-passé : "
            "saisissez un nouveau mouvement."
        )
    inverse = Mouvement.SORTIE if mouvement.type == Mouvement.ENTREE else Mouvement.ENTREE
    mv = appliquer_mouvement(
        type=inverse, article=mouvement.article, emplacement=mouvement.emplacement,
        qte=mouvement.qte, utilisateur=utilisateur,
        note=f"Contre-passation du mouvement #{mouvement.pk}",
        annulation=True, mouvement_source=mouvement,
    )
    mouvement.annule = True
    mouvement.save(update_fields=["annule"])
    return mv


def generer_numero_reception(date=None):
    d = date or timezone.localdate()
    prefixe = "R" + d.strftime("%y%m%d") + "-"
    n = Reception.objects.filter(numero__startswith=prefixe).count() + 1
    numero = f"{prefixe}{n:04d}"
    while Reception.objects.filter(numero=numero).exists():
        n += 1
        numero = f"{prefixe}{n:04d}"
    return numero


@transaction.atomic
def receptionner(*, article, emplacement, qte, utilisateur=None, commande="", commentaire="", staging=False):
    note = "Réception (à ranger)" if staging else "Réception"
    mv = entree(article=article, emplacement=emplacement, qte=qte,
                utilisateur=utilisateur, note=note, commande=commande)
    rec = Reception.objects.create(
        numero=generer_numero_reception(), article=article, emplacement=emplacement, qte=_dec(qte),
        utilisateur=utilisateur, commande=commande, commentaire=commentaire, staging=staging,
    )
    return mv, rec


def generer_ref(categorie):
    lettre = (categorie.nom[:1].upper() if categorie and categorie.nom else "A")
    if not lettre.isalpha():
        lettre = "A"
    n = Article.objects.count() + 1
    ref = f"{lettre}{n:04d}"
    while Article.objects.filter(ref=ref).exists():
        n += 1
        ref = f"{lettre}{n:04d}"
    return ref


def stock_disponible(article, emplacement):
    ligne = Stock.objects.filter(article=article, emplacement=emplacement).first()
    return ligne.qte if ligne else Decimal("0")


@transaction.atomic
def recalculer_stock():
    """Reconstruit intégralement le cache `Stock` en rejouant le journal des mouvements."""
    agg = {}
    for mv in Mouvement.objects.filter(article__isnull=False, emplacement__isnull=False).order_by("date", "id"):
        key = (mv.article_id, mv.emplacement_id)
        cur = agg.get(key, Decimal("0"))
        if mv.type == Mouvement.ENTREE:
            cur += mv.qte
        elif mv.type == Mouvement.SORTIE:
            cur -= mv.qte
        elif mv.type == Mouvement.AJUSTEMENT:
            cur = mv.qte
        agg[key] = cur
    Stock.objects.all().delete()
    Stock.objects.bulk_create([Stock(article_id=a, emplacement_id=e, qte=q) for (a, e), q in agg.items()])
    return len(agg)


# --- Suppression d'un emplacement -------------------------------------------
#: Motifs qui empêchent une suppression *définitive*, du plus dur au plus souple.
#: Voir `suppression_forcable` pour savoir qui peut passer outre, et pourquoi.
BLOCAGE_CABINES, BLOCAGE_STOCK, BLOCAGE_HISTORIQUE = "cabines", "stock", "historique"


def lignes_de_stock(emplacement):
    """Stock non nul présent sur l'emplacement, article par article."""
    from .models import Stock

    return (Stock.objects.filter(emplacement=emplacement).exclude(qte=0)
            .select_related("article").order_by("article__ref"))


def suppression_forcable(motif, utilisateur=None):
    """Ce blocage peut-il être levé, et par qui ?

    - **cabines** : jamais. Le parc se retrouverait « non rangé » sans trace, et
      il existe un geste simple pour l'éviter — « Sortir d'ici », à un clic sur
      l'écran de l'emplacement ;
    - **stock** : réservé aux administrateurs. Les écrans qui vident un
      emplacement (Sortie, Transfert) appartiennent au volet articles, aujourd'hui
      archivé : sans cette porte, un emplacement qui porte du stock est
      définitivement indélébile depuis l'interface ;
    - **historique** : ouvert à tout compte ayant le droit « référentiel ». Ce
      n'est pas de la marchandise qui se perd, c'est de la lisibilité.
    """
    if motif == BLOCAGE_HISTORIQUE:
        return True
    if motif == BLOCAGE_STOCK:
        return bool(utilisateur and getattr(utilisateur, "est_administrateur", False))
    return False


def diagnostic_suppression(emplacement, utilisateur=None):
    """Peut-on supprimer cet emplacement, et sinon pourquoi ?

    Renvoie ``(motif, message)`` — ``(None, "")`` si la suppression est franche.
    Le message s'adresse au compte passé en `utilisateur` : à un opérateur il dit
    à qui s'adresser, à un administrateur il dit ce que la suppression écrira.

    Trois cas :

    - des **cabines** y sont rangées : `Occupation.emplacement` est en SET_NULL, donc
      la suppression ne remonterait aucune erreur — elle détacherait les cabines
      en silence, et le parc se retrouverait « non rangé » sans la moindre trace
      dans le journal. C'est le cas le plus dangereux, et le plus discret ;
    - du **stock** non nul est présent : `Stock.emplacement` est en PROTECT, la
      suppression finirait en 500 ;
    - l'emplacement est cité dans l'**historique** (mouvements, réceptions,
      cabines déjà envoyées). Rien ne casse, mais le journal afficherait « ? »
      à la place du code : on prévient, et l'appelant tranche.
    """
    from .models import Cabine, Mouvement, Reception

    # Ce sont les COLIS qui occupent une place : une cabine peut n'en avoir qu'un
    # ici. `distinct()` évite de compter deux fois celle qui en aurait deux.
    cabines = (Cabine.objects.filter(occupations__emplacement=emplacement)
               .exclude(statut=Cabine.ENVOYE).distinct().count())
    if cabines:
        return BLOCAGE_CABINES, (
            f"{cabines} cabine(s) sont rangées sur {emplacement.code} : sortez-les "
            "(ou transférez-les) avant de supprimer l'emplacement.")

    lignes = list(lignes_de_stock(emplacement))
    if lignes:
        detail = ", ".join(f"{ligne.article.ref} ({_lisible(ligne.qte)})" for ligne in lignes[:4])
        if len(lignes) > 4:
            detail += f" et {len(lignes) - 4} autre(s)"
        if suppression_forcable(BLOCAGE_STOCK, utilisateur):
            return BLOCAGE_STOCK, (
                f"L'emplacement {emplacement.code} porte encore du stock : {detail}. "
                "En tant qu'administrateur, vous pouvez le supprimer malgré tout : une "
                "sortie sera enregistrée pour chaque article, et le journal des "
                "mouvements en gardera la trace avec votre nom et votre motif.")
        return BLOCAGE_STOCK, (
            f"L'emplacement {emplacement.code} porte encore du stock : {detail}. "
            "Videz-le d'abord (sortie ou transfert), ou demandez à un administrateur "
            "de le supprimer avec son stock.")

    traces = (Mouvement.objects.filter(emplacement=emplacement).count()
              + Reception.objects.filter(emplacement=emplacement).count()
              + Cabine.objects.filter(occupations__emplacement=emplacement).distinct().count())
    if traces:
        return BLOCAGE_HISTORIQUE, (
            f"{emplacement.code} apparaît dans {traces} ligne(s) d'historique. Le "
            "supprimer effacerait son code du journal. Désactivez-le plutôt : il "
            "disparaît des écrans de rangement et l'historique reste lisible.")

    return None, ""


def _lisible(quantite):
    """« 12 » plutôt que « 12.000 » : le journal se lit au poste, pas en base."""
    entier = quantite.to_integral_value()
    return str(entier if quantite == entier else quantite.normalize())


@transaction.atomic
def supprimer_emplacement(emplacement, *, force=False, utilisateur=None, motif=""):
    """Supprime un emplacement après contrôle. Lève ErreurStock sinon.

    Avec `force=True`, seuls les blocages que `suppression_forcable` autorise pour
    ce compte sont levés — les cabines rangées ne le sont jamais.

    Quand du stock reste, il est **sorti** avant la suppression, article par
    article. C'est l'invariant du projet : la vérité du stock est le journal des
    mouvements, pas la table `Stock`. Supprimer les lignes en direct ferait
    disparaître de la marchandise des totaux sans la moindre écriture — et
    `recalculer_stock()` ne pourrait rien reconstituer.
    """
    from .models import Stock

    blocage, message = diagnostic_suppression(emplacement, utilisateur)
    if blocage and not (force and suppression_forcable(blocage, utilisateur)):
        raise ErreurStock(message)

    note = f"Suppression de l'emplacement {emplacement.code}"
    if motif:
        note = f"{note} — {motif}"
    for ligne in lignes_de_stock(emplacement):
        if ligne.qte > 0:
            sortie(article=ligne.article, emplacement=emplacement, qte=ligne.qte,
                   utilisateur=utilisateur, note=note[:255])
        else:
            # Quantité négative : anomalie de données, aucune sortie ne s'écrit
            # dessus. On remet la ligne à zéro par ajustement, ce qui se journalise.
            ajustement(article=ligne.article, emplacement=emplacement, qte=0,
                       utilisateur=utilisateur, note=note[:255])

    # Lignes résiduelles à zéro : sans valeur métier, mais `PROTECT` les rendait
    # bloquantes, ce qui condamnait tout emplacement ayant été vidé.
    Stock.objects.filter(emplacement=emplacement).delete()
    emplacement.delete()


# --- Suppression d'un rack entier -------------------------------------------

def emplacements_du_rack(rack):
    """Les emplacements d'un rack, dans l'ordre du plan."""
    return (Emplacement.objects.filter(rack=(rack or "").strip())
            .order_by("colonne", "niveau", "code"))


def diagnostic_rack(rack, utilisateur=None):
    """Ce que la suppression du rack effacerait, et ce qui l'empêche.

    Rendu AVANT toute écriture, pour que l'écran montre les conséquences plutôt
    que de les découvrir à la première erreur. Un rack se supprime d'un geste :
    c'est précisément pourquoi il faut voir ce qu'il contient avant de l'engager.
    """
    rack = (rack or "").strip()
    if not rack:
        raise ErreurStock("Indiquez le rack à supprimer.")
    liste = list(emplacements_du_rack(rack))
    if not liste:
        raise ErreurStock(f"Aucun emplacement ne porte le rack « {rack} ».")

    bloquants, cabines, stock = [], 0, 0
    for e in liste:
        cabines += e.occupations.count()
        stock += lignes_de_stock(e).count()
        blocage, message = diagnostic_suppression(e, utilisateur)
        if blocage and not suppression_forcable(blocage, utilisateur):
            bloquants.append({"code": e.code, "motif": blocage, "message": message})

    return {
        "rack": rack,
        "emplacements": len(liste),
        "codes": [e.code for e in liste],
        "cabines": cabines,
        "lignes_stock": stock,
        "bloquants": bloquants,
        "supprimable": not bloquants,
    }


@transaction.atomic
def supprimer_rack(rack, *, force=False, utilisateur=None, motif=""):
    """Supprime tous les emplacements d'un rack, ou aucun.

    La transaction est le point important : supprimer la moitié d'un rack
    laisserait un plan à trous que personne ne saurait reconstituer. Si un seul
    emplacement résiste, rien n'est écrit.

    Chaque emplacement passe par `supprimer_emplacement` : mêmes règles, mêmes
    écritures de stock, mêmes refus. Rien n'est contourné parce qu'on en
    supprime plusieurs.
    """
    etat = diagnostic_rack(rack, utilisateur)
    if etat["bloquants"]:
        premier = etat["bloquants"][0]
        raise ErreurStock(
            f"{len(etat['bloquants'])} emplacement(s) du rack « {etat['rack']} » "
            f"ne peuvent pas être supprimés. Premier : {premier['code']} — {premier['message']}")

    note = motif or f"Suppression du rack {etat['rack']}"
    for emplacement in emplacements_du_rack(etat["rack"]):
        supprimer_emplacement(emplacement, force=force, utilisateur=utilisateur, motif=note)
    return {"rack": etat["rack"], "supprimes": etat["emplacements"], "codes": etat["codes"]}


# --- Génération d'un rack entier --------------------------------------------
#: Garde-fou : une faute de frappe sur le nombre de colonnes (10 → 1000) créerait
#: des milliers de lignes qu'il faudrait ensuite supprimer une par une.
GENERATION_MAX = 500
COLONNES_MAX, NIVEAUX_MAX, PAS_MAX = 300, 26, 10000


def _entier(valeur, nom, mini, maxi):
    try:
        n = int(str(valeur).strip())
    except (TypeError, ValueError):
        raise ErreurStock(f"« {nom} » doit être un nombre entier.")
    if not (mini <= n <= maxi):
        raise ErreurStock(f"« {nom} » doit être compris entre {mini} et {maxi}.")
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
        raise ErreurStock("Le préfixe du rack est obligatoire (ex. AC).")
    separateur = (separateur or "").strip()

    brut = str(debut if debut is not None else "").strip()
    if not brut.isdigit():
        raise ErreurStock("Le numéro de la première colonne doit être un nombre "
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
        raise ErreurStock(
            f"Avec un pas de {pas}, il ne peut pas y avoir {niveaux} niveaux : les "
            f"codes d'une colonne déborderaient sur la suivante. Augmentez le pas "
            f"(au moins {niveaux}) ou réduisez le nombre de niveaux.")

    total = colonnes * niveaux
    if total > GENERATION_MAX:
        raise ErreurStock(
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
        raise ErreurStock(f"Le code « {trop_long} » dépasse 64 caractères.")
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
def generer_rack(*, zone_cabine=None, mode_places=None, description="", **parametres):
    """Crée le rack. Les codes déjà pris sont laissés intacts et rapportés.

    Volontairement rejouable : ajouter un quatrième niveau à un rack existant se
    fait en relançant la même génération avec `niveaux=4` — les trois premiers
    sont reconnus et sautés, seul le nouveau est créé.
    """
    from django.db import IntegrityError

    apercu = apercu_rack(**parametres)
    a_creer = [x for x in apercu["codes"] if not x["existe"]]
    prefixe = (parametres.get("prefixe") or "").strip().upper()

    # Un par un plutôt que `bulk_create` : `Emplacement.save()` normalise le code,
    # et 500 lignes au maximum dans une seule transaction ne coûtent rien.
    crees = []
    for x in a_creer:
        emplacement = Emplacement(
            code=x["code"], rack=prefixe, colonne=x["colonne"], niveau=x["niveau"],
            zone_cabine=zone_cabine, description=description,
            **({"mode_places": mode_places} if mode_places else {}),
        )
        try:
            emplacement.save()
        except IntegrityError:
            # Deux postes qui génèrent le même rack en même temps : l'aperçu ne
            # voyait pas encore le code de l'autre.
            raise ErreurStock(
                f"Le code {x['code']} vient d'être créé par ailleurs. Relancez la "
                "génération : les codes déjà pris seront simplement ignorés.")
        crees.append(emplacement.code)

    return {
        "rack": prefixe,
        "crees": crees,
        "ignores": apercu["existants"],
        "total": apercu["total"],
    }
