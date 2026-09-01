"""Lecture de la fiche cabine papier à partir d'un texte reconnu (OCR).

La fiche est un tableau à deux colonnes — étiquette à gauche, valeur à droite :

    REVENDEUR      MYAH
    CLIENT         HAS
    N° DE CDE      251280
    REF. CABINE    26_03_47
    CABINE         QUATTRO
    TISSUS BK      A2419
    TISSUS AQ      A2414
    FOND CABINE    VITRE

L'OCR est volontairement traité comme peu fiable : selon la photo, il colle les deux
colonnes sur une ligne, les sépare, confond `0`/`O` et `1`/`I`, ou perd une étiquette.
Ce module extrait ce qu'il peut et **dit ce qu'il n'a pas su lire** ; l'opérateur
confirme ensuite à l'écran. Rien n'est enregistré sans relecture humaine.

L'analyse vit côté serveur, et non dans le navigateur, pour être couverte par la suite
de tests : c'est la partie la plus fragile de la chaîne.
"""
import re
import unicodedata

#: Correction des confusions classiques de l'OCR, appliquée aux seuls champs numériques.
#: G/6 et Z/2 ont été ajoutés après avoir vu « 2G_O3_47 » sortir d'une photo prise
#: de biais : la forme du numéro était parfaite, deux caractères la rejetaient.
_CHIFFRES = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0",
                           "I": "1", "l": "1", "L": "1", "|": "1",
                           "S": "5", "B": "8", "G": "6", "Z": "2"})

#: Caractères qu'un chiffre peut prendre sous l'œil de l'OCR. Sert aux motifs.
_CH = "0-9OoQDIlLS|BGZ"


def normaliser(texte):
    """Majuscules sans accent, espaces réduits — pour comparer des étiquettes."""
    sans_accent = "".join(c for c in unicodedata.normalize("NFD", texte or "")
                          if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sans_accent).strip().upper()


def _numero(valeur, meme_ligne=False):
    """« 26_03_47 », « 26-03-47 », « 26 03 47 », « 2G_O3_47 » → « 26_03_47 »."""
    # Le séparateur peut être un espace seul : l'OCR perd fréquemment les tirets bas.
    m = re.search(rf"([{_CH}]{{2}})[\s_\-–—.]+([{_CH}]{{2}})"
                  rf"[\s_\-–—.]+([{_CH}]{{2}})", valeur)
    if m:
        groupes = [g.translate(_CHIFFRES) for g in m.groups()]
        if all(g.isdigit() for g in groupes):
            return "_".join(groupes)
    if not meme_ligne:
        return None
    # Les tirets bas sont fins : sur une photo d'écran, une impression pâle ou un
    # cliché de biais, l'OCR les avale et rend « 260347 ». On accepte six chiffres
    # d'affilée — mais **uniquement sur la ligne de l'étiquette**. Ailleurs, six
    # chiffres seraient tout aussi bien le numéro de commande, qui en compte six.
    for brut in re.findall(rf"[{_CH}]{{6}}", valeur):
        corrige = brut.translate(_CHIFFRES)
        if corrige.isdigit():
            return f"{corrige[0:2]}_{corrige[2:4]}_{corrige[4:6]}"
    return None


def _chantier(valeur, meme_ligne=False):
    """Six chiffres d'affilée, tolérant les O/I pris pour des chiffres."""
    for brut in re.findall(rf"[{_CH}]{{6,}}", valeur):
        corrige = brut.translate(_CHIFFRES)
        if len(corrige) == 6 and corrige.isdigit():
            return corrige
    return None


def _texte_libre(valeur, meme_ligne=False):
    valeur = valeur.strip(" :.-–—|")
    return valeur or None


def _reference_tissu(valeur, meme_ligne=False):
    """Référence de tissu : une lettre éventuelle puis des chiffres (« A2419 »)."""
    m = re.search(r"\b([A-Z]?\s?\d{3,6})\b", valeur)
    if not m:
        return None
    return re.sub(r"\s+", "", m.group(1))


