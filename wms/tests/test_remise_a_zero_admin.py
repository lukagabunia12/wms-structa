"""Repartir de zéro : dans l'administration, derrière trois phrases, avec filet.

L'opération était un onglet de l'application, dans le menu « Référentiel »,
entre les étiquettes et le fichier de production. Elle est maintenant dans
`/admin` : second mot de passe, trois phrases à recopier, et une sauvegarde
écrite avant le premier effacement.

Elle ne vidait que les cabines. Elle remet désormais l'outil à neuf — c'est ce
qui était demandé : « vraiment une réinitialisation complète ». Tout est coché
à l'ouverture, on décoche ce qu'on garde, et il ne reste toujours que les
comptes.

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

from wms import services_cabines, services_mp, services_remise
from wms.models import (ArticleMP, Cabine, CabineAttendue, Emplacement, ModeleCabine,
                        MouvementCabine, MouvementMP, Occupation, PlaceCondamnee, StockMP,
                        Utilisateur, Zone)

PHRASE = "Oui je suis d'accord et je comprends"
TOUT = services_remise.CLES


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

    def phrases(self, parties=TOUT, **remplacements):
        """Les trois phrases exactes, dont on peut fausser celle qu'on veut, et
        les parties cochées — toutes, comme à l'ouverture de la page."""
        exactes = {
            "confirmation": "confirmer",
            "date_du_jour": f"{timezone.localdate():%d/%m/%Y}",
            "engagement": PHRASE,
            **{f"partie_{p}": "1" for p in parties},
        }
        exactes.update(remplacements)
        return exactes

    def vider(self, parties=TOUT, **remplacements):
        with override_settings(BASE_DIR=self.dossier.name):
            return self.client.post(self.url, self.phrases(parties, **remplacements))

    def sauvegardes(self):
        return sorted(Path(self.dossier.name).glob("sauvegardes/*.json"))


