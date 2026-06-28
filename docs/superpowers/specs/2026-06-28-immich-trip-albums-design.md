# Immich "Away-From-Home" Trip Albummer — Design

**Date:** 2026-06-28
**Status:** Approved (pending spec review)

## 1. Purpose

Scan an Immich library, find photos and videos taken **away from the user's
home city**, cluster them into **trips**, and create **one album per trip**.
Assets with no usable location are skipped from albums but tagged for manual
review. The script is **dry-run by default** and **idempotent** on re-runs.

A thin, optional LLM layer adjudicates ambiguous trip boundaries and generates
human-friendly album names. The LLM is *enrichment, never a dependency*: with no
API key (or `--no-llm`) the pipeline degrades to a fully deterministic version
and still produces correct, idempotent results.

## 2. Core Pattern (the reusable shape)

> The deterministic script owns the data, the loop, the I/O, and idempotency.
> It escalates only its *bounded, low-confidence judgment calls* to an agent as a
> structured request; the agent returns a schema-constrained **verdict**; the
> script then applies that verdict deterministically.
>
> Script **proposes**, LLM **adjudicates**, script **disposes.** The LLM never
> performs a mutation — it only returns a verdict the script chooses to apply.

Invariants that make this trustworthy:

1. **Typed contract** — every escalation is a typed request + a schema-validated
   response. An invalid response is treated as "no answer."
2. **Deterministic fallback** — every escalation has a fallback function. No key,
   timeout, or malformed answer never breaks the pipeline.
3. **Escalate only the ambiguous band** — clear cases are decided by the script.
   The LLM is asked O(few ambiguities), not O(every boundary).
4. **Cacheable + auditable** — escalation input is hashed and the verdict cached,
   so LLM nondeterminism does not break idempotency across re-runs. Every
   escalation is logged (input, verdict, reason, path taken).
5. **Visible in dry-run** — the plan marks which boundaries the LLM decided and
   why, and which titles came from the LLM vs. the fallback.

For this project the pattern is realized minimally: **one file, one
`escalate(...)` seam, two call sites** (`resolve_boundary`, `name_trip`). No
speculative framework — but the seam is clean enough to extract later.

## 3. Configuration

Config block / `.env` at the top of the script:

| Key | Meaning | Example |
|-----|---------|---------|
| `IMMICH_URL` | Base URL of the Immich instance | `https://immich.example.com` |
| `IMMICH_API_KEY` | Sent as `x-api-key` header | — |
| `HOME_CITIES` | City names that count as home (case-insensitive) | `["Paris"]` |
| `HOME_STATES` | Optional broader home match (state/region) | `["Île-de-France"]` |
| `GAP_MIN_DAYS` | Below this, adjacent clusters are *always merged* | `1.5` |
| `GAP_MAX_DAYS` | Above this, adjacent clusters are *always split* | `6` |
| `TRIP_GAP_FALLBACK_DAYS` | Split point used **only** as the deterministic fallback for an *ambiguous* boundary (no LLM / invalid verdict). Must satisfy `GAP_MIN_DAYS ≤ TRIP_GAP_FALLBACK_DAYS ≤ GAP_MAX_DAYS` | `4` |
| `OUTLIER_MAX_ASSETS` | A cluster with `≤` this many assets at a boundary is an "outlier" trigger | `2` |
| `REVIEW_TAG` | Tag applied to no-location assets | `needs-location-review` |
| `ALBUM_PREFIX` | Namespacing prefix for trip albums | `Trip — ` |
| `ANTHROPIC_API_KEY` | Optional; enables the LLM layer | — |

**Threshold roles (authoritative).** `GAP_MIN_DAYS` / `GAP_MAX_DAYS` bound the
deterministic first pass: only gaps strictly inside that band are ever ambiguous.
`TRIP_GAP_FALLBACK_DAYS` is **not** a first-pass threshold — it is consulted only
when an ambiguous boundary cannot be resolved by the LLM, where gap `≥
TRIP_GAP_FALLBACK_DAYS` → split, else merge.

CLI flags: `--apply` (perform writes; default is dry-run), `--no-llm` (force
deterministic-only), `--llm-names` is implied when a key is present.

## 4. Data Fetch

Pull all assets via `POST /api/search/metadata`, paginated (`page`/`size`,
size ~1000), with `withExif: true` so each asset carries `exifInfo`. Request both
images and videos. Accumulate a flat list of normalized records:

```
{ id, type, city, state, country, lat, lon, taken_at }
```

`taken_at` is derived from `exifInfo.dateTimeOriginal` (fallback
`fileCreatedAt`). The HTTP client sends `x-api-key` and fails loudly with a clear
message on auth failure or an unexpected response shape (so an API-version
mismatch is obvious rather than silent).

## 5. Classification

For each asset, evaluated in order:

1. **No location** — no `city` **and** no `lat/lon` → queue for the `REVIEW_TAG`,
   exclude from albums.
2. **Home** — `city` matches `HOME_CITIES` **or** `state` matches `HOME_STATES`
   (case-insensitive) → ignore.
3. **Coordinates-only** — has `lat/lon` but **no** `city`/`state` (a common
   Immich geocoding gap). This is **not** "no location" and cannot be name-matched
   against home, so → treat as **away** and feed into clustering. Such an asset's
   `country`/`city` are `None`; clustering and naming must tolerate that (it
   contributes `lat/lon` for distance but no city to the name; the country-change
   trigger ignores `None` countries).
