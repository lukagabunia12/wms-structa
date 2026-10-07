"""Import du fichier de production : les cabines attendues.

Le fichier réel est un export Excel tenu à la main par la production — 2 392
lignes, 67 colonnes, et de vraies erreurs de saisie dedans. Ces tests reprennent
chacun des cas rencontrés dans ce fichier, en miniature :

- cinq lignes où un n° de chantier avait été recopié dans toutes les colonnes ;
- 123 lignes sans n° de cabine, identifiées seulement par « AF-3164 » ;
- 94 numéros « 25_49_400 », que le WMS refusait avant d'assouplir sa règle ;
- 110 chantiers « 251213-1 » : le chantier 251213, lot 1. Le WMS les stocke
  entiers depuis que le format accepte le lot ; ce qu'il refuse encore est ce
  qui n'a pas de sens comme chantier, et il l'annonce plutôt que de tronquer.

Chaque cas doit être **nommé** à l'écran, jamais avalé en silence : un import
qui annonce « 2 264 lignes » sans dire ce qu'il a laissé de côté ferait croire
le fichier complet.
"""
import io

import openpyxl
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APITestCase

from wms import services_cabines, services_import
from wms.models import (Cabine, CabineAttendue, MouvementCabine,
                        Utilisateur)

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

    def test_chantier_a_lots_stocke_entier(self):
        """« 251213-1 » est stocké tel quel, et ne devient jamais « 251213 ».

        Deux régressions se croisent ici. La première tronquait avant de valider :
        « 251213-1 » passait pour le chantier « 251213 » — un chantier qui existe,
        et qui n'est pas celui-là. La seconde était le refus pur et simple : le
        chantier restait vide et l'opérateur devait retaper à la main un numéro
        que le fichier donnait déjà, 110 fois sur 2 264 lignes.
        """
        rapport = services_import.importer(classeur([ligne(CHANTIER="251213-1")]),
                                           nom="production.xlsx")
        self.assertEqual(rapport["retenues"], 1)
        self.assertEqual(rapport["sans_chantier"], 0)

        attendue = CabineAttendue.objects.get(numero="26_02_49")
        self.assertEqual(attendue.chantier, "251213-1")
        self.assertEqual(attendue.chantier_brut, "251213-1")
        self.assertFalse(attendue.chantier_a_saisir)

    def test_formes_de_chantier_acceptees_et_refusees(self):
        """Le lot va de 1 à 99. Le reste n'est pas un chantier.

        « 251213-0 » est une faute de frappe : l'accepter créerait un lot fantôme
        à côté du vrai. Une référence fournisseur comme « AF-3164 » n'est pas un
        chantier non plus — elle a sa place dans `num_unique`, pas ici.
        """
        for valeur, attendu in [("251213", "251213"), ("251213-1", "251213-1"),
                                ("251213-12", "251213-12"), ("251213-0", ""),
                                ("251213-123", ""), ("25121", ""),
                                ("AF-3164", ""), ("251213 -1", "")]:
            with self.subTest(valeur=valeur):
                CabineAttendue.objects.all().delete()
                services_import.importer(classeur([ligne(CHANTIER=valeur)]),
                                         nom="production.xlsx")
                attendue = CabineAttendue.objects.get(numero="26_02_49")
                self.assertEqual(attendue.chantier, attendu)
                # Le brut est conservé dans tous les cas : c'est la seule trace
                # de ce que le classeur disait, et on le cherche.
                self.assertEqual(attendue.chantier_brut, valeur)

    def test_colonne_chantier_vide_compte_comme_a_saisir(self):
        """Une ligne sans chantier réclame la même saisie qu'une ligne illisible.

        Le compteur du rapport ne regardait que le brut non vide : une colonne
        CHANTIER vide n'apparaissait donc nulle part, ni dans le rapport ni sur
        l'écran d'entrée — et la création échouait sur un 400 sans que rien n'ait
        proposé de saisir le numéro.
        """
        rapport = services_import.importer(classeur([ligne(CHANTIER="")]),
                                           nom="production.xlsx")
        self.assertEqual(rapport["sans_chantier"], 1)
        attendue = CabineAttendue.objects.get(numero="26_02_49")
        self.assertEqual(attendue.chantier, "")
        self.assertEqual(attendue.chantier_brut, "")
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
    """L'import réécrit des milliers de cabines : sa case, et elle seule, l'ouvre."""

    def setUp(self):
        self.admin = Utilisateur.objects.create_user(
            username="chef", password="motdepasse123", role=Utilisateur.ADMIN)
        # Un opérateur avec TOUTES les cases cochées, sauf celle de l'import :
        # aucune autre ne doit l'ouvrir par la bande.
        self.operateur = Utilisateur.objects.create_user(
            username="cariste", password="motdepasse123", role=Utilisateur.OPERATEUR,
            **{f"droit_{d}": True for d in Utilisateur.DROITS if d != "production"})
        CabineAttendue.objects.create(numero="26_02_49", chantier="251314",
                                      modele="MODELE M")

    def test_un_operateur_ne_peut_pas_importer(self):
        self.client.force_authenticate(user=self.operateur)
        r = self.client.post("/api/cabines-attendues/analyser/",
                             {"fichier": classeur([ligne()])}, format="multipart")
        self.assertEqual(r.status_code, 403)
        self.assertIn("importer le fichier de production", str(r.data))

    def test_la_case_import_suffit(self):
        """Cochée seule, sur un opérateur : c'est la souplesse demandée."""
        responsable = Utilisateur.objects.create_user(
            username="planning", password="motdepasse123", role=Utilisateur.OPERATEUR,
            droit_production=True)
        self.client.force_authenticate(user=responsable)
        r = self.client.post("/api/cabines-attendues/importer/",
                             {"fichier": classeur([ligne(CABINE="26_03_02")])},
                             format="multipart")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.assertEqual(CabineAttendue.objects.get(numero="26_03_02").importe_par,
                         responsable)

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

