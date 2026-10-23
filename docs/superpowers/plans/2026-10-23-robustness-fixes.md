# Fuel Route Planner Robustness Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the known correctness and robustness gaps in the existing fuel-route API so it holds up in a live demo and code review.

**Architecture:** Existing Django 6.1.2 + DRF app `routing` (`services.py` = geocode/OSRM/corridor/planner, `views.py` = endpoint, `gazetteer.py` = offline city lookup, `management/commands/load_stations.py` = CSV loader). Changes are local to those files plus a new `tests/` package; no new dependencies except `unittest.mock` from the stdlib.

**Tech Stack:** Django 6.1.2, DRF 3.18.3, numpy, requests, SQLite, Django test runner.

**Spec:** Conversation requirements, 2026-10-22/23: original assignment (500-mile range, 10 mpg, one OSRM call ideal, fast responses) plus the 10-item gap list agreed with the user. No separate spec file.

## Global Constraints

- Django stays at `6.1.2`; do not add dependencies beyond `requirements.txt` as-is.
- Vehicle range 500 miles, 10 mpg (`settings.VEHICLE_RANGE_MILES`, `settings.VEHICLE_MPG`); corridor 10 miles (`settings.STATION_CORRIDOR_MILES`).
- At most one OSRM call per request (plus one cached Nominatim call per free-text address).
- Error responses are JSON `{"error": str}` with status 400 (bad input), 422 (no route/plan), 502 (upstream failure).
- Tests must not hit the network: mock `requests.get` / `services.fetch_route`.
- Run tests with `. .venv/bin/activate && python manage.py test`.

## Review Focus

- Start equals finish (or under 0.1 mile apart): 400, no OSRM call.
- Alaska/Hawaii/Puerto Rico place names: accepted by geocoding; OSRM `NoRoute` becomes 422 "no drivable route", not "not in the USA".
- OSRM timeout / non-JSON / HTTP 5xx: 502 with message, after one retry.
- Station table empty at first request, loaded later: later requests see the stations (no permanent empty cache).
- Trip needing fuel with a 500+ mile station-free gap: 422 with clear message, never a 500.

---

### Task 0: Initialize git

**Files:** Modify `.gitignore` (add `data/_gn/`, `*.pyc`)

- [ ] **Step 1:** `git init`, then `git add -A && git commit -m "chore: baseline fuel route planner"`
- [ ] **Step 2:** Verify `git status` is clean and `.venv/`, `db.sqlite3` are not tracked (`git ls-files | grep -E "venv|sqlite"` prints nothing).

### Task 1: Fix station cache and remove startup thread

**Files:**
- Modify: `routing/services.py` (`_station_arrays`), `routing/apps.py`
- Test: `routing/tests/test_stations.py` (convert `routing/tests.py` into package `routing/tests/` with `__init__.py`; move existing planner tests to `test_planner.py`)

**Interfaces:**
- Produces: `services._station_arrays() -> tuple[list[Station], np.ndarray, np.ndarray]`, thread-safe, lazily loaded, never caches an empty result; `services.reset_station_cache() -> None` for tests.

- [ ] **Step 1: Write failing test** `StationCacheTests.test_empty_table_not_cached` (`django.test.TestCase`): call `_station_arrays()` with no stations (assert `len(rows) == 0`), create one `Station`, call again, assert `len(rows) == 1`. Call `reset_station_cache()` in `setUp`.
- [ ] **Step 2:** Run `python manage.py test routing.tests.test_stations` — expect FAIL (stale empty cache).
- [ ] **Step 3:** In `_station_arrays`, guard with a module-level `threading.Lock`; only assign `_stations` when `rows` is non-empty. Add `reset_station_cache()`. Make `RoutingConfig.ready` a no-op (delete the warm thread); keep the class.
- [ ] **Step 4:** Run full suite — expect PASS.
- [ ] **Step 5:** Commit `fix: lazy thread-safe station cache, drop startup thread`.

