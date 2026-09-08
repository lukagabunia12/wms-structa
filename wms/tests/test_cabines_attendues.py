"""Import du fichier de production : les cabines attendues.

Le fichier réel est un export Excel tenu à la main par la production — 2 392
lignes, 67 colonnes, et de vraies erreurs de saisie dedans. Ces tests reprennent
chacun des cas rencontrés dans ce fichier, en miniature :

- cinq lignes où un n° de chantier avait été recopié dans toutes les colonnes ;
- 123 lignes sans n° de cabine, identifiées seulement par « AF-3164 » ;
- 94 numéros « 25_49_400 », que le WMS refusait avant d'assouplir sa règle ;
- 110 chantiers « 251213-1 », que le champ à 6 chiffres ne peut pas stocker.

Chaque cas doit être **nommé** à l'écran, jamais avalé en silence : un import
qui annonce « 2 264 lignes » sans dire ce qu'il a laissé de côté ferait croire
le fichier complet.
"""
import io

import openpyxl
from rest_framework.test import APITestCase

from wms import services_import
from wms.models import Cabine, CabineAttendue, Utilisateur

#: Les en-têtes du vrai fichier, dans l'ordre, réduites à ce que les tests
#: utilisent. La casse et l'accent de « Semaine prod estimée » sont ceux du
#: fichier : c'est justement ce que la normalisation doit absorber.
ENTETES = ["CHANTIER", "SEMAINE PRODUCTION", "JOUR", "CABINE", "NUM UNIQUE",
           "GAMME", "MODELE", "QUANTITE", "TISSUS BK", "TISSUS AQ", "Moquette",
           "Fond", "COL", "Revendeur", "Client", "Semaine prod estimée",
           "MONTANT NET PRODUIT"]

LIGNE_TYPE = [251314, "S02", "JEUDI", "26_02_49", 1133, "COCON", "MODELE M", 1,
              "A2411", "A2411", "M1", 1, "COC", "UGAP", "CNRS", "S02", 4820.5]


def classeur(lignes, entetes=None):
    """Fabrique un .xlsx en mémoire. Rien n'est écrit sur le disque."""
    livre = openpyxl.Workbook()
    feuille = livre.active
    feuille.append(entetes if entetes is not None else ENTETES)
    for ligne in lignes:
        feuille.append(ligne)
    tampon = io.BytesIO()
    livre.save(tampon)
    tampon.seek(0)
    tampon.name = "production.xlsx"
    return tampon


def ligne(**remplacements):
    """La ligne type, avec les colonnes qu'on veut changer."""
    valeurs = list(LIGNE_TYPE)
    for entete, valeur in remplacements.items():
        valeurs[ENTETES.index(entete)] = valeur
    return valeurs


