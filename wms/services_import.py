"""Import du fichier de production : les spécifications des cabines à venir.

Le fichier est un export Excel tenu à la main par la production. Il annonce les
cabines qui vont entrer en stock, avec toutes leurs caractéristiques. Une fois
importé, l'opérateur n'a plus qu'à identifier la cabine par son numéro à
l'entrée : le reste est déjà là, il n'a plus à recopier la fiche papier.

Trois principes, tirés du fichier réel (2 392 lignes, 67 colonnes) :

1. **Rien n'entre à l'aveugle.** Le fichier contient de vraies erreurs de
   saisie — cinq lignes où un n° de chantier a été recopié dans toutes les
   colonnes, 123 lignes sans n° de cabine. L'import les refuse **en les
   nommant, ligne par ligne**, plutôt que de les faire disparaître.

2. **Analyser d'abord, écrire ensuite.** `analyser()` ne touche à rien et rend
   le compte exact de ce qui va se passer. L'écran le montre, et rien n'est
   écrit avant confirmation.

3. **Un import n'efface jamais.** Une cabine attendue absente du nouveau
   fichier est conservée : rien ne dit qu'un fichier est complet, et perdre une
   spécification parce qu'une ligne a été filtrée dans Excel serait la pire
   des surprises. Le rapport signale simplement combien sont dans ce cas.
"""
import re
import unicodedata

from django.db import transaction

from .models import CabineAttendue

#: L'identifiant est la colonne « CABINE » (26_02_49) — le numéro déjà porté par
#: les étiquettes QR et par le masque de saisie. La colonne « NUM UNIQUE » est
#: importée à côté, cherchable, mais ne peut pas servir de clé : trois formats y
#: cohabitent (1133, AF-3164, 2025_320) et 215 lignes n'en ont pas.
COLONNE_NUMERO = "CABINE"
COLONNE_NUM_UNIQUE = "NUM UNIQUE"

#: Jamais importé. L'entrepôt n'a aucun usage logistique d'un prix, et le compte
#: de test est partagé entre tous les testeurs : l'afficher le mettrait sous les
#: yeux de tout le monde. La colonne est lue puis jetée.
COLONNES_IGNOREES = {"MONTANT NET PRODUIT"}

#: En-tête du fichier → champ du modèle, pour les seules colonnes qu'une requête
#: cherche ou qu'une `Cabine` reprend à l'entrée. Tout le reste part dans
#: `specifications`, sans schéma figé : le fichier gagne et perd des colonnes.
CORRESPONDANCE = {
    "CHANTIER": "chantier",
    "GAMME": "gamme",
    "MODELE": "modele",
    "QUANTITE": "quantite",
    "SEMAINE PRODUCTION": "semaine_production",
    "JOUR": "jour",
    "SEMAINE PROD ESTIMEE": "semaine_estimee",
    "REVENDEUR": "revendeur",
    "CLIENT": "client",
    "TISSUS BK": "tissu_bk",
    "TISSUS AQ": "tissu_aq",
    "TISSUS EXT": "tissu_ext",
    "FOND": "fond_cabine",
}

#: Longueur maximale des champs texte du modèle, pour tronquer plutôt que de
#: faire échouer tout un import sur une cellule bavarde.
TAILLES = {
    "chantier": 6, "gamme": 60, "modele": 120, "semaine_production": 16, "jour": 16,
    "semaine_estimee": 16, "revendeur": 120, "client": 120, "tissu_bk": 32,
    "tissu_aq": 32, "tissu_ext": 32, "fond_cabine": 64,
}

MOTIF_NUMERO = re.compile(r"^\d{2}_\d{2}_\d{1,3}$")
MOTIF_CHANTIER = re.compile(r"^\d{6}$")

#: Au-delà, ce n'est plus le fichier de production : on refuse avant de charger
#: 200 Mo en mémoire sur le poste serveur.
LIGNES_MAX = 20000


class ErreurImport(Exception):
    """Le fichier lui-même est inexploitable — pas une ligne, le fichier."""


def normaliser_entete(valeur):
    """« Semaine prod estimée » et « SEMAINE PROD ESTIMEE » sont la même colonne.

    Le fichier est tenu à la main : la casse, les accents et les espaces doubles
    changent d'une version à l'autre. Comparer les en-têtes brutes ferait
    silencieusement disparaître une colonne au premier renommage cosmétique.
    """
    texte = "" if valeur is None else str(valeur)
    sans_accent = "".join(c for c in unicodedata.normalize("NFD", texte)
                          if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sans_accent).strip().upper()


