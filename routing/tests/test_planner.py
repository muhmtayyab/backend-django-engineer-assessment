import random
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


def exact_cost(stops, total, rng=500):
    """Reference solver: exact DP over (station, fuel in miles) on a 1-mile grid.

    `stops` is [(mile, price)] with integer miles. Cost is in price-miles (price per mile of
    range). Start: full tank, free. Returns inf when the trip is impossible.
    """
    inf = float("inf")
    st = sorted(stops)
    if total <= rng:
        return 0.0
    dp = [[inf] * (rng + 1) for _ in st]
    for j, (m, _) in enumerate(st):
        if m <= rng:
            dp[j][rng - m] = 0.0
    best = inf
    for i, (m, p) in enumerate(st):
        row = dp[i]
        for f in range(rng):  # buy one more mile of range
            row[f + 1] = min(row[f + 1], row[f] + p)
        for f, c in enumerate(row):
            if c == inf:
                continue
            if total - m <= f:
                best = min(best, c)
            for j in range(i + 1, len(st)):
                d = st[j][0] - m
                if d > f:
                    break
                dp[j][f - d] = min(dp[j][f - d], c)
    return best


class ExactSolverTests(SimpleTestCase):
    """plan_fuel must match the exact optimum (and agree on which trips are impossible)."""

    def test_existing_scenarios_feasible(self):
        plan = plan_fuel([(st(3.0), 300, 0), (st(4.0), 600, 0)], 800)
        assert_feasible(self, plan, 800)

    def test_matches_exact_solver_on_random_trips(self):
        rnd = random.Random(2026)
        checked = 0
        for _ in range(250):
            total = rnd.randint(501, 2500)
            raw = [(rnd.randint(1, total - 1), round(rnd.uniform(2.5, 4.5), 3))
                   for _ in range(rnd.randint(3, 20))]
            opt = exact_cost(raw, total)
            stops = [(st(p), m, 0.0) for m, p in sorted(raw)]
            try:
                plan = plan_fuel(stops, float(total))
            except PlanError:
                self.assertEqual(opt, float("inf"), f"planner gave up on a feasible trip: {total} {raw}")
                continue
            self.assertNotEqual(opt, float("inf"), f"planner planned an impossible trip: {total} {raw}")
            assert_feasible(self, plan, total)
            cost = sum(p["miles"] * p["stop"][0].price for p in plan)
            self.assertAlmostEqual(cost, opt, places=6, msg=f"not optimal: {total} {raw}")
            checked += 1
        self.assertGreater(checked, 100)  # guard: enough feasible trips were really compared
