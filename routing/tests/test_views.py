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
ALT_LAT = 41.0  # a second corridor 69 miles north: far enough that stations never match both
ALT_LINE = np.array([[START_LNG, ALT_LAT], [END_LNG, ALT_LAT]])
ALT_MILES = 1210.0


def station(sid, mile, price, off_miles=0.0, lat=LAT):
    return Station.objects.create(
        truckstop_id=sid, name=f"Stop {sid}", address="addr", city="City", state="NV", price=price,
        lat=lat + off_miles / 69.0, lng=START_LNG + mile / MILES_PER_LNG,
    )


def route(line=LINE, miles=TRIP_MILES, hours=20.0):
    return services.Route(coords=line, miles=miles, hours=hours)


class RouteTestCase(TestCase):
    def setUp(self):
        cache.clear()
        services.reset_station_cache()
        self.addCleanup(cache.clear)
        self.addCleanup(services.reset_station_cache)
        patcher = mock.patch("routing.services.fetch_routes", return_value=[route()])
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
        self.assertEqual(d["duration_hours"], 20.0)
        self.assertEqual(len(d["route_options"]), 1)
        self.assertTrue(d["route_options"][0]["selected"])

    def test_short_trip_has_no_stops_and_zero_cost(self):
        self.fetch.return_value = [route(miles=300.0)]
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


class RouteComparisonTests(RouteTestCase):
    """OSRM returns alternatives in one call; we keep the route with the cheapest fuel plan."""

    def stock(self, lat, price, first_id):
        for i, mile in enumerate((300, 700, 1000)):
            station(first_id + i, mile, price, lat=lat)

    def test_picks_the_route_with_cheaper_fuel_even_if_longer(self):
        self.stock(LAT, 3.50, 1)
        self.stock(ALT_LAT, 3.00, 10)
        self.fetch.return_value = [route(), route(ALT_LINE, ALT_MILES, 21.0)]
        d = self.get(start=START, finish=FINISH).json()
        self.assertEqual(d["distance_miles"], ALT_MILES)
        self.assertEqual(d["duration_hours"], 21.0)
        self.assertEqual([o["selected"] for o in d["route_options"]], [False, True])
        costs = [o["total_fuel_cost"] for o in d["route_options"]]
        self.assertLess(costs[1], costs[0])
        self.assertEqual(d["total_fuel_cost"], costs[1])
        self.assertTrue(all(abs(s["location"]["lat"] - ALT_LAT) < 0.5 for s in d["fuel_stops"]))

    def test_keeps_the_first_route_when_it_is_cheaper(self):
        self.stock(LAT, 3.00, 1)
        self.stock(ALT_LAT, 3.50, 10)
        self.fetch.return_value = [route(), route(ALT_LINE, ALT_MILES)]
        d = self.get(start=START, finish=FINISH).json()
        self.assertEqual(d["distance_miles"], TRIP_MILES)
        self.assertEqual([o["selected"] for o in d["route_options"]], [True, False])

    def test_skips_a_route_with_no_feasible_plan(self):
        self.stock(ALT_LAT, 3.00, 10)  # first route has no stations at all
        self.fetch.return_value = [route(), route(ALT_LINE, ALT_MILES)]
        r = self.get(start=START, finish=FINISH)
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["distance_miles"], ALT_MILES)
        self.assertIn("error", d["route_options"][0])
        self.assertTrue(d["route_options"][1]["selected"])

    def test_all_routes_infeasible_is_422(self):
        self.fetch.return_value = [route(), route(ALT_LINE, ALT_MILES)]
        r = self.get(start=START, finish=FINISH)
        self.assertEqual(r.status_code, 422)
        self.assertIn("error", r.json())

    def test_equal_cost_prefers_the_shorter_route(self):
        self.stock(LAT, 3.00, 1)
        self.stock(ALT_LAT, 3.00, 10)
        self.fetch.return_value = [route(ALT_LINE, ALT_MILES), route(miles=1190.0)]
        d = self.get(start=START, finish=FINISH).json()
        self.assertEqual(d["distance_miles"], 1190.0)


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