def _texte(valeur):
    """Cellule → texte propre. Excel rend des entiers, des flottants et des None."""
    if valeur is None:
        return ""
    if isinstance(valeur, float) and valeur.is_integer():
        return str(int(valeur))
    return str(valeur).strip()


def _entier(valeur, defaut=1):
    try:
        n = int(float(_texte(valeur) or defaut))
    except (TypeError, ValueError):
        return defaut
    return n if 0 < n < 32767 else defaut


def lire_classeur(fichier):
    """Rend (en-têtes normalisées, lignes brutes). Ne valide rien encore.

    `read_only` : le fichier de production fait un demi-mégaoctet aujourd'hui et
    grossit d'une semaine de production à l'autre. Le mode normal d'openpyxl
    construit tout l'arbre en mémoire, sur un poste d'entrepôt qui tourne déjà
    le serveur.
    """
    try:
        import openpyxl
    except ImportError as e:                                  # pragma: no cover
        raise ErreurImport(
            "La lecture des fichiers Excel n'est pas installée sur le serveur : "
            "lancez « pip install -r requirements.txt », puis redémarrez.") from e

    try:
        classeur = openpyxl.load_workbook(fichier, data_only=True, read_only=True)
    except Exception as e:
        raise ErreurImport(
            "Ce fichier n'est pas un classeur Excel lisible (.xlsx attendu). "
            f"Détail : {e}") from e

    try:
        feuille = classeur[classeur.sheetnames[0]]
        lignes = feuille.iter_rows(values_only=True)
        try:
            entetes_brutes = next(lignes)
        except StopIteration:
            raise ErreurImport("Le fichier est vide : pas même une ligne d'en-têtes.")

        entetes = [normaliser_entete(v) for v in entetes_brutes]
        if COLONNE_NUMERO not in entetes:
            raise ErreurImport(
                f"Colonne « {COLONNE_NUMERO} » introuvable. En-têtes lues : "
                + (", ".join(e for e in entetes if e) or "aucune"))

        corps = []
        for valeurs in lignes:
            if valeurs is None:
                continue
            if any(v not in (None, "") for v in valeurs):
                corps.append(valeurs)
            if len(corps) > LIGNES_MAX:
                raise ErreurImport(
                    f"Fichier trop volumineux : plus de {LIGNES_MAX} lignes. "
                    "Est-ce bien le fichier de production ?")
        return entetes, corps
    finally:
        classeur.close()


def _preparer(entetes, valeurs):
    """Une ligne du fichier → (numero, champs du modèle, spécifications)."""
    brut = {}
    for i, entete in enumerate(entetes):
        if not entete or entete in COLONNES_IGNOREES:
            continue
        v = valeurs[i] if i < len(valeurs) else None
        brut[entete] = v

    numero = _texte(brut.get(COLONNE_NUMERO))
    champs = {"num_unique": _texte(brut.get(COLONNE_NUM_UNIQUE))[:32]}

    for entete, champ in CORRESPONDANCE.items():
        if entete not in brut:
            continue
        if champ == "quantite":
            champs["quantite"] = _entier(brut[entete])
            continue
        if champ == "chantier":
            continue          # validé plus bas, et surtout PAS tronqué avant
        champs[champ] = _texte(brut[entete])[:TAILLES.get(champ, 255)]

    # Le chantier est validé ENTIER, jamais tronqué d'abord : couper « 251213-1 »
    # à six caractères le transforme en « 251213 » — un chantier qui existe, et
    # qui n'est pas celui-là. La première version de ce code faisait exactement
    # cela, et annonçait sereinement 110 chantiers reconnus.
    #
    # « 251213-1 » est probablement le chantier 251213, lot 1. Probablement ne
    # suffit pas : la valeur brute est conservée, `chantier` reste vide, et
    # l'opérateur saisira le chantier à l'entrée de la cabine.
    chantier = _texte(brut.get("CHANTIER"))
    champs["chantier_brut"] = chantier[:32]
    champs["chantier"] = chantier if MOTIF_CHANTIER.match(chantier) else ""

    # Les spécifications gardent la ligne telle qu'elle a été lue, y compris les
    # colonnes déjà reprises dans un champ : c'est ce que l'écran affiche, et une
    # colonne retirée de la correspondance ne doit pas disparaître de l'affichage.
    specifications = {k: _texte(v) for k, v in brut.items() if _texte(v) != ""}
    return numero, champs, specifications


