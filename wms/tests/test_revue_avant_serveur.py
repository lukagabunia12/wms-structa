"""Les défauts relevés par la revue d'avant la mise en serveur.

Chaque classe tient un défaut constaté — scénario reproduit, puis corrigé. Le
nom du test dit ce qui doit rester vrai ; la docstring, ce qui se passait.
Plusieurs ne se voyaient que sur PostgreSQL (textes trop longs, entiers hors
bornes, ex aequo dans un tri) : ils sont tenus ici par la règle qui les évite.
"""
import datetime as dt
import io

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase

from wms import export_inventaire, services_cabines, services_import, services_mp
from wms.models import (ArticleMP, Cabine, CabineAttendue, Emplacement, ModeleCabine,
                        MouvementCabine, PlaceCondamnee, StockMP, Utilisateur, Zone)
from wms.serializers import EmplacementSerializer


class Base(APITestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create_user(
            username="chef", password="motdepasse-123", role=Utilisateur.ADMIN, nom="Véro")
        self.client.force_authenticate(self.admin)
        self.zone = Zone.objects.create(nom="Hall", role=Zone.RANGEMENT)
        self.e1 = Emplacement.objects.create(code="AC550", rack="AC", zone_cabine=self.zone)
        self.e2 = Emplacement.objects.create(code="AC551", rack="AC", zone_cabine=self.zone)
        ModeleCabine.objects.update_or_create(cle="QUATTRO",
                                              defaults={"nom": "QUATTRO", "grand": True})
        ModeleCabine.objects.update_or_create(cle="DUO", defaults={"nom": "DUO", "grand": False})

    def cabine(self, numero="26_10_01", modele="DUO", chantier="251213"):
        return services_cabines.creer_cabine(numero=numero, chantier=chantier, modele=modele,
                                             utilisateur=self.admin)


class StatutEnvoyeTest(Base):
    """La seule case « changer le statut » suffisait à faire partir une cabine :
    `/statut/` avec « envoye » passait par l'envoi, sans la case de l'envoi."""

    def test_envoyer_par_le_statut_exige_la_case_de_l_envoi(self):
        cabine = self.cabine()
        operateur = Utilisateur.objects.create_user(username="op", password="x",
                                                    droit_cab_statut=True)
        self.client.force_authenticate(operateur)
        r = self.client.post(f"/api/cabines/{cabine.id}/statut/",
                             {"statut": "envoye", "motif": "camion"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertIn("sortir", r.json()["detail"].lower())
        cabine.refresh_from_db()
        self.assertEqual(cabine.statut, Cabine.LIBRE)

    def test_les_autres_statuts_restent_ouverts_a_la_case_statut(self):
        cabine = self.cabine()
        operateur = Utilisateur.objects.create_user(username="op", password="x",
                                                    droit_cab_statut=True)
        self.client.force_authenticate(operateur)
        r = self.client.post(f"/api/cabines/{cabine.id}/statut/",
                             {"statut": "quarantaine", "motif": "rayure"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)


class PlanDesEmplacementsTest(Base):
    """Le plan affichait « 1 cabine » sur un emplacement complet : la liste ne
    connaissait ni la place « T » d'un grand modèle, ni les places condamnées."""

    def places(self, emplacement):
        liste = self.client.get("/api/emplacements/?page=1").json()["results"]
        return next(e for e in liste if e["id"] == emplacement.id)["places_libres"]

    def test_un_grand_modele_remplit_l_emplacement(self):
        quattro = self.cabine("26_10_02", modele="QUATTRO")
        services_cabines.ranger(cabine=quattro, emplacement=self.e1, utilisateur=self.admin)
        self.assertEqual(self.places(self.e1), [])

    def test_une_place_prise_et_l_autre_condamnee(self):
        duo = self.cabine()
        services_cabines.ranger(cabine=duo, emplacement=self.e2, place="G",
                                utilisateur=self.admin)
        PlaceCondamnee.objects.create(emplacement=self.e2, place="D", motif="pilier")
        self.assertEqual(self.places(self.e2), [])

    def test_un_emplacement_vide_garde_ses_deux_places(self):
        self.assertEqual(self.places(self.e1), ["G", "D"])


class RechercheExacteTest(Base):
    """« 25_49_1 » ramenait 105 cabines « contenant » ce numéro, et 25_49_1
    n'était pas sur la première page : le scanner la disait inconnue."""

    def test_la_correspondance_exacte_passe_en_tete(self):
        CabineAttendue.objects.all().delete()
        for n in range(100, 160):
            Cabine.objects.create(numero=f"25_49_{n}", chantier="251213")
        Cabine.objects.create(numero="25_49_1", chantier="251213")
        d = self.client.get("/api/cabines/?toutes=1&numero=25_49_1").json()
        self.assertGreater(d["count"], 50)
        self.assertEqual(d["results"][0]["numero"], "25_49_1")


class TriStableTest(Base):
    """PostgreSQL rend des ex aequo dans un ordre qui peut changer d'une page à
    l'autre : trié par chantier, « Voir la suite » doublait ou sautait des
    cabines. Le tri finit maintenant toujours par l'identifiant."""

    def ordre(self, url):
        from rest_framework.request import Request
        from rest_framework.test import APIRequestFactory

        from wms.views import CabineViewSet, TriStable
        requete = Request(APIRequestFactory().get(url))
        return TriStable().get_ordering(requete, Cabine.objects.all(), CabineViewSet())

    def test_ex_aequo_departages(self):
        self.assertEqual(self.ordre("/api/cabines/?ordering=chantier"), ["chantier", "pk"])
        self.assertEqual(self.ordre("/api/cabines/?ordering=-date"), ["-date", "-pk"])

    def test_pas_de_tri_demande_rien_n_est_ajoute(self):
        self.assertIsNone(self.ordre("/api/cabines/"))


class ImportCellulesFusionneesTest(Base):
    """Un chantier ou un modèle fusionné sur plusieurs lignes n'arrivait que sur
    la première : les autres lignes étaient importées vides, sans un mot."""

    def classeur(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["CABINE", "CHANTIER", "MODELE"])
        ws.append(["26_02_50", "251213", "QUATTRO"])
        ws.append(["26_02_51", None, None])
        ws.append(["26_02_52", None, None])
        ws.merge_cells("B2:B4")
        ws.merge_cells("C2:C4")
        tampon = io.BytesIO()
        wb.save(tampon)
        tampon.seek(0)
        return tampon

    def test_les_lignes_couvertes_recoivent_la_valeur(self):
        rapport = services_import.importer(self.classeur(), utilisateur=self.admin,
                                           nom="fusion.xlsx")
        self.assertEqual(rapport["erreurs"], [])
        for numero in ("26_02_50", "26_02_51", "26_02_52"):
            ligne = CabineAttendue.objects.get(numero=numero)
            self.assertEqual(ligne.chantier, "251213", numero)
            self.assertEqual(ligne.modele, "QUATTRO", numero)


class RepriseEnQuarantaineTest(Base):
    """Reprendre une cabine envoyée la rendait « Conforme » : une cabine en
    quarantaine sortie par erreur repartait ensuite sans avertissement."""

    def test_la_quarantaine_survit_a_l_aller_retour(self):
        cabine = self.cabine()
        services_cabines.changer_statut(cabine=cabine, statut=Cabine.QUARANTAINE,
                                        motif="rayure paroi gauche", utilisateur=self.admin)
        services_cabines.envoyer(cabine=cabine, utilisateur=self.admin, note="erreur")
        services_cabines.reprendre(cabine=cabine, utilisateur=self.admin)
        cabine.refresh_from_db()
        self.assertEqual(cabine.statut, Cabine.QUARANTAINE)
        d = self.client.get(f"/api/cabines/?numero={cabine.numero}").json()["results"][0]
        self.assertIn("rayure paroi gauche", d["quarantaine"]["motif"])

    def test_une_cabine_conforme_revient_conforme(self):
        cabine = self.cabine()
        services_cabines.envoyer(cabine=cabine, utilisateur=self.admin, note="camion")
        services_cabines.reprendre(cabine=cabine, utilisateur=self.admin)
        cabine.refresh_from_db()
        self.assertEqual(cabine.statut, Cabine.LIBRE)


class CreationEnDoubleTest(Base):
    """Deux appuis sur « Créer » : les deux requêtes passent le contrôle, la
    seconde se heurte en base à la première — et l'opérateur lisait une erreur
    500. Ici, la seconde arrive alors que la première est déjà écrite."""

    def test_le_doublon_donne_une_phrase(self):
        Cabine.objects.create(numero="26_10_09", chantier="251213")
        with self.assertRaises(services_cabines.ErreurCabine) as refus:
            services_cabines.creer_cabine(numero="26_10_09", chantier="251213",
                                          utilisateur=self.admin)
        self.assertIn("déjà enregistrée", " ".join(refus.exception.messages))
        self.assertEqual(Cabine.objects.filter(numero="26_10_09").count(), 1)


class EntreesMalFormeesTest(Base):
    """Des valeurs du mauvais type donnaient des erreurs 500."""

    def test_reponses_400(self):
        cabine = self.cabine()
        url = f"/api/cabines/{cabine.id}"
        cas = [
            (f"{url}/ranger/", {"emplacement": self.e1.id, "place": 7}),
            (f"{url}/ranger/", {"emplacement": self.e1.id, "place": "G", "occupation": "abc"}),
            (f"{url}/statut/", {"statut": 5}),
            (f"{url}/statut/", {"statut": ["libre"]}),
            (f"{url}/envoyer/", {"note": {"a": 1}}),
            (f"{url}/chantier/", {"chantier": 12}),
            ("/api/token/", ["chef"]),
            (f"{url}/statut/", ["libre"]),
        ]
        for chemin, corps in cas:
            with self.subTest(chemin=chemin, corps=corps):
                r = self.client.post(chemin, corps, format="json")
                self.assertEqual(r.status_code, 400, r.content[:200])

    def test_filtre_immobile_hors_bornes(self):
        r = self.client.get("/api/cabines/?immobile=1000000000")
        self.assertEqual(r.status_code, 400)


class ProposerUnEmplacementTest(Base):
    def test_la_liste_n_est_pas_coupee_a_soixante(self):
        for n in range(80):
            Emplacement.objects.create(code=f"AD{n:03d}", rack="AD", zone_cabine=self.zone)
        cabine = self.cabine()
        d = self.client.get(f"/api/emplacements/pour_cabine/?cabine={cabine.id}").json()
        self.assertEqual(len(d["emplacements"]), Emplacement.objects.count())
        self.assertEqual(d["possibles"], Emplacement.objects.count())

    def test_on_ne_propose_pas_la_place_d_a_cote_de_la_sienne(self):
        """Sa propre présence faisait passer l'emplacement pour « entamé »."""
        cabine = self.cabine()
        services_cabines.ranger(cabine=cabine, emplacement=self.e1, place="G",
                                utilisateur=self.admin)
        d = self.client.get(f"/api/emplacements/pour_cabine/?cabine={cabine.id}").json()
        ligne = next(e for e in d["emplacements"] if e["id"] == self.e1.id)
        self.assertFalse(ligne["possible"])
        self.assertNotEqual(d["proposition"], self.e1.id)


class CabineEnvoyeeTest(Base):
    def test_elle_garde_son_chantier(self):
        """« Aucune cabine ne sort sans chantier » doit tenir après coup."""
        cabine = self.cabine()
        services_cabines.envoyer(cabine=cabine, utilisateur=self.admin, note="camion")
        r = self.client.patch(f"/api/cabines/{cabine.id}/",
                              {"type_cabine": "express", "chantier": ""}, format="json")
        self.assertEqual(r.status_code, 400)
        cabine.refresh_from_db()
        self.assertEqual(cabine.chantier, "251213")

    def test_la_date_d_envoi_est_a_l_heure_de_paris(self):
        cabine = self.cabine()
        services_cabines.envoyer(cabine=cabine, utilisateur=self.admin, note="camion")
        # 00 h 30 à Paris le 15 mars = 23 h 30 UTC le 14.
        Cabine.objects.filter(pk=cabine.pk).update(
            envoi_date=dt.datetime(2026, 3, 14, 23, 30, tzinfo=dt.timezone.utc))
        cabine.refresh_from_db()
        _, message = services_cabines.diagnostic_suppression(cabine)
        self.assertIn("15/03/2026", message)

    def test_un_envoi_aux_positions_tres_longues_ne_casse_pas(self):
        """MouvementCabine.depuis tient 160 caractères : PostgreSQL refusait
        l'envoi d'une cabine sur quatre emplacements aux zones longues."""
        zone = Zone.objects.create(nom="Z" * 110, role=Zone.RANGEMENT)
        cabine = self.cabine()
        for i, code in enumerate(["BB001", "BB002", "BB003"]):
            e = Emplacement.objects.create(code=code, rack="BB", zone_cabine=zone)
            services_cabines.ranger(cabine=cabine, emplacement=e, place="G",
                                    ajouter=bool(i), utilisateur=self.admin)
        services_cabines.envoyer(cabine=cabine, utilisateur=self.admin, note="camion")
        envoi = MouvementCabine.objects.get(cabine=cabine, type=MouvementCabine.ENVOI)
        self.assertLessEqual(len(envoi.depuis), 160)
        self.assertTrue(envoi.depuis.endswith("…"))


class GenerateurDeRacksTest(Base):
    def test_saisies_hors_bornes_refusees_en_400(self):
        cas = [
            {"prefixe": "AC", "debut": "²", "colonnes": 2, "niveaux": 1, "pas": 10},
            {"prefixe": "R" * 40, "debut": "1", "colonnes": 2, "niveaux": 1, "pas": 10},
            {"prefixe": "AC", "debut": "3000000000", "colonnes": 2, "niveaux": 1, "pas": 10},
        ]
        for corps in cas:
            with self.subTest(corps=corps):
                r = self.client.post("/api/emplacements/generer/",
                                     {**corps, "apercu": True}, format="json")
                self.assertEqual(r.status_code, 400, r.content[:200])


class ExportFormulesTest(Base):
    def test_un_texte_qui_commence_comme_une_formule_est_neutralise(self):
        self.assertEqual(export_inventaire.cellule('=HYPERLINK("x")'), "'=HYPERLINK(\"x\")")
        self.assertEqual(export_inventaire.cellule("@SOMME(1+1)"), "'@SOMME(1+1)")
        self.assertEqual(export_inventaire.cellule("-2+3"), "'-2+3")
        self.assertEqual(export_inventaire.cellule("251213-1"), "251213-1")
        self.assertEqual(export_inventaire.cellule(-4), -4)

    def test_l_export_des_cabines_est_protege(self):
        cabine = self.cabine()
        Cabine.objects.filter(pk=cabine.pk).update(client='=HYPERLINK("http://x")')
        r = self.client.get("/api/cabines/export/")
        contenu = b"".join(r.streaming_content).decode("utf-8")
        self.assertIn("'=HYPERLINK", contenu)


class AdministrationTest(Base):
    def setUp(self):
        super().setUp()
        self.chef = Utilisateur.objects.create_superuser("super", "s@exemple.fr", "motdepasse-123")
        self.client.force_login(self.chef)

    def test_hors_service_ne_se_coche_pas_dans_l_administration(self):
        r = self.client.get(f"/admin/wms/emplacement/{self.e1.id}/change/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'name="actif"')

    def test_un_code_en_minuscules_deja_pris_est_refuse_sans_erreur_500(self):
        r = self.client.post("/admin/wms/emplacement/add/", {
            "code": "ac550", "rack": "AC", "usage": Emplacement.CABINES,
            "mode_places": Emplacement.GD,
            "zone": "", "description": ""})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "existe")

    def test_un_code_mp_en_stock_ne_change_pas_de_famille(self):
        vitrages = Emplacement.objects.create(code="AH500", rack="AH",
                                              usage=Emplacement.MP_VITRAGE)
        article = ArticleMP.objects.get(code="VITR.470X2072.BP")
        services_mp.entrer(emplacement=vitrages, place="G", article=article, quantite=5,
                           utilisateur=self.admin)
        from wms.admin import ArticleMPForm
        donnees = {champ.name: getattr(article, champ.name)
                   for champ in ArticleMP._meta.fields if champ.editable and champ.name != "id"}
        donnees["famille"] = ArticleMP.CARTON
        formulaire = ArticleMPForm(data=donnees, instance=article)
        self.assertFalse(formulaire.is_valid())
        self.assertIn("stock posé", " ".join(formulaire.errors.get("famille", [])))


class UsageSousVerrouTest(Base):
    """L'usage d'un emplacement se changeait sans verrou : une palette entrée
    entre le contrôle et l'écriture restait sur un emplacement de cabines."""

    def test_le_controle_est_refait_au_moment_d_ecrire(self):
        vitrages = Emplacement.objects.create(code="AH600", rack="AH",
                                              usage=Emplacement.MP_VITRAGE)
        serialiseur = EmplacementSerializer(vitrages, data={"usage": Emplacement.CABINES},
                                            partial=True)
        self.assertTrue(serialiseur.is_valid(), serialiseur.errors)
        # La palette arrive après le contrôle, avant l'écriture.
        services_mp.entrer(emplacement=vitrages, place="G",
                           article=ArticleMP.objects.get(code="VITR.470X2072.BP"),
                           quantite=3, utilisateur=self.admin)
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            serialiseur.save()
        vitrages.refresh_from_db()
        self.assertEqual(vitrages.usage, Emplacement.MP_VITRAGE)
        self.assertTrue(StockMP.objects.filter(emplacement=vitrages).exists())


class LectureFicheImportTest(Base):
    def test_le_classeur_illisible_reste_une_phrase(self):
        r = self.client.post("/api/cabines-attendues/analyser/",
                             {"fichier": SimpleUploadedFile("x.xlsx", b"pas un classeur")},
                             format="multipart")
        self.assertEqual(r.status_code, 400)
