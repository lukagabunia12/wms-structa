"""Tests de la logique métier des mouvements de stock (cœur du WMS)."""
from decimal import Decimal

from django.test import TestCase

from wms import services
from wms.models import Article, Categorie, Emplacement, Mouvement, Reception, Stock


class MoteurMouvementsTest(TestCase):
    def setUp(self):
        self.cat = Categorie.objects.create(nom="Visserie")
        self.a = Article.objects.create(ref="v0001", designation="Vis M6")
        self.e1 = Emplacement.objects.create(code="a001")
        self.e2 = Emplacement.objects.create(code="b001")

    def dispo(self, emp):
        return services.stock_disponible(self.a, emp)

    def test_entree_augmente_le_stock(self):
        services.entree(article=self.a, emplacement=self.e1, qte=10)
        self.assertEqual(self.dispo(self.e1), Decimal("10"))

    def test_sortie_diminue_le_stock(self):
        services.entree(article=self.a, emplacement=self.e1, qte=10)
        services.sortie(article=self.a, emplacement=self.e1, qte=4)
        self.assertEqual(self.dispo(self.e1), Decimal("6"))

    def test_sortie_insuffisante_refusee(self):
        services.entree(article=self.a, emplacement=self.e1, qte=3)
        with self.assertRaises(services.ErreurStock):
            services.sortie(article=self.a, emplacement=self.e1, qte=5)
        self.assertEqual(self.dispo(self.e1), Decimal("3"))  # inchangé

    def test_stock_jamais_negatif(self):
        with self.assertRaises(services.ErreurStock):
            services.sortie(article=self.a, emplacement=self.e1, qte=1)

    def test_ajustement_est_absolu(self):
        services.entree(article=self.a, emplacement=self.e1, qte=10)
        services.ajustement(article=self.a, emplacement=self.e1, qte=7)
        self.assertEqual(self.dispo(self.e1), Decimal("7"))

    def test_quantite_decimale(self):
        services.entree(article=self.a, emplacement=self.e1, qte="2.5")
        self.assertEqual(self.dispo(self.e1), Decimal("2.5"))

    def test_transfert_cree_deux_mouvements_et_conserve_le_total(self):
        services.entree(article=self.a, emplacement=self.e1, qte=10)
        n0 = Mouvement.objects.count()
        services.transfert(article=self.a, source=self.e1, destination=self.e2, qte=4)
        self.assertEqual(Mouvement.objects.count(), n0 + 2)
        self.assertEqual(self.dispo(self.e1), Decimal("6"))
        self.assertEqual(self.dispo(self.e2), Decimal("4"))

    def test_transfert_meme_emplacement_refuse(self):
        services.entree(article=self.a, emplacement=self.e1, qte=10)
        with self.assertRaises(services.ErreurStock):
            services.transfert(article=self.a, source=self.e1, destination=self.e1, qte=1)

    def test_contre_passation_inverse_le_mouvement(self):
        mv = services.entree(article=self.a, emplacement=self.e1, qte=8)
        services.contre_passer(mv)
        mv.refresh_from_db()
        self.assertTrue(mv.annule)
        self.assertEqual(self.dispo(self.e1), Decimal("0"))

    def test_contre_passation_interdite_sur_ajustement(self):
        mv = services.ajustement(article=self.a, emplacement=self.e1, qte=5)
        with self.assertRaises(services.ErreurStock):
            services.contre_passer(mv)

    def test_reception_cree_mouvement_et_reception_numerotee(self):
        mv, rec = services.receptionner(article=self.a, emplacement=self.e1, qte=12, commande="CMD1")
        self.assertEqual(mv.type, Mouvement.ENTREE)
        self.assertEqual(Reception.objects.count(), 1)
        self.assertTrue(rec.numero.startswith("R"))
        self.assertEqual(self.dispo(self.e1), Decimal("12"))

    def test_recalcul_stock_egale_le_journal(self):
        services.entree(article=self.a, emplacement=self.e1, qte=10)
        services.sortie(article=self.a, emplacement=self.e1, qte=3)
        services.transfert(article=self.a, source=self.e1, destination=self.e2, qte=2)
        avant = {(s.article_id, s.emplacement_id): s.qte for s in Stock.objects.all()}
        services.recalculer_stock()
        apres = {(s.article_id, s.emplacement_id): s.qte for s in Stock.objects.all()}
        self.assertEqual(avant, apres)
        self.assertEqual(avant, {(self.a.id, self.e1.id): Decimal("5"),
                                 (self.a.id, self.e2.id): Decimal("2")})

    def test_recalcul_stock_repare_un_cache_faux(self):
        """Le test précédent comparait avant/après : il passait même si
        recalculer_stock() ne faisait rien. Ici on falsifie le cache d'abord."""
        services.entree(article=self.a, emplacement=self.e1, qte=10)
        services.sortie(article=self.a, emplacement=self.e1, qte=3)
        Stock.objects.filter(article=self.a, emplacement=self.e1).update(qte=Decimal("999"))
        Stock.objects.create(article=self.a, emplacement=self.e2, qte=Decimal("42"))
        services.recalculer_stock()
        self.assertEqual(self.dispo(self.e1), Decimal("7"))
        self.assertEqual(self.dispo(self.e2), Decimal("0"))

    def test_contre_passation_d_une_sortie_remet_le_stock(self):
        services.entree(article=self.a, emplacement=self.e1, qte=10)
        mv = services.sortie(article=self.a, emplacement=self.e1, qte=4)
        inverse = services.contre_passer(mv)
        mv.refresh_from_db()
        self.assertEqual(self.dispo(self.e1), Decimal("10"))
        self.assertTrue(mv.annule)
        self.assertFalse(mv.annulation)
        self.assertEqual(inverse.type, Mouvement.ENTREE)
        self.assertTrue(inverse.annulation)
        self.assertFalse(inverse.annule)
        self.assertEqual(inverse.mouvement_source, mv)

    def test_contre_passation_d_une_annulation_refusee(self):
        """Sinon l'effet du mouvement d'origine est rétabli alors qu'il reste marqué
        « annulé » : l'historique devient incohérent."""
        mv = services.entree(article=self.a, emplacement=self.e1, qte=8)
        inverse = services.contre_passer(mv)
        with self.assertRaises(services.ErreurStock):
            services.contre_passer(inverse)
        self.assertEqual(self.dispo(self.e1), Decimal("0"))

    def test_contre_passation_refusee_si_le_stock_est_deja_sorti(self):
        mv = services.entree(article=self.a, emplacement=self.e1, qte=5)
        services.sortie(article=self.a, emplacement=self.e1, qte=5)
        with self.assertRaises(services.ErreurStock):
            services.contre_passer(mv)
        mv.refresh_from_db()
        self.assertFalse(mv.annule)  # rien n'a été marqué à tort

    def test_quantite_invalide_refusee_par_le_moteur(self):
        for qte in (None, "", "abc", "1,5", "1e3", "0.0004", "1e40", "12345678901234567"):
            with self.subTest(qte=qte):
                with self.assertRaises(services.ErreurStock):
                    services.entree(article=self.a, emplacement=self.e1, qte=qte)
        self.assertEqual(Mouvement.objects.count(), 0)

    def test_numero_de_reception_au_format_specifie(self):
        _, rec = services.receptionner(article=self.a, emplacement=self.e1, qte=1)
        self.assertRegex(rec.numero, r"^R\d{6}-\d{4}$")
        _, rec2 = services.receptionner(article=self.a, emplacement=self.e1, qte=1)
        self.assertEqual(int(rec2.numero[-4:]), int(rec.numero[-4:]) + 1)
