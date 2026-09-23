from django.test import TestCase

from wms.models import Emplacement


class ModelesTest(TestCase):
    def test_code_emplacement_normalise_en_majuscules(self):
        e = Emplacement.objects.create(code="a001")
        self.assertEqual(e.code, "A001")
