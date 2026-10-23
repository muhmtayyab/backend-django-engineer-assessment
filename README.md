# Fuel Route Planner (Django 6.1)

`GET /api/route/?start=<place>&finish=<place>` returns the driving route, the cheapest fuel stops along it
(500-mile range, 10 mpg) and the total fuel cost. A place is `City, ST`, a free-text address, or `lat,lng`.
If the routing service offers an alternative route, both are costed and the cheaper one is returned.
`GET /api/route/map/?start=...&finish=...` renders the same result on a Leaflet map (needs internet for the
Leaflet script and map tiles).

## Run
Tested on Python 3.14. The database (`db.sqlite3`) is not committed, so a fresh clone needs the two commands below.

    python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
    python manage.py migrate && python manage.py load_stations   # geocodes the CSV offline
    python manage.py runserver
    curl -G localhost:8000/api/route/ --data-urlencode "start=Los Angeles, CA" --data-urlencode "finish=New York, NY"

## Example
`GET /api/route/?start=Chicago, IL&finish=Atlanta, GA` (route coordinates and later stops trimmed):

```json
{
  "start": {"query": "Chicago, IL", "lat": 41.85421, "lng": -87.67605},
  "finish": {"query": "Atlanta, GA", "lat": 33.81708, "lng": -84.38023},
  "distance_miles": 681.2,
  "duration_hours": 13.35,
  "fuel_consumed_gallons": 68.12,
  "fuel_stops": [
    {"name": "Thorntons #155", "city": "Louisville", "state": "KY",
     "location": {"lat": 38.20845, "lng": -85.69631}, "price_per_gallon": 2.906,
     "mile_marker": 300.5, "distance_from_route_miles": 2.3, "gallons_purchased": 6.7, "cost": 19.46}
  ],
  "total_fuel_cost": 52.17,
  "route_options": [
    {"distance_miles": 681.2, "duration_hours": 13.35, "total_fuel_cost": 52.17, "fuel_stop_count": 3, "selected": true},
    {"distance_miles": 748.6, "duration_hours": 13.85, "total_fuel_cost": 70.64, "fuel_stop_count": 3, "selected": false}
  ],
  "route": {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-87.6759, 41.85421], "..."]}},
  "map_url": "http://localhost:8000/api/route/map/?start=Chicago%2C+IL&finish=Atlanta%2C+GA"
}
```
The response also includes an `assumptions` object. `route_options` has one entry per route; a route with no
feasible plan has an `error` field instead of a cost.

## Design
- **One external call per request**: OSRM public API (`router.project-osrm.org`) returns the full route geometry.
  `City, ST` inputs are geocoded offline from `data/places.csv` (GeoNames); only free-text addresses fall
  back to Nominatim (one extra call each, cached). Routes and plans are cached.
- **Stations**: the CSV is deduplicated (lowest price per truckstop ID), Canadian stops dropped, and each stop
  placed at its city centroid (`load_stations`). Held in memory as numpy arrays.
- **Route choice**: the same OSRM call (`alternatives=true`) returns the best route plus usually one alternative.
  Each is planned separately (about 20 ms each) and the route with the **lowest total fuel cost** is returned;
  ties go to the shorter route. `route_options` lists every route's distance, duration, cost and whether it was
  selected, so the cost/time trade-off is visible. A route with no feasible plan is skipped (422 only if all fail).
- **Corridor search**: the route is resampled every 2 miles; stations within 10 miles of it get a mile marker.
- **Planner**: the fixed-path gas station problem (Khuller, Malekian & Mestre, "To Fill or not to Fill").
  Greedy: buy only enough fuel to reach a cheaper stop in range, otherwise fill up and head to the cheapest
  reachable stop. Tested against an exact DP solver on random trips; runs in milliseconds.
- **Resilience**: OSRM is called with a 15 s timeout and one retry; failures return a clear JSON error.
- **Assumptions**: tank starts full (free); cost = fuel bought en route (`fuel_consumed_gallons` is also
  returned). Station positions are city-level, so mile markers/offsets are approximate.

## Error responses
All errors are JSON: `{"error": "<message>"}`.

| Status | Meaning | Example |
|---|---|---|
| 400 | Bad input | missing `start`/`finish`; place outside the USA; start and finish are the same place |
| 422 | No drivable route or plan | Honolulu to Los Angeles (`NoRoute`); Portland, OR to San Francisco, CA (a 500+ mile gap with no fuel station) |
| 502 | Upstream service failed after a retry | OSRM or Nominatim unavailable |

Alaska, Hawaii and Puerto Rico are accepted as places; routing between disconnected regions returns 422.

## Data
- `data/fuel-prices-for-be-assessment.csv`: the supplied fuel prices.
- `data/places.csv`: one lat/lng per US city and state, built from the GeoNames US postal-code file
  (`python manage.py build_places US.txt`; GeoNames data is CC BY 4.0). It is committed, so you do not need to rebuild it.

## Known limitations
- Station coordinates are city centroids (the CSV has no lat/lng), so mile markers and "distance from route" are approximate.
- The corridor uses straight-line distance (10 miles) from the route, not the real detour.
- The vehicle starts with a full tank that is not charged; cost covers fuel bought en route only.
- Some fill-ups are small (a few gallons): buying just enough to reach a cheaper station is the cheapest plan, so they are kept.
- Canadian stations in the CSV are ignored.
- The CSV has only 8 California stations (all in the far southeast), so California routes often return 422.
- Only the routes OSRM returns (the best plus usually one alternative) are compared, not every possible road.
- Free-text lookups are restricted to US results, so an ambiguous name such as "Toronto, ON" can resolve to a US place of that name.

## Production notes
- Self-host OSRM instead of the public demo server (rate limits, no SLA); same for Nominatim.
- Use a shared cache (Redis) instead of per-process memory, so workers share routes and plans.
- Geocode station addresses for exact positions; add API rate limiting and authentication.
- Set `DEBUG = False`, a real `SECRET_KEY` and `ALLOWED_HOSTS` (the settings are development defaults).
- Use a keyed map tile provider; the map uses Esri's public tiles, which suit a demo.

## Tests
`python manage.py test` runs 34 tests: planner (including a comparison with an exact solver), geocoding, city
matching, the OSRM client with mocked HTTP, route comparison, views and corridor search. No test touches the network.
