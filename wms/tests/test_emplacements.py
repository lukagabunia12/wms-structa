"""Gestion du référentiel des emplacements : création, modification, suppression.

`Occupation.emplacement` est en SET_NULL — une suppression « réussie » pouvait
détacher tout un rack de cabines sans le moindre message. D'où un seul refus,
mais ferme : pas de suppression tant qu'une cabine est rangée.
"""
import re
from pathlib import Path

from django.db.models import ProtectedError
from rest_framework.test import APITestCase

from wms import services_cabines, services_emplacements
from wms.models import Cabine, Emplacement, MouvementCabine, Utilisateur, Zone


class BaseEmplacement(APITestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create_user(
            username="chef", password="motdepasse123", role=Utilisateur.ADMIN)
        self.client.force_authenticate(user=self.admin)
        self.emp = Emplacement.objects.create(code="C001")


class SuppressionEmplacementTest(BaseEmplacement):
    def test_emplacement_neuf_se_supprime(self):
        r = self.client.delete(f"/api/emplacements/{self.emp.id}/")
        self.assertEqual(r.status_code, 204, getattr(r, "data", None))
        self.assertFalse(Emplacement.objects.filter(pk=self.emp.pk).exists())

    def test_refus_si_des_cabines_y_sont_rangees(self):
        """Le cas le plus dangereux : SET_NULL les aurait détachées en silence."""
        cabine = Cabine.objects.create(numero="26_01_01", chantier="000123")
        services_ranger(cabine, self.emp)
        r = self.client.delete(f"/api/emplacements/{self.emp.id}/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cabine", " ".join(r.data["erreur"]).lower())
        cabine.refresh_from_db()
        self.assertEqual(cabine.emplacement_id, self.emp.pk)

    def test_le_message_dit_quoi_faire(self):
        cabine = Cabine.objects.create(numero="26_01_05", chantier="000127")
        services_ranger(cabine, self.emp)
        message = " ".join(self.client.delete(f"/api/emplacements/{self.emp.id}/").data["erreur"])
        self.assertIn("1 cabine(s)", message)
        self.assertIn("déplacez-les ou envoyez-les", message)

    def test_le_passe_ne_bloque_pas_et_reste_lisible(self):
        """Une cabine passée par ici puis partie ne retient pas l'emplacement.

        Le journal recopie le code en toutes lettres : il se lit encore une fois
        l'emplacement supprimé. C'est ce qui rend le refus « historique »
        d'autrefois inutile.
        """
        cabine = Cabine.objects.create(numero="26_01_06", chantier="000128")
        services_ranger(cabine, self.emp)
        services_cabines.envoyer(cabine=cabine, note="départ chantier")
        r = self.client.delete(f"/api/emplacements/{self.emp.id}/")
        self.assertEqual(r.status_code, 204, getattr(r, "data", None))
        rangement = MouvementCabine.objects.get(cabine=cabine, type=MouvementCabine.RANGEMENT)
        self.assertIn("C001", rangement.vers)

    def test_un_parametre_force_ne_leve_rien(self):
        """Il n'y a plus rien à forcer : les cabines rangées ne se forcent pas."""
        cabine = Cabine.objects.create(numero="26_01_02", chantier="000124")
        services_ranger(cabine, self.emp)
        r = self.client.delete(f"/api/emplacements/{self.emp.id}/?force=1")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Emplacement.objects.filter(pk=self.emp.pk).exists())

    def test_la_suppression_laisse_une_trace_au_journal_du_serveur(self):
        """Les emplacements n'ont pas de journal : la ligne du serveur en tient lieu."""
        with self.assertLogs("wms.services_emplacements", level="WARNING") as traces:
            self.client.delete(f"/api/emplacements/{self.emp.id}/?motif=rack+démonté")
        self.assertIn("C001", traces.output[0])
        self.assertIn("rack démonté", traces.output[0])
        self.assertIn("chef", traces.output[0])

    def test_lecture_seule_ne_peut_pas_supprimer(self):
        lecteur = Utilisateur.objects.create_user(
            username="obs", password="motdepasse123", role=Utilisateur.LECTURE)
        self.client.force_authenticate(user=lecteur)
        r = self.client.delete(f"/api/emplacements/{self.emp.id}/")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Emplacement.objects.filter(pk=self.emp.pk).exists())


