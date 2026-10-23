"""Offline US city lookup built from GeoNames postal data (data/places.csv)."""
import csv
import re
from functools import lru_cache

from django.conf import settings


_ABBREV = {"st": "saint", "ft": "fort", "mt": "mount"}


def _norm(s):
    """Canonical key: abbreviations expanded, all spaces/punctuation dropped ('De Forest' == 'DeForest')."""
    words = re.sub(r"[^a-z0-9]+", " ", s.lower()).split()
    return "".join(_ABBREV.get(w, w) for w in words)


@lru_cache(maxsize=1)
def _load():
    idx = {}
    with open(settings.BASE_DIR / "data" / "places.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pt = (float(r["lat"]), float(r["lng"]))
            idx[(_norm(r["city"]), _norm(r["state"]))] = pt
            idx[(_norm(r["city"]), _norm(r["state_name"]))] = pt
    return idx


def lookup(city, state):
    return _load().get((_norm(city), _norm(state)))
