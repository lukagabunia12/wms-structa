"""Tests de la lecture de la fiche cabine papier (texte issu de l'OCR).

L'OCR est la partie fragile de la chaîne : ces tests l'exercent avec du bruit réaliste
— colonnes collées ou séparées, confusions 0/O et 1/I, étiquettes abîmées, lignes
parasites — plutôt qu'avec un texte idéal qui ne prouverait rien.
"""
import io
import unittest
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from wms import lecture_fiche, ocr_fiche
from wms.models import Cabine, Utilisateur


#: Lecture « propre », colonnes séparées comme le fait souvent Tesseract sur un tableau.
FICHE_COLONNES = """REVENDEUR
MYAH
CLIENT
HAS
N° DE CDE
251280
REF. CABINE
26_03_47
CABINE
QUATTRO
TISSUS BK
A2419
TISSUS AQ
A2414
FOND CABINE
VITRE
"""

#: Même fiche, colonnes collées sur une seule ligne.
FICHE_LIGNES = """REVENDEUR MYAH
CLIENT HAS
N° DE CDE 251280
REF. CABINE 26_03_47
CABINE QUATTRO
TISSUS BK A2419
TISSUS AQ A2414
FOND CABINE VITRE
"""


class AnalyseFicheTest(APITestCase):
    def test_colonnes_separees(self):
        champs, manquants = lecture_fiche.analyser(FICHE_COLONNES)
        self.assertEqual(manquants, [])
        self.assertEqual(champs["numero"], "26_03_47")
        self.assertEqual(champs["chantier"], "251280")
        self.assertEqual(champs["modele"], "QUATTRO")
        self.assertEqual(champs["revendeur"], "MYAH")
        self.assertEqual(champs["client"], "HAS")
        self.assertEqual(champs["tissu_bk"], "A2419")
        self.assertEqual(champs["tissu_aq"], "A2414")
        self.assertEqual(champs["fond_cabine"], "VITRE")

    def test_colonnes_collees(self):
        champs, manquants = lecture_fiche.analyser(FICHE_LIGNES)
        self.assertEqual(manquants, [])
        self.assertEqual(champs["numero"], "26_03_47")
        self.assertEqual(champs["chantier"], "251280")
        self.assertEqual(champs["modele"], "QUATTRO")

    def test_cabine_ne_capture_pas_ref_cabine_ni_fond_cabine(self):
        """« CABINE » est contenu dans « REF. CABINE » et « FOND CABINE ».

        Sans traiter les étiquettes longues d'abord, le modèle vaudrait « 26_03_47 »
        ou « VITRE ».
        """
        champs, _ = lecture_fiche.analyser(FICHE_LIGNES)
        self.assertEqual(champs["modele"], "QUATTRO")
        self.assertEqual(champs["numero"], "26_03_47")
        self.assertEqual(champs["fond_cabine"], "VITRE")

    def test_confusion_lettres_chiffres_corrigee(self):
        """« 2G_O3_47 » et « 2S128O » : O pris pour 0, S pour 5."""
        texte = "REF. CABINE 26_O3_47\nN° DE CDE 2512BO\n"
        champs, manquants = lecture_fiche.analyser(texte)
        self.assertEqual(champs["numero"], "26_03_47")
        self.assertEqual(champs["chantier"], "251280")
        self.assertEqual(manquants, [])

    def test_separateurs_alternatifs_du_numero(self):
        for brut, attendu in [("26-03-47", "26_03_47"), ("26 03 47", "26_03_47"),
                              ("26.03.47", "26_03_47"), ("26–03–47", "26_03_47")]:
            with self.subTest(brut=brut):
                champs, _ = lecture_fiche.analyser(f"REF. CABINE {brut}")
                self.assertEqual(champs.get("numero"), attendu)

    def test_etiquette_abimee(self):
        """L'accent et le symbole du « N° » sautent souvent à la reconnaissance."""
        champs, manquants = lecture_fiche.analyser("N* DE CDE 251280\nREF CABINE 26_03_47")
        self.assertEqual(champs["chantier"], "251280")
        self.assertEqual(champs["numero"], "26_03_47")
        self.assertEqual(manquants, [])

    def test_lignes_parasites_ignorees(self):
        texte = ("STRUCTA INDUSTRIES\n\n|||\nREVENDEUR MYAH\n---\n"
                 "REF. CABINE 26_03_47\nN° DE CDE 251280\nPage 1/1\n")
        champs, manquants = lecture_fiche.analyser(texte)
        self.assertEqual(manquants, [])
        self.assertEqual(champs["numero"], "26_03_47")
        self.assertEqual(champs["revendeur"], "MYAH")

    def test_champs_essentiels_manquants_signales(self):
        champs, manquants = lecture_fiche.analyser("REVENDEUR MYAH\nCLIENT HAS\n")
        self.assertEqual(sorted(manquants), ["chantier", "numero"])
        self.assertNotIn("numero", champs)
        self.assertEqual(champs["revendeur"], "MYAH")

    def test_texte_vide(self):
        champs, manquants = lecture_fiche.analyser("")
        self.assertEqual(champs, {})
        self.assertEqual(sorted(manquants), ["chantier", "numero"])

    def test_numero_invalide_non_invente(self):
        """Mieux vaut ne rien renvoyer qu'un numéro fabriqué."""
        champs, manquants = lecture_fiche.analyser("REF. CABINE ZZ_YY_XX\nN° DE CDE 12\n")
        self.assertNotIn("numero", champs)
        self.assertNotIn("chantier", champs)
        self.assertEqual(sorted(manquants), ["chantier", "numero"])

    def test_chantier_a_cinq_chiffres_rejete(self):
        champs, _ = lecture_fiche.analyser("N° DE CDE 25128\n")
        self.assertNotIn("chantier", champs)

    def test_normalisation_des_accents(self):
        self.assertEqual(lecture_fiche.normaliser(" réf.  Cabiné "), "REF. CABINE")

    def test_valeur_avant_son_etiquette(self):
        """Cas réel : la valeur est détectée un peu plus haut que son étiquette.

        L'OCR rend alors « 26_03_47 » puis « REF. CABINE ». Le numéro était perdu.
        """
        texte = ("REVENDEUR MYAH\n251280\nN° DE CDE\n26_03_47\nREF. CABINE\n"
                 "QUATTRO\nCABINE\n")
        champs, manquants = lecture_fiche.analyser(texte)
        self.assertEqual(manquants, [])
        self.assertEqual(champs["numero"], "26_03_47")
        self.assertEqual(champs["chantier"], "251280")


