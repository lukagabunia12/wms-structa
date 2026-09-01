from django.test import TestCase
from django.db import IntegrityError

from wms.models import Article, Emplacement


class ModelesTest(TestCase):
    def test_ref_article_normalisee_en_majuscules(self):
        a = Article.objects.create(ref="  v0001 ", designation="Vis")
        self.assertEqual(a.ref, "V0001")

    def test_code_emplacement_normalise_en_majuscules(self):
        e = Emplacement.objects.create(code="a001")
        self.assertEqual(e.code, "A001")

    def test_ean_unique_si_present(self):
        Article.objects.create(ref="A1", designation="x", ean="123")
        with self.assertRaises(IntegrityError):
            Article.objects.create(ref="A2", designation="y", ean="123")

    def test_ean_vide_non_soumis_a_unicite(self):
        Article.objects.create(ref="A1", designation="x", ean="")
        Article.objects.create(ref="A2", designation="y", ean="")  # ne lève pas
        self.assertEqual(Article.objects.filter(ean="").count(), 2)
