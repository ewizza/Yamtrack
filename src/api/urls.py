from django.urls import path, register_converter

from api import converters, views

register_converter(converters.TvMovieType, "tv_movie_type")

urlpatterns = [
    path("watchlist", views.watchlist, name="api_watchlist"),
    path(
        "media/<tv_movie_type:media_type>/<str:tmdb_id>/providers",
        views.providers,
        name="api_providers",
    ),
    path(
        "media/<tv_movie_type:media_type>/<str:tmdb_id>/default-provider",
        views.set_default_provider,
        name="api_default_provider",
    ),
]