#: Ordre d'analyse : les étiquettes longues d'abord. Sinon « CABINE » capturerait la
#: ligne « REF. CABINE » ou « FOND CABINE » et écraserait le modèle.
CHAMPS = [
    ("numero", ["REF. CABINE", "REF CABINE", "REFCABINE", "REF.CABINE", "REF"], _numero),
    ("fond_cabine", ["FOND CABINE", "FOND DE CABINE", "FOND"], _texte_libre),
    ("chantier", ["N° DE CDE", "N DE CDE", "NO DE CDE", "N* DE CDE", "DE CDE",
                  "N° CDE", "CDE", "COMMANDE"], _chantier),
    ("tissu_bk", ["TISSUS BK", "TISSU BK", "TISSUSBK"], _reference_tissu),
    ("tissu_aq", ["TISSUS AQ", "TISSU AQ", "TISSUSAQ"], _reference_tissu),
    ("revendeur", ["REVENDEUR"], _texte_libre),
    ("client", ["CLIENT"], _texte_libre),
    ("modele", ["CABINE"], _texte_libre),
]

#: Champs indispensables pour créer une cabine ; les autres sont informatifs.
ESSENTIELS = ["numero", "chantier"]


def analyser(texte):
    """Extrait les champs de la fiche depuis le texte OCR.

    Renvoie `(champs, manquants)` : `champs` ne contient que ce qui a été lu et validé,
    `manquants` liste les clés attendues et introuvables, pour que l'écran les mette en
    évidence au lieu de laisser croire à une lecture complète.
    """
    lignes = [normaliser(brut) for brut in (texte or "").splitlines()]
    lignes = [ligne for ligne in lignes if ligne]
    champs, consommees = {}, set()

    for cle, libelles, extraire in CHAMPS:
        for i, ligne in enumerate(lignes):
            if i in consommees:
                continue
            libelle = next((normaliser(attendu) for attendu in libelles
                            if normaliser(attendu) in ligne), None)
            if libelle is None:
                continue

            # Valeur sur la même ligne, à droite de l'étiquette…
            debut = ligne.index(libelle)
            reste = ligne[debut + len(libelle):]
            valeur = extraire(reste, meme_ligne=True)
            lignes_prises = {i}
            # … ou à sa GAUCHE. Les colonnes sont reconstituées de gauche à droite
            # d'après les boîtes rendues par l'OCR ; sur une photo prise de biais,
            # ces boîtes se croisent et la valeur ressort avant son étiquette.
            if valeur is None:
                valeur = extraire(ligne[:debut], meme_ligne=True)
            # … sinon sur une ligne voisine. La suivante d'abord (colonnes séparées par
            # l'OCR), puis la précédente : selon la photo, la valeur est parfois détectée
            # légèrement plus haut que son étiquette et sort donc avant elle.
            if valeur is None:
                for j in (i + 1, i + 2, i - 1):
                    if 0 <= j < len(lignes) and j not in consommees:
                        valeur = extraire(lignes[j])
                        if valeur is not None:
                            lignes_prises = {i, j}
                            break
            if valeur is not None:
                champs[cle] = valeur
                consommees |= lignes_prises
                break

    # Dernier recours : le n° de cabine coûte que coûte.
    # Tout le reste de la fiche peut manquer sans conséquence — l'opérateur le
    # complète. Le numéro, lui, est la clé : sans lui il n'y a rien à ranger, et
    # la photo est à refaire. Quand l'étiquette « REF. CABINE » n'a pas été
    # reconnue (pliure, reflet, ombre), on cherche donc la FORME du numéro dans
    # tout le texte.
    if "numero" not in champs:
        secours = _numero_de_secours(lignes)
        if secours:
            champs["numero"] = secours

    manquants = [c for c in ESSENTIELS if c not in champs]
    return champs, manquants


#: Étiquettes dont la valeur ne peut pas être un n° de cabine. Le n° de commande
#: compte six chiffres lui aussi : sans cette garde, une commande « 25 12 80 »
#: mal segmentée par l'OCR passerait pour une cabine.
_LIGNES_INTERDITES = ("CDE", "COMMANDE", "CHANTIER", "TISSU", "DATE")


def _numero_de_secours(lignes):
    """Cherche un n° de cabine dans tout le texte, sans s'appuyer sur l'étiquette.

    Uniquement la forme SÉPARÉE — « 26_03_47 », « 26-03-47 », « 26 03 47 ». Six
    chiffres d'affilée ne sont PAS acceptés ici : ce serait tout aussi bien le
    numéro de commande, et se tromper de clé est pire que ne pas lire.
    """
    for ligne in lignes:
        if any(mot in ligne for mot in _LIGNES_INTERDITES):
            continue
        # `meme_ligne=False` : on refuse justement les six chiffres collés.
        trouve = _numero(ligne, meme_ligne=False)
        if trouve:
            return trouve
    return None