class TroisPhrasesTest(BaseRemiseAZero):
    def test_la_page_coche_tout_et_compte_sans_rien_effacer(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        parties = {p["cle"]: p for p in r.context["parties"]}
        self.assertEqual(list(parties), TOUT)
        self.assertTrue(all(p["cochee"] for p in parties.values()),
                        "à l'ouverture, c'est la remise à neuf")
        self.assertEqual(parties["cabines"]["detail"],
                         "1 cabine, dont 1 rangée · 2 lignes de journal.")
        self.assertIn("1 emplacement", parties["plan"]["detail"])
        self.assertEqual(r.context["comptes"], 1)
        self.assertContains(r, "Ce qui reste toujours")
        self.assertEqual(Cabine.objects.count(), 1, "regarder n'efface rien")

    def test_les_trois_phrases_exactes_remettent_a_zero(self):
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

    def test_une_page_en_erreur_garde_les_cases_telles_qu_on_les_a_laissees(self):
        r = self.vider(parties=["cabines", "mp"], confirmation="")
        cochees = [p["cle"] for p in r.context["parties"] if p["cochee"]]
        self.assertEqual(cochees, ["cabines", "mp"])


class CeQuiPartTest(BaseRemiseAZero):
    def test_tout_coche_il_ne_reste_que_les_comptes(self):
        """La demande : « vraiment une réinitialisation complète de l'outil »."""
        ligne = services_mp.entrer(
            emplacement=self._emplacement_mp(), place="G",
            article=ArticleMP.objects.get(code="VITR.470X2072.BP"), quantite=12,
            utilisateur=self.admin)
        self.assertTrue(ligne.pk)
        comptes = Utilisateur.objects.count()
        self.vider()
        self.assertEqual(Cabine.objects.count(), 0)
        self.assertEqual(MouvementCabine.objects.count(), 0)
        self.assertEqual(StockMP.objects.count(), 0)
        self.assertEqual(MouvementMP.objects.count(), 0)
        self.assertEqual(CabineAttendue.objects.count(), 0)
        self.assertEqual(Emplacement.objects.count(), 0)
        self.assertEqual(Zone.objects.count(), 0)
        self.assertEqual(Utilisateur.objects.count(), comptes)

    def test_les_reglages_reviennent_a_l_origine(self):
        """À neuf, ce n'est pas vide : c'est ce que l'installation écrit — les
        six grands modèles et les codes MP livrés, avec leurs seuils."""
        livres, grands = services_remise._semis()
        ArticleMP.objects.create(code="VITR.AJOUTE", famille="vitrage")
        modifie = ArticleMP.objects.get(code="VITR.470X2072.BP")
        modifie.seuil_reappro, modifie.designation = 999, "retouché"
        modifie.save()
        ArticleMP.objects.filter(code="VITR.927X2075.BP").delete()
        ModeleCabine.objects.filter(cle="QUATTRO").update(grand=False)
        self.vider()
        self.assertEqual(set(ArticleMP.objects.values_list("code", flat=True)), set(livres))
        modifie.refresh_from_db()
        self.assertEqual(modifie.seuil_reappro, livres["VITR.470X2072.BP"]["seuil_reappro"])
        self.assertEqual(modifie.designation, livres["VITR.470X2072.BP"]["designation"])
        self.assertTrue(ArticleMP.objects.filter(code="VITR.927X2075.BP").exists())
        self.assertEqual(set(ModeleCabine.objects.values_list("cle", flat=True)), set(grands))
        self.assertTrue(all(ModeleCabine.objects.values_list("grand", flat=True)))
        # Rien ne reste à remettre : la page le dit à la remise suivante.
        e = services_remise.etat()
        self.assertEqual((e["codes_mp"]["ajoutes"], e["codes_mp"]["modifies"],
                          e["codes_mp"]["manquants"]), (0, 0, 0))
        self.assertEqual(e["modeles"]["changes"], 0)

    def test_decoche_le_plan_reste(self):
        """L'entrepôt, ses places condamnées, le fichier de production et les
        réglages restent quand on ne coche que les cabines et le stock."""
        services_cabines.condamner_place(emplacement=self.emp, place=Occupation.DROITE,
                                         motif="pilier", utilisateur=self.admin)
        avant = {
            "emplacements": Emplacement.objects.count(),
            "zones": Zone.objects.count(),
            "attendues": CabineAttendue.objects.count(),
            "modeles": ModeleCabine.objects.count(),
            "codes": ArticleMP.objects.count(),
        }
        self.vider(parties=["cabines", "mp"])
        self.assertEqual(Cabine.objects.count(), 0)
        # Comparé À CE QU'IL Y AVAIT, pas à un nombre écrit d'avance : les
        # réglages de modèle et les codes sont semés par des migrations.
        self.assertEqual(Emplacement.objects.count(), avant["emplacements"])
        self.assertEqual(Zone.objects.count(), avant["zones"])
        self.assertEqual(PlaceCondamnee.objects.count(), 1)
        self.assertEqual(CabineAttendue.objects.count(), avant["attendues"])
        self.assertEqual(ModeleCabine.objects.count(), avant["modeles"])
        self.assertEqual(ArticleMP.objects.count(), avant["codes"])
        self.assertTrue(avant["attendues"], "le fichier de production doit être peuplé")

    def test_l_emplacement_est_libre_tout_de_suite_apres(self):
        """La preuve utile : on doit pouvoir ranger au même endroit dans la foulée."""
        self.vider(parties=["cabines"])
        CabineAttendue.objects.create(numero="00_00_02", modele="DUO", chantier="000124")
        neuve = services_cabines.creer_cabine(
            numero="00_00_02", chantier="000124", modele="DUO", utilisateur=self.admin)
        services_cabines.ranger(cabine=neuve, emplacement=self.emp,
                                place=Occupation.GAUCHE, utilisateur=self.admin)
        self.assertEqual(neuve.position, "A001·G")

    def test_sans_fichier_de_production_la_saisie_redevient_libre(self):
        operateur = Utilisateur.objects.create_user(
            username="op", password="secret123", role=Utilisateur.OPERATEUR,
            droit_cab_ranger=True)
        self.vider(parties=["production"])
        cabine = services_cabines.creer_cabine(numero="12_12_12", chantier="000125",
                                               utilisateur=operateur)
        self.assertTrue(cabine.pk, "plus de fichier : la règle n'est plus armée")

    def test_le_plan_n_part_pas_sans_les_cabines_qui_y_sont(self):
        """Effacer le plan en gardant les cabines les laisserait « rangées nulle
        part » — ce qui est faux, elles sont toujours sur le rack."""
        r = self.vider(parties=["plan", "mp"])
        self.assertEqual(r.status_code, 200)
        self.assertIn("ne s'efface pas sans « Les cabines »",
                      " ".join(r.context["manques"]["parties"]))
        self.assertEqual(Emplacement.objects.count(), 1)
        self.assertEqual(Cabine.objects.count(), 1)

    def test_les_codes_ne_reviennent_pas_sans_vider_le_stock_mp(self):
        r = self.vider(parties=["codes_mp"])
        self.assertEqual(r.status_code, 200)
        self.assertIn("Les matières premières", " ".join(r.context["manques"]["parties"]))

    def test_rien_de_coche_rien_d_efface(self):
        r = self.vider(parties=[])
        self.assertEqual(r.status_code, 200)
        self.assertIn("Cochez au moins une partie", " ".join(r.context["manques"]["parties"]))
        self.assertEqual(Cabine.objects.count(), 1)

    def test_une_partie_inconnue_est_refusee_par_le_service(self):
        with self.assertRaises(Exception):
            services_remise.remettre_a_zero(parties=["tout"], dossier=self.dossier.name)
        self.assertEqual(Cabine.objects.count(), 1)

    def test_vider_une_base_deja_vide_ne_casse_rien(self):
        self.vider()
        r = self.vider()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(self.sauvegardes()), 2, "chaque geste laisse sa trace")

    def _emplacement_mp(self):
        return Emplacement.objects.create(code="AH500", usage=Emplacement.MP_VITRAGE)


