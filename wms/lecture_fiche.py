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


#: Fin d'un numéro : ni chiffre ni lettre juste après. Sans cette garde,
#: « 25_49_400 » était lu « 25_49_40 » — le dernier groupe s'arrêtait à deux
#: caractères — et c'est une AUTRE cabine, bien réelle, qui était proposée au
#: rangement ou à la sortie. Un numéro collé à un mot (« 26_03_47QUATTRO »)
#: n'est plus lu du tout : l'opérateur le tape, plutôt que d'en deviner un.
_FIN = r"(?![0-9A-Za-z|])"


def _assez_de_chiffres(brut):
    """Au moins trois vrais chiffres : « BLOGS » se traduirait en « 81065 »."""
    return sum(c.isdigit() for c in brut) >= 3


def _numero(valeur, meme_ligne=False):
    """« 26_03_47 », « 26-03-47 », « 26 03 47 », « 2G_O3_47 » → « 26_03_47 ».

    Le dernier groupe compte un à trois chiffres, comme le numéro lui-même
    (`Cabine.MOTIF_NUMERO`) : « 26_03_7 » et « 25_49_400 » existent.
    """
    # Le séparateur peut être un espace seul : l'OCR perd fréquemment les tirets bas.
    m = re.search(rf"(?<![0-9])([{_CH}]{{2}})[\s_\-–—.]+([{_CH}]{{2}})"
                  rf"[\s_\-–—.]+([{_CH}]{{1,3}}){_FIN}", valeur)
    if m and _assez_de_chiffres("".join(m.groups())):
        groupes = [g.translate(_CHIFFRES) for g in m.groups()]
        if all(g.isdigit() for g in groupes):
            return "_".join(groupes)
    if not meme_ligne:
        return None
    # Les tirets bas sont fins : sur une photo d'écran, une impression pâle ou un
    # cliché de biais, l'OCR les avale et rend « 260347 ». On accepte cinq à
    # sept chiffres d'affilée — deux pour l'année, deux pour la semaine, le
    # reste pour le rang — mais **uniquement sur la ligne de l'étiquette**.
    # Ailleurs, six chiffres seraient tout aussi bien le numéro de commande.
    for brut in re.findall(rf"(?<![0-9A-Za-z])([{_CH}]{{5,7}}){_FIN}", valeur):
        corrige = brut.translate(_CHIFFRES)
        if corrige.isdigit() and _assez_de_chiffres(brut):
            return f"{corrige[0:2]}_{corrige[2:4]}_{corrige[4:]}"
    return None


#: Ce qu'on cherche sur la fiche papier : le NUMÉRO, et rien d'autre.
#:
#: La liste en portait huit. Chantier, modèle, revendeur, client, tissus, fond
#: de cabine : tous viennent du fichier de production, qui est la source. Les
#: relire sur une photo créait une seconde version des mêmes informations, et
#: quand les deux différaient personne ne savait laquelle croire — l'écran
#: montrait les deux côte à côte en laissant la question ouverte.
#:
#: Cinq champs de moins à extraire, c'est aussi cinq occasions de moins de lire
#: de travers un tableau photographié de biais.
CHAMPS = [
    ("numero", ["REF. CABINE", "REF CABINE", "REFCABINE", "REF.CABINE", "REF"], _numero),
]

#: Le seul champ indispensable. Le chantier vient du fichier de production, ou
#: se saisit à la main quand le classeur n'en porte pas — ce chemin existait
#: déjà (`CabineAttendue.chantier_a_saisir`), il devient le seul.
ESSENTIELS = ["numero"]


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