class CreationHorsFichierTest(APITestCase):
    """Une cabine que la production n'annonce pas ne s'enregistre plus.

    Un opérateur qui a une cabine inconnue devant lui n'a pas de quoi inventer
    sa fiche. Un compte qui a la case « enregistrer une cabine absente du
    fichier de production » — un administrateur l'a d'office — peut passer
    outre, mais doit dire pourquoi : le motif part au journal avec son nom, et
    c'est la seule trace de l'exception.
    """

    def setUp(self):
        self.admin = Utilisateur.objects.create_user(
            username="chef", password="motdepasse123", role=Utilisateur.ADMIN)
        # Toutes les cases sauf celle de l'exception : importer le fichier ne
        # vaut pas passer outre.
        self.operateur = Utilisateur.objects.create_user(
            username="cariste", password="motdepasse123", role=Utilisateur.OPERATEUR,
            **{f"droit_{d}": True for d in Utilisateur.DROITS if d != "hors_fichier"})
        CabineAttendue.objects.create(numero="26_02_49", chantier="251314",
                                      modele="MODELE M", client="CNRS")

    # ---------------------------------------------------------------- annoncée
    def test_une_cabine_annoncee_entre_normalement(self):
        self.client.force_authenticate(user=self.operateur)
        r = self.client.post("/api/cabines/",
                             {"numero": "26_02_49", "chantier": "251314"},
                             format="json")
        self.assertEqual(r.status_code, 201, getattr(r, "data", None))

    # ------------------------------------------------------------ non annoncée
    def test_un_operateur_ne_peut_pas_creer_une_cabine_hors_fichier(self):
        self.client.force_authenticate(user=self.operateur)
        r = self.client.post("/api/cabines/",
                             {"numero": "99_99_99", "chantier": "251314"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        message = " ".join(r.data["erreur"])
        self.assertIn("fichier de production", message)
        # Le refus dit quelle case manque — et qu'un administrateur l'a.
        self.assertIn("absente du fichier de production", message)
        self.assertIn("administrateur", message)
        self.assertFalse(Cabine.objects.filter(numero="99_99_99").exists())

    def test_la_case_hors_fichier_ouvre_l_exception_avec_motif(self):
        chef = Utilisateur.objects.create_user(
            username="chef_quai", password="motdepasse123", role=Utilisateur.OPERATEUR,
            droit_cab_ranger=True, droit_hors_fichier=True)
        self.client.force_authenticate(user=chef)
        r = self.client.post("/api/cabines/",
                             {"numero": "99_99_98", "chantier": "251314"}, format="json")
        self.assertEqual(r.status_code, 400, "le motif reste exigé")
        r = self.client.post("/api/cabines/",
                             {"numero": "99_99_98", "chantier": "251314",
                              "motif_hors_fichier": "cabine d'exposition"}, format="json")
        self.assertEqual(r.status_code, 201, getattr(r, "data", None))
        mouvement = MouvementCabine.objects.get(cabine_numero="99_99_98",
                                                type=MouvementCabine.CREATION)
        self.assertEqual(mouvement.utilisateur, chef)

    def test_corriger_vers_un_numero_inconnu_suit_la_meme_regle(self):
        """Sans cela, entrer une cabine annoncée puis corriger son numéro vers un
        numéro que le fichier n'annonce pas enregistrait par la bande ce que
        l'entrée refuse."""
        correcteur = Utilisateur.objects.create_user(
            username="correcteur", password="motdepasse123", role=Utilisateur.OPERATEUR,
            droit_cab_ranger=True, droit_cab_corriger=True)
        self.client.force_authenticate(user=correcteur)
        r = self.client.post("/api/cabines/", {"numero": "26_02_49", "chantier": "251314"},
                             format="json")
        self.assertEqual(r.status_code, 201, getattr(r, "data", None))
        cabine_id = r.data["id"]
        r = self.client.patch(f"/api/cabines/{cabine_id}/", {"numero": "99_99_96"},
                              format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("absente du fichier de production", " ".join(r.data["erreur"]))
        self.assertEqual(Cabine.objects.get(pk=cabine_id).numero, "26_02_49")
        # Les autres corrections restent libres.
        r = self.client.patch(f"/api/cabines/{cabine_id}/", {"client": "CNRS Lyon"},
                              format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))

    def test_avec_la_case_la_correction_passe_et_le_journal_le_dit(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post("/api/cabines/", {"numero": "26_02_49", "chantier": "251314"},
                             format="json")
        r = self.client.patch(f"/api/cabines/{r.data['id']}/", {"numero": "99_99_95"},
                              format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        mouvement = MouvementCabine.objects.filter(type=MouvementCabine.CORRECTION).latest("date")
        self.assertIn("hors fichier de production", mouvement.note)

    def test_la_case_hors_fichier_seule_ne_fait_pas_entrer(self):
        """L'exception est une création : il faut aussi la case « entrer et ranger »."""
        seul = Utilisateur.objects.create_user(
            username="seul", password="motdepasse123", role=Utilisateur.OPERATEUR,
            droit_hors_fichier=True)
        self.client.force_authenticate(user=seul)
        r = self.client.post("/api/cabines/",
                             {"numero": "99_99_97", "chantier": "251314",
                              "motif_hors_fichier": "essai"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_un_motif_ne_suffit_pas_a_un_operateur(self):
        """Sans quoi la barrière se contournerait en remplissant un champ."""
        self.client.force_authenticate(user=self.operateur)
        r = self.client.post("/api/cabines/",
                             {"numero": "99_99_99", "chantier": "251314",
                              "motif_hors_fichier": "je sais ce que je fais"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Cabine.objects.filter(numero="99_99_99").exists())

    def test_un_administrateur_sans_motif_est_refuse(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post("/api/cabines/",
                             {"numero": "99_99_99", "chantier": "251314"},
                             format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("motif", " ".join(r.data["erreur"]).lower())
        self.assertFalse(Cabine.objects.filter(numero="99_99_99").exists())

    def test_un_motif_vide_ou_blanc_ne_compte_pas(self):
        self.client.force_authenticate(user=self.admin)
        for motif in ("", "   ", "\t"):
            r = self.client.post("/api/cabines/",
                                 {"numero": "99_99_99", "chantier": "251314",
                                  "motif_hors_fichier": motif}, format="json")
            self.assertEqual(r.status_code, 400, repr(motif))

    def test_un_administrateur_avec_motif_cree_et_le_journal_le_dit(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post("/api/cabines/",
                             {"numero": "99_99_99", "chantier": "251314",
                              "motif_hors_fichier": "cabine de salon, hors chantier"},
                             format="json")
        self.assertEqual(r.status_code, 201, getattr(r, "data", None))

        mouvement = MouvementCabine.objects.get(cabine_numero="99_99_99",
                                                type=MouvementCabine.CREATION)
        self.assertIn("hors fichier de production", mouvement.note)
        self.assertIn("cabine de salon", mouvement.note)
        self.assertEqual(mouvement.utilisateur, self.admin)

    def test_une_creation_annoncee_ne_porte_pas_la_mention(self):
        self.client.force_authenticate(user=self.admin)
        self.client.post("/api/cabines/",
                         {"numero": "26_02_49", "chantier": "251314"}, format="json")
        mouvement = MouvementCabine.objects.get(cabine_numero="26_02_49",
                                                type=MouvementCabine.CREATION)
        self.assertNotIn("hors fichier", mouvement.note)

    # -------------------------------------------------- avant le premier import
    def test_sans_aucun_fichier_importe_la_saisie_reste_libre(self):
        """Sur une installation neuve, refuser tout rendrait le WMS inutilisable.

        La règle s'arme avec le premier import, pas avant : sinon personne ne
        pourrait enregistrer la moindre cabine le jour de la mise en service, et
        rien à l'écran n'expliquerait pourquoi.
        """
        CabineAttendue.objects.all().delete()
        self.client.force_authenticate(user=self.operateur)
        r = self.client.post("/api/cabines/",
                             {"numero": "99_99_99", "chantier": "251314"},
                             format="json")
        self.assertEqual(r.status_code, 201, getattr(r, "data", None))

    def test_le_front_sait_si_la_regle_est_armee(self):
        self.client.force_authenticate(user=self.operateur)
        self.assertTrue(self.client.get("/api/referentiels-cabine/").data["fichier_production"])
        CabineAttendue.objects.all().delete()
        self.assertFalse(self.client.get("/api/referentiels-cabine/").data["fichier_production"])


class ChantierObligatoireTest(TestCase):
    """Aucune cabine n'entre en stock sans chantier, hors express/salon/occasion.

    La règle vit à trois endroits, volontairement : `Cabine.clean()` la porte en
    base, le serializer DRF la traduit en 400 sur le champ « chantier », et
    l'écran la vérifie avant d'envoyer. Ces tests ferment les deux premiers — le
    troisième est couvert par les contrôles d'interface.
    """

    def setUp(self):
        self.user = Utilisateur.objects.create_user(
            username="CHEF", password="chef1234", role=Utilisateur.ADMIN)
        self.client.force_login(self.user)

    def test_le_modele_refuse_une_normale_sans_chantier(self):
        with self.assertRaises(ValidationError) as bilan:
            Cabine(numero="30_01_01", chantier="", type_cabine=Cabine.NORMALE).save()
        self.assertIn("chantier", bilan.exception.message_dict)

    def test_le_modele_accepte_une_express_sans_chantier(self):
        Cabine(numero="30_01_02", chantier="", type_cabine=Cabine.EXPRESS).save()
        self.assertTrue(Cabine.objects.filter(numero="30_01_02").exists())

    def test_l_api_refuse_une_normale_sans_chantier(self):
        r = self.client.post("/api/cabines/", {"numero": "30_01_03", "chantier": "",
                                               "type_cabine": Cabine.NORMALE},
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("chantier", r.json())
        self.assertFalse(Cabine.objects.filter(numero="30_01_03").exists())

    def test_l_api_accepte_un_chantier_a_lot(self):
        r = self.client.post("/api/cabines/", {"numero": "30_01_04",
                                               "chantier": "251213-1",
                                               "type_cabine": Cabine.NORMALE},
                             content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content[:400])
        self.assertEqual(Cabine.objects.get(numero="30_01_04").chantier, "251213-1")

    def test_l_api_refuse_un_chantier_mal_forme(self):
        for mauvais in ["25121", "251213-0", "251213-123", "AF-3164", "251213 -1"]:
            with self.subTest(chantier=mauvais):
                r = self.client.post("/api/cabines/",
                                     {"numero": "30_02_01", "chantier": mauvais,
                                      "type_cabine": Cabine.NORMALE},
                                     content_type="application/json")
                self.assertEqual(r.status_code, 400, mauvais)
                self.assertFalse(Cabine.objects.filter(numero="30_02_01").exists())

    def test_le_journal_ecrit_le_chantier_a_lot_sans_le_tronquer(self):
        """`MouvementCabine.chantier` doit suivre la taille du champ d'origine.

        Il faisait 6 caractères quand `Cabine.chantier` en fait 9 : sur
        PostgreSQL, écrire « 251213-1 » au journal lève une erreur de base, et le
        mouvement échoue APRÈS que la cabine a bougé — l'état réel et le journal
        divergent, et c'est le journal qui fait foi.
        """
        cabine = services_cabines.creer_cabine(
            numero="30_03_01", chantier="251213-12", utilisateur=self.user)
        mouvement = cabine.historique.first()
        self.assertEqual(mouvement.chantier, "251213-12")

    def test_affecter_un_chantier_a_lot_a_une_express(self):
        cabine = services_cabines.creer_cabine(
            numero="30_03_02", chantier="", type_cabine=Cabine.EXPRESS,
            utilisateur=self.user)
        services_cabines.affecter_chantier(cabine=cabine, chantier="251297-2",
                                           utilisateur=self.user)
        cabine.refresh_from_db()
        self.assertEqual(cabine.chantier, "251297-2")

    def test_le_referentiel_annonce_la_forme_attendue(self):
        """L'écran ne réécrit pas la règle : il la lit.

        Quatre écrans annonçaient « 6 chiffres » en dur. Le jour où le lot a été
        accepté, aucun ne l'a su.
        """
        r = self.client.get("/api/referentiels-cabine/")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["aide_chantier"], Cabine.AIDE_CHANTIER)
        self.assertEqual(d["taille_chantier"], Cabine.TAILLE_CHANTIER)