class ServiceImportTest(APITestCase):
    def test_une_ligne_valide_entre_avec_ses_champs(self):
        rapport = services_import.importer(classeur([ligne()]), nom="production.xlsx")
        self.assertEqual(rapport["retenues"], 1)
        self.assertEqual(rapport["nouvelles"], 1)
        self.assertEqual(rapport["erreurs"], [])

        attendue = CabineAttendue.objects.get(numero="26_02_49")
        self.assertEqual(attendue.chantier, "251314")
        self.assertEqual(attendue.num_unique, "1133")
        self.assertEqual(attendue.gamme, "COCON")
        self.assertEqual(attendue.modele, "MODELE M")
        self.assertEqual(attendue.tissu_bk, "A2411")
        self.assertEqual(attendue.client, "CNRS")
        self.assertEqual(attendue.revendeur, "UGAP")
        self.assertEqual(attendue.fichier, "production.xlsx")

    def test_le_montant_net_produit_n_est_jamais_importe(self):
        """La seule colonne volontairement jetée. L'entrepôt n'a pas à voir les prix."""
        services_import.importer(classeur([ligne()]), nom="production.xlsx")
        attendue = CabineAttendue.objects.get(numero="26_02_49")
        self.assertNotIn("MONTANT NET PRODUIT", attendue.specifications)
        self.assertNotIn("4820", str(attendue.specifications))

    def test_les_colonnes_hors_correspondance_sont_conservees(self):
        services_import.importer(classeur([ligne()]), nom="production.xlsx")
        specs = CabineAttendue.objects.get(numero="26_02_49").specifications
        self.assertEqual(specs["MOQUETTE"], "M1")
        self.assertEqual(specs["COL"], "COC")

    def test_entetes_accentuees_et_en_minuscules_reconnues(self):
        """« Semaine prod estimée » et « SEMAINE PROD ESTIMEE » sont la même colonne."""
        services_import.importer(classeur([ligne()]), nom="production.xlsx")
        self.assertEqual(CabineAttendue.objects.get(numero="26_02_49").semaine_estimee,
                         "S02")

    def test_numero_a_trois_chiffres_accepte(self):
        """Les 94 lignes « 25_49_400 » : une semaine peut dépasser 99 cabines."""
        rapport = services_import.importer(classeur([ligne(CABINE="25_49_400")]),
                                           nom="production.xlsx")
        self.assertEqual(rapport["retenues"], 1)
        self.assertTrue(CabineAttendue.objects.filter(numero="25_49_400").exists())

    def test_ligne_sans_numero_refusee_et_nommee(self):
        """Les 123 lignes identifiées seulement par « AF-3164 »."""
        rapport = services_import.analyser(
            classeur([ligne(CABINE=None, **{"NUM UNIQUE": "AF-3164"})]))
        self.assertEqual(rapport["retenues"], 0)
        self.assertEqual(len(rapport["erreurs"]), 1)
        erreur = rapport["erreurs"][0]
        self.assertEqual(erreur["ligne"], 2)
        self.assertIn("pas de n° de cabine", erreur["motif"])
        # L'indice permet de retrouver la ligne dans le classeur.
        self.assertEqual(erreur["indice"], "AF-3164")

    def test_numero_hors_format_refuse_avec_la_valeur_lue(self):
        rapport = services_import.analyser(classeur([ligne(CABINE="26/03/33")]))
        self.assertEqual(rapport["retenues"], 0)
        self.assertEqual(rapport["erreurs"][0]["numero"], "26/03/33")
        self.assertIn("hors format", rapport["erreurs"][0]["motif"])

    def test_ligne_ecrasee_par_un_collage_est_diagnostiquee(self):
        """Les cinq lignes 109-113 du fichier réel.

        Un collage a recouvert sept colonnes d'un coup : CABINE, JOUR, GAMME…
        portent toutes le n° de chantier de la ligne. Dire « hors format » est
        vrai mais inutile — on cherche alors une faute de frappe qui n'existe
        pas. Le message nomme la cause.
        """
        rapport = services_import.analyser(
            classeur([ligne(CHANTIER=251280, CABINE=251280, JOUR=251280,
                            GAMME=251280, MODELE=251280)]))
        self.assertEqual(rapport["retenues"], 0)
        motif = rapport["erreurs"][0]["motif"]
        self.assertIn("251280", motif)
        self.assertIn("chantier de cette même ligne", motif)
        self.assertIn("écrasées", motif)

    def test_un_numero_hors_format_qui_n_est_pas_le_chantier_garde_l_autre_message(self):
        """Sans quoi toute erreur de format serait attribuée à un collage."""
        rapport = services_import.analyser(
            classeur([ligne(CHANTIER=251280, CABINE="26_03_3333")]))
        self.assertIn("hors format", rapport["erreurs"][0]["motif"])
        self.assertNotIn("écrasées", rapport["erreurs"][0]["motif"])

    def test_numero_en_double_dans_le_fichier_refuse_a_la_seconde_ligne(self):
        rapport = services_import.analyser(classeur([ligne(), ligne()]))
        self.assertEqual(rapport["retenues"], 1)
        self.assertEqual(len(rapport["erreurs"]), 1)
        self.assertEqual(rapport["erreurs"][0]["ligne"], 3)
        self.assertIn("ligne 2", rapport["erreurs"][0]["motif"])

    def test_chantier_a_lots_conserve_sans_etre_tronque(self):
        """« 251213-1 » ne devient PAS « 251213 ».

        Le champ du WMS n'accepte que 6 chiffres. La première version de ce code
        tronquait avant de valider : « 251213-1 » passait pour le chantier
        « 251213 » — un chantier qui existe, et qui n'est pas celui-là.
        """
        rapport = services_import.importer(classeur([ligne(CHANTIER="251213-1")]),
                                           nom="production.xlsx")
        self.assertEqual(rapport["retenues"], 1)
        self.assertEqual(rapport["sans_chantier"], 1)

        attendue = CabineAttendue.objects.get(numero="26_02_49")
        self.assertEqual(attendue.chantier, "")
        self.assertEqual(attendue.chantier_brut, "251213-1")
        self.assertTrue(attendue.chantier_a_saisir)

    def test_reimporter_le_meme_fichier_ne_double_rien(self):
        services_import.importer(classeur([ligne()]), nom="production.xlsx")
        rapport = services_import.importer(classeur([ligne()]), nom="production.xlsx")
        self.assertEqual(CabineAttendue.objects.count(), 1)
        self.assertEqual(rapport["nouvelles"], 0)
        self.assertEqual(rapport["modifiees"], 0)
        self.assertEqual(rapport["inchangees"], 1)

    def test_une_caracteristique_qui_change_est_signalee_puis_mise_a_jour(self):
        services_import.importer(classeur([ligne()]), nom="v1.xlsx")
        rapport = services_import.analyser(classeur([ligne(MODELE="MODELE L")]))
        self.assertEqual(rapport["modifiees"], 1)
        self.assertEqual(rapport["nouvelles"], 0)

        services_import.importer(classeur([ligne(MODELE="MODELE L")]), nom="v2.xlsx")
        self.assertEqual(CabineAttendue.objects.get(numero="26_02_49").modele,
                         "MODELE L")

    def test_un_import_n_efface_jamais_ce_qui_manque_au_fichier(self):
        """Rien ne dit qu'un fichier est complet : une ligne filtrée dans Excel ne
        doit pas faire disparaître une spécification déjà en base."""
        services_import.importer(classeur([ligne(), ligne(CABINE="26_02_50")]),
                                 nom="complet.xlsx")
        rapport = services_import.importer(classeur([ligne()]), nom="partiel.xlsx")
        self.assertEqual(rapport["absentes_du_fichier"], 1)
        self.assertEqual(CabineAttendue.objects.count(), 2)
        self.assertTrue(CabineAttendue.objects.filter(numero="26_02_50").exists())

    def test_analyser_n_ecrit_rien(self):
        services_import.analyser(classeur([ligne()]))
        self.assertEqual(CabineAttendue.objects.count(), 0)

    def test_fichier_sans_colonne_cabine_refuse_en_entier(self):
        entetes = [e for e in ENTETES if e != "CABINE"]
        with self.assertRaises(services_import.ErreurImport) as leve:
            services_import.analyser(classeur([], entetes=entetes))
        self.assertIn("CABINE", str(leve.exception))

    def test_fichier_qui_n_est_pas_un_classeur(self):
        faux = io.BytesIO(b"ceci n'est pas un xlsx")
        faux.name = "faux.xlsx"
        with self.assertRaises(services_import.ErreurImport):
            services_import.analyser(faux)

    def test_lignes_vides_du_bas_de_feuille_ignorees(self):
        rapport = services_import.analyser(
            classeur([ligne(), [None] * len(ENTETES), [None] * len(ENTETES)]))
        self.assertEqual(rapport["lignes"], 1)
        self.assertEqual(rapport["retenues"], 1)


