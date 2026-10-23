from django.urls import path

from routing.views import RoutePlanView, route_map

urlpatterns = [
    path("api/route/", RoutePlanView.as_view()),
    path("api/route/map/", route_map),
]
