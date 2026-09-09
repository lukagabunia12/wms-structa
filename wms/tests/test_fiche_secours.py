"""Le n° de cabine doit ressortir même quand l'étiquette n'est pas reconnue.

Sur une photo prise de biais, mal éclairée ou pliée, l'OCR perd régulièrement
« REF. CABINE » alors qu'il lit parfaitement « 26_03_47 » à côté. Sans
rattrapage, l'écran annonçait « n° de cabine non lu » et renvoyait l'opérateur
à sa photo — alors que le numéro était sous ses yeux dans le texte reconnu.
"""
from django.test import SimpleTestCase

from wms.lecture_fiche import analyser


class NumeroDeSecoursTest(SimpleTestCase):
    def test_numero_lu_sans_son_etiquette(self):
        champs, _ = analyser("REVENDEUR MYAH\nCLIENT HAS\n26_03_47\nCABINE QUATTRO")
        self.assertEqual(champs["numero"], "26_03_47")

    def test_separateurs_varies(self):
        for brut in ("26-03-47", "26 03 47", "26.03.47"):
            with self.subTest(brut=brut):
                champs, _ = analyser(f"CLIENT HAS\n{brut}\nCABINE QUATTRO")
                self.assertEqual(champs["numero"], "26_03_47")

    def test_confusions_ocr_corrigees(self):
        champs, _ = analyser("CLIENT HAS\n2G_O3_47\n")
        self.assertEqual(champs.get("numero"), "26_03_47")

    def test_le_numero_de_commande_ne_passe_pas_pour_une_cabine(self):
        """Six chiffres collés ne suffisent pas : ce serait la commande."""
        champs, _ = analyser("REVENDEUR MYAH\n251280\nCLIENT HAS")
        self.assertNotIn("numero", champs)

    def test_une_commande_mal_segmentee_est_ignoree(self):
        champs, _ = analyser("N° DE CDE 25 12 80\nCLIENT HAS")
        self.assertNotIn("numero", champs)

    def test_l_etiquette_reste_prioritaire(self):
        """Quand l'étiquette est lue, c'est elle qui décide — pas le rattrapage."""
        champs, _ = analyser("99_99_99\nREF. CABINE 26_03_47\n")
        self.assertEqual(champs["numero"], "26_03_47")

    def test_le_rattrapage_ne_casse_pas_une_fiche_complete(self):
        """Une fiche qui porte tout ne rend QUE le numéro.

        Le reste vient du fichier de production : le relire ici créerait une
        seconde version des mêmes informations.
        """
        texte = ("REVENDEUR MYAH\nCLIENT HAS\nN° DE CDE 251280\n"
                 "REF. CABINE 26_03_47\nCABINE QUATTRO\nTISSUS BK A2419")
        champs, manquants = analyser(texte)
        self.assertEqual(champs["numero"], "26_03_47")
        self.assertEqual(list(champs), ["numero"])
        self.assertEqual(manquants, [])
