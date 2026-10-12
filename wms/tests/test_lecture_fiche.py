"""Tests de la lecture de la fiche cabine papier (texte issu de l'OCR).

On ne cherche plus qu'UNE chose sur la fiche : le n° de cabine. Tout le reste —
chantier, modèle, revendeur, client, tissus, fond de cabine — vient du fichier
de production, qui est la source. Les relire sur une photo créait une seconde
version des mêmes informations, et quand les deux différaient personne ne savait
laquelle croire.

Ces tests portent donc sur deux choses, et la seconde est celle qui protège la
règle :

- le numéro est lu malgré le bruit réaliste (colonnes collées ou séparées,
  confusions 0/O et 1/I, étiquettes abîmées, lignes parasites, valeur détectée
  avant son étiquette) — un texte idéal ne prouverait rien ;
- les autres champs ne sont PAS lus, même quand la fiche les porte
  lisiblement. Un test qui se contenterait de vérifier le numéro laisserait
  revenir les sept autres sans rien signaler.
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
        self.assertNotIn("chantier", champs)
        self.assertNotIn("modele", champs)
        self.assertNotIn("revendeur", champs)
        self.assertNotIn("client", champs)
        self.assertNotIn("tissu_bk", champs)
        self.assertNotIn("tissu_aq", champs)
        self.assertNotIn("fond_cabine", champs)

    def test_colonnes_collees(self):
        champs, manquants = lecture_fiche.analyser(FICHE_LIGNES)
        self.assertEqual(manquants, [])
        self.assertEqual(champs["numero"], "26_03_47")
        self.assertNotIn("chantier", champs)
        self.assertNotIn("modele", champs)

    def test_cabine_ne_capture_pas_ref_cabine_ni_fond_cabine(self):
        """« CABINE » est contenu dans « REF. CABINE » et « FOND CABINE ».

        Sans traiter les étiquettes longues d'abord, le modèle vaudrait « 26_03_47 »
        ou « VITRE ».
        """
        champs, _ = lecture_fiche.analyser(FICHE_LIGNES)
        self.assertNotIn("modele", champs)
        self.assertEqual(champs["numero"], "26_03_47")
        self.assertNotIn("fond_cabine", champs)

    def test_confusion_lettres_chiffres_corrigee(self):
        """« 2G_O3_47 » et « 2S128O » : O pris pour 0, S pour 5."""
        texte = "REF. CABINE 26_O3_47\nN° DE CDE 2512BO\n"
        champs, manquants = lecture_fiche.analyser(texte)
        self.assertEqual(champs["numero"], "26_03_47")
        self.assertNotIn("chantier", champs)
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
        self.assertNotIn("chantier", champs)
        self.assertEqual(champs["numero"], "26_03_47")
        self.assertEqual(manquants, [])

    def test_lignes_parasites_ignorees(self):
        texte = ("STRUCTA INDUSTRIES\n\n|||\nREVENDEUR MYAH\n---\n"
                 "REF. CABINE 26_03_47\nN° DE CDE 251280\nPage 1/1\n")
        champs, manquants = lecture_fiche.analyser(texte)
        self.assertEqual(manquants, [])
        self.assertEqual(champs["numero"], "26_03_47")
        self.assertNotIn("revendeur", champs)

    def test_champs_essentiels_manquants_signales(self):
        champs, manquants = lecture_fiche.analyser("REVENDEUR MYAH\nCLIENT HAS\n")
        self.assertEqual(manquants, ["numero"])
        self.assertNotIn("numero", champs)
        self.assertNotIn("revendeur", champs)

    def test_texte_vide(self):
        champs, manquants = lecture_fiche.analyser("")
        self.assertEqual(champs, {})
        self.assertEqual(manquants, ["numero"])

    def test_numero_invalide_non_invente(self):
        """Mieux vaut ne rien renvoyer qu'un numéro fabriqué."""
        champs, manquants = lecture_fiche.analyser("REF. CABINE ZZ_YY_XX\nN° DE CDE 12\n")
        self.assertNotIn("numero", champs)
        self.assertNotIn("chantier", champs)
        self.assertEqual(manquants, ["numero"])

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
        self.assertNotIn("chantier", champs)


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


