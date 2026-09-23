"""Vider le stock : dans l'administration, derrière trois phrases, avec filet.

L'opération était un onglet de l'application, dans le menu « Référentiel »,
entre les étiquettes et le fichier de production. Un bouton permanent, à portée
de doigt des gestes quotidiens, qui efface l'entrepôt. Elle est maintenant dans
`/admin` : second mot de passe, trois phrases à recopier, et une sauvegarde
écrite avant le premier effacement.

Les trois phrases ne sont pas trois fois la même barrière — c'est pour cela
qu'elles sont testées séparément :

1. « confirmer » dit qu'on fait bien CE geste ;
2. la date du jour dit qu'on est dans la bonne fenêtre : un onglet laissé
   ouvert la veille, une capture d'écran ou une requête rejouée ne passent plus ;
3. la phrase d'engagement est trop longue pour être tapée distraitement.

Et le vrai filet, vérifié ici comme le reste : la sauvegarde se RECHARGE. Une
sauvegarde qu'on n'a jamais rechargée n'est pas une sauvegarde, c'est un
fichier.
"""
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from wms import services_cabines
from wms.models import (Cabine, CabineAttendue, Emplacement, ModeleCabine,
                        MouvementCabine, Occupation, Utilisateur, Zone)

PHRASE = "Oui je suis d'accord et je comprends"


class BaseRemiseAZero(TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)
        # `is_staff` ouvre la porte de l'administration ; `role=admin` ouvre
        # celle-ci. Les deux sont nécessaires, et le second essai le prouve.
        self.admin = Utilisateur.objects.create_user(
            username="chef", password="secret123", role=Utilisateur.ADMIN,
            nom="Chef L.", is_staff=True)
        self.client.force_login(self.admin)
        self.zone = Zone.objects.create(nom="Rack A", ordre=1)
        self.emp = Emplacement.objects.create(code="A001", zone_cabine=self.zone)
        ModeleCabine.objects.update_or_create(
            cle="DUO", defaults={"nom": "DUO", "grand": False})
        CabineAttendue.objects.create(numero="00_00_01", modele="DUO", chantier="000123")
        self.cab = services_cabines.creer_cabine(
            numero="00_00_01", chantier="000123", modele="DUO", utilisateur=self.admin)
        services_cabines.ranger(cabine=self.cab, emplacement=self.emp,
                                place=Occupation.GAUCHE, utilisateur=self.admin)
        self.url = reverse("admin:wms_cabine_remise_a_zero")

    def phrases(self, **remplacements):
        """Les trois phrases exactes, dont on peut fausser celle qu'on veut."""
        exactes = {
            "confirmation": "confirmer",
            "date_du_jour": f"{timezone.localdate():%d/%m/%Y}",
            "engagement": PHRASE,
        }
        exactes.update(remplacements)
        return exactes

    def vider(self, **remplacements):
        with override_settings(BASE_DIR=self.dossier.name):
            return self.client.post(self.url, self.phrases(**remplacements))

    def sauvegardes(self):
        return sorted(Path(self.dossier.name).glob("sauvegardes/*.json"))


