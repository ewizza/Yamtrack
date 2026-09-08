# Yamtrack API request: per-provider deep link field

**For**: Eric's Yamtrack fork (separate project/repo).
**From**: YAM-TV, the Android TV launcher that consumes this API — see that
project's `CLAUDE.md` for full context if useful, but this doc is meant to
stand alone.
**Why now**: found while building YAM-TV's Milestone 4 (title-page launch
precision) — see `YAM-TV/docs/launch-patterns.md`'s Disney+ row for the full
investigation this came out of.

## The problem

YAM-TV launches a streaming app when Eric picks a title from his watchlist.
Today it can only do a *plain package launch* — open the app to wherever it
last was, not to the specific title. Landing on the exact title's page
instead would be a real quality-of-life improvement.

The blocker: doing that requires a URL built from the streaming service's
own internal content ID (e.g. Disney+ title pages are
`https://www.disneyplus.com/video/<disney-guid>`, Prime Video needs an ASIN).
**There's no public mapping from a TMDB ID to those native IDs** — confirmed
by web research 2026-09-08, nothing found for Disney+, and the app spec
already flagged the same gap for Prime Video. YAM-TV has no path to that data
on its own, and per its architecture it's explicitly *not* supposed to call
any streaming service's own catalog directly (see YAM-TV's
"pure LAN client of Yamtrack" rule) — that's exactly the kind of thing
Yamtrack is supposed to own.

**JustWatch's data model already has this.** JustWatch tracks a `deeplink`
(or equivalent) URL per streaming offer — the whole point of JustWatch is
"here's where to watch this, and here's the direct link." If Yamtrack's
provider-availability feature is already backed by JustWatch data (directly,
or via TMDB's watch-providers endpoint, which itself is JustWatch-sourced),
that deep link may already be sitting in data Yamtrack has fetched but isn't
returning today.

## What's being asked for

Add a `deeplink` field to each provider entry on the existing endpoint:

```
GET /api/media/<media_type>/<tmdb_id>/providers
```

**Current confirmed response shape** (as of 2026-09-07, per YAM-TV's
CLAUDE.md):
```json
{
  "media_type": "tv",
  "tmdb_id": 12345,
  "region_configured": true,
  "providers": [
    {"id": 8, "name": "Netflix", "logo": "https://..."}
  ],
  "default_provider": {"id": 8, "name": "Netflix"} 
}
```

**Requested addition** — a `deeplink` field on each provider object, and
(for convenience, so a consumer doesn't have to cross-reference the full
`providers` list just to launch a saved default) on `default_provider` too:

```json
{
  "media_type": "tv",
  "tmdb_id": 12345,
  "region_configured": true,
  "providers": [
    {"id": 8, "name": "Netflix", "logo": "https://...", "deeplink": "https://www.netflix.com/title/70142329"}
  ],
  "default_provider": {"id": 8, "name": "Netflix", "deeplink": "https://www.netflix.com/title/70142329"}
}
```

- `deeplink` should be `null` (not an omitted field) when no direct link is
  available for that offer — YAM-TV will treat that the same as today
  (package-launch fallback), so this can degrade gracefully per-title,
  per-provider.
- Ideally this is a real `https://` URL to the title's page on that service
  (what Android's App Link system needs to route straight into the
  installed app — see YAM-TV's `AppLauncher.kt`), not a `justwatch.com`
  redirect page or a raw internal API reference.
- No change requested to `PUT /api/media/<media_type>/<tmdb_id>/default-provider`
  — it can keep just taking `provider_id`.

## Open questions to resolve on the Yamtrack side (please investigate, don't assume)

1. **What does `filter_providers()` (or wherever the provider list is
   currently built) actually source data from today?**
   - If it's **TMDB's `/watch/providers` endpoint**: that endpoint does
     *not* expose a per-offer deep link — only `provider_id`/`provider_name`/
     `logo_path`, plus one aggregate `link` per region that points to a
     generic JustWatch listing page for the title (not a specific app deep
     link, and not something Android's App Link routing can use to open the
     right app directly). If this is the current source, getting real
     per-offer deep links likely means adding a second data source, not just
     exposing a field that's already there.
   - If it's **already JustWatch data** (their own GraphQL API, or a scraper
     wrapping it): check whether the response Yamtrack already receives
     includes a deep link per offer that's just not being passed through.
     If so, this could be a small change — surface the field that already
     exists.
2. **If a new/different data source is needed**: JustWatch doesn't have a
   free public API — there's an unofficial GraphQL API various open-source
   tools scrape (no SLA, could break), and a paid Partner API with
   documented per-offer fields including something deep-link-shaped. Worth
   comparing cost/reliability against what this feature is actually worth in
   practice before committing to either.
3. **Caching**: this data changes rarely per title (a deep link doesn't
   change just because availability does) — if a new external call is
   needed per title, consider caching it rather than fetching fresh on every
   `providers` request.
4. **Region**: deep links are presumably region-specific the same way
   availability already is (see `region_configured`) — should follow
   whatever region logic the existing provider matching already uses.

## What this unblocks on the YAM-TV side

Once this field exists, YAM-TV's `AppLauncher.kt` can drop its current
per-service URL-guessing approach (which already hit a dead end on Disney+ —
see `docs/launch-patterns.md`) and just launch whatever `deeplink` URL
Yamtrack returns, generically, for any of the 8 services at once — no more
per-service ADB discovery needed for title-page precision. It'll still keep
the package-launch fallback for whenever `deeplink` is null.

## Not urgent

This is a nice-to-have on top of an already-working app (plain package
launch always works today). No timeline pressure — worth doing when it's a
reasonable-sized chunk of Yamtrack work, not something YAM-TV is blocked on.

---

## Resolution (2026-09-08)

Planned as Milestone 5 in Yamtrack's own `yamtrack-api-additions-spec.md` (§5), not started yet. Answering the open questions above:

1. **Data source today**: confirmed the pessimistic branch — `filter_providers()` in `src/app/providers/tmdb.py` sources from TMDB's `watch/providers` wrapper, which only exposes one aggregate region-level JustWatch listing link, no per-offer deep links. A new data source is required.
2. **Which JustWatch access**: going with the free unofficial `simple-justwatch-python-api` GraphQL client over the paid Partner API — reasonable for a single-user local deployment; accepted the "could break without notice" risk.
3. **Caching**: yes — resolved JustWatch node IDs cached long-lived, per-region offer/deeplink maps cached ~7 days, reusing Yamtrack's existing Redis cache.
4. **Region**: will follow the same region logic `filter_providers()` already uses.

See the spec doc for the full design, including the still-open spike (TMDB vs JustWatch provider-ID reconciliation) to resolve during implementation.

---

*Related, lower-priority ask already flagged in YAM-TV's `MILESTONES.md`
(M6): Yamtrack's own web UI shows a "next episode" badge (episode + air
date) per show that YAM-TV would like to show on its grid tiles too — not
yet confirmed whether that's available via any API field today. Different
feature, mentioning here only because it's the same shape of ask (a Yamtrack
API addition) and might be worth bundling into the same round of work if
convenient.*