class ReconstitutionLignesTest(APITestCase):
    """Regroupement des zones OCR en rangées de tableau."""

    @staticmethod
    def _zone(texte, x, y, h=30, largeur=200):
        return [[[x, y], [x + largeur, y], [x + largeur, y + h], [x, y + h]], texte, 0.99]

    def test_etiquette_et_valeur_sur_la_meme_rangee(self):
        """Même avec un décalage vertical de quelques pixels, la rangée reste entière."""
        zones = [
            self._zone("26_03_47", 470, 298),      # valeur, 4 px plus haut
            self._zone("REF. CABINE", 58, 302),    # étiquette
            self._zone("MYAH", 470, 42),
            self._zone("REVENDEUR", 58, 40),
        ]
        texte = ocr_fiche.reconstituer_lignes(zones)
        self.assertEqual(texte.splitlines(),
                         ["REVENDEUR MYAH", "REF. CABINE 26_03_47"])

    def test_rangees_distinctes_non_fusionnees(self):
        zones = [self._zone("REVENDEUR", 58, 40), self._zone("MYAH", 470, 40),
                 self._zone("CLIENT", 58, 132), self._zone("HAS", 470, 132)]
        self.assertEqual(ocr_fiche.reconstituer_lignes(zones).splitlines(),
                         ["REVENDEUR MYAH", "CLIENT HAS"])

    def test_ordre_gauche_droite_respecte(self):
        zones = [self._zone("HAS", 470, 40), self._zone("CLIENT", 58, 40)]
        self.assertEqual(ocr_fiche.reconstituer_lignes(zones), "CLIENT HAS")

    def test_zones_vides_ignorees(self):
        zones = [self._zone("  ", 58, 40), self._zone("CLIENT", 58, 40)]
        self.assertEqual(ocr_fiche.reconstituer_lignes(zones), "CLIENT")

    def test_aucune_zone(self):
        self.assertEqual(ocr_fiche.reconstituer_lignes([]), "")


