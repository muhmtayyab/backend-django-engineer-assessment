from types import SimpleNamespace as NS

from django.test import SimpleTestCase

from .services import PlanError, plan_fuel


def st(price):
    return NS(price=price)


class PlanFuelTests(SimpleTestCase):
    def test_short_trip_needs_no_stop(self):
        self.assertEqual(plan_fuel([], 400), [])

    def test_buys_only_what_is_needed(self):
        # 800 mi trip, cheap stop at 300, pricey at 600: buy just enough at 300 to finish.
        stops = [(st(3.0), 300, 0), (st(4.0), 600, 0)]
        plan = plan_fuel(stops, 800)
        self.assertEqual([p["stop"][1] for p in plan], [300])
        self.assertAlmostEqual(plan[0]["miles"], 800 - 500)  # arrive with 200 left, need 500 more

    def test_gap_too_large(self):
        with self.assertRaises(PlanError):
            plan_fuel([(st(3.0), 100, 0)], 1200)
