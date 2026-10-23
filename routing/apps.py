import threading

from django.apps import AppConfig


class RoutingConfig(AppConfig):
    name = "routing"

    def ready(self):
        # Warm the in-memory lookups so the first request isn't slow.
        def warm():
            try:
                from . import gazetteer, services
                gazetteer._load()
                services._station_arrays()
            except Exception:
                pass  # e.g. before migrations/load_stations; lazy loading still works
        threading.Thread(target=warm, daemon=True).start()
