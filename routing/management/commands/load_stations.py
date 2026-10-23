import csv

from django.conf import settings
from django.core.management.base import BaseCommand

from routing import gazetteer
from routing.models import Station


CANADIAN_PROVINCES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}


class Command(BaseCommand):
    help = "Load fuel stations from the CSV, geocoding each by city/state (offline, via data/places.csv)."

    def handle(self, **opts):
        best = {}
        with open(settings.BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                sid = int(r["OPIS Truckstop ID"])
                price = float(r["Retail Price"])
                # The file repeats stops; keep the lowest listed price per stop.
                if sid not in best or price < best[sid][0]:
                    best[sid] = (price, r)
        rows, missed, us_missed = [], 0, []
        for sid, (price, r) in best.items():
            pt = gazetteer.lookup(r["City"], r["State"])
            if not pt:
                missed += 1
                if r["State"].strip() not in CANADIAN_PROVINCES:
                    us_missed.append(f"{r['City'].strip()}, {r['State'].strip()}")
                continue
            rows.append(Station(
                truckstop_id=sid, name=r["Truckstop Name"].strip(), address=r["Address"].strip(),
                city=r["City"].strip(), state=r["State"].strip(), price=price, lat=pt[0], lng=pt[1],
            ))
        Station.objects.all().delete()
        Station.objects.bulk_create(rows)
        self.stdout.write(f"Loaded {len(rows)} stations ({missed} skipped: city not found)")
        if us_missed:
            self.stdout.write(f"Unmatched US stations ({len(us_missed)}): {sorted(set(us_missed))}")
