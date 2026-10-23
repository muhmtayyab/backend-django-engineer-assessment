"""Geocoding, routing (one OSRM call) and the fuel-stop planner."""
import hashlib
import re
import threading

import numpy as np
import requests
from django.conf import settings
from django.core.cache import cache

from . import gazetteer
from .models import Station

EARTH_MILES = 3958.8
METERS_PER_MILE = 1609.344
CONTIG_US = (24.0, 50.0, -125.0, -66.0)  # lat_min, lat_max, lng_min, lng_max


class PlanError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---------- geocoding ----------

def geocode(text):
    """'lat,lng' | 'City, ST' (offline) | free-text address (Nominatim, cached)."""
    text = text.strip()
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", text)
    if m:
        lat, lng = float(m[1]), float(m[2])
    else:
        lat = lng = None
        m = re.fullmatch(r"([^,]+),\s*([A-Za-z .]+?)(?:,\s*(?:USA?|United States))?", text)
        if m:
            pt = gazetteer.lookup(m[1], m[2])
            if pt:
                lat, lng = pt
        if lat is None:
            lat, lng = _nominatim(text)
    if not (CONTIG_US[0] <= lat <= CONTIG_US[1] and CONTIG_US[2] <= lng <= CONTIG_US[3]):
        raise PlanError(f"Location '{text}' is not within the contiguous USA.")
    return lat, lng


def _nominatim(text):
    key = "geo:" + hashlib.md5(text.lower().encode()).hexdigest()
    hit = cache.get(key)
    if hit:
        return hit
    try:
        r = requests.get(
            settings.NOMINATIM_URL,
            params={"q": text, "format": "json", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": settings.HTTP_USER_AGENT}, timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise PlanError(f"Geocoding service unavailable: {e}", 502)
    if not data:
        raise PlanError(f"Could not find location '{text}' in the USA.")
    pt = (float(data[0]["lat"]), float(data[0]["lon"]))
    cache.set(key, pt, 86400)
    return pt


# ---------- routing ----------

def fetch_route(a, b):
    """Single OSRM call. Returns (coords as Nx2 [lng, lat] array, distance in miles)."""
    key = f"route:{a[0]:.4f},{a[1]:.4f};{b[0]:.4f},{b[1]:.4f}"
    hit = cache.get(key)
    if hit:
        return hit
    url = f"{settings.OSRM_URL}/{a[1]},{a[0]};{b[1]},{b[0]}"
    try:
        r = requests.get(url, params={"overview": "full", "geometries": "geojson"}, timeout=20)
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        raise PlanError(f"Routing service unavailable: {e}", 502)
    if data.get("code") != "Ok":
        raise PlanError(f"No drivable route found ({data.get('code')}).", 422)
    route = data["routes"][0]
    result = (np.asarray(route["geometry"]["coordinates"], dtype=float), route["distance"] / METERS_PER_MILE)
    cache.set(key, result, 3600)
    return result


# ---------- stations ----------

_stations = None
_stations_lock = threading.Lock()


def _station_arrays():
    """Station rows + lat/lng arrays, loaded once. An empty table is never cached."""
    global _stations
    with _stations_lock:
        if _stations is not None:
            return _stations
        rows = list(Station.objects.all())
        arrays = (
            rows,
            np.array([s.lat for s in rows]),
            np.array([s.lng for s in rows]),
        )
        if rows:
            _stations = arrays
        return arrays


def reset_station_cache():
    global _stations
    with _stations_lock:
        _stations = None


def stations_along(coords, total_miles):
    """Stations within the corridor of the route, with their mile marker along it."""
    rows, lats, lngs = _station_arrays()
    # Resample the polyline to ~2 mile spacing so nearest-point matching is accurate.
    seg = np.hypot(np.diff(coords[:, 0]) * np.cos(np.radians(coords[:-1, 1])), np.diff(coords[:, 1])) * 69.0
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    cum *= total_miles / cum[-1] if cum[-1] else 1.0  # align to OSRM road distance
    miles = np.linspace(0, total_miles, max(2, int(total_miles / 2) + 1))
    plng = np.interp(miles, cum, coords[:, 0])
    plat = np.interp(miles, cum, coords[:, 1])

    corridor = settings.STATION_CORRIDOR_MILES
    pad = corridor / 69.0 + 0.05
    box = (lats >= plat.min() - pad) & (lats <= plat.max() + pad) & \
          (lngs >= plng.min() - pad * 1.5) & (lngs <= plng.max() + pad * 1.5)
    idx = np.flatnonzero(box)
    if not idx.size:
        return []
    out = []
    for chunk in np.array_split(idx, max(1, idx.size // 1500 + 1)):
        dlat = (lats[chunk, None] - plat[None, :]) * 69.0
        dlng = (lngs[chunk, None] - plng[None, :]) * 69.0 * np.cos(np.radians(lats[chunk, None]))
        d2 = dlat * dlat + dlng * dlng
        nearest = d2.argmin(axis=1)
        dist = np.sqrt(d2[np.arange(len(chunk)), nearest])
        for k in np.flatnonzero(dist <= corridor):
            out.append((rows[chunk[k]], float(miles[nearest[k]]), float(dist[k])))
    out.sort(key=lambda t: t[1])
    return out


# ---------- planner ----------

def plan_fuel(stops, total_miles):
    """Cheapest refuelling plan. Tank starts full; buy only what is needed.

    Greedy "nearest cheaper station in range" (optimal for the gas-station problem):
    at each stop buy just enough to reach a cheaper stop, else fill up and go to the
    cheapest stop reachable on a full tank. The destination acts as a free stop.
    Returns [{"stop": (Station, mile, offset), "miles": range_bought_in_miles}].
    """
    rng = settings.VEHICLE_RANGE_MILES
    if total_miles <= rng:
        return []
    nodes = [n for n in stops if 0 < n[1] < total_miles]
    pos, fuel, cur, plan = 0.0, float(rng), None, []  # fuel = miles of range left
    while True:
        window = fuel if cur is None else rng
        reach = [n for n in nodes if pos < n[1] <= pos + window + 1e-9]
        if cur is None:
            # Start: free fuel, so head for the cheapest stop within range.
            if not reach:
                raise PlanError("No fuel station within vehicle range of the start.", 422)
            target = min(reach, key=lambda n: (n[0].price, -n[1]))
            buy = 0.0
        else:
            cheaper = next((n for n in reach if n[0].price < cur[0].price), None)
            if cheaper is None and total_miles - pos <= rng + 1e-9:
                plan[-1]["miles"] += max(0.0, total_miles - pos - fuel)
                return plan
            if cheaper:
                target, buy = cheaper, max(0.0, cheaper[1] - pos - fuel)
            elif reach:
                target, buy = min(reach, key=lambda n: (n[0].price, -n[1])), rng - fuel
            else:
                raise PlanError("Gap between fuel stations on this route exceeds vehicle range.", 422)
            plan[-1]["miles"] += buy
        fuel += buy - (target[1] - pos)
        pos, cur = target[1], target
        plan.append({"stop": target, "miles": 0.0})