class DiagnostiqueExposeTest(BaseEmplacement):
    """La fiche annonce ce qui bloquera AVANT que l'opérateur ne clique."""

    def test_fiche_dit_que_la_suppression_est_possible(self):
        r = self.client.get(f"/api/emplacements/{self.emp.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["suppression"], {"possible": True, "message": ""})

    def test_fiche_explique_le_blocage(self):
        cabine = Cabine.objects.create(numero="26_01_03", chantier="000125")
        services_ranger(cabine, self.emp)
        r = self.client.get(f"/api/emplacements/{self.emp.id}/")
        self.assertFalse(r.data["suppression"]["possible"])
        self.assertIn("cabine", r.data["suppression"]["message"])

    def test_la_liste_ne_paie_pas_le_diagnostic(self):
        """Une requête par ligne × 50 lignes : l'info n'a de sens que sur la fiche."""
        r = self.client.get("/api/emplacements/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data["results"][0]["suppression"])


class ContratApiTest(BaseEmplacement):
    """Les clés annoncées sont toujours là, même quand la relation est nulle."""

    def test_zone_nulle_donne_null_et_pas_une_cle_absente(self):
        """DRF retire la clé (SkipField) quand la source traverse un None : le champ
        `zone_cabine_nom` disparaissait de la réponse pour tout emplacement sans
        zone — c'est-à-dire les cinq du poste."""
        for url in (f"/api/emplacements/{self.emp.id}/", "/api/emplacements/"):
            r = self.client.get(url)
            ligne = r.data if "results" not in r.data else r.data["results"][0]
            self.assertIn("zone_cabine_nom", ligne, url)
            self.assertIsNone(ligne["zone_cabine_nom"], url)


class ModificationEmplacementTest(BaseEmplacement):
    def test_renommer_normalise_en_majuscules(self):
        r = self.client.patch(f"/api/emplacements/{self.emp.id}/", {"code": "d012"},
                              format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.code, "D012")

    def test_code_en_doublon_refuse_avec_un_message(self):
        Emplacement.objects.create(code="D012")
        r = self.client.patch(f"/api/emplacements/{self.emp.id}/", {"code": "d012"},
                              format="json")
        self.assertEqual(r.status_code, 400)

    def test_tous_les_champs_du_formulaire_sont_modifiables(self):
        """Aucun des trois anciens formulaires ne les proposait tous.

        `actif` n'en fait PAS partie, et c'est voulu : il a ses règles — motif
        obligatoire, refus tant qu'une cabine est là — et son propre geste
        (`/activation/`). Une case à cocher dans ce formulaire les contournait
        toutes.
        """
        zone = Zone.objects.create(nom="Attente départ", role=Zone.ENVOI)
        r = self.client.patch(f"/api/emplacements/{self.emp.id}/", {
            "code": "C001", "zone_cabine": zone.id, "mode_places": Emplacement.ILLIMITE,
            "description": "rack du fond", "staging": True,
        }, format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.zone_cabine_id, zone.id)
        self.assertEqual(self.emp.mode_places, Emplacement.ILLIMITE)
        self.assertEqual(self.emp.description, "rack du fond")
        self.assertTrue(self.emp.staging)

    def test_emplacement_inactif_refuse_les_rangements(self):
        """Le geste passe par `/activation/`, avec un motif — pas par le PATCH."""
        r = self.client.post(f"/api/emplacements/{self.emp.id}/activation/",
                             {"actif": False, "motif": "rack démonté"}, format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        cabine = Cabine.objects.create(numero="26_01_04", chantier="000126")
        r = self.client.post(f"/api/cabines/{cabine.id}/ranger/",
                             {"emplacement": self.emp.id, "place": "G"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("inactif", " ".join(r.data["erreur"]).lower())


class SuppressionZoneTest(BaseEmplacement):
    """Les zones se règlent dans l'administration : la protection est donc au
    niveau du modèle, là où l'administration la rencontre."""

    def test_zone_vide_se_supprime(self):
        zone = Zone.objects.create(nom="Provisoire")
        zone.delete()
        self.assertFalse(Zone.objects.filter(nom="Provisoire").exists())

    def test_zone_rattachee_a_des_emplacements_est_protegee(self):
        """SET_NULL débranchait les emplacements sans rien dire, et l'étape
        « attente de départ » se vidait sans explication."""
        zone = Zone.objects.create(nom="Attente départ", role=Zone.ENVOI)
        self.emp.zone_cabine = zone
        self.emp.save()
        with self.assertRaises(ProtectedError):
            zone.delete()
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.zone_cabine_id, zone.id)

    def test_l_administration_refuse_et_nomme_l_emplacement(self):
        zone = Zone.objects.create(nom="Attente départ", role=Zone.ENVOI)
        self.emp.zone_cabine = zone
        self.emp.save()
        self.admin.is_staff = self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)
        r = self.client.post(f"/admin/wms/zone/{zone.id}/delete/", {"post": "yes"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "C001")
        self.assertTrue(Zone.objects.filter(pk=zone.pk).exists())


class SuppressionRackTest(BaseEmplacement):
    """Supprimer un rack entier — l'opération la plus destructrice de l'écran.

    Ce qui compte ici n'est pas qu'elle marche, c'est qu'elle soit ENTIÈRE ou
    NULLE. Un rack à moitié supprimé laisse un plan à trous que personne ne sait
    reconstituer, et la panne se découvre des jours plus tard, devant le rack.
    """

    def setUp(self):
        super().setUp()
        services_emplacements.generer_rack(prefixe="AC", debut=550, pas=10, colonnes=3, niveaux=2)
        self.codes = sorted(Emplacement.objects.filter(rack="AC").values_list("code", flat=True))
        self.assertEqual(len(self.codes), 6)

    def test_diagnostic_annonce_ce_qui_sera_efface(self):
        r = self.client.get("/api/emplacements/rack-diagnostic/?rack=AC")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.assertEqual(r.data["emplacements"], 6)
        self.assertEqual(r.data["cabines"], 0)
        self.assertTrue(r.data["supprimable"])
        self.assertEqual(sorted(r.data["codes"]), self.codes)

    def test_rack_vide_se_supprime_entierement(self):
        r = self.client.post("/api/emplacements/supprimer-rack/", {"rack": "AC"}, format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.assertEqual(r.data["supprimes"], 6)
        self.assertEqual(Emplacement.objects.filter(rack="AC").count(), 0)

    def test_refus_si_une_seule_cabine_est_rangee(self):
        cabine = Cabine.objects.create(numero="26_01_02", chantier="000123")
        vise = Emplacement.objects.get(code=self.codes[3])
        services_ranger(cabine, vise)

        diag = self.client.get("/api/emplacements/rack-diagnostic/?rack=AC")
        self.assertFalse(diag.data["supprimable"])
        self.assertEqual(diag.data["cabines"], 1)

        r = self.client.post("/api/emplacements/supprimer-rack/", {"rack": "AC"}, format="json")
        self.assertEqual(r.status_code, 400)
        # LE point du test : les cinq emplacements libres sont intacts eux aussi.
        self.assertEqual(Emplacement.objects.filter(rack="AC").count(), 6)
        cabine.refresh_from_db()
        self.assertEqual(cabine.emplacement_id, vise.pk)

    def test_un_parametre_force_ne_leve_rien(self):
        cabine = Cabine.objects.create(numero="26_01_03", chantier="000123")
        services_ranger(cabine, Emplacement.objects.get(code=self.codes[0]))
        r = self.client.post("/api/emplacements/supprimer-rack/",
                             {"rack": "AC", "force": True}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Emplacement.objects.filter(rack="AC").count(), 6)

    def test_rack_inconnu_refuse(self):
        r = self.client.post("/api/emplacements/supprimer-rack/", {"rack": "ZZ"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_rack_vide_de_nom_refuse(self):
        """Sans ce garde-fou, un rack vide viserait tous les emplacements isolés."""
        isole = Emplacement.objects.create(code="ISOLE")
        r = self.client.post("/api/emplacements/supprimer-rack/", {"rack": ""}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Emplacement.objects.filter(pk=isole.pk).exists())

    def test_droit_referentiel_exige(self):
        operateur = Utilisateur.objects.create_user(
            username="cariste", password="motdepasse123",
            role=Utilisateur.OPERATEUR, droit_cab=True)
        self.client.force_authenticate(user=operateur)
        r = self.client.post("/api/emplacements/supprimer-rack/", {"rack": "AC"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Emplacement.objects.filter(rack="AC").count(), 6)


class SuppressionLotTest(BaseEmplacement):
    """Supprimer une sélection cochée à la main.

    Entre « un emplacement » et « tout un rack », il n'existait rien. Le risque
    est le même que pour un rack, et la règle donc la même : la sélection part
    ENTIÈRE ou pas du tout. Une sélection à moitié supprimée laisse l'opérateur
    devant son plan sans savoir laquelle des six cases a résisté.
    """

    def setUp(self):
        super().setUp()
        services_emplacements.generer_rack(prefixe="AC", debut=550, pas=10, colonnes=3, niveaux=2)
        self.emps = list(Emplacement.objects.filter(rack="AC").order_by("code"))
        self.assertEqual(len(self.emps), 6)

    def ids(self, *emplacements):
        return ",".join(str(e.pk) for e in emplacements)

    def test_diagnostic_annonce_la_selection(self):
        trois = self.emps[:3]
        r = self.client.get("/api/emplacements/lot-diagnostic/?ids=" + self.ids(*trois))
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.assertEqual(r.data["emplacements"], 3)
        self.assertTrue(r.data["supprimable"])
        self.assertEqual(r.data["codes"], [e.code for e in trois])
        self.assertEqual(r.data["bloquants"], [])

    def test_selection_libre_se_supprime(self):
        trois = self.emps[:3]
        r = self.client.post("/api/emplacements/supprimer-lot/",
                             {"ids": [e.pk for e in trois]}, format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        self.assertEqual(r.data["supprimes"], 3)
        self.assertEqual(Emplacement.objects.filter(rack="AC").count(), 3)

    def test_une_seule_cabine_annule_toute_la_selection(self):
        """LE test de cette fonctionnalité : rien ne part si un seul résiste."""
        cabine = Cabine.objects.create(numero="00_00_11", chantier="123456")
        services_ranger(cabine, self.emps[1])
        trois = self.emps[:3]
        r = self.client.post("/api/emplacements/supprimer-lot/",
                             {"ids": [e.pk for e in trois]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn(self.emps[1].code, str(r.data))
        self.assertEqual(Emplacement.objects.filter(rack="AC").count(), 6)

    def test_diagnostic_designe_la_case_qui_bloque(self):
        cabine = Cabine.objects.create(numero="00_00_12", chantier="123456")
        services_ranger(cabine, self.emps[2])
        r = self.client.get("/api/emplacements/lot-diagnostic/?ids="
                            + self.ids(*self.emps[:3]))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["supprimable"])
        self.assertEqual([b["code"] for b in r.data["bloquants"]], [self.emps[2].code])
        self.assertEqual(r.data["cabines"], 1)

    def test_une_cabine_sur_deux_emplacements_compte_pour_une(self):
        cabine = Cabine.objects.create(numero="00_00_13", chantier="123456")
        services_ranger(cabine, self.emps[0])
        services_cabines.ranger(cabine=cabine, emplacement=self.emps[1], place="G", ajouter=True)
        r = self.client.get("/api/emplacements/lot-diagnostic/?ids="
                            + self.ids(*self.emps[:3]))
        self.assertEqual(len(r.data["bloquants"]), 2)
        self.assertEqual(r.data["cabines"], 1)

    def test_selection_vide_refusee(self):
        r = self.client.post("/api/emplacements/supprimer-lot/", {"ids": []}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Emplacement.objects.filter(rack="AC").count(), 6)

    def test_emplacement_disparu_entre_temps(self):
        """Deux opérateurs sur le même rack : on refuse plutôt que d'en supprimer 2 sur 3."""
        trois = self.emps[:3]
        perdu = trois[0].pk
        trois[0].delete()
        r = self.client.post("/api/emplacements/supprimer-lot/",
                             {"ids": [perdu, trois[1].pk, trois[2].pk]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("n'existent plus", str(r.data))
        self.assertEqual(Emplacement.objects.filter(rack="AC").count(), 5)

    def test_doublons_dans_la_selection(self):
        """Deux clics sur la même case ne comptent qu'une fois."""
        r = self.client.get("/api/emplacements/lot-diagnostic/?ids="
                            + self.ids(self.emps[0], self.emps[0], self.emps[1]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["emplacements"], 2)

    def test_au_dela_du_plafond_refuse(self):
        r = self.client.get("/api/emplacements/lot-diagnostic/?ids="
                            + ",".join(str(i) for i in range(services_emplacements.LOT_MAX + 5)))
        self.assertEqual(r.status_code, 400)

    def test_droit_referentiel_exige(self):
        operateur = Utilisateur.objects.create_user(
            username="cariste2", password="motdepasse123",
            role=Utilisateur.OPERATEUR, droit_cab=True)
        self.client.force_authenticate(user=operateur)
        r = self.client.post("/api/emplacements/supprimer-lot/",
                             {"ids": [self.emps[0].pk]}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Emplacement.objects.filter(rack="AC").count(), 6)


class ModesDeRangementTest(BaseEmplacement):
    """L'écran écrit les modes en dur ; le serveur les définit. Ils ont divergé
    une fois — « gmd » est resté dans l'écran après le passage à deux places,
    et chaque création d'emplacement était refusée. Ce test les tient alignés."""

    def test_l_ecran_propose_exactement_les_modes_du_serveur(self):
        app = (Path(__file__).resolve().parents[1] / "static" / "app" / "app.js").read_text("utf-8")
        ligne = re.search(r"const MODES_EMP = \[(.*?)\];", app).group(1)
        codes = re.findall(r"\['([a-z]+)',", ligne)
        self.assertEqual(codes, [code for code, _ in Emplacement.MODES_PLACES])

    def test_chaque_mode_de_l_ecran_est_accepte(self):
        for code, _ in Emplacement.MODES_PLACES:
            r = self.client.post("/api/emplacements/", {"code": f"M-{code}", "mode_places": code},
                                 format="json")
            self.assertEqual(r.status_code, 201, getattr(r, "data", None))


def services_ranger(cabine, emplacement, place="G"):
    return services_cabines.ranger(cabine=cabine, emplacement=emplacement, place=place)
