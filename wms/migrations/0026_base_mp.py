"""La base des codes éléments, prête à l'emploi : 19 vitrages et 26 cartons.

Recopiée des deux tableaux de l'exploitation — le fichier des matières
premières (famille VERRE, fournisseurs ATV et MT) et le tableau des cartons
(code article, références TNM, réf. Structa, colisage).

- Vitrages : les lignes grisées du fichier sont d'ancienne génération (379,
  434, 382, 374, 591). Le seuil de réappro n'est connu que pour les cinq codes
  ATV : les captures des codes MT ne montraient pas la colonne des valeurs.
- Cartons : un code article fournisseur donne DEUX éléments, le couvercle
  (réf. TNM « -CV » ou « -COUV », réf. Structa « .CF. ») et le fond (« -FD »,
  « .FD. »). Les lignes rouges (PFC6ESS = C13, PFC7ESS = C14) ne servent plus :
  ancienne génération. La réf. Structa de la ligne fond du PFBBCUBEC2-B est
  recopiée telle quelle (C2.CV.1100x1050x115) : elle se corrige dans
  l'administration si c'est une coquille.

La migration n'écrase rien : un code déjà présent est laissé tel quel. Les
comptes qui manipulent les cabines reçoivent aussi la case « matières
premières » — sans quoi l'onglet MP n'ouvrirait que des écrans en lecture
seule le jour de la mise à jour.

Les fonctions de normalisation sont recopiées ici et non importées : une
migration doit rejouer demain exactement ce qu'elle fait aujourd'hui, même si
le code de l'application a changé entre-temps.
"""
import unicodedata

from django.db import migrations


def _cle(texte):
    texte = str(texte or "").replace("×", "X")
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return "".join(c for c in texte.upper() if c.isalnum())


#: (fournisseur, n°, code, désignation, seuil de réappro, ancienne génération)
VITRAGES = [
    ("ATV", "380", "VITR.927X2075.BP",
     "Vitrages arrières SOLO dims : 927 x 2075 44/2 acoustique bords polis", 50, False),
    ("ATV", "379", "VITR.449X2075.BP",
     "Vitrages avant DUO QUATTRO SIXO dims : 449 x 2075 44/2 acoustique bords polis",
     100, True),
    ("ATV", "613", "VITR.474X2075.BP",
     "Vitrages avant DQSX Premium dim : 474 x 2075 mm 44/2 acoustique bords polis", 50, False),
    ("ATV", "434", "VITR.445X2072.BP",
     "Vitrage avant ESSENTIELLE / INDUS dimensions : 445 x 2072 bords polis", 100, True),
    ("ATV", "612", "VITR.470X2072.BP",
     "Vitrages avant MLXL Essentielle dim : 470 x 2072 mm 44/2 acoustique bords polis",
     50, False),
    ("MT", "423", "VITR.1060X2075.BP",
     "Vitrage milieu XL3 dimensions : 1060 x 2075 44/2 acoustique bords polis", None, False),
    ("MT", "383", "VITR.739X2075.BP",
     "Vitrages arrières DUO QUATTRO 739 x 2075 44/2 acoustique bords polis", None, False),
    ("MT", "384", "VITR.988X2075.BP",
     "Vitrages arrières XL dims : 988 x 2075 44/2 acoustique bords polis", None, False),
    ("MT", "382", "VITR.694X2075.BP",
     "Vitrages avant XL dims : 694 x 2075 44/2 acoustique bords polis", None, True),
    ("MT", "614", "VITR.719X2075.BP",
     "Vitrages avant LXL Premium dim : 719 x 2075 mm 44/2 acoustique bords polis",
     None, False),
    ("MT", "381", "VITR.1101X2075.BP",
     "Vitrages latéral XL dims : 1101 x 2075 44/2 acoustique bords polis", None, False),
    ("MT", "374", "VITR.831X1981",
     "Vitrages portes dims : 831 x 1981 44/2 acoustique bords bruts", None, True),
    ("MT", "591", "VITR.831X1977.BB",
     "Vitrages portes dims : 831 x 1977 44/2 acoustique bords bruts", None, True),
    ("MT", "615", "VITR.790X1957.BB",
     "Vitrage porte dim : 790 x 1957 mm 44/2 acoustique bords bruts", None, False),
    ("MT", "652", "VITR.790X1961.BB",
     "Vitrage porte dims : 790 x 1961 44/2 acoustique bords bruts", None, False),
    ("MT", "543", "VITR.572X2072.BP",
     "Vitrage fond S Essentielle dimensions : 572 x 2072 44/2 acoustique bords polis",
     None, False),
    ("MT", "544", "VITR.784X2072.BP",
     "Vitrage fond M L XL Essentielle dimensions : 784 x 2072 44/2 acoustique bords polis",
     None, False),
    ("MT", "566", "VITR.814X2007.BB",
     "Vitrage de porte Upgrade dim : 814 x 2007 mm 44/2 acoustique bords bruts",
     None, False),
    ("MT", "586", "VITR.732X2072.BP",
     "Vitrage arrière Indus dimensions : 732 x 2072 44/2 acoustique bords polis",
     None, False),
]

