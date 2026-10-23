from types import SimpleNamespace as NS

from django.conf import settings
from django.test import SimpleTestCase

from routing.services import PlanError, plan_fuel


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


def assert_feasible(test, plan, total_miles, eps=1e-6):
    """Simulate the plan: never run dry, never exceed the tank, reach the destination."""
    rng = settings.VEHICLE_RANGE_MILES
    fuel, pos = float(rng), 0.0
    for p in plan:
        mile = p["stop"][1]
        fuel -= mile - pos
        test.assertGreaterEqual(fuel, -eps, f"ran dry before mile {mile}")
        fuel += p["miles"]
        test.assertLessEqual(fuel, rng + eps, f"overfilled at mile {mile}")
        pos = mile
    test.assertGreaterEqual(fuel - (total_miles - pos), -eps, "did not reach destination")


class MinPurchaseTests(SimpleTestCase):
    min_miles = settings.MIN_PURCHASE_GALLONS * settings.VEHICLE_MPG

    def test_tiny_final_purchase_merged_into_previous_stop(self):
        stops = [(st(3.0), 400, 0), (st(2.9), 790, 0)]
        plan = plan_fuel(stops, 805)  # would buy 1.5 gal at mile 790
        assert_feasible(self, plan, 805)
        self.assertEqual([p["stop"][1] for p in plan], [400])
        for p in plan:
            self.assertGreaterEqual(p["miles"], self.min_miles)

    def test_tiny_purchase_kept_when_tank_cannot_absorb_it(self):
        stops = [(st(3.0), 300, 0), (st(2.9), 790, 0)]
        plan = plan_fuel(stops, 805)  # stop at 300 would overfill (490 + 15 > 500)
        assert_feasible(self, plan, 805)
        self.assertEqual([p["stop"][1] for p in plan], [300, 790])

    def test_existing_scenarios_feasible(self):
        plan = plan_fuel([(st(3.0), 300, 0), (st(4.0), 600, 0)], 800)
        assert_feasible(self, plan, 800)