4. **Away** — has a `city` (or `state`), not matching home → feed into clustering.

Rationale for ordering: coordinates-only assets are kept (they are genuinely
located, just un-geocoded) rather than dumped into review, because dropping every
location-on-but-not-yet-geocoded shot would silently miss real trips.

## 6. Trip Clustering + Boundary Escalation

1. **Deterministic first pass.** Sort away-assets by `taken_at`. Walk them:
   gap `> GAP_MAX_DAYS` → **always split**; gap `< GAP_MIN_DAYS` → **always
   merge**. Produces initial clusters.
2. **Identify ambiguous boundaries.** An adjacent cluster pair enters the
   escalation queue if **any** of these concrete triggers fires:
   - **Middle-band gap** — `GAP_MIN_DAYS < gap_days < GAP_MAX_DAYS`.
   - **Country change** — the two clusters' Immich `country` fields differ and
     both are non-`None` (a `None` country never triggers this).
   - **Sparse outlier** — either adjacent cluster has `≤ OUTLIER_MAX_ASSETS`
     assets (default `2`) — e.g. a layover or single drive-through shot between
     two larger trips.
   `approx_distance_km` is the great-circle (haversine) distance between the two
   clusters' centroids, where a cluster centroid is the mean of its assets'
   available `lat/lon`. If either cluster has **no** coordinates at all,
   `approx_distance_km` is `null` and is simply omitted from the LLM's reasoning.
3. **Batch escalate `resolve_boundary`.** Pack all queued boundaries into one (or
   a few) Claude API call(s). Each boundary payload:
   `{ left: {cities, dates, count}, right: {cities, dates, count}, gap_days,
   approx_distance_km }`. Response per boundary:
   `{ decision: "merge" | "split", reason }`. Schema-invalid or no key →
   fallback to the `TRIP_GAP_FALLBACK_DAYS` rule (gap `≥` → split, else merge).
4. Apply merge/split verdicts to produce final trips.

## 7. Naming (enrichment)

Each final trip calls `name_trip`: payload `{ cities_in_order, date_range,
count }`, response `{ title, confidence }`. Fallback title = `"<top city/cities>,
<Mon Year>"` (multi-city → `"Lisbon & Porto"`). `ALBUM_PREFIX` is prepended in
all cases, e.g. `Trip — Lisbon long weekend` or `Trip — Lisbon & Porto, Apr 2025`.

## 8. Shared Escalation Seam

A single function:

```
escalate(kind, payload, response_schema, fallback_fn) -> verdict
```

Responsibilities: prompt assembly, Claude API call, schema validation, caching
(hash of `payload`), audit logging, and fallback on any failure. Two call sites:
`resolve_boundary` and `name_trip`. With no key or `--no-llm`, every call routes
straight to `fallback_fn`, so the pipeline behaves as a pure deterministic
version and remains idempotent.

## 9. Apply (idempotent, dry-run by default)

Default run **prints the plan only** and changes nothing: trip list with names,
date ranges, asset counts, the review-tag count, and — for each ambiguous
boundary — the merge/split decision + reason and whether each title is LLM or
fallback.

With `--apply`:

- **Albums** — `GET /api/albums` first; reuse an album whose name matches the
  intended title **exactly** (full title including `ALBUM_PREFIX`), else
  `POST /api/albums`. Add assets via `PUT /api/albums/{id}/assets`; Immich skips
  assets already in the album, so re-adds are safe. Note: changing `ALBUM_PREFIX`
  or an LLM-generated title between runs yields a new album rather than renaming
  the old one — exact-match reuse is the predictable, least-surprising rule.
- **Tag** — ensure `REVIEW_TAG` exists (`POST /api/tags`), then bulk-attach the
  no-location assets via the tag-assets endpoint.

## 10. Auditability

`escalations.jsonl` records every escalation: `kind`, hashed input, full payload,
verdict, reason, and whether the verdict or the fallback was applied. This answers
"why was this trip split / named this way?" after the fact.

## 11. Error Handling

- Auth failure or unexpected API response shape → fail loudly with a message
  naming the endpoint and the assumed Immich API version.
- LLM failure (no key, timeout, malformed/invalid verdict) → silent, logged
  fallback. Never aborts the pipeline.

## 12. Testing

- **Pure functions** (classification, first-pass clustering, ambiguous-band
  detection, fallback naming) → unit-tested with fixture assets. No network, no
  LLM.
- **`escalate`** → injected fake adjudicator. Assert: a valid verdict is adopted;
  an invalid verdict triggers the fallback; a cache hit does not re-invoke the
  adjudicator.
- **API client** → thin layer exercised via the dry-run plan output against
  recorded/fake responses.

## 13. Out of Scope (YAGNI)

- No external reverse-geocoder — rely on Immich's stored geocoding.
- No GPS-radius home zone — home is matched by city/state name.
- No generalized escalation framework — only the single-file seam above.
- No automatic album deletion or re-clustering of previously created albums.

## 14. Assumptions / Version Risk

Endpoints target a recent Immich API: `POST /api/search/metadata`,
`GET/POST /api/albums`, `PUT /api/albums/{id}/assets`, `POST /api/tags` and the
tag-assets bulk endpoint, with `exifInfo` carrying `city/state/country/
dateTimeOriginal/latitude/longitude`. If the live instance differs, the client
fails loudly so the mismatch is visible and fixable.