class LectureFicheAPITest(APITestCase):
    """Le contrat de `/lire-fiche/`, avec un moteur de reconnaissance simulé.

    Le texte « reconnu » est celui de la fiche : ce qui est vérifié ici, c'est
    ce que l'API en fait. La chaîne complète, moteur compris, est éprouvée plus
    bas quand `requirements-ocr.txt` est installé.
    """

    def setUp(self):
        self.user = Utilisateur.objects.create_user(
            username="op", password="secret123", role=Utilisateur.ADMIN, nom="Testeur")
        self.client.force_authenticate(user=self.user)
        for nom, valeur in (("disponible", True), ("lire_image", FICHE_LIGNES)):
            simulation = mock.patch.object(ocr_fiche, nom, return_value=valeur)
            self.lecture = simulation.start()
            self.addCleanup(simulation.stop)

    def lire(self):
        fichier = SimpleUploadedFile("fiche.png", b"\x89PNG\r\n", content_type="image/png")
        return self.client.post("/api/cabines/lire-fiche/", {"photo": fichier},
                                format="multipart")

    def test_seul_le_numero_est_rendu(self):
        r = self.lire()
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.assertEqual(r.data["champs"]["numero"], "26_03_47")
        # L'API ne renvoie QUE le numéro, même sur une fiche qui porte tout le
        # reste lisiblement : c'est ce qui empêche une seconde source de vérité
        # de revenir par la porte de l'API.
        self.assertEqual(list(r.data["champs"]), ["numero"])
        self.assertEqual(r.data["manquants"], [])
        self.assertIsNone(r.data["cabine_existante"])

    def test_cabine_deja_connue_signalee(self):
        """Éviter le doublon : si la fiche désigne une cabine existante, on le dit."""
        from wms import services_cabines
        services_cabines.creer_cabine(numero="26_03_47", chantier="251280",
                                      utilisateur=self.user)
        r = self.lire()
        self.assertIsNotNone(r.data["cabine_existante"])
        self.assertEqual(r.data["cabine_existante"]["numero"], "26_03_47")

    def test_photo_sans_texte_refusee(self):
        self.lecture.return_value = "   "
        self.assertEqual(self.lire().status_code, 400)

    def test_la_lecture_ne_cree_rien(self):
        self.lire()
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
        self.assertIn(self.lire().status_code, (401, 403))


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
        self.assertNotIn("chantier", champs)
        self.assertNotIn("modele", champs)
        self.assertNotIn("revendeur", champs)
        self.assertNotIn("client", champs)
        self.assertNotIn("tissu_bk", champs)
        self.assertNotIn("tissu_aq", champs)
        self.assertNotIn("fond_cabine", champs)
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
        self.assertNotIn("chantier", champs)

    def test_valeur_avant_son_etiquette(self):
        """Photo de biais : les boîtes de l'OCR se croisent, la valeur sort d'abord."""
        champs = self.analyser("26_03_47 REF. CABINE\n251280 N° DE CDE")
        self.assertEqual(champs.get("numero"), "26_03_47")
        self.assertNotIn("chantier", champs)

    def test_les_deux_defauts_a_la_fois(self):
        champs = self.analyser("260347 REF. CABINE\n251280 N° DE CDE")
        self.assertEqual(champs.get("numero"), "26_03_47")

    def test_lignes_parasites_de_la_photo_d_ecran(self):
        """Le nom du fichier affiché à l'écran est photographié avec la fiche."""
        champs = self.analyser(
            "WhatsApp Image 2026-07-30 at 15.17.29.jpeg\nREVENDEUR MYAH\n"
            "CLIENT HAS\nN° DE CDE 251280\n| |\nREF. CABINE 26_03_47")
        self.assertEqual(champs.get("numero"), "26_03_47")
        self.assertNotIn("revendeur", champs)

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


class LongueurDuDernierGroupe(unittest.TestCase):
    """Le rang de la cabine compte un à trois chiffres.

    Le dernier groupe était lu sur deux caractères exactement : « 25_49_400 »
    devenait « 25_49_40 », une AUTRE cabine bien réelle, que l'écran proposait
    aussitôt au rangement ou à la sortie. « 26_03_7 » n'était pas lu du tout.
    """

    def numero(self, texte):
        return lecture_fiche.analyser(texte)[0].get("numero")

    def test_trois_chiffres(self):
        self.assertEqual(self.numero("REF. CABINE 25_49_400\nCABINE QUATTRO"), "25_49_400")

    def test_un_chiffre(self):
        self.assertEqual(self.numero("REF. CABINE 26_03_7"), "26_03_7")

    def test_trois_chiffres_sur_la_ligne_suivante(self):
        self.assertEqual(self.numero("REF. CABINE\n25 49 400\nCABINE\nDUO"), "25_49_400")

    def test_tirets_avales_sept_chiffres(self):
        self.assertEqual(self.numero("REF. CABINE 2549400"), "25_49_400")

    def test_tirets_avales_cinq_chiffres(self):
        self.assertEqual(self.numero("REF. CABINE 26037"), "26_03_7")

    def test_quatre_chiffres_au_bout_ne_sont_pas_un_numero(self):
        """Mieux vaut ne rien lire que lire une autre cabine."""
        self.assertIsNone(self.numero("REF. CABINE 25_49_4000"))

    def test_numero_colle_a_un_mot_n_est_pas_devine(self):
        self.assertIsNone(self.numero("REF. CABINE 26_03_47QUATTRO"))

    def test_un_mot_de_lettres_confondables_n_est_pas_un_numero(self):
        """B, L, O, G, S se lisent 8, 1, 0, 6, 5 : « BLOGS » n'est pas 81_06_5."""
        self.assertIsNone(self.numero("REF. CABINE BLOGS"))