class SauvegardeTest(BaseRemiseAZero):
    def test_une_sauvegarde_est_ecrite_avant_l_effacement(self):
        self.vider()
        fichiers = self.sauvegardes()
        self.assertEqual(len(fichiers), 1, "un fichier, daté, et un seul")
        self.assertIn("remise-a-zero_", fichiers[0].name)

    def test_la_sauvegarde_contient_tout_ce_qui_part(self):
        self.vider()
        contenu = json.loads(self.sauvegardes()[0].read_text(encoding="utf-8"))
        modeles = {objet["model"] for objet in contenu}
        for attendu in ("wms.cabine", "wms.occupation", "wms.mouvementcabine",
                        "wms.emplacement", "wms.zone", "wms.cabineattendue",
                        "wms.modelecabine", "wms.articlemp"):
            self.assertIn(attendu, modeles)
        numeros = [o["fields"]["numero"] for o in contenu if o["model"] == "wms.cabine"]
        self.assertEqual(numeros, ["00_00_01"])
        self.assertNotIn("wms.utilisateur", modeles, "les comptes ne partent pas")

    def test_la_sauvegarde_ne_contient_que_ce_qui_part(self):
        self.vider(parties=["cabines"])
        contenu = json.loads(self.sauvegardes()[0].read_text(encoding="utf-8"))
        self.assertEqual({o["model"] for o in contenu},
                         {"wms.cabine", "wms.occupation", "wms.mouvementcabine"})

    def test_la_sauvegarde_se_RECHARGE(self):
        """La preuve qui compte. Une sauvegarde jamais rechargée est un fichier."""
        vitrages = Emplacement.objects.create(code="AH500", usage=Emplacement.MP_VITRAGE)
        services_mp.entrer(emplacement=vitrages, place="G",
                           article=ArticleMP.objects.get(code="VITR.470X2072.BP"),
                           quantite=12, utilisateur=self.admin)
        self.vider()
        self.assertEqual(Cabine.objects.count(), 0)
        self.assertEqual(Emplacement.objects.count(), 0)

        call_command("loaddata", str(self.sauvegardes()[0]), verbosity=0)

        self.assertEqual(Cabine.objects.count(), 1)
        revenue = Cabine.objects.get(numero="00_00_01")
        self.assertEqual(revenue.chantier, "000123")
        # Et elle est revenue À SA PLACE, pas seulement dans la liste — le plan
        # est revenu avec elle, zone comprise.
        self.assertEqual(revenue.position, "A001·G")
        self.assertEqual(Emplacement.objects.get(code="A001").zone_cabine.nom, "Rack A")
        self.assertGreaterEqual(MouvementCabine.objects.count(), 2)
        self.assertEqual(StockMP.objects.get().quantite, 12)
        self.assertTrue(CabineAttendue.objects.filter(numero="00_00_01").exists())
        self.assertFalse(ModeleCabine.objects.get(cle="DUO").grand)

    def test_les_codes_et_les_modeles_se_rechargent_sans_doublon(self):
        """Les codes d'origine sont remis SUR leurs lignes : le fichier les
        retrouve à leur identifiant, au lieu de buter sur un code en double."""
        ArticleMP.objects.create(code="VITR.AJOUTE", famille="vitrage", seuil_reappro=4)
        ArticleMP.objects.filter(code="VITR.470X2072.BP").update(seuil_reappro=999)
        ModeleCabine.objects.filter(cle="QUATTRO").update(grand=False)
        self.vider()
        self.assertFalse(ArticleMP.objects.filter(code="VITR.AJOUTE").exists())

        call_command("loaddata", str(self.sauvegardes()[0]), verbosity=0)

        self.assertEqual(ArticleMP.objects.get(code="VITR.AJOUTE").seuil_reappro, 4)
        self.assertEqual(ArticleMP.objects.get(code="VITR.470X2072.BP").seuil_reappro, 999)
        self.assertFalse(ModeleCabine.objects.get(cle="QUATTRO").grand)
        self.assertTrue(ModeleCabine.objects.get(cle="DUO"))

    def test_une_reservation_qui_tombe_avec_son_code_se_recharge(self):
        """Le plan gardé, un code ajouté retiré : la réservation qui le citait
        tombe — et revient avec la sauvegarde."""
        ajoute = ArticleMP.objects.create(code="VITR.AJOUTE", famille="vitrage")
        livre = ArticleMP.objects.get(code="VITR.470X2072.BP")
        vitrages = Emplacement.objects.create(code="AH500", usage=Emplacement.MP_VITRAGE)
        vitrages.codes_acceptes.set([ajoute, livre])
        self.vider(parties=["cabines", "mp", "codes_mp"])
        self.assertEqual(list(vitrages.codes_acceptes.values_list("code", flat=True)),
                         ["VITR.470X2072.BP"], "le code livré reste réservé")

        call_command("loaddata", str(self.sauvegardes()[0]), verbosity=0)

        self.assertEqual(set(vitrages.codes_acceptes.values_list("code", flat=True)),
                         {"VITR.AJOUTE", "VITR.470X2072.BP"})

    def test_rien_n_est_efface_si_la_sauvegarde_echoue(self):
        """L'ordre n'est pas négociable : le fichier d'abord, l'effacement après.

        L'inverse laisserait une base vide et pas de fichier — le pire des deux
        mondes, et celui qu'on ne découvre qu'au moment de vouloir revenir.
        """
        with self.assertRaises(OSError):
            services_remise.remettre_a_zero(
                parties=TOUT, utilisateur=self.admin,
                dossier="/proc/impossible/sauvegardes")
        self.assertEqual(Cabine.objects.count(), 1)
        self.assertEqual(MouvementCabine.objects.count(), 2)
        self.assertEqual(Emplacement.objects.count(), 1)


