# YAM-TV Launcher — Project Spec

**Status**: Planning complete, feasibility confirmed. Ready to hand to a Claude Code project for build.
**Owner**: Eric Wisniewski
**Last updated**: 2026-09-07

## 1. What this is

A native Android TV / Google TV app for the living room device. It shows Eric's Yamtrack watchlist as a TV-friendly grid, shows which streaming service(s) carry each title (via Yamtrack, which already knows this), and launches the right service's app when a title is selected — remembering a per-show provider choice so repeat launches are one click.

Landing on the exact episode is explicitly **not** a goal. Landing on the right app / the show's page within it is good enough.

## 2. Feasibility summary (from planning session)

- **Platform**: the living room device runs Google TV, which is Android TV OS underneath. No special "Google TV SDK" needed — this is a normal Android TV app, built with Compose for TV (Google's current recommended toolkit over the older Leanback library). Sideloaded, not published to Play Store.
- **Watchlist data**: comes from Eric's own Yamtrack fork over the LAN. Yamtrack doesn't currently expose a documented read API for the watchlist — will need a small endpoint added to the fork (see §4).
- **Availability data ("who has this show")**: Yamtrack already computes this. It calls TMDB's `watch/providers` endpoint live on page load (`src/app/providers/tmdb.py`, `filter_providers()`), filtered to Eric's configured region (`watch_provider_region` on the user model), free/subscription only. **Not stored in Yamtrack's DB long-term** — computed per request. No dedicated JSON API for it yet either — it's baked into the `media_details` Django view/template.
  - **Decision**: don't call TMDB a second time from the TV app. Add one small endpoint to the Yamtrack fork that reuses `filter_providers()` and returns JSON. Single source of truth, no second API key/rate limit to manage, reuses the region setting that's already configured.
- **Launching into a streaming service**: no universal, sanctioned "open this exact title" API exists across services.
  - Google's own mechanism for this (Watch Actions / Media Actions — what powers Google TV's built-in "continue watching" row) is a certified-partner content feed; the streaming services themselves register with Google. Not usable by a third-party app to launch into *their* apps.
  - Android TV's Watch Next / home-screen-channels API only lets an app add its *own* content, not launch other apps' content — dead end for this.
  - What's real: several services (Disney+, Hulu, Max, Peacock, Paramount+) use **Android App Links** — verified `https://` URLs that Android auto-routes to the installed app instead of a browser. Netflix and Prime Video additionally have documented custom URI schemes (`netflix://`, `aiv://`). Package-name launch (just opening the app, no title context) always works as a fallback for any of the 8 services.
  - Nothing here needs approval or an SDK — it's per-service trial and error to find working title-page URL patterns, and it can break silently on a service's app update. Treated as a "make it nicer over time" layer, not a hard requirement.

## 3. Services in scope

Netflix, Hulu, Disney+, Max (HBO), Amazon Prime Video, Apple TV app, Paramount+, Peacock.

| Service | Launch mechanism found | Title-page precision |
|---|---|---|
| Netflix | custom scheme `netflix://` / `nflx://`, also `https://www.netflix.com/title/...` | Documented, fairly stable |
| Prime Video | custom scheme `aiv://` (regional variants exist: `aiv-uk://`, `aiv-de://`, etc.), also `https://app.primevideo.com/detail?gti=<ASIN>` | Documented but needs ASIN mapping (not a TMDB ID) |
| Disney+ | Android App Link (`https://www.disneyplus.com/...`) | Package name confirmed; title-page pattern not yet confirmed — needs hands-on testing |
| Hulu | Android App Link | Package name confirmed; title-page pattern not yet confirmed |
| Max (HBO) | Android App Link / `hbomax://deeplink` mentioned in community docs | Not yet confirmed — needs hands-on testing |
| Paramount+ | package `com.cbs.app` (older) / newer Paramount package — needs re-verification against current install | App Link domain not yet confirmed |
| Peacock | package `com.peacocktv.peacockandroid` | App Link/title pattern not yet confirmed |
| Apple TV app | package likely `com.apple.atve.android.appletv` — needs verification | Not yet confirmed |

Anything marked "not yet confirmed" is v1.5 work: install each app on the actual device, sign in, and manually test URL patterns against a known title.

## 4. Architecture

**Three pieces, home-network only, no cloud dependency:**

1. **Yamtrack fork (backend)** — ✅ all three additions built on the `yamtv-api-additions` branch (see `yamtrack-api-additions-spec.md`), not yet merged/PR'd:
   - `GET /api/watchlist` — returns the user's tracked shows/movies with TMDB IDs and watch status.
   - `GET /api/media/<tv|movie>/<tmdb_id>/providers` — reuses existing `filter_providers()` logic, returns JSON list of providers for that title, plus the saved default (see below).
   - `DefaultProvider` model + `PUT /api/media/<tv|movie>/<tmdb_id>/default-provider` for **per-show default provider** (§5) — written by the TV app when Eric picks "always use this," read back on subsequent loads.
   - Auth: an `Authorization: Token <token>` header, reusing Yamtrack's existing per-user token (same one used for the Jellyfin/Plex/Emby webhooks) — not fully open on the LAN as originally sketched, but still no separate account/OAuth system for the TV app to deal with.

2. **Android TV app (Compose for TV)**:
   - Home screen: grid of watchlist tiles (poster art from TMDB, same as Yamtrack already has).
   - Tap a tile → look up saved default provider for that show:
     - If set and still in the current availability list → launch it directly.
     - If set but no longer available → show the "no longer on X" notice, then fall through to the picker.
     - If not set → show provider picker.
   - Provider picker: simple dialog listing available services for that title, each selectable, with a "always use this" checkbox. Confirms → launches, and if checked, POSTs the choice back to Yamtrack.

3. **Launch layer**: given a chosen provider + title, attempt (in order): known title-URL pattern for that service → App Link/custom scheme → plain package-name launch as the guaranteed fallback.

## 5. Feature: per-show default provider

- When a title has more than one available provider, tapping it opens a picker (list of services + "always use this" checkbox).
- Checking the box + picking a service saves that choice **to Yamtrack** (not local-only) via the new endpoint — keeps it as the single source of truth, follows Eric to any future device.
- Next tap on that show: skips the picker, launches straight to the saved provider.
- If the saved provider drops the show later (TMDB availability changes), the app shows a brief one-time notice ("X is no longer on Hulu") and re-opens the picker rather than failing silently or nagging repeatedly.
- Eric can always override / change the saved choice — the picker should stay reachable (e.g. long-press, or a small "change" affordance on the tile) even after a default is set.

## 6. Open items before/at build time

- Confirm current package names for Paramount+ and Apple TV app against what's actually installed on the living room device (app IDs drift with rebrands/updates).
- Hands-on test title-page URL patterns for Disney+, Hulu, Max, Paramount+, Peacock, Apple TV — no public docs found for these; will need manual discovery with real titles.
- Decide exact Yamtrack API auth story (likely none needed if it's LAN-only and the TV app is trusted on the home network — confirm this is acceptable).
- Confirm Yamtrack fork's existing `filter_providers()` signature so the new endpoint can call it directly rather than reimplementing.

## 7. Explicit non-goals

- Jumping to a specific episode/timestamp within a streaming app.
- Supporting services outside the 8 listed.
- Any Play Store publishing or Google certification process.