class AnalyserFicheAPITest(APITestCase):
    def setUp(self):
        self.user = Utilisateur.objects.create_user(
            username="op", password="secret123", role=Utilisateur.ADMIN, nom="Testeur")
        self.client.force_authenticate(user=self.user)

    def test_analyse_par_api(self):
        r = self.client.post("/api/cabines/analyser-fiche/", {"texte": FICHE_LIGNES},
                             format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["champs"]["numero"], "26_03_47")
        self.assertEqual(r.data["champs"]["chantier"], "251280")
        self.assertEqual(r.data["manquants"], [])
        self.assertIsNone(r.data["cabine_existante"])

    def test_cabine_deja_connue_signalee(self):
        """Éviter le doublon : si la fiche désigne une cabine existante, on le dit."""
        from wms import services_cabines
        services_cabines.creer_cabine(numero="26_03_47", chantier="251280",
                                      utilisateur=self.user)
        r = self.client.post("/api/cabines/analyser-fiche/", {"texte": FICHE_LIGNES},
                             format="json")
        self.assertIsNotNone(r.data["cabine_existante"])
        self.assertEqual(r.data["cabine_existante"]["numero"], "26_03_47")

    def test_texte_vide_refuse(self):
        r = self.client.post("/api/cabines/analyser-fiche/", {"texte": "   "}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_analyse_ne_cree_rien(self):
        self.client.post("/api/cabines/analyser-fiche/", {"texte": FICHE_LIGNES},
                         format="json")
        self.assertEqual(Cabine.objects.count(), 0)

    def test_creation_avec_les_champs_de_la_fiche(self):
        r = self.client.post("/api/cabines/", {
            "numero": "26_03_47", "chantier": "251280", "modele": "QUATTRO",
            "revendeur": "MYAH", "client": "HAS", "tissu_bk": "A2419",
            "tissu_aq": "A2414", "fond_cabine": "VITRE"}, format="json")
        self.assertEqual(r.status_code, 201)
        c = Cabine.objects.get(numero="26_03_47")
        self.assertEqual(c.revendeur, "MYAH")
        self.assertEqual(c.client, "HAS")
        self.assertEqual(c.tissu_bk, "A2419")
        self.assertEqual(c.tissu_aq, "A2414")
        self.assertEqual(c.fond_cabine, "VITRE")
        self.assertEqual(c.modele, "QUATTRO")

    def test_authentification_requise(self):
        self.client.force_authenticate(user=None)
        r = self.client.post("/api/cabines/analyser-fiche/", {"texte": FICHE_LIGNES},
                             format="json")
        self.assertIn(r.status_code, (401, 403))


def _image_fiche():
    """Reproduit le tableau de la fiche papier, pour exercer la chaîne complète."""
    from PIL import Image, ImageDraw, ImageFont
    lignes = [("REVENDEUR", "MYAH"), ("CLIENT", "HAS"), ("N° DE CDE", "251280"),
              ("REF. CABINE", "26_03_47"), ("CABINE", "QUATTRO"),
              ("TISSUS BK", "A2419"), ("TISSUS AQ", "A2414"), ("FOND CABINE", "VITRE")]
    largeur, hauteur_ligne = 900, 92
    img = Image.new("RGB", (largeur, 80 + len(lignes) * hauteur_ligne), "white")
    d = ImageDraw.Draw(img)
    try:
        gras = ImageFont.truetype("arialbd.ttf", 38)
        normal = ImageFont.truetype("arial.ttf", 36)
    except OSError:                                    # poste sans les polices Arial
        gras = normal = ImageFont.load_default()
    for i, (libelle, valeur) in enumerate(lignes):
        y = 40 + i * hauteur_ligne
        d.rectangle([40, y, 420, y + hauteur_ligne], fill="#d9d9d9", outline="black", width=3)
        d.rectangle([420, y, 860, y + hauteur_ligne], outline="black", width=3)
        d.text((58, y + 26), libelle, fill="black", font=gras)
        d.text((470, y + 28), valeur, fill="black", font=normal)
    tampon = io.BytesIO()
    img.save(tampon, format="PNG")
    return tampon.getvalue()


class LirePhotoFicheTest(APITestCase):
    """Chaîne complète : photo → reconnaissance → analyse → champs."""

    def setUp(self):
        self.user = Utilisateur.objects.create_user(
            username="op", password="secret123", role=Utilisateur.ADMIN, nom="Testeur")
        self.client.force_authenticate(user=self.user)

    def test_photo_absente_refusee(self):
        r = self.client.post("/api/cabines/lire-fiche/", {}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_moteur_absent_signale_clairement(self):
        """Sans la dépendance optionnelle, l'API doit expliquer, pas tomber en 500."""
        with mock.patch.object(ocr_fiche, "disponible", return_value=False):
            fichier = SimpleUploadedFile("f.png", b"\x89PNG\r\n", content_type="image/png")
            r = self.client.post("/api/cabines/lire-fiche/", {"photo": fichier},
                                 format="multipart")
        self.assertEqual(r.status_code, 503)
        self.assertIn("requirements-ocr", " ".join(r.data["erreur"]))

    @unittest.skipUnless(ocr_fiche.disponible(),
                         "requirements-ocr.txt non installé sur ce poste")
    def test_image_illisible_refusee(self):
        # Sans le moteur, l'API répond 503 (« installez requirements-ocr ») et non
        # 400 : le test échouait sur toute installation standard, CI comprise, où
        # la dépendance optionnelle n'est justement pas installée.

        fichier = SimpleUploadedFile("f.png", b"pas une image", content_type="image/png")
        r = self.client.post("/api/cabines/lire-fiche/", {"photo": fichier},
                             format="multipart")
        self.assertEqual(r.status_code, 400)

    @unittest.skipUnless(ocr_fiche.disponible(),
                         "requirements-ocr.txt non installé sur ce poste")
    def test_lecture_reelle_de_la_fiche(self):
        fichier = SimpleUploadedFile("fiche.png", _image_fiche(), content_type="image/png")
        r = self.client.post("/api/cabines/lire-fiche/", {"photo": fichier},
                             format="multipart")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        champs = r.data["champs"]
        self.assertEqual(champs["numero"], "26_03_47")
        self.assertEqual(champs["chantier"], "251280")
        self.assertEqual(champs["modele"], "QUATTRO")
        self.assertEqual(champs["revendeur"], "MYAH")
        self.assertEqual(champs["client"], "HAS")
        self.assertEqual(champs["tissu_bk"], "A2419")
        self.assertEqual(champs["tissu_aq"], "A2414")
        self.assertEqual(champs["fond_cabine"], "VITRE")
        self.assertEqual(r.data["manquants"], [])
        self.assertEqual(Cabine.objects.count(), 0)   # la lecture ne crée rien

    @unittest.skipUnless(ocr_fiche.disponible(),
                         "requirements-ocr.txt non installé sur ce poste")
    def test_lecture_signale_une_cabine_deja_connue(self):
        from wms import services_cabines
        services_cabines.creer_cabine(numero="26_03_47", chantier="251280",
                                      utilisateur=self.user)
        fichier = SimpleUploadedFile("fiche.png", _image_fiche(), content_type="image/png")
        r = self.client.post("/api/cabines/lire-fiche/", {"photo": fichier},
                             format="multipart")
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.data["cabine_existante"])
        self.assertEqual(r.data["cabine_existante"]["numero"], "26_03_47")


class LecturesDegradees(unittest.TestCase):
    """Sorties d'OCR réellement rencontrées, du cliché propre au pire.

    Ces cas viennent d'un échec en exploitation : la fiche photographiée sur un
    écran d'ordinateur, de biais, revenait « n° de cabine non lu ». Deux causes
    ont été isolées et corrigées ; elles sont figées ici pour ne pas revenir.
    """

    def analyser(self, texte):
        return lecture_fiche.analyser(texte)[0]

    def test_tirets_bas_avales_par_l_ocr(self):
        """« 26_03_47 » rendu « 260347 » : les tirets bas sont fins, l'OCR les perd."""
        champs = self.analyser("N° DE CDE 251280\nREF. CABINE 260347")
        self.assertEqual(champs.get("numero"), "26_03_47")
        self.assertEqual(champs.get("chantier"), "251280")

    def test_valeur_avant_son_etiquette(self):
        """Photo de biais : les boîtes de l'OCR se croisent, la valeur sort d'abord."""
        champs = self.analyser("26_03_47 REF. CABINE\n251280 N° DE CDE")
        self.assertEqual(champs.get("numero"), "26_03_47")
        self.assertEqual(champs.get("chantier"), "251280")

    def test_les_deux_defauts_a_la_fois(self):
        champs = self.analyser("260347 REF. CABINE\n251280 N° DE CDE")
        self.assertEqual(champs.get("numero"), "26_03_47")

    def test_lignes_parasites_de_la_photo_d_ecran(self):
        """Le nom du fichier affiché à l'écran est photographié avec la fiche."""
        champs = self.analyser(
            "WhatsApp Image 2026-07-30 at 15.17.29.jpeg\nREVENDEUR MYAH\n"
            "CLIENT HAS\nN° DE CDE 251280\n| |\nREF. CABINE 26_03_47")
        self.assertEqual(champs.get("numero"), "26_03_47")
        self.assertEqual(champs.get("revendeur"), "MYAH")

    def test_six_chiffres_seuls_ne_font_pas_un_numero(self):
        """Le garde-fou du durcissement : sans étiquette de cabine, on n'invente rien.

        Le n° de commande compte six chiffres lui aussi. Accepter six chiffres
        n'importe où ferait passer une commande pour une référence de cabine —
        une cabine enregistrée sous un faux numéro est introuvable ensuite.
        """
        champs = self.analyser("N° DE CDE 251280\nCLIENT HAS")
        self.assertIsNone(champs.get("numero"))

    def test_texte_sans_rapport(self):
        self.assertIsNone(self.analyser("FACTURE 2026 TOTAL 1234.56 EUROS").get("numero"))
