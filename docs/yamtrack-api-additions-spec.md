# Yamtrack Fork — API Additions Spec

**Project**: Eric's Yamtrack fork (existing Claude Code project, Docker on the home server)
**Why**: supports a new companion project, the YAM-TV Launcher Android TV app (see `yam-tv-launcher-app-spec.md`, same Research folder). This doc covers only the changes needed *inside Yamtrack* — the TV app itself is a separate project/spec.
**Status**: ✅ All of v1 (Milestones 1-3, 5, 6) and v2 (Milestones 7-9, plus Ask 3's no-code resolution) pushed to `origin/yamtv-api-additions` and verified end-to-end against the real Docker deployment (rebuilt image, real tracked data, real TMDB/JustWatch calls - see §6). Not merged to `dev`, and **decided 2026-09-09 not to PR upstream** - `upstream/feat/add-api` is already a large, active, DRF-based official API effort with a different design; see §7 and `yam-ecosystem/STATUS.md`'s backlog for the full reasoning.
**Last updated**: 2026-09-09

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

**Milestone 5 — Per-provider deep links** (requested in `yam-ecosystem/yamtrack-api-request-deeplinks.md` — shared cross-project folder, `C:\Share\projects\yam-ecosystem\`, moved out of this repo's own docs/ 2026-09-09) ✅ Built 2026-09-08

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

**Milestone 7 — Status write endpoint** (Ask 1 of `yam-ecosystem/yamtrack-api-request-v2.md`'s bundled 4-ask v2 request) ✅ Built 2026-09-09

Adds `PUT /api/media/<tv|movie>/<tmdb_id>/status`, so YAM-TV can mark a title Watching/Planning/Completed/etc. without opening the web UI. Blocks 3 of the 4 YAM-TV v2 features (mark-complete, the unified status modal, the Planning-detail view's "Start" action).

Investigated (the ask doc's open questions, answered from the actual model rather than assumed):

1. **Status vocabulary**: a fixed Django `TextChoices` enum (`app.models.Status`), five values — `Completed`, `In progress`, `Planning`, `Paused`, `Dropped` — not free text. The two values YAM-TV had observed live were only a subset. The endpoint validates against this enum and rejects anything else with a 400.
2. **Transition rules**: none exist. Nothing in the model or the web UI's own `MediaForm` restricts which status can follow which — any of the five is a valid write from any current value, same as the web UI already allows. Nothing to enforce server-side beyond enum membership.
3. **Side effects — yes, real ones, and this endpoint intentionally doesn't suppress them**: it's a thin wrapper around the exact same `Media.save()` path the web UI's own status field already goes through, so whatever the web UI does on a status change, this does too. Concretely: setting `Completed` fills `progress` to the title's max (fetched from provider metadata) — i.e. marks it fully watched. For TV specifically, `TV.save()` goes further: `Completed` creates any missing Season/Episode records and marks every already-released episode watched; `Dropped` cascades to any in-progress seasons; and every status change (regardless of target) triggers an async recalendar (`item.fetch_releases(delay=True)`) — the same trigger Milestone 6's `next_episode` data depends on, relevant context for Ask 3's renewal-signal investigation. Movies have no season cascade — just the progress fill.
4. **Field naming**: `status` is already the literal field name on the model, storing the enum's string values directly (no internal numeric code) — the request/response shape from the ask doc (`{"status": "Completed"}`) needed no adjustment.

**Scope decision**: the endpoint requires an existing TV/Movie tracking record for the (user, item) pair — it doesn't create one from scratch the way the full web `MediaForm`/`media_save` flow does (fetching provider metadata, creating the `Item`, etc.). Every title the watchlist endpoint surfaces already has one, since it's filtered to `In progress`/`Planning`. If YAM-TV's v2 "Start" action turns out to need creating a tracking record for a title that isn't tracked at all yet (as opposed to moving an already-Planning title to In progress), that's a new ask, not something this milestone covers.

Built: `set_status` in `src/api/views.py`, reusing `_get_item` and a new `_get_tracked_media`/`_parse_status` pair; routed at `media/<tv_movie_type:media_type>/<str:tmdb_id>/status` in `src/api/urls.py`. An untracked item (no matching `Item`, or an `Item` no TV/Movie row of this user's points at) returns the same 404 shape the default-provider endpoint uses.

Tests added to `src/api/tests/test_views.py` (`SetStatusViewTest`): valid status on a movie, valid status on a TV show (side effects verified via a mocked provider call, same pattern the model-level `TV` tests already use), an out-of-enum value rejected, malformed/empty body rejected, untracked item and cross-user isolation both 404, missing token 401. `api.tests.test_views` full module run clean (36/36). Full-suite run has 70 pre-existing errors/8 pre-existing failures unrelated to this change (MyAnimeList webhook tests failing on a missing local `Invalid client id` secret, present before this milestone) — not new failures.

**Milestone 8 — Last-activity timestamp** (Ask 4 of `yam-ecosystem/yamtrack-api-request-v2.md`'s bundled 4-ask v2 request) ✅ Built 2026-09-09

Adds a `last_activity` field (ISO 8601 datetime) to every `GET /api/watchlist` result, for YAM-TV's recently-watched sort. Fully independent of the other three v2 asks — no dependency on Milestone 7's status endpoint.

Investigated (empirically, via a throwaway Django shell/test script - not just read from source) rather than assumed:

1. **Does this data exist internally already?** Yes - `progressed_at` is an existing `MonitorField` on the base `Media` model (both `TV` and `Movie` inherit it), already a real DB column. No migration needed. But it's not a trivial pass-through: confirmed empirically that `Movie.progressed_at` defaults to `created_at` at creation time (a fresh, untouched movie is *not* null), while `TV.progressed_at` is a Python *property* computed across the show's `Season` rows and returns `None` until at least one season has recorded progress - the two media types don't behave the same way for an untouched title. See the **build decision** below for how this got normalized.
2. **What counts as "activity"?** Confirmed empirically, not assumed: `progressed_at` updates **only** when the `progress` field itself changes (an episode/movie logged as watched). A status-only edit (e.g. `Planning` → `Dropped` with no progress change) does **not** move it, and neither does a rating or notes edit. This is meaningfully narrower than "last modified for any reason" - it specifically means "last time real watch progress was made," which matches what a "recently watched" sort should mean.
3. **Format/timezone**: full ISO 8601 with an explicit UTC offset (Python's `datetime.isoformat()` on Django's timezone-aware value, e.g. `2026-09-09T13:20:06.537128+00:00`) - the same raw `.isoformat()` convention `src/app/providers/tmdb.py` already uses for its own date fields; `next_episode`'s `air_date` is date-only by contrast, since it's a calendar date rather than an instant.
4. **Movies**: progress is effectively binary for a movie (0 or its `max_progress`, normally 1), so `last_activity` for a movie means "when I last marked it watched/unwatched" - a single instant rather than TV's richer per-episode signal, but still a meaningful, comparable timestamp across both media types.

**Build decision**: `last_activity = (media.progressed_at or media.created_at).isoformat()`. Falling back to `created_at` when `progressed_at` is falsy normalizes the Movie/TV asymmetry found in question 1 - every watchlist item always carries a real, non-null timestamp of the same shape, and an unwatched item's "activity" reads as "when it was added," which is the same fallback Movie already got for free from its own field default.

Built: `_last_activity()` in `src/api/views.py`, called per result in `watchlist()`. TV's `progressed_at` property iterates `self.seasons.all()`, which is already `prefetch_related` by `get_media_list()` for TV - no new N+1 query.

Tests added to `src/api/tests/test_views.py` (`WatchlistLastActivityTest`): an untouched movie falls back to `created_at`; a real progress change moves `last_activity` forward and matches the model's own `progressed_at`; a status-only change leaves it unchanged. Existing `test_result_shape` updated to expect the new field. `api.tests.test_views` full module run clean (39/39). Broader suite carries the same pre-existing, unrelated failures as before this session (missing local credentials for MyAnimeList, Hardcover, and similar external providers) - confirmed unrelated since none of the failing tests touch anything this or Milestone 7 changed.

**Ask 3 (renewal signal, `yam-ecosystem/yamtrack-api-request-v2.md`) — investigated 2026-09-09, ✅ no API change needed**

Not a milestone - no code changed here. Yamtrack already auto-detects a renewed show and reopens it server-side: `reopen_completed_tv_with_new_seasons()` in `src/events/calendar/tv.py`, already tested (`events/tests/calendar/test_tv.py::test_process_tv_reopens_completed_show_with_new_season_as_planning`), already running on the `reload_calendar` Celery Beat schedule (`src/config/settings.py`, every 24h, `user=None` so it covers every user's Completed shows). When that scan discovers a future-dated episode Event for a season a Completed `TV` row doesn't have yet, it creates the season as `Planning` and flips the show's own `status` to `In progress` - unprompted, with no dependency on Milestone 7's status endpoint. A renewed show simply reappears in `GET /api/watchlist`'s normal In-progress/Planning filter the next time it's polled. Full resolution write-up (data flow traced through `src/events/calendar/selectors.py` and `tv.py`): `yam-ecosystem/yamtrack-api-request-v2.md`.

**Milestone 9 — Detail fields on the providers endpoint** (Ask 2 of `yam-ecosystem/yamtrack-api-request-v2.md`'s bundled 4-ask v2 request) ✅ Built 2026-09-09

Adds `title`, `synopsis`, and (media-type-dependent) `season_count` or `runtime` to `GET /api/media/<tv|movie>/<tmdb_id>/providers`, for YAM-TV's Planning-tab detail view. Last of the four v2 asks; only Ask 2 needed actual new code (Ask 3 needed none).

Investigated (read the actual TMDB provider functions, not assumed) rather than guessed:

1. **Does Yamtrack already have this data anywhere?** Yes, and better than "somewhere" - it's already sitting in the exact same in-memory dict `_get_available_providers()` fetches via `services.get_media_metadata()` for provider availability. `tmdb.tv()`/`tmdb.movie()` (`src/app/providers/tmdb.py`) already return `synopsis` and (for TV) `details.seasons`/`details.episodes`, or (for movies) `details.runtime` - all sourced from the *same* single TMDB call the `providers` endpoint already makes and already caches. This isn't a "small pass-through," it's a **zero-cost** one: the view was already discarding these fields from a dict it had fully in hand.
2. **New endpoint vs. extending `.../providers`?** Extended `.../providers` - the ask doc's own instinct (bundling is cheaper than a second round trip) turned out to be even more true than assumed, since there's no second *fetch* either, just more keys read off a dict already in scope.
3. **Movies**: `runtime` — already a human-readable string from `get_readable_duration()` (e.g. `"2h 15m"`, or `null` if TMDB doesn't know the movie's runtime) - reused as-is rather than inventing a new format. `season_count` is simply absent from a movie's response rather than sent as `null`, since the two fields are mutually exclusive by media type.
4. **Caching**: no new caching needed - this rides the same `services.get_media_metadata()` Redis cache (`CACHE_TIMEOUT = 86400`, 24h, `src/config/settings.py`) the `providers` endpoint's own data already comes from.

Built: `_detail_fields(media_type, media_metadata)` in `src/api/views.py`, merged into the `providers()` response. `_get_available_providers()` now returns `media_metadata` as a fourth tuple element (it was already fetching it and discarding everything but `providers`/`title`) - both call sites (`providers()`, `set_default_provider()`) updated for the new tuple shape; `set_default_provider()` ignores the new element, since the write path never needed detail fields.

Tests added to `src/api/tests/test_views.py` (extending `ProvidersViewTest`): TV response carries `synopsis`/`season_count` and omits `runtime`; movie response carries `synopsis`/`runtime` and omits `season_count`; metadata missing these fields degrades to `null` rather than erroring. `api.tests.test_views` full module run clean (42/42).

## 6. Docker deployment verification (2026-09-09)

Pushed `yamtv-api-additions` to `origin`, rebuilt the local Docker image (`docker build -t ewizza/yamtrack:yamtv-api-additions .`), and recreated the running `yamtrack_dashboard` container from it (`docker compose up -d --force-recreate yamtrack`). No new migrations (Milestones 7-9 added no model fields); container came up healthy on the first try; logs clean of errors.

Smoke-tested every v2 endpoint end-to-end against real tracked data (Eric's actual `ewizza` account, not a test fixture) rather than just the unit-test suite:

- `GET /api/watchlist` — real results across ~50 tracked TV shows/movies, each carrying a real, populated `last_activity` timestamp (Milestone 8) and, for TV, `next_episode` where known (pre-existing Milestone 6) - both fields' values held up against the real DB, not just mocked data.
- `GET /api/media/tv/<id>/providers` — real synopsis and `season_count` for a tracked show (Reacher), `runtime` correctly absent.
- `GET /api/media/movie/<id>/providers` — real synopsis and `runtime` for a tracked movie (The Menu), `season_count` correctly absent. Confirmed `default_provider`'s write/read/clear cycle still works after Milestone 9 changed `_get_available_providers()`'s return shape.
- `PUT /api/media/tv/<id>/status` — set a real tracked show's status to `Paused`, confirmed it dropped out of `GET /api/watchlist` (correctly excluded, since only `In progress`/`Planning` show), reverted it back to `Planning`, confirmed it reappeared with its original `last_activity` unchanged (matching Milestone 8's finding that a status-only write doesn't move it). Also confirmed an invalid status value still 400s against the real deployment.

All test writes were reverted immediately after confirming them - no lasting changes to Eric's real tracked data.

## 7. Upstream PR decision (2026-09-09) — ❌ not now

Investigated before deciding rather than assuming a personal-use API surface should default to staying local or default to going up: fetched `upstream/feat/add-api` and diffed it against `upstream/dev`.

**Finding**: it's a large, deliberate, still-real official API effort - not a stray experiment. 100+ commits, four contributors including FuzzyGrim (the maintainer) themselves, a full [Django REST Framework](https://www.django-rest-framework.org/) implementation with `drf-spectacular` OpenAPI schema generation, its own dedicated CI image-publish workflow, and endpoint coverage for media, seasons, episodes, lists, calendar, history, and search - substantially broader in scope than this fork's four endpoints. Last commit 2026-07-13 (stale relative to `dev`'s 2026-08-27 HEAD, so not actively landing right now), but the contributor count and design investment make clear it's a sanctioned direction, not something to route around.

**Decision**: this fork's API work stays on `yamtv-api-additions`, not proposed upstream. Two things made this the wrong contribution to make, not just a stylistic preference:
- **Overlapping purpose, incompatible shape.** Both efforts solve "expose Yamtrack's data over an API," but this fork's endpoints are plain Django views (`JsonResponse`, no schema, reusing the existing web-UI token) built to serve YAM-TV's specific needs, while upstream's is a general-purpose DRF API with OpenAPI docs meant for arbitrary API consumers. Proposing this fork's version alongside or instead of that effort would mean either a from-scratch DRF rewrite (not worth it for code that already works for its one actual consumer) or maintainer confusion about which API surface is canonical.
- **Ongoing maintenance cost that isn't Eric's to take on.** Merging upstream would mean fielding other self-hosters' bug reports, feature requests, and compatibility expectations for an API designed around one specific companion app's needs - a cost with no offsetting benefit here, since YAM-TV already has what it needs on the fork.

**Revisit condition**: not "never" - if/when `upstream/feat/add-api` actually merges to `dev` and ships, the real question becomes whether **YAM-TV should migrate to consume the official API** instead of this fork's, not whether to upstream this fork's version. Worth checking `upstream/dev` for that merge occasionally; not something to poll for actively.
