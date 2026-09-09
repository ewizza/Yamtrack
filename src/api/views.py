"""JSON API views for companion apps (e.g. the YAM-TV launcher)."""

import json
import logging

from django.apps import apps
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from api.auth import token_auth
from api.models import DefaultProvider
from app.models import BasicMedia, Item, MediaTypes, Sources, Status
from app.providers import justwatch, services, tmdb
from events.models import Event, SentinelDatetime
from users.models import WATCH_PROVIDER_REGION_UNSET, MediaStatusChoices

logger = logging.getLogger(__name__)

WATCHLIST_MEDIA_TYPES = ("tv", "movie")
DEFAULT_WATCHLIST_STATUSES = {Status.IN_PROGRESS.value, Status.PLANNING.value}


def _next_episodes(tv_media_list, source):
    """Return {media_id: {"season", "episode", "air_date"}} - each show's next episode.

    Mirrors BasicMedia.objects._annotate_tv_released_episodes()'s season-Item
    traversal (an episode's Event is attached to its *season* Item, not the show's
    own Item), but looks forward instead of back: the earliest not-yet-aired
    episode per show. Batched as one query across the whole list to avoid N+1.
    Excludes the far-future sentinel datetime used for episodes with no confirmed
    air date yet - that's not a real date to hand back to a client.
    """
    if not tv_media_list:
        return {}

    media_ids = [media.item.media_id for media in tv_media_list]

    upcoming_events = (
        Event.objects.filter(
            item__media_id__in=media_ids,
            item__source=source,
            item__media_type=MediaTypes.SEASON.value,
            item__season_number__gt=0,
            content_number__isnull=False,
            datetime__gte=timezone.now(),
        )
        .exclude(datetime=SentinelDatetime.max_datetime())
        .select_related("item")
        .order_by("datetime")
    )

    next_episodes = {}
    for event in upcoming_events:
        media_id = event.item.media_id
        # Already ordered by datetime - the first event seen per show is its
        # earliest upcoming episode.
        next_episodes.setdefault(
            media_id,
            {
                "season": event.item.season_number,
                "episode": event.content_number,
                "air_date": event.datetime.date().isoformat(),
            },
        )
    return next_episodes


def _last_activity(media):
    """Return the ISO 8601 timestamp of a media item's most recent progress.

    Sourced from the existing ``progressed_at`` field (a ``MonitorField`` on
    the base ``Media`` model) - it updates only when ``progress`` itself
    changes, not on a status/rating/notes-only edit. Movie's ``progressed_at``
    is a real column that already defaults to creation time, but TV's is a
    property computed across its seasons and is ``None`` until an episode has
    actually been logged - falling back to ``created_at`` normalizes that gap
    so every item always carries a real, non-null timestamp of the same
    shape regardless of media type.
    """
    return (media.progressed_at or media.created_at).isoformat()


def _backdrop_url(media_type, media_id, source):
    """Return a title's backdrop URL, or None if it can't be resolved.

    Reads the ``backdrop`` field ``tmdb.tv()``/``tmdb.movie()`` now resolve
    (a textless backdrop, preferred, or TMDB's plain default) straight off
    ``services.get_media_metadata()``'s cached response - the same 24h
    Redis cache the providers endpoint already rides. TV shows get that
    cache warmed daily regardless of whether the watchlist endpoint is
    ever polled, since ``events/calendar/tv.py``'s ``reload_calendar`` job
    already calls ``tmdb.tv()`` for every tracked show; movies aren't
    covered by that job, so a movie's backdrop lookup may occasionally be
    a fresh TMDB fetch here instead of a cache hit. Either way, a failure
    degrades this one field to ``None`` rather than failing the whole
    watchlist response - same treatment ``justwatch.get_deeplinks()``
    already gets for the providers endpoint.
    """
    try:
        media_metadata = services.get_media_metadata(media_type, media_id, source)
    except services.ProviderAPIError:
        logger.warning(
            "Failed to fetch backdrop metadata for %s %s",
            media_type,
            media_id,
        )
        return None
    return media_metadata.get("backdrop")


