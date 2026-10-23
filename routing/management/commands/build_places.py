import csv
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Collapse a GeoNames US.txt postal file into data/places.csv (one centroid per city/state)."

    def add_arguments(self, parser):
        parser.add_argument("us_txt")

    def handle(self, us_txt, **opts):
        acc = defaultdict(lambda: [0.0, 0.0, 0, ""])
        with open(us_txt, encoding="utf-8") as f:
            for row in csv.reader(f, delimiter="\t"):
                city, state_name, st = row[2], row[3], row[4]
                if not st:
                    continue
                a = acc[(city, st)]
                a[0] += float(row[9])
                a[1] += float(row[10])
                a[2] += 1
                a[3] = state_name
        out = settings.BASE_DIR / "data" / "places.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["city", "state", "state_name", "lat", "lng"])
            for (city, st), (la, ln, n, sn) in sorted(acc.items()):
                w.writerow([city, st, sn, round(la / n, 5), round(ln / n, 5)])
        self.stdout.write(f"Wrote {len(acc)} places to {out}")
