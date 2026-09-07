# Yamtrack Fork — API Additions Spec

**Project**: Eric's Yamtrack fork (existing Claude Code project, Docker on the home server)
**Why**: supports a new companion project, the YAM-TV Launcher Android TV app (see `yam-tv-launcher-app-spec.md`, same Research folder). This doc covers only the changes needed *inside Yamtrack* — the TV app itself is a separate project/spec.
**Status**: Planning complete, ready to build.
**Last updated**: 2026-09-07

## 1. Context

Yamtrack already knows two things the TV app needs: the user's watchlist (TMDB-backed) and, per title, which streaming providers currently carry it (calls TMDB's `watch/providers` endpoint live, filtered to the user's configured region via `filter_providers()` in `src/app/providers/tmdb.py`, rendered into the `media_details` HTML view). Neither is currently exposed as a reusable API — both are baked into Django HTML views/templates.

Rather than have the TV app duplicate this (its own TMDB calls, its own region-filtering, a second API key to manage), Yamtrack gets three small additions. This keeps Yamtrack the single source of truth for watchlist + availability + the new provider preference.

## 2. Additions needed

### 2.1 Watchlist read endpoint
`GET /api/watchlist` (path negotiable to fit existing URL conventions)
- Returns the tracked shows/movies (watching + want-to-watch, at minimum) with TMDB IDs, titles, poster path, and watch status.
- Read-only; no auth beyond whatever LAN-only trust model Yamtrack already uses (open item — see §4).

### 2.2 Providers-as-JSON endpoint
`GET /api/media/<tmdb_id>/providers` (path negotiable)
- Reuses the existing `filter_providers()` function directly rather than reimplementing region-filtering logic.
- Returns JSON: list of provider names/logos currently available for that title, already filtered to the user's `watch_provider_region`, free/subscription only (matches current `media_details` behavior).
- Confirm `filter_providers()`'s current signature/return shape before building this — it may need a thin wrapper rather than a direct call if it's tightly coupled to the Django view/template context.

### 2.3 Default-provider preference (new data)
- New field or small table: per-title (TMDB ID) → chosen provider name, scoped to the user.
- Written by the TV app when Eric checks "always use this" in the provider picker (see app spec §5 for the UX this supports).
- Read back by the providers endpoint (§2.2) or a small addition to it — the TV app needs to know, alongside current availability, whether a saved default exists and whether it's still in the availability list.
- Suggested shape: `GET /api/media/<tmdb_id>/providers` returns both the current availability list *and* `default_provider` (nullable) in the same response, so the TV app doesn't need a second round-trip.
- `POST`/`PUT` to set or clear the default (e.g. `PUT /api/media/<tmdb_id>/default-provider` with a body like `{"provider": "Hulu"}`, or `null` to clear).

## 3. Explicit non-goals for this project

- No streaming-service deep-linking logic lives here — that's entirely the TV app's job. Yamtrack just reports availability + the saved preference; it never launches anything.
- No new UI in Yamtrack's own web interface is required for this (though exposing the saved default there too, later, would be a nice-to-have — not scoped now).

## 4. Open items

- Confirm current `filter_providers()` signature/return shape in `src/app/providers/tmdb.py` so §2.2 can call it directly.
- Decide the auth story: is LAN-only trust acceptable for these endpoints, or does Yamtrack already have a lightweight API-token mechanism to reuse?
- Confirm exact watch-status values to include in §2.1 (e.g. does "watching" vs "planning to watch" both need to surface in the TV app's grid, or just "watching"?).
- Pick final URL paths to match whatever REST conventions (if any) the rest of Yamtrack's codebase already follows.

## 5. Suggested build milestones

Each milestone should go through the existing dev-harness → verify → push to GitHub → pull into Docker cycle before moving to the next. None of these are blocked on the YAM-TV app project — this side can be built and shipped fully independently.

**Milestone 1 — Watchlist read endpoint**
`GET /api/watchlist` returning tracked titles (TMDB ID, title, poster path, watch status). This alone is enough for the YAM-TV app's M1 (rendering the grid) to start in parallel.

**Milestone 2 — Providers-as-JSON endpoint**
`GET /api/media/<tmdb_id>/providers`, wrapping the existing `filter_providers()` logic, region-filtered, matching current `media_details` behavior but as JSON. Resolve the §4 open items about its signature as part of this milestone, not before — they're implementation details, not planning gaps.

**Milestone 3 — Default-provider preference**
The new field/table, folding `default_provider` into the M2 response, and the write endpoint to set/clear it. This is the one the YAM-TV app's "always use this" feature depends on directly — sequence it before that app milestone starts (see app spec's milestone list).

**Milestone 4 (optional, only if needed) — Auth hardening / polish**
Only pursue this if the LAN-only trust model from §4 turns out to be insufficient once the app is actually in use, or if real usage surfaces a need (e.g. filtering by watch-status, batching). Not required for a working v1 — don't build ahead of an actual need.
