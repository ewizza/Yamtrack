"""Per-provider deep links, sourced from JustWatch's unofficial GraphQL API.

TMDB's own ``watch/providers`` data (see ``app.providers.tmdb``) only exposes one
aggregate, region-level JustWatch listing link - not a URL to a title's page on
each streaming service. Getting a real per-provider deep link (e.g. straight to
a title on netflix.com) means asking JustWatch directly.

This uses the free, unofficial ``simple-justwatch-python-api`` package rather
than JustWatch's paid Partner API - appropriate for a single-user, self-hosted
deployment. It's a reverse-engineered client with no SLA, so every call here is
best-effort: any failure (network, no match, a schema change upstream) degrades
to "no deep link available" rather than breaking the caller. A deep link is a
nice-to-have on top of the availability data TMDB already provides, never a
requirement for the provider endpoint to function.

Provider matching: JustWatch's own ``package_id`` for a platform (e.g. ``8`` for
Netflix) matches TMDB's ``provider_id`` for the same platform - confirmed by
spiking the API against real titles, since neither service documents this.
Matching by that numeric id (rather than name/technical_name) also naturally
excludes near-duplicate JustWatch packages for the same platform (e.g. "Netflix
Standard with Ads" carries a different package_id and is skipped).

Title matching: JustWatch search results carry TMDB's own id (``tmdb_id`` on
each ``MediaEntry``), so resolving a TMDB id to a JustWatch entry is an exact-id
match on search results, not fuzzy title/year matching.
"""

import logging

from django.core.cache import cache
from simplejustwatchapi.justwatch import offers_for_countries, search

from app.models import MediaTypes

logger = logging.getLogger(__name__)

# A title's JustWatch entry never changes once matched - cache indefinitely.
NODE_ID_CACHE_TIMEOUT = None
# A deep link for a given provider rarely changes; refetch periodically rather
# than on every request, since this is an unofficial API best used sparingly.
OFFERS_CACHE_TIMEOUT = 60 * 60 * 24 * 7  # 7 days

# Only these monetization types correspond to what tmdb.filter_providers()
# already surfaces as "available" (subscription/free tiers) - rent/buy offers
# are out of scope here.
INCLUDED_MONETIZATION_TYPES = frozenset({"FLATRATE", "FREE"})

# JustWatch's search object_types filter, keyed by Yamtrack's own media type.
_OBJECT_TYPES = {
    MediaTypes.TV.value: "SHOW",
    MediaTypes.MOVIE.value: "MOVIE",
}

# No match found for a title, cached so repeated lookups don't keep retrying.
_NO_MATCH_SENTINEL = ""


def get_deeplinks(media_type, tmdb_id, title, region):
    """Return {tmdb_provider_id: deeplink_url} for a title in a region.

    Best-effort: returns {} on any failure, including no JustWatch match,
    an upstream error, or a region JustWatch has no offers for.
    """
    if not title or not region:
        return {}

    try:
        node_id = _find_node_id(media_type, tmdb_id, title, region)
        if node_id is None:
            return {}
        return _get_offer_deeplinks(node_id, region)
    except Exception:
        logger.exception(
            "JustWatch deep link lookup failed for %s tmdb_id=%s",
            media_type,
            tmdb_id,
        )
        return {}


def _find_node_id(media_type, tmdb_id, title, region):
    """Resolve a TMDB id to its JustWatch entry id via title search.

    Cached indefinitely once resolved (or once confirmed unmatched) - a
    title's JustWatch entry doesn't depend on the requesting user's region,
    so the cache key deliberately excludes it.
    """
    cache_key = f"justwatch_node_id_{media_type}_{tmdb_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached or None

    object_type = _OBJECT_TYPES.get(media_type)
    if object_type is None:
        cache.set(cache_key, _NO_MATCH_SENTINEL, timeout=NODE_ID_CACHE_TIMEOUT)
        return None

    results = search(title, region, "en", 5, object_types=[object_type])
    match = next((r for r in results if r.tmdb_id == str(tmdb_id)), None)
    node_id = match.entry_id if match else _NO_MATCH_SENTINEL

    cache.set(cache_key, node_id, timeout=NODE_ID_CACHE_TIMEOUT)
    return node_id or None


def _get_offer_deeplinks(node_id, region):
    """Return {tmdb_provider_id: deeplink_url} for a JustWatch entry."""
    cache_key = f"justwatch_offers_{node_id}_{region}"
    deeplinks = cache.get(cache_key)
    if deeplinks is not None:
        return deeplinks

    offers_by_country = offers_for_countries(node_id, {region})
    deeplinks = {}
    for offer in offers_by_country.get(region, []):
        if offer.monetization_type not in INCLUDED_MONETIZATION_TYPES:
            continue
        provider_id = offer.package.package_id
        # Keep the first (highest-relevance) offer per provider.
        deeplinks.setdefault(provider_id, offer.url)

    cache.set(cache_key, deeplinks, timeout=OFFERS_CACHE_TIMEOUT)
    return deeplinks
