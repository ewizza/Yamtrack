from django.urls import path

from api import views

urlpatterns = [
    path("watchlist", views.watchlist, name="api_watchlist"),
]
