"""Test de la commande d'import des données de la maquette."""
import json
import tempfile

from django.core.management import call_command
from django.test import TestCase

from wms import services
from wms.models import (Article, Cabine, Categorie, Emplacement, EtatCabine,
                        Mouvement, Reception, Stock)

MAQUETTE = {
    "rev": 1,
    "data": {
        "categories": [{"id": "c1", "nom": "ADHESIF", "zone": ""}, {"id": "c2", "nom": "MOUSSE", "zone": "Z2"}],
        "locations": [
            {"id": "__ARANGER__", "code": "À RANGER", "zone": "Réception", "staging": True},
            {"id": "l1", "code": "a001", "zone": "A", "description": ""},
        ],
        "articles": [
            {"id": "a1", "ref": "doub.fac.moquet.9472", "ean": "", "designation": "DOUBLE FACE 50m",
             "categorieId": "c1", "emplacementId": "l1", "unite": "ML", "stockMin": 800},
            {"id": "a2", "ref": "MOUSSE.COL.1", "ean": "123456", "designation": "Mousse colonne",
             "categorieId": "c2", "emplacementId": "", "unite": "U", "stockMin": 0},
        ],
        # a1 possède un mouvement correspondant ; a2 n'en a AUCUN. C'est le cas réel de
        # la maquette : le tableau `stock` fait foi, le journal est partiel. Sans
        # ajustement de reprise, un recalcul ferait disparaître la ligne de a2.
        "stock": [{"articleId": "a1", "locationId": "l1", "qte": 250},
                  {"articleId": "a2", "locationId": "l1", "qte": 40}],
        "mouvements": [{"id": "m1", "date": "2026-07-22T08:39:27.691Z", "type": "IN", "articleId": "a1",
                        "locationId": "l1", "qte": 250, "user": "Luka", "note": "Réception", "commande": ""}],
        "receptions": [{"id": "r1", "date": "2026-07-22T08:39:27.691Z", "articleId": "a1", "locationId": "l1",
                        "qte": 250, "user": "Luka", "commande": "CMD1", "commentaire": "", "staging": False}],
        "cabines": [{"id": "cab1", "numero": "00_00_01", "chantier": "000001", "modele": "TEST",
                     "locationId": "l1", "date": "2026-07-08T12:16:14.153Z", "user": "Luka", "etat": "Quarantaine"}],
    },
}


