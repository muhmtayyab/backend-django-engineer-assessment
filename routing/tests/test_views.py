import math
from unittest import mock

import numpy as np
from django.core.cache import cache
from django.test import TestCase

from routing import services
from routing.models import Station

LAT = 40.0
START_LNG = -120.0
MILES_PER_LNG = 69.0 * math.cos(math.radians(LAT))  # ~52.9 miles per degree along lat 40
TRIP_MILES = 1200.0
END_LNG = START_LNG + TRIP_MILES / MILES_PER_LNG
LINE = np.array([[START_LNG, LAT], [END_LNG, LAT]])
START, FINISH = f"{LAT},{START_LNG}", f"{LAT},{END_LNG}"


def station(sid, mile, price, off_miles=0.0):
    return Station.objects.create(
        truckstop_id=sid, name=f"Stop {sid}", address="addr", city="City", state="NV", price=price,
        lat=LAT + off_miles / 69.0, lng=START_LNG + mile / MILES_PER_LNG,
    )


class RouteTestCase(TestCase):
    def setUp(self):
        cache.clear()
        services.reset_station_cache()
        self.addCleanup(cache.clear)
        self.addCleanup(services.reset_station_cache)
        patcher = mock.patch("routing.services.fetch_route", return_value=(LINE, TRIP_MILES))
        self.fetch = patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, **params):
        return self.client.get("/api/route/", params)


class RoutePlanViewTests(RouteTestCase):
    def setUp(self):
        super().setUp()
        station(1, 300, 3.00)
        station(2, 700, 3.10)
        station(3, 1000, 2.90)

    def test_success_shape_and_total(self):
        r = self.get(start=START, finish=FINISH)
        self.assertEqual(r.status_code, 200)
        d = r.json()
        for key in ("route", "fuel_stops", "total_fuel_cost", "distance_miles", "map_url"):
            self.assertIn(key, d)
        self.assertEqual(d["distance_miles"], 1200.0)
        self.assertTrue(d["fuel_stops"])
        self.assertAlmostEqual(d["total_fuel_cost"], sum(s["cost"] for s in d["fuel_stops"]), delta=0.05)
        self.assertEqual(d["route"]["geometry"]["type"], "LineString")

    def test_short_trip_has_no_stops_and_zero_cost(self):
        self.fetch.return_value = (LINE, 300.0)
        d = self.get(start=START, finish=FINISH).json()
        self.assertEqual(d["fuel_stops"], [])
        self.assertEqual(d["total_fuel_cost"], 0)

    def test_missing_parameter_is_400(self):
        r = self.get(start=START)
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.json())

    def test_places_outside_us_are_400(self):
        r = self.get(start="48.85,2.35", finish="51.5,-0.12")
        self.assertEqual(r.status_code, 400)
        self.fetch.assert_not_called()

    def test_second_identical_request_does_not_call_osrm_again(self):
        self.get(start=START, finish=FINISH)
        self.get(start=START, finish=FINISH)
        self.assertEqual(self.fetch.call_count, 1)


class NoStationsTests(RouteTestCase):
    def test_long_route_without_stations_is_422(self):
        r = self.get(start=START, finish=FINISH)
        self.assertEqual(r.status_code, 422)
        self.assertIn("error", r.json())


class CorridorTests(RouteTestCase):
    def test_includes_near_and_excludes_far_stations(self):
        near = station(1, 500, 3.0, off_miles=5)
        station(2, 500, 3.0, off_miles=30)
        found = services.stations_along(LINE, TRIP_MILES)
        self.assertEqual([s.truckstop_id for s, _, _ in found], [near.truckstop_id])
        _, mile, offset = found[0]
        self.assertAlmostEqual(mile, 500, delta=10)
        self.assertAlmostEqual(offset, 5, delta=1)

    def test_results_sorted_by_mile_marker(self):
        station(1, 900, 3.0)
        station(2, 100, 3.0)
        station(3, 500, 3.0)
        miles = [m for _, m, _ in services.stations_along(LINE, TRIP_MILES)]
        self.assertEqual(miles, sorted(miles))
