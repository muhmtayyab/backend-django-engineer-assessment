import hashlib

import numpy as np
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.template.loader import render_to_string
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .services import PlanError


def build_plan(start_text, finish_text):
    a, b = services.geocode(start_text), services.geocode(finish_text)
    if services.haversine_miles(a, b) < services.MIN_TRIP_MILES:
        raise PlanError("Start and finish are the same place.", 400)
    coords, miles = services.fetch_route(a, b)
    stops = services.stations_along(coords, miles)
    plan = services.plan_fuel(stops, miles)
    mpg = settings.VEHICLE_MPG

    fuel_stops, total_cost = [], 0.0
    for p in plan:
        st, mile, offset = p["stop"]
        gallons = p["miles"] / mpg
        cost = gallons * st.price
        total_cost += cost
        fuel_stops.append({
            "name": st.name, "address": st.address, "city": st.city, "state": st.state,
            "location": {"lat": st.lat, "lng": st.lng},
            "price_per_gallon": round(st.price, 3),
            "mile_marker": round(mile, 1),
            "distance_from_route_miles": round(offset, 1),
            "gallons_purchased": round(gallons, 2),
            "cost": round(cost, 2),
        })
    return {
        "start": {"query": start_text, "lat": a[0], "lng": a[1]},
        "finish": {"query": finish_text, "lat": b[0], "lng": b[1]},
        "distance_miles": round(miles, 1),
        "fuel_consumed_gallons": round(miles / mpg, 2),
        "assumptions": {
            "vehicle_range_miles": settings.VEHICLE_RANGE_MILES,
            "miles_per_gallon": mpg,
            "starts_with_full_tank": True,
            "note": "Cost covers fuel bought en route; the starting tank is not charged. "
                    "Station coordinates are city-level approximations.",
        },
        "fuel_stops": fuel_stops,
        "total_fuel_cost": round(total_cost, 2),
        "route": {"type": "Feature", "properties": {}, "geometry": {
            "type": "LineString", "coordinates": coords_list(coords)}},
    }


def coords_list(coords, min_gap_miles=0.3):
    """Thin the polyline for the response (planning already used the full geometry)."""
    step = np.hypot(np.diff(coords[:, 0]) * np.cos(np.radians(coords[:-1, 1])), np.diff(coords[:, 1])) * 69.0
    cum = np.concatenate([[0.0], np.cumsum(step)])
    bucket = (cum // min_gap_miles).astype(int)
    keep = np.concatenate([[True], bucket[1:] != bucket[:-1]])
    keep[-1] = True
    return np.round(coords[keep], 5).tolist()


class RoutePlanView(APIView):
    """GET /api/route/?start=<place>&finish=<place>  (place: 'City, ST', address, or 'lat,lng')"""

    def get(self, request):
        start, finish = request.query_params.get("start"), request.query_params.get("finish")
        if not start or not finish:
            return Response({"error": "Both 'start' and 'finish' query parameters are required."}, status=400)
        key = "plan:" + hashlib.md5(f"{start.strip().lower()}|{finish.strip().lower()}".encode()).hexdigest()
        data = cache.get(key)
        if data is None:
            try:
                data = build_plan(start, finish)
            except PlanError as e:
                return Response({"error": str(e)}, status=e.status)
            cache.set(key, data, 3600)
        data = dict(data)
        data["map_url"] = request.build_absolute_uri("/api/route/map/") + "?" + request.META["QUERY_STRING"]
        return Response(data)


def route_map(request):
    """HTML map (Leaflet) that renders the JSON from the API above."""
    return HttpResponse(render_to_string("routing/map.html"))
