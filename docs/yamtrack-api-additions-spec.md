# Yamtrack Fork — API Additions Spec

**Project**: Eric's Yamtrack fork (existing Claude Code project, Docker on the home server)
**Why**: supports a new companion project, the YAM-TV Launcher Android TV app (see `yam-tv-launcher-app-spec.md`, same Research folder). This doc covers only the changes needed *inside Yamtrack* — the TV app itself is a separate project/spec.
**Status**: ✅ All 3 milestones built, tested, and pushed to the `yamtv-api-additions` branch (`src/api/` app). Milestone 4 remains optional/deferred. Not yet merged to `dev` or opened as a PR — pending end-to-end testing against the Docker deployment.
**Last updated**: 2026-09-07

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
