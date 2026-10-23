from unittest import mock

from django.test import SimpleTestCase

from routing import services
from routing.services import PlanError
from routing.views import build_plan


class GeocodeTests(SimpleTestCase):
    def test_alaska_coordinates_accepted(self):
        self.assertEqual(services.geocode("61.2,-149.9"), (61.2, -149.9))

    def test_hawaii_by_city_accepted(self):
        lat, lng = services.geocode("Honolulu, HI")
        self.assertTrue(18.5 <= lat <= 22.5 and -161 <= lng <= -154)

    def test_outside_us_rejected(self):
        with self.assertRaises(PlanError) as cm:
            services.geocode("48.85,2.35")
        self.assertEqual(cm.exception.status, 400)

    def test_mid_pacific_rejected(self):
        with self.assertRaises(PlanError):
            services.geocode("30.0,-140.0")


class SamePlaceTests(SimpleTestCase):
    def test_identical_start_finish_rejected_before_routing(self):
        with mock.patch("routing.views.services.fetch_route") as fetch:
            with self.assertRaises(PlanError) as cm:
                build_plan("Dallas, TX", "Dallas, TX")
        self.assertEqual(cm.exception.status, 400)
        fetch.assert_not_called()