def _parse_watchlist_statuses(request):
    """Parse the ``?status=`` query param into a set of Status values, or an error.

    Returns a ``(statuses, error_response)`` tuple. Comma-separated list of
    ``Status`` enum values, e.g. ``?status=Completed`` or
    ``?status=In%20progress,Planning``. Omitted entirely -> today's default
    (``In progress``, ``Planning``), so existing callers see no change unless
    they opt in. Rejects anything outside the fixed 5-value enum, same as
    ``_parse_status()`` does for the status-write endpoint.
    """
    raw = request.GET.get("status")
    if raw is None:
        return DEFAULT_WATCHLIST_STATUSES, None

    requested = {value.strip() for value in raw.split(",") if value.strip()}
    valid_values = {choice.value for choice in Status}
    if not requested or not requested <= valid_values:
        detail = f"status must be one or more of: {', '.join(sorted(valid_values))}."
        return None, JsonResponse({"detail": detail}, status=400)

    return requested, None


@token_auth
@require_GET
def watchlist(request):
    """Return the authenticated user's tracked, TMDB-sourced TV shows and movies.

    Filtered to ``In progress``/``Planning`` by default; pass ``?status=`` to
    opt into other statuses (e.g. ``?status=Completed``) - see
    ``_parse_watchlist_statuses()``.
    """
    statuses, error_response = _parse_watchlist_statuses(request)
    if error_response is not None:
        return error_response

    results = []

    for media_type in WATCHLIST_MEDIA_TYPES:
        media_list = BasicMedia.objects.get_media_list(
            user=request.user,
            media_type=media_type,
            status_filter=MediaStatusChoices.ALL,
            sort_filter=None,
        )
        tracked = [
            media
            for media in media_list
            if media.item.source == Sources.TMDB and media.status in statuses
        ]

        is_tv = media_type == MediaTypes.TV.value
        next_episodes = _next_episodes(tracked, Sources.TMDB.value) if is_tv else {}

        for media in tracked:
            result = {
                "media_type": media_type,
                "media_id": media.item.media_id,
                "title": media.item.title,
                "image": media.item.image,
                "backdrop_url": _backdrop_url(
                    media_type,
                    media.item.media_id,
                    Sources.TMDB.value,
                ),
                "status": media.status,
                "last_activity": _last_activity(media),
            }
            if is_tv:
                result["next_episode"] = next_episodes.get(media.item.media_id)
            results.append(result)

    return JsonResponse({"results": results})


def _get_available_providers(media_type, tmdb_id, region, *, include_deeplinks=True):
    """Return the region-filtered provider list for a title, or an error response.

    Returns a ``(providers, deeplinks, media_metadata, error_response)`` tuple:
    on success ``error_response`` is ``None``. On an upstream failure
    ``providers``, ``deeplinks`` and ``media_metadata`` are all ``None`` and
    ``error_response`` is a ready-to-return ``JsonResponse``. ``deeplinks`` is
    a ``{provider_id: url}`` map - pass ``include_deeplinks=False`` to skip the
    JustWatch lookup entirely for callers (like the default-provider write)
    that don't need it. ``media_metadata`` is the raw dict from
    ``services.get_media_metadata()`` - already fetched here, so callers that
    want synopsis/season-count/runtime (see ``_detail_fields()``) get it for
    free rather than triggering a second call.
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
        return None, None, None, response

    available = tmdb.filter_providers(media_metadata.get("providers"), region) or []

    deeplinks = {}
    if include_deeplinks and available:
        deeplinks = justwatch.get_deeplinks(
            media_type,
            tmdb_id,
            media_metadata.get("title"),
            region,
        )

    providers = [
        {
            "id": provider.get("provider_id"),
            "name": provider.get("provider_name"),
            "logo": provider.get("image"),
            "deeplink": deeplinks.get(provider.get("provider_id")),
        }
        for provider in available
    ]
    return providers, deeplinks, media_metadata, None


def _detail_fields(media_type, media_metadata):
    """Return title/synopsis/season_count (TV) or /runtime (movie) fields.

    All sourced from the same ``media_metadata`` dict ``providers()`` already
    fetched for provider availability - no extra TMDB call or cache lookup.
    ``season_count`` doesn't apply to movies, so a movie gets ``runtime``
    (already a readable string, e.g. "2h 15m", or ``None`` if TMDB doesn't
    know it) in its place instead.
    """
    fields = {
        "title": media_metadata.get("title"),
        "synopsis": media_metadata.get("synopsis"),
    }
    details = media_metadata.get("details") or {}
    if media_type == MediaTypes.TV.value:
        fields["season_count"] = details.get("seasons")
    else:
        fields["runtime"] = details.get("runtime")
    return fields


def _get_item(media_type, tmdb_id):
    """Return the matching TMDB-sourced Item, or None if it isn't tracked yet."""
    return Item.objects.filter(
        media_id=tmdb_id,
        media_type=media_type,
        source=Sources.TMDB.value,
    ).first()