### Task 2: Better city matching and a miss report in station loading

**Files:**
- Modify: `routing/gazetteer.py` (`_norm`, `lookup`), `routing/management/commands/load_stations.py`
- Test: `routing/tests/test_gazetteer.py`

**Interfaces:**
- Produces: `gazetteer.lookup(city: str, state: str) -> tuple[float, float] | None` now tolerant of: trailing whitespace, case, `Saint/St/St.`, `Fort/Ft/Ft.`, `Mount/Mt`, internal spaces (`De Forest` ↔ `DeForest`), `Mc ` prefix spacing. `load_stations` prints the unmatched **US-state** rows (skip the Canadian provinces `AB BC MB NB NL NS NT NU ON PE QC SK YT`) so nothing real is silently dropped.

- [ ] **Step 1: Write failing tests** (use a small fixture CSV via `override_settings(BASE_DIR=tmp)` or patch `gazetteer._load`): `lookup("De Forest", "WI")` and `lookup("DeForest", "WI")` return the same point; `lookup("Fort Worth   ", "TX")` and `lookup("Ft. Worth", "TX")` match; `lookup("Nowhere", "TX") is None`.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Implement normalization: key = lowercase, abbreviations expanded to canonical (`st.`→`saint`, `ft`→`fort`, `mt`→`mount`), then **all non-alphanumerics removed including spaces**. Rebuild index with the same function. In `load_stations`, after loading, list unmatched non-Canadian `(city, state)` pairs on stdout.
- [ ] **Step 4:** Run suite; then `python manage.py load_stations` and confirm the unmatched US list is short (record the count in the commit message).
- [ ] **Step 5:** Commit `fix: tolerant city matching, report unmatched US stations`.

### Task 3: Geocoding bounds and input edge cases

**Files:**
- Modify: `routing/services.py` (`geocode`, `PlanError` users), `routing/views.py` (`build_plan`)
- Test: `routing/tests/test_geocode.py`

**Interfaces:**
- Produces: `services.geocode(text: str) -> tuple[float, float]` accepting points in the contiguous US box (24–50N, -125…-66), Alaska (51–72N, -180…-129), Hawaii (18.5–22.5N, -161…-154), Puerto Rico (17.5–18.7N, -68…-65); outside → `PlanError(400)`. `build_plan` raises `PlanError("Start and finish are the same place.", 400)` when haversine distance < 0.1 mile, before calling OSRM.

- [ ] **Step 1: Write failing tests**: `geocode("61.2,-149.9")` (Anchorage) returns a point; `geocode("48.85,2.35")` raises `PlanError` with status 400; `geocode("Honolulu, HI")` works via the gazetteer; `build_plan("Dallas, TX", "Dallas, TX")` raises `PlanError` and `fetch_route` (patched) is not called.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Replace `CONTIG_US` with a list of bounding boxes and an `_in_us(lat, lng)` helper; add the same-place check in `build_plan`.
- [ ] **Step 4:** Run suite — expect PASS.
- [ ] **Step 5:** Commit `feat: accept AK/HI/PR bounds, reject identical start and finish`.

### Task 4: Resilient OSRM client

**Files:**
- Modify: `routing/services.py` (`fetch_route`), `config/settings.py` (`OSRM_TIMEOUT = 15`, `OSRM_RETRIES = 1`)
- Test: `routing/tests/test_osrm.py`

**Interfaces:**
- Produces: `fetch_route(a, b) -> (np.ndarray, float)` unchanged shape; retries once on `requests.RequestException`, HTTP >=500, or non-JSON body; `{"code": "NoRoute"}` → `PlanError(..., 422)` with message containing "No drivable route"; persistent failure → `PlanError(..., 502)`.

