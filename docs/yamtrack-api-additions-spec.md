# Yamtrack Fork — API Additions Spec

**Project**: Eric's Yamtrack fork (existing Claude Code project, Docker on the home server)
**Why**: supports a new companion project, the YAM-TV Launcher Android TV app (see `yam-tv-launcher-app-spec.md`, same Research folder). This doc covers only the changes needed *inside Yamtrack* — the TV app itself is a separate project/spec.
**Status**: ✅ Milestones 1-3 built and pushed to `origin/yamtv-api-additions`. ✅ Milestones 5 (deep links) and 6 (next-episode badge) built and committed locally, not yet pushed or tested end-to-end. Not yet merged to `dev` or opened as a PR — pending end-to-end testing against the Docker deployment.
**Last updated**: 2026-09-08

## 1. Context

Yamtrack already knows two things the TV app needs: the user's watchlist (TMDB-backed) and, per title, which streaming providers currently carry it (calls TMDB's `watch/providers` endpoint live, filtered to the user's configured region via `filter_providers()` in `src/app/providers/tmdb.py`, rendered into the `media_details` HTML view). Neither is currently exposed as a reusable API — both are baked into Django HTML views/templates.

Rather than have the TV app duplicate this (its own TMDB calls, its own region-filtering, a second API key to manage), Yamtrack gets three small additions. This keeps Yamtrack the single source of truth for watchlist + availability + the new provider preference.

## 2. Additions needed

### 2.1 Watchlist read endpoint ✅ Built (Milestone 1)
`GET /api/watchlist`
- Returns the user's tracked TV shows and movies with status `In progress` or `Planning` (TMDB-sourced only), with TMDB IDs, titles, poster path, and watch status.
- Auth: `Authorization: Token <token>` header, reusing the existing `User.token` field (see §4 resolution below).
- Implementation: `src/api/views.py` (`watchlist`), `src/api/auth.py` (`token_auth`).