def _identiques(existante, champs, specifications):
    """Vrai si un nouvel import ne changerait rien à cette ligne."""
    if existante.specifications != specifications:
        return False
    return all(getattr(existante, champ) == valeur for champ, valeur in champs.items())


def analyser(fichier, *, nom=""):
    """Compte ce qu'un import ferait, sans rien écrire.

    C'est cette fonction que l'écran appelle en premier : personne ne devrait
    découvrir qu'un fichier était le mauvais après l'avoir importé.
    """
    entetes, corps = lire_classeur(fichier)
    inconnues = sorted({e for e in entetes if e} - set(CORRESPONDANCE)
                       - {COLONNE_NUMERO, COLONNE_NUM_UNIQUE} - COLONNES_IGNOREES)

    existantes = {c.numero: c for c in CabineAttendue.objects.all()}
    vus = {}
    rapport = {
        "fichier": nom, "lignes": len(corps), "colonnes": len([e for e in entetes if e]),
        "nouvelles": 0, "modifiees": 0, "inchangees": 0, "sans_chantier": 0,
        "erreurs": [], "colonnes_libres": inconnues, "prepare": [],
    }

    for decalage, valeurs in enumerate(corps):
        ligne = decalage + 2          # 1 = en-têtes, et Excel compte à partir de 1
        numero, champs, specifications = _preparer(entetes, valeurs)

        if not numero:
            rapport["erreurs"].append({
                "ligne": ligne, "numero": "",
                "motif": "pas de n° de cabine (colonne CABINE vide)",
                "indice": _texte(champs.get("num_unique")) or ""})
            continue
        if not MOTIF_NUMERO.match(numero):
            # Le cas le plus fréquent n'est pas une faute de frappe : c'est un
            # collage qui a recouvert plusieurs colonnes d'un coup, et la colonne
            # CABINE porte alors le n° de chantier de sa propre ligne. Le dire
            # évite de chercher un problème de format là où il n'y en a pas.
            ecrasee = numero and numero == champs["chantier_brut"]
            rapport["erreurs"].append({
                "ligne": ligne, "numero": numero,
                "motif": ("la colonne CABINE contient « " + numero + " », le n° de "
                          "chantier de cette même ligne : les colonnes de cette ligne "
                          "ont été écrasées dans le classeur")
                         if ecrasee else
                         ("n° de cabine hors format (attendu 26_02_49, jusqu'à "
                          "3 chiffres à la fin)"), "indice": ""})
            continue
        if numero in vus:
            rapport["erreurs"].append({
                "ligne": ligne, "numero": numero,
                "motif": f"numéro déjà présent ligne {vus[numero]} du même fichier",
                "indice": ""})
            continue

        vus[numero] = ligne
        if champs["chantier_brut"] and not champs["chantier"]:
            rapport["sans_chantier"] += 1

        existante = existantes.get(numero)
        if existante is None:
            rapport["nouvelles"] += 1
        elif _identiques(existante, champs, specifications):
            rapport["inchangees"] += 1
        else:
            rapport["modifiees"] += 1
        rapport["prepare"].append((numero, champs, specifications))

    rapport["absentes_du_fichier"] = len(set(existantes) - set(vus))
    rapport["retenues"] = len(rapport["prepare"])
    return rapport


def rapport_public(rapport):
    """Le rapport sans `prepare` : ce qui part vers l'écran.

    `prepare` porte les 2 000 lignes déjà préparées — utile entre l'analyse et
    l'écriture, inutile et lourd à traverser le réseau. Une seule fonction le
    retire, pour qu'aucune vue ne l'oublie.
    """
    return {cle: valeur for cle, valeur in rapport.items() if cle != "prepare"}


@transaction.atomic
def importer(fichier, *, utilisateur=None, nom=""):
    """Analyse puis applique. Tout ou rien : une seule transaction.

    Un import à moitié appliqué serait le pire état possible — une partie des
    cabines annoncées avec les anciennes caractéristiques, l'autre avec les
    nouvelles, et aucun moyen de savoir où la coupure a eu lieu.
    """
    rapport = analyser(fichier, nom=nom)
    for numero, champs, specifications in rapport["prepare"]:
        CabineAttendue.objects.update_or_create(
            numero=numero,
            defaults={**champs, "specifications": specifications,
                      "fichier": nom[:200], "importe_par": utilisateur})
    rapport["importees"] = rapport["retenues"]
    del rapport["prepare"]
    return rapport