class QuiPeutVraimentTest(BaseRemiseAZero):
    def test_un_compte_equipe_qui_n_est_pas_administrateur_est_refuse(self):
        """Entrer dans l'administration ne suffit pas à vider l'entrepôt — pas
        même avec toutes les cases cochées : aucune case n'ouvre ce geste."""
        gestionnaire = Utilisateur.objects.create_user(
            username="gestion", password="secret123", role=Utilisateur.OPERATEUR,
            is_staff=True, **{f"droit_{d}": True for d in Utilisateur.DROITS})
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

    def test_l_accueil_de_l_administration_y_mene_les_administrateurs(self):
        r = self.client.get(reverse("admin:index"))
        self.assertContains(r, self.url)
        equipe = Utilisateur.objects.create_user(
            username="equipe", password="secret123", role=Utilisateur.OPERATEUR,
            is_staff=True)
        self.client.force_login(equipe)
        self.assertNotContains(self.client.get(reverse("admin:index")), self.url)


class DetailsEtGardeFousTest(BaseRemiseAZero):
    def test_l_installation_est_lue_dans_les_migrations(self):
        """Si une migration de semis était renommée ou fusionnée, la page de
        remise à zéro ne s'ouvrirait plus : ce test le dit avant."""
        livres, grands = services_remise._semis()
        self.assertEqual(len(livres), 45)
        self.assertEqual(len(grands), 6)
        # Une base fraîche est exactement « à neuf ».
        e = services_remise.etat()
        self.assertEqual((e["codes_mp"]["ajoutes"], e["codes_mp"]["modifies"],
                          e["codes_mp"]["manquants"]), (0, 0, 0))

    def test_la_page_dit_quelles_reservations_tombent_si_le_plan_reste(self):
        """Un emplacement réservé à un code ajouté n'aura plus de réservation :
        il acceptera toute sa famille. La page le nomme avant le geste."""
        ajoute = ArticleMP.objects.create(code="VITR.AJOUTE", famille="vitrage")
        livre = ArticleMP.objects.get(code="VITR.470X2072.BP")
        seul = Emplacement.objects.create(code="AH510", usage=Emplacement.MP_VITRAGE)
        seul.codes_acceptes.set([ajoute])
        mixte = Emplacement.objects.create(code="AH520", usage=Emplacement.MP_VITRAGE)
        mixte.codes_acceptes.set([ajoute, livre])
        detail = {p["cle"]: p["detail"] for p in services_remise.presenter()}["codes_mp"]
        self.assertIn("Si le plan est gardé, AH510 et AH520 perdent un code réservé", detail)
        self.assertIn("AH510 n'en garde aucun et acceptera tous les codes de sa famille",
                      detail)

    def test_une_sauvegarde_impossible_n_efface_rien_et_le_dit(self):
        from unittest import mock
        with mock.patch.object(services_remise, "sauvegarder",
                               side_effect=OSError("disque plein")):
            r = self.vider()
        self.assertEqual(r.status_code, 200, "la page, pas une erreur 500")
        self.assertContains(r, "Sauvegarde impossible (disque plein) : rien n")
        self.assertEqual(Cabine.objects.count(), 1)
        self.assertEqual(Emplacement.objects.count(), 1)

    def test_une_ecriture_interrompue_ne_laisse_pas_de_faux_fichier(self):
        """Le disque se remplit au milieu de l'écriture : le début du fichier est
        sur le disque, la suite non. Il ne doit rester ni un .json tronqué, qui
        passerait pour une sauvegarde, ni le fichier partiel."""
        from unittest import mock

        def ecrire_a_moitie(chemin, texte, encoding=None):
            with open(chemin, "w", encoding=encoding) as f:
                f.write(texte[:20])
            raise OSError("disque plein")

        with mock.patch.object(Path, "write_text", ecrire_a_moitie):
            with self.assertRaises(OSError):
                services_remise.sauvegarder(TOUT, dossier=self.dossier.name)
        self.assertEqual(list(Path(self.dossier.name).iterdir()), [],
                         "ni .json tronqué, ni .partiel")

    def test_le_verrou_est_pris_avant_la_sauvegarde(self):
        """L'ordre fait la garantie : verrouiller, puis lire et écrire la
        sauvegarde, puis effacer. Verrouillé après, une écriture d'un poste
        pourrait se glisser entre la sauvegarde et l'effacement."""
        from unittest import mock
        ordre = []
        vraie_sauvegarde = services_remise.sauvegarder
        with mock.patch.object(services_remise, "_verrouiller",
                               side_effect=lambda parties: ordre.append(("verrou", parties))), \
             mock.patch.object(services_remise, "sauvegarder",
                               side_effect=lambda *a, **k: (ordre.append(("sauvegarde",)),
                                                            vraie_sauvegarde(*a, **k))[1]):
            services_remise.remettre_a_zero(parties=["cabines"], dossier=self.dossier.name)
        self.assertEqual([etape[0] for etape in ordre], ["verrou", "sauvegarde"])
        self.assertEqual(ordre[0][1], {"cabines"})

    def test_une_base_occupee_n_est_pas_une_erreur_500(self):
        """Sur PostgreSQL, un geste en cours peut tenir une table : le verrou
        attend, puis renonce. Rien n'est effacé, et la page le dit."""
        from unittest import mock

        from django.db import OperationalError
        with mock.patch.object(services_remise, "_verrouiller",
                               side_effect=OperationalError("lock timeout")):
            r = self.vider()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Rien n&#x27;a été effacé : réessayez dans un instant.")
        self.assertEqual(Cabine.objects.count(), 1)
        self.assertEqual(self.sauvegardes(), [], "annulée avant la sauvegarde")

    def test_sur_postgresql_les_tables_sont_verrouillees_avant_la_sauvegarde(self):
        """Une cabine rangée pendant que la sauvegarde s'écrit serait effacée
        sans y être. Sur PostgreSQL, les tables touchées sont fermées aux
        écritures jusqu'à la fin de la remise."""
        from unittest import mock
        executees = []

        class Curseur:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql):
                executees.append(sql)

        faux = mock.Mock(vendor="postgresql")
        faux.ops.quote_name = lambda nom: f'"{nom}"'
        faux.cursor = Curseur
        with mock.patch.object(services_remise, "connection", faux):
            services_remise._verrouiller({"cabines", "plan", "mp"})
        # D'abord la limite d'attente — un geste en cours a quinze secondes —,
        # puis le verrou.
        self.assertEqual(len(executees), 2)
        self.assertEqual(executees[0], "SET LOCAL lock_timeout = '15s'")
        sql = executees[1]
        self.assertTrue(sql.startswith("LOCK TABLE ") and sql.endswith(" IN EXCLUSIVE MODE"))
        for table in ("wms_cabine", "wms_occupation", "wms_mouvementcabine", "wms_stockmp",
                      "wms_mouvementmp", "wms_emplacement", "wms_zone",
                      "wms_placecondamnee", "wms_emplacement_codes_acceptes"):
            self.assertIn(f'"{table}"', sql)
        self.assertNotIn("wms_utilisateur", sql, "les comptes ne sont jamais touchés")

    def test_chaque_table_effacee_est_verrouillee(self):
        """Ce que la remise efface ou réécrit, partie par partie, est dans le verrou."""
        attendu = {
            "cabines": {Cabine, Occupation, MouvementCabine},
            "mp": {StockMP, MouvementMP},
            "production": {CabineAttendue},
            "plan": {Zone, Emplacement, PlaceCondamnee},
            "modeles": {ModeleCabine},
            "codes_mp": {ArticleMP, Emplacement},
        }
        for partie, modeles in attendu.items():
            with self.subTest(partie=partie):
                tables = set(services_remise._tables({partie}))
                self.assertLessEqual({m._meta.db_table for m in modeles}, tables)