#: (code article, libellé fournisseur, colisage, ancienne génération,
#:  (réf. TNM couvercle, réf. Structa couvercle), (réf. TNM fond, réf. Structa fond))
CARTONS = [
    ("PFC2ESS", "0300 BC75 1015 X 1015 X 80", 160, False,
     ("PFC2ESS-CV", "C9.CF.1015x1015x80"), ("PFC2ESS-FD", "C9.FD.1015x1015x80")),
    ("PFC6ESS", "0300 BC75 1325 X 500 X 120", 100, True,
     ("PFC6ESS-CV", "C13.CF.1325x500x120"), ("PFC6ESS-FD", "C13.FD.1325x500x120")),
    ("PFC5ESS", "0300 BC75 1385 X 350 X 90", 100, False,
     ("PFC5ESS-CV", "C12.CF.1385x350x90"), ("PFC5ESS-FD", "C12.FD.1385x350x90")),
    ("PFC7ESS", "0300 BC75 1730 X 500 X 120", 100, True,
     ("PFC7ESS-CV", "C14.CF.1730x500x120"), ("PFC7ESS-FD", "C14.FD.1730x500x120")),
    ("PFBBCUBEC2-B", "0300 BC75K 1110 X 1050 X 115", 160, False,
     ("PFC2-B-CV", "C2.CF.1100x1050x115"), ("PC2-B-FD", "C2.CV.1100x1050x115")),
    ("PFBBCUBECARTON6", "0300 BC75K 1730 X 1096 X 95", 160, False,
     ("PFC6-CV", "C6.CF.1730x1270x95"), ("PFC6-FD", "C6.FD.1730x1270x95")),
    ("PFC1ESS", "0300 BC75K 2115 X 1015 X 90", 160, False,
     ("PFC1ESS-CV", "C8.CF.2115x1015x90"), ("PFC1ESS-FD", "C8.FD.2115x1015x90")),
    ("PFC4ESS", "0300 BC75K 2115 X 1415 X 80", 160, False,
     ("PFC4ESS-CV", "C11.CF.2115x1415x80"), ("PFC4ESS-FD", "C11.FD.2115x1415x80")),
    ("PFBBCUBECARTON3", "0300 BC75K 2145 X 450 X 165", 160, False,
     ("PFC3-CV", "C3.CF.2145x450x165"), ("PFC3-FD", "C3.FD.2145x450x165")),
    ("PFBBCUBEC1-B", "0300 BC75K 2190 X 1050 X 115", 160, False,
     ("PFC1-B-CV", "C1.CF.2190x1050x115"), ("PFC1-B-FD", "C1.FD.2190x1050x115")),
    ("PFBBCUBEC4-B", "0300 BC75K 2190 X 1550 X 115", 160, False,
     ("PFC4-B-COUV", "C4.CF.2150x1550x90"), ("PFC4-B-FD", "C4.FD.2150x1550x90")),
    ("PFBBCUBEC7", "0300 BC75K 2190X1700X115", 110, False,
     ("PFC7-CV", "C7.CF.2190x1700x115"), ("PFC7-FD", "C7.FD.2190x1700x115")),
    ("PFBBCUBECARTON5", "0300 BC75K 2520 X 1340 X 90", 160, False,
     ("PFC5-CV", "C5.CF.2520x1340x90"), ("PFC5-FD", "C5.FD.2520x1340x90")),
]


def _alias_ess(code_article, piece):
    """Le marquage peint sur la palette : « ESS 1 F » pour le fond du PFC1ESS.

    Seule la gamme ESS se marque ainsi d'après les palettes photographiées ;
    les autres se retrouvent par leurs références TNM et leur code Structa.
    """
    if code_article.startswith("PFC") and code_article.endswith("ESS"):
        rang = code_article[3:-3]
        alias = [f"ESS {rang}"]
        if piece == "fond":
            alias.append(f"ESS {rang} F")
        return alias
    return []


def _lignes():
    for fournisseur, numero, code, designation, seuil, ancienne in VITRAGES:
        yield {"code": code, "famille": "vitrage", "designation": designation,
               "fournisseur": fournisseur, "numero": numero, "references": "",
               "colisage": None, "seuil_reappro": seuil,
               "ancienne_generation": ancienne}
    for article, libelle, colisage, ancienne, couvercle, fond in CARTONS:
        for piece, (tnm, structa) in (("couvercle", couvercle), ("fond", fond)):
            dimensions = structa.split(".", 2)[2] if structa.count(".") >= 2 else ""
            refs = [article, tnm, libelle, *_alias_ess(article, piece)]
            yield {"code": structa, "famille": "carton",
                   "designation": f"Carton — {piece} {dimensions}".strip(),
                   "fournisseur": "", "numero": "", "references": " · ".join(refs),
                   "colisage": colisage, "seuil_reappro": None,
                   "ancienne_generation": ancienne}


def remplir(apps, schema_editor):
    ArticleMP = apps.get_model("wms", "ArticleMP")
    for ligne in _lignes():
        code = " ".join(ligne["code"].split()).upper()
        if ArticleMP.objects.filter(code=code).exists():
            continue
        ArticleMP.objects.create(
            **{**ligne, "code": code},
            cle=_cle(code),
            cle_references="|".join(_cle(r) for r in ligne["references"].split("·")
                                    if _cle(r)),
        )

    Utilisateur = apps.get_model("wms", "Utilisateur")
    Utilisateur.objects.filter(droit_cab=True).update(droit_mp=True)


class Migration(migrations.Migration):

    dependencies = [
        ("wms", "0025_matieres_premieres"),
    ]

    operations = [
        # Retour en arrière sans effet : défaire 0025 supprime la table entière.
        migrations.RunPython(remplir, migrations.RunPython.noop),
    ]