class DroitsImportTest(APITestCase):
    """L'import réécrit des milliers de cabines : administrateurs seulement."""

    def setUp(self):
        self.admin = Utilisateur.objects.create_user(
            username="chef", password="motdepasse123", role=Utilisateur.ADMIN)
        # Un opérateur avec TOUS les droits fins cochés : la barrière ne doit pas
        # dépendre d'une case, sinon elle finirait cochée « pour débloquer ».
        self.operateur = Utilisateur.objects.create_user(
            username="cariste", password="motdepasse123", role=Utilisateur.OPERATEUR,
            droit_cab=True, droit_ref=True, droit_data=True, droit_mvt=True)
        CabineAttendue.objects.create(numero="26_02_49", chantier="251314",
                                      modele="MODELE M")

    def test_un_operateur_ne_peut_pas_importer(self):
        self.client.force_authenticate(user=self.operateur)
        r = self.client.post("/api/cabines-attendues/analyser/",
                             {"fichier": classeur([ligne()])}, format="multipart")
        self.assertEqual(r.status_code, 403)
        self.assertIn("administrateur", str(r.data).lower())

    def test_un_visiteur_anonyme_est_refuse(self):
        r = self.client.post("/api/cabines-attendues/importer/",
                             {"fichier": classeur([ligne()])}, format="multipart")
        self.assertIn(r.status_code, (401, 403))

    def test_l_administrateur_importe(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post("/api/cabines-attendues/importer/",
                             {"fichier": classeur([ligne(CABINE="26_03_01")])},
                             format="multipart")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.assertEqual(r.data["importees"], 1)
        attendue = CabineAttendue.objects.get(numero="26_03_01")
        self.assertEqual(attendue.importe_par, self.admin)

    def test_la_lecture_reste_ouverte_a_l_operateur(self):
        """C'est elle qui pré-remplit l'écran d'entrée : la fermer viderait la
        fonctionnalité de son intérêt."""
        self.client.force_authenticate(user=self.operateur)
        r = self.client.get("/api/cabines-attendues/26_02_49/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["modele"], "MODELE M")

    def test_le_rapport_ne_traverse_pas_les_lignes_preparees(self):
        """`prepare` porte 2 000 lignes : inutile et lourd côté réseau."""
        self.client.force_authenticate(user=self.admin)
        r = self.client.post("/api/cabines-attendues/analyser/",
                             {"fichier": classeur([ligne()])}, format="multipart")
        self.assertNotIn("prepare", r.data)

    def test_un_csv_est_refuse_avec_une_phrase_utile(self):
        self.client.force_authenticate(user=self.admin)
        faux = io.BytesIO(b"CHANTIER;CABINE\n251314;26_02_49\n")
        faux.name = "liste.csv"
        r = self.client.post("/api/cabines-attendues/analyser/", {"fichier": faux},
                             format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn(".xlsx", " ".join(r.data["erreur"]))

    def test_sans_fichier(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post("/api/cabines-attendues/analyser/", {}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_moi_annonce_le_niveau_administrateur(self):
        for utilisateur, attendu in ((self.admin, True), (self.operateur, False)):
            self.client.force_authenticate(user=utilisateur)
            r = self.client.get("/api/moi/")
            self.assertEqual(r.data["administrateur"], attendu, utilisateur.username)


class NumeroAssoupliTest(APITestCase):
    """Le dernier groupe du numéro passe de 2 à 1-3 chiffres."""

    def setUp(self):
        self.admin = Utilisateur.objects.create_user(
            username="chef", password="motdepasse123", role=Utilisateur.ADMIN)
        self.client.force_authenticate(user=self.admin)

    def test_trois_chiffres_acceptes_par_l_api(self):
        r = self.client.post("/api/cabines/",
                             {"numero": "25_49_400", "chantier": "251213"},
                             format="json")
        self.assertEqual(r.status_code, 201, getattr(r, "data", None))
        self.assertTrue(Cabine.objects.filter(numero="25_49_400").exists())

    def test_quatre_chiffres_toujours_refuses(self):
        r = self.client.post("/api/cabines/",
                             {"numero": "25_49_4000", "chantier": "251213"},
                             format="json")
        self.assertEqual(r.status_code, 400)

    def test_les_deux_premiers_groupes_restent_stricts(self):
        for mauvais in ("2_49_40", "251_49_40", "25_4_40"):
            r = self.client.post("/api/cabines/",
                                 {"numero": mauvais, "chantier": "251213"},
                                 format="json")
            self.assertEqual(r.status_code, 400, mauvais)