def _serialize_default_provider(item, user, deeplinks):
    """Return the user's saved default provider for an item, or None."""
    preference = DefaultProvider.objects.filter(user=user, item=item).first()
    if preference is None:
        return None
    return {
        "id": preference.provider_id,
        "name": preference.provider_name,
        "deeplink": deeplinks.get(preference.provider_id),
    }


@token_auth
@require_GET
def providers(request, media_type, tmdb_id):
    """Return provider availability and any saved default for a title.

    Region-filtered using the authenticated user's watch_provider_region.
    """
    region = request.user.watch_provider_region
    available, deeplinks, media_metadata, error_response = _get_available_providers(
        media_type,
        tmdb_id,
        region,
    )
    if error_response is not None:
        return error_response

    item = _get_item(media_type, tmdb_id)
    default_provider = (
        _serialize_default_provider(item, request.user, deeplinks) if item else None
    )

    return JsonResponse(
        {
            "media_type": media_type,
            "tmdb_id": tmdb_id,
            "region_configured": region != WATCH_PROVIDER_REGION_UNSET,
            "providers": available,
            "default_provider": default_provider,
            **_detail_fields(media_type, media_metadata),
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
    available, _deeplinks, _media_metadata, error_response = _get_available_providers(
        media_type,
        tmdb_id,
        region,
        include_deeplinks=False,
    )
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


def _get_tracked_media(media_type, item, user):
    """Return the user's TV/Movie tracking record for this item, or None.

    ``status`` lives on the TV/Movie row itself (not a separate preference
    table like ``DefaultProvider``), so unlike the default-provider write
    this requires an existing tracking record - it doesn't create one from
    scratch. Every title the watchlist endpoint surfaces already has one,
    since it's filtered to "In progress"/"Planning" statuses.
    """
    model = apps.get_model(app_label="app", model_name=media_type)
    return model.objects.filter(item=item, user=user).first()


def _parse_status(request):
    """Parse the request body into a valid Status value, or an error response.

    Returns a ``(status, error_response)`` tuple. Rejects anything outside
    Yamtrack's fixed ``Status`` choices (it's a Django enum, not free text)
    rather than passing arbitrary strings through to the model.
    """
    try:
        payload = json.loads(request.body) if request.body else None
    except json.JSONDecodeError:
        return None, JsonResponse({"detail": "Invalid JSON body."}, status=400)

    status = payload.get("status") if isinstance(payload, dict) else None
    valid_values = [choice.value for choice in Status]
    if status not in valid_values:
        response = JsonResponse(
            {"detail": f"status must be one of: {', '.join(valid_values)}."},
            status=400,
        )
        return None, response

    return status, None


@token_auth
@require_http_methods(["PUT"])
def set_status(request, media_type, tmdb_id):
    """Set the authenticated user's watch status for an already-tracked title.

    Setting status has real side effects in Yamtrack itself (e.g. Completed
    fills in progress/watched-episode state) - this endpoint is a thin
    wrapper around the same model save() path the web UI's own status field
    already uses, so those side effects apply exactly the same way here.
    """
    item = _get_item(media_type, tmdb_id)
    media = _get_tracked_media(media_type, item, request.user) if item else None
    if media is None:
        return JsonResponse({"detail": "This title isn't tracked yet."}, status=404)

    status, error_response = _parse_status(request)
    if error_response is not None:
        return error_response

    media.status = status
    media.save()

    return JsonResponse({"status": media.status})
