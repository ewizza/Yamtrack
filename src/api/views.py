"""Read-only JSON API views for companion apps (e.g. the YAM-TV launcher)."""

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from api.auth import token_auth
from app.models import BasicMedia, Sources, Status
from app.providers import services, tmdb
from users.models import WATCH_PROVIDER_REGION_UNSET, MediaStatusChoices

WATCHLIST_MEDIA_TYPES = ("tv", "movie")
WATCHLIST_STATUSES = {Status.IN_PROGRESS, Status.PLANNING}


@token_auth
@require_GET
def watchlist(request):
    """Return the authenticated user's tracked, TMDB-sourced TV shows and movies."""
    results = []

    for media_type in WATCHLIST_MEDIA_TYPES:
        media_list = BasicMedia.objects.get_media_list(
            user=request.user,
            media_type=media_type,
            status_filter=MediaStatusChoices.ALL,
            sort_filter=None,
        )
        for media in media_list:
            if media.item.source != Sources.TMDB:
                continue
            if media.status not in WATCHLIST_STATUSES:
                continue

            results.append(
                {
                    "media_type": media_type,
                    "media_id": media.item.media_id,
                    "title": media.item.title,
                    "image": media.item.image,
                    "status": media.status,
                },
            )

    return JsonResponse({"results": results})


@token_auth
@require_GET
def providers(request, media_type, tmdb_id):
    """Return TMDB watch-provider availability for a title, region-filtered."""
    try:
        media_metadata = services.get_media_metadata(
            media_type,
            tmdb_id,
            Sources.TMDB.value,
        )
    except services.ProviderAPIError as error:
        return JsonResponse({"detail": str(error)}, status=error.status_code or 502)

    region = request.user.watch_provider_region
    available = tmdb.filter_providers(media_metadata.get("providers"), region) or []

    return JsonResponse(
        {
            "media_type": media_type,
            "tmdb_id": tmdb_id,
            "region_configured": region != WATCH_PROVIDER_REGION_UNSET,
            "providers": [
                {
                    "id": provider.get("provider_id"),
                    "name": provider.get("provider_name"),
                    "logo": provider.get("image"),
                }
                for provider in available
            ],
        },
    )
