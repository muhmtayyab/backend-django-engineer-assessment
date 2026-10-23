from unittest import mock

import requests
from django.core.cache import cache
from django.test import SimpleTestCase

from routing import services
from routing.services import PlanError

A, B = (32.78, -96.8), (29.76, -95.37)
OK = {"code": "Ok", "routes": [{"distance": 1609.344 * 240, "geometry": {"coordinates": [[-96.8, 32.78], [-95.37, 29.76]]}}]}


def resp(payload=None, status=200, bad_json=False):
    r = mock.Mock(status_code=status)
    if bad_json:
        r.json.side_effect = ValueError("not json")
    else:
        r.json.return_value = payload
    return r


@mock.patch("routing.services.requests.get")
class FetchRouteTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_retries_once_after_timeout(self, get):
        get.side_effect = [requests.Timeout(), resp(OK)]
        coords, miles = services.fetch_route(A, B)
        self.assertEqual(get.call_count, 2)
        self.assertAlmostEqual(miles, 240)
        self.assertEqual(coords.shape, (2, 2))

    def test_retries_on_5xx_and_bad_json(self, get):
        get.side_effect = [resp(status=503, bad_json=True), resp(OK)]
        services.fetch_route(A, B)
        self.assertEqual(get.call_count, 2)

    def test_persistent_failure_is_502(self, get):
        get.side_effect = requests.Timeout()
        with self.assertRaises(PlanError) as cm:
            services.fetch_route(A, B)
        self.assertEqual(cm.exception.status, 502)
        self.assertEqual(get.call_count, 2)

    def test_no_route_is_422_without_retry(self, get):
        get.return_value = resp({"code": "NoRoute"}, status=400)
        with self.assertRaises(PlanError) as cm:
            services.fetch_route(A, B)
        self.assertEqual(cm.exception.status, 422)
        self.assertIn("No drivable route", str(cm.exception))
        self.assertEqual(get.call_count, 1)

    def test_second_call_served_from_cache(self, get):
        get.return_value = resp(OK)
        services.fetch_route(A, B)
        services.fetch_route(A, B)
        self.assertEqual(get.call_count, 1)