class TroisPhrasesTest(BaseRemiseAZero):
    def test_la_page_annonce_ce_qui_part_et_ce_qui_reste_sans_rien_effacer(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["etat"]["cabines"], 1)
        self.assertEqual(r.context["etat"]["rangees"], 1)
        self.assertEqual(r.context["etat"]["conserves"]["emplacements"], 1)
        self.assertEqual(Cabine.objects.count(), 1, "regarder n'efface rien")

    def test_les_trois_phrases_exactes_vident_le_stock(self):
        r = self.vider()
        self.assertEqual(r.status_code, 302, "on repart sur la page, vidée")
        self.assertEqual(Cabine.objects.count(), 0)
        self.assertEqual(MouvementCabine.objects.count(), 0)
        # Les occupations partent avec les cabines : sans cela la place
        # resterait réservée par une cabine qui n'existe plus.
        self.assertEqual(Occupation.objects.count(), 0)

    def test_sans_le_mot_confirmer_rien_n_est_efface(self):
        r = self.vider(confirmation="")
        self.assertEqual(r.status_code, 200)
        self.assertIn("confirmation", r.context["manques"])
        self.assertEqual(Cabine.objects.count(), 1)

    def test_avec_la_date_d_hier_rien_n_est_efface(self):
        """C'est la phrase qui protège d'un onglet resté ouvert la veille."""
        hier = timezone.localdate() - timezone.timedelta(days=1)
        r = self.vider(date_du_jour=f"{hier:%d/%m/%Y}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("date_du_jour", r.context["manques"])
        # Le refus donne la date attendue : sans elle on essaie trois formats.
        self.assertIn(f"{timezone.localdate():%d/%m/%Y}",
                      r.context["manques"]["date_du_jour"])
        self.assertEqual(Cabine.objects.count(), 1)

    def test_une_phrase_d_engagement_approximative_ne_passe_pas(self):
        r = self.vider(engagement="oui d'accord")
        self.assertEqual(r.status_code, 200)
        self.assertIn("engagement", r.context["manques"])
        self.assertEqual(Cabine.objects.count(), 1)

    def test_les_trois_manques_sont_signales_ensemble(self):
        """Corriger une phrase pour découvrir la suivante userait la patience,
        et c'est ainsi qu'on finit par tout écrire sur un post-it."""
        r = self.vider(confirmation="x", date_du_jour="x", engagement="x")
        self.assertEqual(set(r.context["manques"]),
                         {"confirmation", "date_du_jour", "engagement"})

    def test_la_forme_est_tolerante_le_fond_ne_l_est_pas(self):
        """Majuscules, accents, apostrophe typographique, espaces en trop.

        Refuser « Confirmer » pour une majuscule ferait retaper trois fois sans
        comprendre. Le garde-fou est la lecture de la phrase, pas sa casse.
        """
        r = self.vider(confirmation="  Confirmer ",
                       date_du_jour=f"{timezone.localdate():%Y-%m-%d}",
                       engagement="OUI JE SUIS D’ACCORD ET JE COMPRENDS")
        self.assertEqual(r.status_code, 302, "ces trois saisies sont correctes")
        self.assertEqual(Cabine.objects.count(), 0)


class SauvegardeTest(BaseRemiseAZero):
    def test_une_sauvegarde_est_ecrite_avant_l_effacement(self):
        self.vider()
        fichiers = self.sauvegardes()
        self.assertEqual(len(fichiers), 1, "un fichier, daté, et un seul")
        self.assertIn("remise-a-zero_", fichiers[0].name)

    def test_la_sauvegarde_contient_la_cabine_sa_position_et_son_journal(self):
        self.vider()
        contenu = json.loads(self.sauvegardes()[0].read_text(encoding="utf-8"))
        modeles = {objet["model"] for objet in contenu}
        self.assertIn("wms.cabine", modeles)
        self.assertIn("wms.occupation", modeles)
        self.assertIn("wms.mouvementcabine", modeles)
        numeros = [o["fields"]["numero"] for o in contenu if o["model"] == "wms.cabine"]
        self.assertEqual(numeros, ["00_00_01"])

    def test_la_sauvegarde_se_RECHARGE(self):
        """La preuve qui compte. Une sauvegarde jamais rechargée est un fichier."""
        self.vider()
        self.assertEqual(Cabine.objects.count(), 0)

        call_command("loaddata", str(self.sauvegardes()[0]), verbosity=0)

        self.assertEqual(Cabine.objects.count(), 1)
        revenue = Cabine.objects.get(numero="00_00_01")
        self.assertEqual(revenue.chantier, "000123")
        # Et elle est revenue À SA PLACE, pas seulement dans la liste.
        self.assertEqual(revenue.position, "A001·G")
        self.assertGreaterEqual(MouvementCabine.objects.count(), 2)

    def test_rien_n_est_efface_si_la_sauvegarde_echoue(self):
        """L'ordre n'est pas négociable : le fichier d'abord, l'effacement après.

        L'inverse laisserait une base vide et pas de fichier — le pire des deux
        mondes, et celui qu'on ne découvre qu'au moment de vouloir revenir.
        """
        with self.assertRaises(OSError):
            services_cabines.vider_le_stock(
                utilisateur=self.admin,
                dossier="/proc/impossible/sauvegardes")
        self.assertEqual(Cabine.objects.count(), 1)
        self.assertEqual(MouvementCabine.objects.count(), 2)


class CeQuiSurvitTest(BaseRemiseAZero):
    def test_l_entrepot_les_comptes_et_le_fichier_de_production_restent(self):
        """Effacer le fichier de production obligerait à réimporter deux mille
        lignes avant de pouvoir entrer la première cabine."""
        avant = {
            "emplacements": Emplacement.objects.count(),
            "zones": Zone.objects.count(),
            "comptes": Utilisateur.objects.count(),
            "attendues": CabineAttendue.objects.count(),
            "modeles": ModeleCabine.objects.count(),
        }
        self.vider()
        # Comparé À CE QU'IL Y AVAIT, pas à un nombre écrit d'avance : les
        # réglages de modèle sont semés par une migration, et fixer leur
        # nombre ici ferait échouer cet essai le jour où on en ajoute un.
        self.assertEqual(Emplacement.objects.count(), avant["emplacements"])
        self.assertEqual(Zone.objects.count(), avant["zones"])
        self.assertEqual(Utilisateur.objects.count(), avant["comptes"])
        self.assertEqual(CabineAttendue.objects.count(), avant["attendues"])
        self.assertEqual(ModeleCabine.objects.count(), avant["modeles"])
        self.assertTrue(avant["attendues"], "le fichier de production doit être peuplé")

    def test_l_emplacement_est_libre_tout_de_suite_apres(self):
        """La preuve utile : on doit pouvoir ranger au même endroit dans la foulée."""
        self.vider()
        CabineAttendue.objects.create(numero="00_00_02", modele="DUO", chantier="000124")
        neuve = services_cabines.creer_cabine(
            numero="00_00_02", chantier="000124", modele="DUO", utilisateur=self.admin)
        services_cabines.ranger(cabine=neuve, emplacement=self.emp,
                                place=Occupation.GAUCHE, utilisateur=self.admin)
        self.assertEqual(neuve.position, "A001·G")

    def test_vider_une_base_deja_vide_ne_casse_rien(self):
        self.vider()
        r = self.vider()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(self.sauvegardes()), 2, "chaque geste laisse sa trace")