- [ ] **Step 1: Write failing tests** (patch `routing.services.requests.get`, clear cache in `setUp` with `django.core.cache.cache.clear()`): (a) first call raises `requests.Timeout`, second returns valid JSON → succeeds, `get` called twice; (b) two timeouts → `PlanError.status == 502`; (c) `NoRoute` payload → status 422; (d) a second identical call is served from cache (`get` call count unchanged).
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Wrap the request in a loop of `1 + OSRM_RETRIES` attempts; do not retry on `NoRoute`.
- [ ] **Step 4:** Run suite — expect PASS.
- [ ] **Step 5:** Commit `feat: OSRM retry, timeouts and clear error statuses`.

### Task 5: Minimum purchase in the planner

**Files:**
- Modify: `routing/services.py` (`plan_fuel`), `config/settings.py` (`MIN_PURCHASE_GALLONS = 2`)
- Test: `routing/tests/test_planner.py`

**Interfaces:**
- Produces: `plan_fuel(stops, total_miles)` unchanged signature/return. Postcondition: any stop whose purchase is under `MIN_PURCHASE_GALLONS * VEHICLE_MPG` miles of range is removed and its miles added to the previous stop's purchase **only if** that does not exceed a full tank at the previous stop; otherwise it is kept. Total range purchased and feasibility (never below 0 fuel between stops) are unchanged.

- [ ] **Step 1: Write failing test**: stops at miles 300 ($3.00), 790 ($2.90), trip 1000: assert no returned `p["miles"]` is positive but under 20, and an invariant check helper simulates the plan (fuel never < 0, ends with ≥ 0) for this case and for the existing three tests.
- [ ] **Step 2:** Run — expect FAIL.
- [ ] **Step 3:** Add a post-pass over the plan implementing the rule above; add the feasibility simulator as a test helper.
- [ ] **Step 4:** Run suite — expect PASS.
- [ ] **Step 5:** Commit `feat: merge tiny fuel purchases`.

### Task 6: View and corridor tests, plus real-route checks

**Files:**
- Test: `routing/tests/test_views.py`, `routing/tests/test_corridor.py`

**Interfaces:**
- Consumes: `services.fetch_route`, `services.stations_along(coords, total_miles) -> list[tuple[Station, float, float]]`, `RoutePlanView`.

- [ ] **Step 1: Write tests** (patch `routing.views.services.fetch_route` to return a straight 1200-mile synthetic line; create `Station` rows along it): 200 response has keys `route`, `fuel_stops`, `total_fuel_cost`, `distance_miles`, `map_url`; `total_fuel_cost == round(sum(stop cost), 2)`; missing `finish` → 400; both places outside US → 400; no stations on a 1200-mile route → 422; `stations_along` excludes a station 30 miles off the line and includes one 5 miles off; a second identical request does not call `fetch_route` again.
- [ ] **Step 2:** Run — expect PASS or fix any bug these expose (note each in the commit message).
- [ ] **Step 3:** Manual real-route checks against live OSRM: LA→NYC, Seattle→Miami, Dallas→Houston, `Honolulu, HI`→`Los Angeles, CA` (expect 422), identical start/finish (expect 400). Record results in the commit message.
- [ ] **Step 4:** Commit `test: view and corridor coverage`.

### Task 7: Map check and README

**Files:**
- Modify: `README.md`

- [ ] **Step 1:** Start the server (`python manage.py runserver`), open `/api/route/map/?start=Los%20Angeles,%20CA&finish=New%20York,%20NY` in a browser and confirm route line, start/finish markers, stop popups and the info box render. Fix `routing/templates/routing/map.html` if not.
- [ ] **Step 2:** Add README sections "Error responses" (400/422/502 table), "Known limitations" (city-centroid station positions, straight-line corridor distance, first-tank free) and "Production notes" (self-hosted OSRM, Redis cache, real station geocoding, rate limiting).
- [ ] **Step 3:** Run full suite once more, then commit `docs: error table, limitations, production notes`.
