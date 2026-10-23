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
- **Assumptions**: tank starts full (free); cost = fuel bought en route (`fuel_consumed_gallons` is also
  returned). Station positions are city-level, so mile markers/offsets are approximate.

`python manage.py test` runs the planner unit tests.