class QuiPeutVraimentTest(BaseRemiseAZero):
    def test_un_compte_equipe_qui_n_est_pas_administrateur_est_refuse(self):
        """Entrer dans l'administration ne suffit pas à vider l'entrepôt."""
        gestionnaire = Utilisateur.objects.create_user(
            username="gestion", password="secret123",
            role=Utilisateur.OPERATEUR, is_staff=True)
        self.client.force_login(gestionnaire)
        r = self.vider()
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/wms/cabine/", r["Location"])
        self.assertEqual(Cabine.objects.count(), 1, "rien n'a été effacé")

    def test_un_cariste_n_entre_meme_pas_dans_l_administration(self):
        cariste = Utilisateur.objects.create_user(
            username="cariste", password="secret123", role=Utilisateur.OPERATEUR)
        self.client.force_login(cariste)
        r = self.vider()
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r["Location"])
        self.assertEqual(Cabine.objects.count(), 1)

    def test_sans_compte_c_est_la_page_de_connexion(self):
        self.client.logout()
        r = self.vider()
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r["Location"])
        self.assertEqual(Cabine.objects.count(), 1)

    def test_l_ancienne_route_d_API_n_existe_plus(self):
        """Laisser l'ancien chemin ouvert ferait de la nouvelle page une façade."""
        r = self.client.post("/api/cabines/vider_le_stock/",
                             {"confirmation": "EFFACER"},
                             content_type="application/json")
        # 405 et non 404 : l'adresse est désormais lue comme « la cabine dont
        # l'identifiant est vider_le_stock », et une fiche ne se poste pas. Dans
        # les deux cas, il n'y a plus d'action derrière.
        self.assertIn(r.status_code, (404, 405))
        self.assertEqual(Cabine.objects.count(), 1)