### 2.2 Providers-as-JSON endpoint ✅ Built (Milestone 2)
`GET /api/media/<tv|movie>/<tmdb_id>/providers`
- Wraps `services.get_media_metadata()` + the existing `filter_providers()` function directly — same Redis cache `media_details` already populates, no duplicate TMDB calls.
- Returns JSON: region-filtered provider list (`id`/`name`/`logo` per provider), plus a `region_configured` flag (see §4 resolution — `filter_providers()` can't itself distinguish "no region set" from "no providers in your region", so the endpoint checks this explicitly).
- An unknown/invalid `tmdb_id` returns a clean JSON error (real upstream status code) instead of the app's HTML 500 page.
- Implementation: `src/api/views.py` (`providers`, `_get_available_providers`).

### 2.3 Default-provider preference (new data) ✅ Built (Milestone 3)
- New `DefaultProvider` model (`src/api/models.py`): per-user, per-`Item` chosen provider, unique on `(user, item)`.
- Written by the TV app when Eric checks "always use this" in the provider picker (see app spec §5 for the UX this supports).
- Read back as part of §2.2's response: `GET .../providers` includes a nullable `default_provider` (`{"id", "name"}`) in the same response — no second round-trip needed.
- `PUT /api/media/<tv|movie>/<tmdb_id>/default-provider` sets or clears it. Body is `{"provider_id": <TMDB provider id>}` or `null`/empty body to clear — **note this ended up keyed by `provider_id`, not the provider-name string this section originally sketched (`{"provider": "Hulu"}`)**, since §2.2's response already hands the client that numeric id and matching by id avoids name-collision/typo edge cases. The write is re-validated against the title's current region-filtered availability before saving.
- Implementation: `src/api/views.py` (`set_default_provider`, `_parse_provider_id`).

## 3. Explicit non-goals for this project

- No streaming-service deep-linking logic lives here — that's entirely the TV app's job. Yamtrack just reports availability + the saved preference; it never launches anything.
- No new UI in Yamtrack's own web interface is required for this (though exposing the saved default there too, later, would be a nice-to-have — not scoped now).

## 4. Open items — all resolved during build

- ~~Confirm current `filter_providers()` signature/return shape~~ → `filter_providers(all_providers, region)` takes TMDB's raw country-keyed blob and a region string, returns a deduped/sorted list or `None`/`[]`. Called directly from `src/api/views.py`, no wrapper needed. One gotcha found along the way: a user who's never configured `watch_provider_region` has it default to the literal string `"UNSET"`, not `""` — `filter_providers()` only special-cases `""`, so an unset region silently returns an empty list, indistinguishable from "no providers in your region" unless checked separately. The API does that check explicitly and surfaces it as `region_configured` in the §2.2 response.
- ~~Decide the auth story~~ → reused the existing `User.token` field (already used for the Jellyfin/Plex/Emby webhooks and the iCal feed), but passed as an `Authorization: Token <token>` header instead of a URL path segment — better fit for a client hitting multiple endpoints repeatedly. No new secret to manage.
- ~~Confirm exact watch-status values~~ → `In progress` and `Planning` (i.e. "watching" + "want to watch"), TMDB-sourced items only.
- ~~Pick final URL paths~~ → `/api/watchlist`, `/api/media/<tv|movie>/<tmdb_id>/providers`, `/api/media/<tv|movie>/<tmdb_id>/default-provider`. The `<tv|movie>` segment scopes routing to just those two media types via a dedicated URL converter, since TMDB ids aren't unique across all 10 of Yamtrack's media types.

## 5. Suggested build milestones

Each milestone should go through the existing dev-harness → verify → push to GitHub → pull into Docker cycle before moving to the next. None of these are blocked on the YAM-TV app project — this side can be built and shipped fully independently.

**Milestone 1 — Watchlist read endpoint ✅ Done**
`GET /api/watchlist` returning tracked titles (TMDB ID, title, poster path, watch status). This alone is enough for the YAM-TV app's M1 (rendering the grid) to start in parallel.

**Milestone 2 — Providers-as-JSON endpoint ✅ Done**
`GET /api/media/<tv|movie>/<tmdb_id>/providers`, wrapping the existing `filter_providers()` logic, region-filtered, matching current `media_details` behavior but as JSON.

**Milestone 3 — Default-provider preference ✅ Done**
The new `DefaultProvider` model, folding `default_provider` into the M2 response, and the write endpoint to set/clear it. This is the one the YAM-TV app's "always use this" feature depends on directly.

All three milestones are on the `yamtv-api-additions` branch, fully tested (unit tests + full suite clean), not yet merged/PR'd — pending a real end-to-end test against the Docker deployment, then one combined PR for all three.

**Milestone 4 (optional, only if needed) — Auth hardening / polish**
Not started, and not currently planned — only pursue this if the token-header auth from §4 turns out to be insufficient once the app is actually in use, or if real usage surfaces a need (e.g. filtering by watch-status, batching). Not required for a working v1 — don't build ahead of an actual need.

**Milestone 5 — Per-provider deep links** (requested in `yamtrack-api-request-deeplinks.md`) ✅ Built 2026-09-08

Adds a nullable `deeplink` field to each provider in `GET /api/media/<tv|movie>/<tmdb_id>/providers` (and to `default_provider`), so YAM-TV can launch straight to a title's page in the streaming app instead of just the app's home screen.

Investigated: Yamtrack's provider data came from TMDB's `watch/providers` (`filter_providers()` in `src/app/providers/tmdb.py`), which only exposes one aggregate region-level JustWatch listing link — no per-offer deep links. Getting real per-offer links needed a **new data source**. Used the unofficial `simple-justwatch-python-api` PyPI package (free, GraphQL-based JustWatch client) rather than JustWatch's paid Partner API — appropriate for a single-user local deployment; accepted risk that it's unofficial/reverse-engineered and could break without notice.

**Spike results (better than assumed when this milestone was planned)**:
- The library's `search()` results carry TMDB's own id (`MediaEntry.tmdb_id`), so matching a TMDB id to its JustWatch entry is an **exact-id match on search results**, not fuzzy title/year matching as originally planned — eliminates the false-positive-match risk entirely.
- Confirmed against real titles that JustWatch's own `package_id` for a platform (e.g. `8` for Netflix) equals TMDB's `provider_id` for the same platform — no name/technical_name-based reconciliation needed. Matching by that numeric id also naturally excludes near-duplicate JustWatch packages for the same platform (e.g. "Netflix Standard with Ads" carries a different `package_id`).

Built:
1. Added `simple-justwatch-python-api` to `pyproject.toml`.
2. New `src/app/providers/justwatch.py`: `get_deeplinks(media_type, tmdb_id, title, region)` returns `{tmdb_provider_id: url}`, filtered to `FLATRATE`/`FREE` offers (matching what `filter_providers()` already surfaces — rent/buy is out of scope). Any failure (network, no match, library break) is caught and degrades to `{}` — never surfaces as a 500 on `/providers`.
3. Caching (reuses the existing Redis cache): resolved `{media_type, tmdb_id} -> justwatch_node_id` (or a "no match" sentinel) cached indefinitely; `{node_id, region} -> {provider_id: url}` cached 7 days.
4. Wired into `_get_available_providers()` (`src/api/views.py`, now returns a `(providers, deeplinks, error_response)` tuple) so both `providers` and `default_provider` carry `deeplink`. The JustWatch lookup is skipped entirely when there's nothing to look up (no available providers) or when the caller doesn't need it (`include_deeplinks=False`, used by the `default-provider` write path, which only needs availability, not links).
5. Tests: `src/app/tests/providers/test_justwatch.py` (mocked JustWatch client, no live calls) plus updated `src/api/tests/test_views.py` for the new response shape. Full suite run clean against the pre-existing baseline (no new failures).

Not yet pushed to the branch or tested end-to-end against the Docker deployment — next step before that's done.

**Milestone 6 — Next-episode badge** (bundled with Milestone 5) ✅ Built 2026-09-08

Adds a nullable `next_episode` field (`{"season", "episode", "air_date"}`) per TV show to `GET /api/watchlist`, for the "next episode" badge on YAM-TV's grid tiles (flagged as a lower-priority related ask in the deep-links request doc). Movie results don't carry the field at all.

Better source than first guessed: rather than re-deriving from TMDB's raw `next_episode_to_air` (no TVMaze correction), reuses Yamtrack's existing `Event` model, which already tracks accurate per-episode air dates (TMDB + TVMaze-corrected, refreshed by the existing Celery calendar sync) for the calendar feature. Pure DB read — no new external API calls.

One correction from the original plan: `Event.item` is a TV show's **season** `Item`, not an episode-type `Item` as first assumed (confirmed by reading `src/events/calendar/tv.py` and the existing `BasicMedia.objects._annotate_tv_released_episodes()`, which does the same season-Item traversal for *past* episodes) — `event.item.season_number` gives the season, `event.content_number` gives the episode number within it.

Built: `_next_episodes()` in `src/api/views.py`, batched as one query across the whole watchlist (`item__media_id__in=[...]`) rather than per-show, mirroring `_annotate_tv_released_episodes()`'s query shape but forward-looking (`datetime__gte=now`, earliest instead of latest). Excludes season 0 (specials, matching that same existing convention), season-level events with no episode number, and the far-future sentinel datetime `Event` uses for episodes with no confirmed air date yet (`SentinelDatetime.max_datetime()` — that's a placeholder, not a real date to hand back to a client).

Tests added to `src/api/tests/test_views.py` (`WatchlistNextEpisodeTest`): earliest-episode-wins, past episodes ignored, specials ignored, season-level (no episode number) events ignored, the unknown-air-date sentinel ignored, and no cross-show leakage. Full suite run clean against the pre-existing baseline.
