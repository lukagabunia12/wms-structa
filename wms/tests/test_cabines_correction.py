"""Correction et suppression d'une cabine mal saisie.

Avant : une cabine créée avec un mauvais numéro n'avait aucune issue dans
l'interface — ni correction, ni suppression. Il fallait passer par l'administration
Django, qui écrit sans rien journaliser : la cabine disparaissait sans explication.
"""
from rest_framework.test import APITestCase

from wms import services_cabines
from wms.models import Cabine, Emplacement, MouvementCabine, Utilisateur, Zone


class BaseCorrection(APITestCase):
    def setUp(self):
        self.user = Utilisateur.objects.create_user(
            username="luka", password="motdepasse123", role=Utilisateur.ADMIN, nom="Luka G.")
        self.client.force_authenticate(user=self.user)
        self.emp = Emplacement.objects.create(code="C001")

    def cabine(self, numero="26_03_47", chantier="000123", **kw):
        return services_cabines.creer_cabine(numero=numero, chantier=chantier,
                                             utilisateur=self.user, **kw)


class CorrectionFicheTest(BaseCorrection):
    def test_corriger_le_numero(self):
        c = self.cabine()
        r = self.client.patch(f"/api/cabines/{c.id}/", {"numero": "26_03_48"}, format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        c.refresh_from_db()
        self.assertEqual(c.numero, "26_03_48")

    def test_la_correction_est_journalisee_avec_l_avant_et_l_apres(self):
        """Un numéro qui change du jour au lendemain doit avoir une explication."""
        c = self.cabine()
        self.client.patch(f"/api/cabines/{c.id}/",
                          {"numero": "26_03_48", "modele": "PRIVILEGE 90"}, format="json")
        trace = MouvementCabine.objects.filter(type=MouvementCabine.CORRECTION).first()
        self.assertIsNotNone(trace)
        self.assertIn("26_03_47", trace.note)
        self.assertIn("26_03_48", trace.note)
        self.assertIn("PRIVILEGE 90", trace.note)
        self.assertEqual(trace.utilisateur_nom, "Luka G.")

    def test_numero_en_doublon_refuse_proprement(self):
        c = self.cabine()
        self.cabine(numero="26_03_48", chantier="000124")
        r = self.client.patch(f"/api/cabines/{c.id}/", {"numero": "26_03_48"}, format="json")
        self.assertEqual(r.status_code, 400)
        c.refresh_from_db()
        self.assertEqual(c.numero, "26_03_47")

    def test_format_de_numero_invalide_refuse(self):
        c = self.cabine()
        r = self.client.patch(f"/api/cabines/{c.id}/", {"numero": "nawak"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_correction_sans_changement_refusee(self):
        c = self.cabine()
        r = self.client.patch(f"/api/cabines/{c.id}/", {"numero": "26_03_47"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_la_position_ne_se_corrige_pas_par_patch(self):
        """Ranger a son opération dédiée, qui journalise le déplacement."""
        c = self.cabine()
        r = self.client.patch(f"/api/cabines/{c.id}/",
                              {"emplacement": self.emp.id, "place": "G"}, format="json")
        self.assertEqual(r.status_code, 400)   # aucun champ modifiable fourni
        c.refresh_from_db()
        self.assertIsNone(c.emplacement_id)

    def test_une_cabine_envoyee_reste_corrigeable(self):
        """Une faute de frappe reste une faute de frappe une fois la cabine partie."""
        c = self.cabine()
        services_cabines.envoyer(cabine=c, utilisateur=self.user)
        r = self.client.patch(f"/api/cabines/{c.id}/", {"modele": "ARTIC 120"}, format="json")
        self.assertEqual(r.status_code, 200, getattr(r, "data", None))
        c.refresh_from_db()
        self.assertEqual(c.modele, "ARTIC 120")
        self.assertEqual(c.statut, Cabine.ENVOYE)

    def test_lecture_seule_ne_corrige_rien(self):
        c = self.cabine()
        self.client.force_authenticate(user=Utilisateur.objects.create_user(
            username="obs", password="motdepasse123", role=Utilisateur.LECTURE))
        r = self.client.patch(f"/api/cabines/{c.id}/", {"numero": "26_03_49"}, format="json")
        self.assertEqual(r.status_code, 403)


class SuppressionCabineTest(BaseCorrection):
    def test_cabine_fraichement_creee_se_supprime(self):
        c = self.cabine()
        r = self.client.delete(f"/api/cabines/{c.id}/")
        self.assertEqual(r.status_code, 204, getattr(r, "data", None))
        self.assertFalse(Cabine.objects.filter(pk=c.pk).exists())

    def test_le_journal_garde_la_trace_de_la_suppression(self):
        """« Où est passée la 26_03_47 ? » doit avoir une réponse."""
        c = self.cabine()
        self.client.delete(f"/api/cabines/{c.id}/?motif=doublon+de+saisie")
        trace = MouvementCabine.objects.filter(type=MouvementCabine.SUPPRESSION).first()
        self.assertIsNotNone(trace)
        self.assertIsNone(trace.cabine_id)          # SET_NULL après la suppression
        self.assertEqual(trace.cabine_numero, "26_03_47")
        self.assertEqual(trace.chantier, "000123")
        self.assertEqual(trace.utilisateur_nom, "Luka G.")
        self.assertEqual(trace.note, "doublon de saisie")

    def test_cabine_corrigee_reste_supprimable_franchement(self):
        """Corriger puis supprimer est le parcours normal d'une saisie ratée.

        Constaté sur la base réelle : la correction laissait une trace au journal,
        que le diagnostic comptait comme du vécu — le WMS refusait alors la
        suppression en conseillant… de corriger la fiche.
        """
        c = self.cabine(numero="26_99_01")
        self.client.patch(f"/api/cabines/{c.id}/", {"numero": "26_99_02"}, format="json")
        d = self.client.get(f"/api/cabines/{c.id}/").data["suppression"]
        self.assertTrue(d["possible"], d["message"])
        self.assertEqual(self.client.delete(f"/api/cabines/{c.id}/").status_code, 204)

    def test_cabine_rangee_demande_confirmation(self):
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.emp, place="G",
                                utilisateur=self.user)
        refus = self.client.delete(f"/api/cabines/{c.id}/")
        self.assertEqual(refus.status_code, 400)
        self.assertIn("libérera cette place", " ".join(refus.data["erreur"]))
        self.assertTrue(Cabine.objects.filter(pk=c.pk).exists())

        force = self.client.delete(f"/api/cabines/{c.id}/?force=1&motif=erreur")
        self.assertEqual(force.status_code, 204, getattr(force, "data", None))
        # La place redevient libre : c'est justement l'effet à annoncer avant.
        self.assertEqual(services_cabines.places_libres(self.emp), ["G", "D"])

    def test_cabine_avec_historique_demande_confirmation(self):
        c = self.cabine()
        services_cabines.changer_statut(cabine=c, statut=Cabine.QUARANTAINE,
                                        utilisateur=self.user, motif="paroi à reprendre")
        refus = self.client.delete(f"/api/cabines/{c.id}/")
        self.assertEqual(refus.status_code, 400)
        self.assertIn("corriger la fiche", " ".join(refus.data["erreur"]).lower())
        self.assertEqual(self.client.delete(f"/api/cabines/{c.id}/?force=1").status_code, 204)

    def test_cabine_envoyee_demande_confirmation(self):
        c = self.cabine()
        services_cabines.envoyer(cabine=c, utilisateur=self.user)
        refus = self.client.delete(f"/api/cabines/{c.id}/")
        self.assertEqual(refus.status_code, 400)
        self.assertIn("archivée", " ".join(refus.data["erreur"]))
        self.assertEqual(self.client.delete(f"/api/cabines/{c.id}/?force=1").status_code, 204)

    def test_les_mouvements_passes_survivent(self):
        """Invariant du projet : les FK historiques sont en SET_NULL, jamais CASCADE."""
        c = self.cabine()
        services_cabines.ranger(cabine=c, emplacement=self.emp, place="G",
                                utilisateur=self.user)
        self.client.delete(f"/api/cabines/{c.id}/?force=1&motif=erreur")
        lignes = MouvementCabine.objects.filter(cabine_numero="26_03_47")
        self.assertEqual(lignes.count(), 3)   # création, rangement, suppression
        self.assertTrue(all(m.cabine_id is None for m in lignes))

    def test_lecture_seule_ne_supprime_rien(self):
        c = self.cabine()
        self.client.force_authenticate(user=Utilisateur.objects.create_user(
            username="obs", password="motdepasse123", role=Utilisateur.LECTURE))
        r = self.client.delete(f"/api/cabines/{c.id}/")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Cabine.objects.filter(pk=c.pk).exists())


class DiagnosticExposeTest(BaseCorrection):
    """La fiche annonce ce qui sera perdu AVANT que l'opérateur ne clique."""

    def test_fiche_annonce_une_suppression_franche(self):
        c = self.cabine()
        d = self.client.get(f"/api/cabines/{c.id}/").data["suppression"]
        self.assertTrue(d["possible"])
        self.assertIsNone(d["motif"])

    def test_fiche_annonce_la_place_qui_sera_liberee(self):
        c = self.cabine()
        zone = Zone.objects.create(nom="Attente départ", role=Zone.ENVOI)
        self.emp.zone_cabine = zone
        self.emp.save()
        services_cabines.ranger(cabine=c, emplacement=self.emp, place="D",
                                utilisateur=self.user)
        d = self.client.get(f"/api/cabines/{c.id}/").data["suppression"]
        self.assertFalse(d["possible"])
        self.assertEqual(d["motif"], services_cabines.BLOCAGE_RANGEE)
        self.assertTrue(d["forcable"])
        self.assertIn("C001·D", d["message"])

    def test_la_liste_ne_paie_pas_le_diagnostic(self):
        self.cabine()
        self.assertIsNone(self.client.get("/api/cabines/").data["results"][0]["suppression"])