class ImportMaquetteTest(TestCase):
    def _fichier(self, contenu=None):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(contenu or MAQUETTE, f, ensure_ascii=False)
        f.close()
        return f.name

    def test_import_complet(self):
        call_command("importer_maquette", self._fichier(), purge=True)
        self.assertEqual(Categorie.objects.count(), 2)
        self.assertEqual(Emplacement.objects.count(), 2)
        self.assertEqual(Article.objects.count(), 2)
        self.assertEqual(Stock.objects.count(), 2)
        # 1 mouvement du journal de la maquette + 1 ajustement de reprise par ligne de stock
        self.assertEqual(Mouvement.objects.count(), 3)
        self.assertEqual(Reception.objects.count(), 1)
        self.assertEqual(Cabine.objects.count(), 1)

    def test_reprise_de_stock_rend_le_cache_reconstructible(self):
        """Invariant n°1 : le journal doit expliquer le stock importé.

        Le journal de la maquette est partiel (le tableau `stock` fait foi) : ici a2 a
        une ligne de stock sans aucun mouvement. Sans ajustement de reprise, un
        `recalculer_stock()` après import ferait disparaître cette ligne.
        """
        call_command("importer_maquette", self._fichier(), purge=True)
        avant = {(s.article_id, s.emplacement_id): s.qte for s in Stock.objects.all()}
        self.assertEqual(len(avant), 2)
        services.recalculer_stock()
        apres = {(s.article_id, s.emplacement_id): s.qte for s in Stock.objects.all()}
        self.assertEqual(avant, apres)

    def test_stock_sans_mouvement_survit_au_recalcul(self):
        """Cas qui échouerait sans la reprise : a2 n'a aucun mouvement importé."""
        call_command("importer_maquette", self._fichier(), purge=True)
        a2 = Article.objects.get(ref="MOUSSE.COL.1")
        emplacement = Emplacement.objects.get(code="A001")
        self.assertEqual(float(services.stock_disponible(a2, emplacement)), 40.0)
        services.recalculer_stock()
        self.assertEqual(float(services.stock_disponible(a2, emplacement)), 40.0)

    def test_reprise_marquee_comme_ajustement(self):
        call_command("importer_maquette", self._fichier(), purge=True)
        reprises = Mouvement.objects.filter(note="Reprise de stock (import maquette)")
        self.assertEqual(reprises.count(), 2)
        self.assertTrue(all(m.type == Mouvement.AJUSTEMENT for m in reprises))
        self.assertEqual(sorted(float(m.qte) for m in reprises), [40.0, 250.0])

    def test_cabine_invalide_reellement_ignoree(self):
        """`Cabine.objects.create()` n'exécutait aucun validator : le bloc « cabine
        ignorée » de l'import ne filtrait rien et les numéros invalides entraient."""
        contenu = json.loads(json.dumps(MAQUETTE))
        contenu["data"]["cabines"] = [
            {"id": "bad1", "numero": "nawak", "chantier": "AB", "modele": "M", "locationId": "l1"},
            {"id": "bad2", "numero": "00_00_02", "chantier": "12", "modele": "M", "locationId": "l1"},
            {"id": "ok", "numero": "00_00_03", "chantier": "000003", "modele": "M", "locationId": "l1"},
        ]
        call_command("importer_maquette", self._fichier(contenu), purge=True)
        self.assertEqual(list(Cabine.objects.values_list("numero", flat=True)), ["00_00_03"])

    def test_normalisation_des_references_et_codes(self):
        call_command("importer_maquette", self._fichier(), purge=True)
        self.assertTrue(Article.objects.filter(ref="DOUB.FAC.MOQUET.9472").exists())
        self.assertTrue(Emplacement.objects.filter(code="A001").exists())

    def test_zone_a_ranger_marquee_staging(self):
        call_command("importer_maquette", self._fichier(), purge=True)
        self.assertTrue(Emplacement.objects.get(code="À RANGER").staging)

    def test_liens_categorie_et_emplacement_par_defaut(self):
        call_command("importer_maquette", self._fichier(), purge=True)
        a = Article.objects.get(ref="DOUB.FAC.MOQUET.9472")
        self.assertEqual(a.categorie.nom, "ADHESIF")
        self.assertEqual(a.emplacement_defaut.code, "A001")
        self.assertEqual(a.unite, "ML")
        self.assertEqual(float(a.stock_min), 800.0)

    def test_stock_importe(self):
        call_command("importer_maquette", self._fichier(), purge=True)
        s = Stock.objects.get(article__ref="DOUB.FAC.MOQUET.9472")
        self.assertEqual(float(s.qte), 250.0)
        self.assertEqual(s.emplacement.code, "A001")

    def test_reception_renumerotee(self):
        call_command("importer_maquette", self._fichier(), purge=True)
        self.assertTrue(Reception.objects.get().numero.startswith("R"))

    def test_etat_cabine_cree(self):
        call_command("importer_maquette", self._fichier(), purge=True)
        self.assertTrue(EtatCabine.objects.filter(nom="Quarantaine").exists())

    def test_purge_vide_avant_import(self):
        call_command("importer_maquette", self._fichier(), purge=True)
        call_command("importer_maquette", self._fichier(), purge=True)
        self.assertEqual(Article.objects.count(), 2)  # pas de doublon

    def test_fichier_introuvable(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("importer_maquette", "/chemin/inexistant.json")
