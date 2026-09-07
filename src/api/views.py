"""JSON API views for companion apps (e.g. the YAM-TV launcher)."""

import json

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from api.auth import token_auth
from api.models import DefaultProvider
from app.models import BasicMedia, Item, Sources, Status
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


def _get_available_providers(media_type, tmdb_id, region):
    """Return the region-filtered provider list for a title, or an error response.

    Returns a ``(providers, error_response)`` tuple: on success ``error_response``
    is ``None``. On an upstream failure ``providers`` is ``None`` and
    ``error_response`` is a ready-to-return ``JsonResponse``.
    """
    try:
        media_metadata = services.get_media_metadata(
            media_type,
            tmdb_id,
            Sources.TMDB.value,
        )
    except services.ProviderAPIError as error:
        response = JsonResponse(
            {"detail": str(error)},
            status=error.status_code or 502,
        )
        return None, response

    available = tmdb.filter_providers(media_metadata.get("providers"), region) or []
    providers = [
        {
            "id": provider.get("provider_id"),
            "name": provider.get("provider_name"),
            "logo": provider.get("image"),
        }
        for provider in available
    ]
    return providers, None


def _get_item(media_type, tmdb_id):
    """Return the matching TMDB-sourced Item, or None if it isn't tracked yet."""
    return Item.objects.filter(
        media_id=tmdb_id,
        media_type=media_type,
        source=Sources.TMDB.value,
    ).first()


def _serialize_default_provider(item, user):
    """Return the user's saved default provider for an item, or None."""
    preference = DefaultProvider.objects.filter(user=user, item=item).first()
    if preference is None:
        return None
    return {"id": preference.provider_id, "name": preference.provider_name}


@token_auth
@require_GET
def providers(request, media_type, tmdb_id):
    """Return provider availability and any saved default for a title.

    Region-filtered using the authenticated user's watch_provider_region.
    """
    region = request.user.watch_provider_region
    available, error_response = _get_available_providers(media_type, tmdb_id, region)
    if error_response is not None:
        return error_response

    item = _get_item(media_type, tmdb_id)
    default_provider = _serialize_default_provider(item, request.user) if item else None

    return JsonResponse(
        {
            "media_type": media_type,
            "tmdb_id": tmdb_id,
            "region_configured": region != WATCH_PROVIDER_REGION_UNSET,
            "providers": available,
            "default_provider": default_provider,
        },
    )


def _parse_provider_id(request):
    """Parse the request body into a provider_id, or an error response.

    Returns a ``(provider_id, error_response)`` tuple. ``provider_id`` is
    ``None`` both when the request means "clear the preference" (empty body,
    JSON ``null``, or ``{"provider_id": null}``) and when parsing failed —
    check ``error_response`` first to tell the two apart.
    """
    try:
        payload = json.loads(request.body) if request.body else None
    except json.JSONDecodeError:
        return None, JsonResponse({"detail": "Invalid JSON body."}, status=400)

    provider_id = payload.get("provider_id") if isinstance(payload, dict) else None
    if provider_id is not None and not isinstance(provider_id, int):
        response = JsonResponse(
            {"detail": "provider_id must be an integer or null."},
            status=400,
        )
        return None, response

    return provider_id, None


@token_auth
@require_http_methods(["PUT"])
def set_default_provider(request, media_type, tmdb_id):
    """Set or clear the authenticated user's saved default provider for a title."""
    item = _get_item(media_type, tmdb_id)
    if item is None:
        return JsonResponse({"detail": "This title isn't tracked yet."}, status=404)

    provider_id, error_response = _parse_provider_id(request)
    if error_response is not None:
        return error_response

    if provider_id is None:
        DefaultProvider.objects.filter(user=request.user, item=item).delete()
        return JsonResponse({"default_provider": None})

    region = request.user.watch_provider_region
    available, error_response = _get_available_providers(media_type, tmdb_id, region)
    if error_response is not None:
        return error_response

    match = next((p for p in available if p["id"] == provider_id), None)
    if match is None:
        return JsonResponse(
            {"detail": "provider_id is not currently available for this title."},
            status=400,
        )

    DefaultProvider.objects.update_or_create(
        user=request.user,
        item=item,
        defaults={"provider_id": match["id"], "provider_name": match["name"]},
    )
    default_provider = {"id": match["id"], "name": match["name"]}
    return JsonResponse({"default_provider": default_provider})
