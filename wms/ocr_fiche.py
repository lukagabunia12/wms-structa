"""Reconnaissance de texte sur la photo d'une fiche cabine, côté serveur.

Pourquoi côté serveur : la reconnaissance dans le navigateur (tesseract.js) ne rendait
aucun texte — worker initialisé, résultat vide, confiance nulle. Ici le moteur tourne
dans le processus Django, ce qui a deux avantages décisifs : c'est testable, et le
téléphone n'a qu'à envoyer la photo (pas de 6 Mo de dictionnaire à télécharger, pas de
WASM à exécuter sur un mobile d'entrepôt).

Moteur : RapidOCR (ONNX). Installé par pip seul, sans binaire système à déployer :
    pip install -r requirements-ocr.txt

La dépendance est **optionnelle**. Si elle est absente, `disponible()` renvoie False et
l'API répond clairement au lieu de tomber : le reste du WMS n'en dépend pas.
"""
import io
import threading

_moteur = None
_verrou = threading.Lock()
_indisponible = None


def disponible():
    """Le moteur peut-il être utilisé ? Ne lève jamais."""
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def _obtenir_moteur():
    """Moteur unique, chargé à la première demande.

    Le chargement des modèles coûte quelques secondes : le refaire à chaque photo
    rendrait l'écran inutilisable au poste.
    """
    global _moteur, _indisponible
    if _moteur is not None:
        return _moteur
    if _indisponible is not None:
        raise _indisponible
    with _verrou:
        if _moteur is None and _indisponible is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
                _moteur = RapidOCR()
            except Exception as e:  # dépendance absente ou modèles illisibles
                _indisponible = RuntimeError(
                    "Moteur de reconnaissance indisponible : installez "
                    "requirements-ocr.txt sur le serveur.")
                raise _indisponible from e
    if _indisponible is not None:
        raise _indisponible
    return _moteur


def lire_image(donnees):
    """Renvoie le texte reconnu sur une image (bytes).

    Les zones sont rendues une par ligne : c'est la forme que
    `wms.lecture_fiche.analyser` attend, et celle que produit une photo de tableau —
    étiquette et valeur dans des cellules distinctes.
    """
    import numpy as np
    from PIL import Image, ImageOps

    image = Image.open(io.BytesIO(donnees))
    # Redresse selon l'orientation EXIF : une photo prise en portrait arrive souvent
    # couchée, et le texte devient illisible pour le moteur.
    image = ImageOps.exif_transpose(image).convert("RGB")

    # Une photo de téléphone fait 4000 px de large : inutile, et lent. On borne.
    LARGEUR_MAX = 1600
    if image.width > LARGEUR_MAX:
        hauteur = round(image.height * LARGEUR_MAX / image.width)
        image = image.resize((LARGEUR_MAX, hauteur), Image.LANCZOS)

    resultat, _ = _obtenir_moteur()(np.array(image))
    if not resultat:
        return ""
    return reconstituer_lignes(resultat)


def reconstituer_lignes(zones):
    """Regroupe les zones reconnues en lignes de tableau, étiquette puis valeur.

    Un simple tri de haut en bas ne suffit pas : dans une même rangée, la valeur est
    souvent détectée deux pixels plus haut que son étiquette, et l'on obtient
    « 26_03_47 » AVANT « REF. CABINE ». Le parseur cherchant la valeur après
    l'étiquette, le numéro était perdu. On regroupe donc par chevauchement vertical,
    puis on ordonne de gauche à droite — ce qui rend fidèlement les deux colonnes.

    `zones` : liste de (boîte 4 points, texte, confiance), telle que RapidOCR la rend.
    """
    boites = []
    for zone in zones:
        points, texte = zone[0], str(zone[1]).strip()
        if not texte:
            continue
        ys = [p[1] for p in points]
        xs = [p[0] for p in points]
        boites.append({"texte": texte, "centre": (min(ys) + max(ys)) / 2,
                       "hauteur": max(ys) - min(ys), "x": min(xs)})
    if not boites:
        return ""

    boites.sort(key=lambda b: b["centre"])
    # Tolérance liée à la hauteur des caractères : deux zones appartiennent à la même
    # rangée si leurs centres sont plus proches que la moitié d'une hauteur de texte.
    hauteurs = sorted(b["hauteur"] for b in boites)
    tolerance = max(6.0, hauteurs[len(hauteurs) // 2] * 0.6)

    rangees, courante = [], [boites[0]]
    for boite in boites[1:]:
        if abs(boite["centre"] - courante[-1]["centre"]) <= tolerance:
            courante.append(boite)
        else:
            rangees.append(courante)
            courante = [boite]
    rangees.append(courante)

    return "\n".join(" ".join(b["texte"] for b in sorted(r, key=lambda b: b["x"]))
                     for r in rangees)
