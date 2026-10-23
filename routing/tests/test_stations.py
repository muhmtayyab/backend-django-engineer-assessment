from django.test import TestCase

from routing import services
from routing.models import Station


def make_station(sid=1):
    return Station.objects.create(
        truckstop_id=sid, name="S", address="a", city="c", state="TX", price=3.0, lat=32.0, lng=-97.0,
    )


class StationCacheTests(TestCase):
    def setUp(self):
        services.reset_station_cache()
        self.addCleanup(services.reset_station_cache)

    def test_empty_table_not_cached(self):
        rows, _, _ = services._station_arrays()
        self.assertEqual(len(rows), 0)
        make_station()
        rows, lats, lngs = services._station_arrays()
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(lats), 1)
