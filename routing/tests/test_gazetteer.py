import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from routing import gazetteer

PLACES = """city,state,state_name,lat,lng
DeForest,WI,Wisconsin,43.24,-89.34
Fort Worth,TX,Texas,32.75,-97.33
Saint Louis,MO,Missouri,38.63,-90.2
Mount Vernon,NY,New York,40.91,-73.84
McAllen,TX,Texas,26.2,-98.23
"""


class GazetteerTests(SimpleTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "data").mkdir()
        (Path(tmp.name) / "data" / "places.csv").write_text(PLACES)
        ctx = override_settings(BASE_DIR=Path(tmp.name))
        ctx.enable()
        self.addCleanup(ctx.disable)
        gazetteer._load.cache_clear()
        self.addCleanup(gazetteer._load.cache_clear)

    def test_internal_space_variants_match(self):
        self.assertEqual(gazetteer.lookup("De Forest", "WI"), gazetteer.lookup("DeForest", "WI"))
        self.assertIsNotNone(gazetteer.lookup("De Forest", "WI"))

    def test_abbreviations_and_padding(self):
        self.assertIsNotNone(gazetteer.lookup("Ft. Worth", "TX"))
        self.assertEqual(gazetteer.lookup("Fort Worth   ", "TX"), gazetteer.lookup("fort worth", "tx"))
        self.assertIsNotNone(gazetteer.lookup("St. Louis", "MO"))
        self.assertIsNotNone(gazetteer.lookup("Mt Vernon", "NY"))

    def test_mc_prefix_spacing(self):
        self.assertIsNotNone(gazetteer.lookup("Mc Allen", "TX"))

    def test_full_state_name_and_unknown(self):
        self.assertIsNotNone(gazetteer.lookup("Mount Vernon", "New York"))
        self.assertIsNone(gazetteer.lookup("Nowhere", "TX"))
