# Fuel Route Planner (Django 6.1)

`GET /api/route/?start=<place>&finish=<place>` returns the driving route, the cheapest fuel stops along it
(500-mile range, 10 mpg) and the total fuel cost. A place is `City, ST`, a free-text address, or `lat,lng`.
`GET /api/route/map/?start=...&finish=...` renders the same result on a Leaflet map.

## Run
    python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
    python manage.py migrate && python manage.py load_stations   # geocodes the CSV offline
    python manage.py runserver
    curl -G localhost:8000/api/route/ --data-urlencode "start=Los Angeles, CA" --data-urlencode "finish=New York, NY"

## Design
- **One external call per request**: OSRM public API (`router.project-osrm.org`) returns the full route geometry.
  `City, ST` inputs are geocoded offline from `data/places.csv` (GeoNames); only free-text addresses fall
  back to Nominatim (one extra call each, cached). Routes and plans are cached.
- **Stations**: the CSV is deduplicated (lowest price per truckstop ID), Canadian stops dropped, and each stop
  placed at its city centroid (`load_stations`). Held in memory as numpy arrays.
- **Corridor search**: the route is resampled every 2 miles; stations within 10 miles of it get a mile marker.
- **Planner**: greedy "nearest cheaper station in range" – buys only enough fuel to reach a cheaper stop,
  otherwise fills up and heads to the cheapest reachable stop. Optimal for this problem; runs in milliseconds.
- **Small fill-ups**: purchases under 2 gallons are folded into the previous stop when its tank has room.
- **Resilience**: OSRM is called with a 15 s timeout and one retry; failures return a clear JSON error.
- **Assumptions**: tank starts full (free); cost = fuel bought en route (`fuel_consumed_gallons` is also
  returned). Station positions are city-level, so mile markers/offsets are approximate.

## Error responses
All errors are JSON: `{"error": "<message>"}`.

| Status | Meaning | Example |
|---|---|---|
| 400 | Bad input | missing `start`/`finish`; place outside the USA; start and finish are the same place |
| 422 | No drivable route or plan | Honolulu to Los Angeles (`NoRoute`); a 500+ mile gap with no fuel station |
| 502 | Upstream service failed after a retry | OSRM or Nominatim unavailable |

Alaska, Hawaii and Puerto Rico are accepted as places; routing between disconnected regions returns 422.

## Known limitations
- Station coordinates are city centroids (the CSV has no lat/lng), so mile markers and "distance from route" are approximate.
- The corridor uses straight-line distance (10 miles) from the route, not the real detour.
- The vehicle starts with a full tank that is not charged; cost covers fuel bought en route only.
- A few sub-2-gallon fill-ups remain where the previous tank was already full.
- Canadian stations in the CSV are ignored.

## Production notes
- Self-host OSRM instead of the public demo server (rate limits, no SLA); same for Nominatim.
- Use a shared cache (Redis) instead of per-process memory, so workers share routes and plans.
- Geocode station addresses for exact positions; add API rate limiting and authentication.

## Tests
`python manage.py test` runs the suite (planner, geocoding, OSRM client with mocked HTTP, views, corridor search).
No test touches the network.
