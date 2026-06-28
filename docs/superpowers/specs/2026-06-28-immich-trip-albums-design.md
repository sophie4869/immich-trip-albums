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
| `HOME_CITIES` | City names that count as home (case-insensitive). Primary home rule | `["Paris"]` |
| `HOME_STATES` | Optional broader home match (state/region) | `["Île-de-France"]` |
| `HOME_COUNTRIES` | Optional guard against same-named foreign cities (e.g. `Paris, Texas`). When set, a name match counts as home **only if** the asset's `country` is in this list **or** the asset has no country | `["France"]` |
| `HOME_LAT` / `HOME_LON` | Optional home coordinates. Used **only** to classify *coordinates-only* assets (GPS present, no geocoded city). Leave unset to disable | `48.8566` / `2.3522` |
| `HOME_RADIUS_KM` | Radius around `HOME_LAT/LON` counted as home (only if home coords set) | `25` |
| `GAP_MIN_DAYS` | A gap `≥` this (or any country change) opens a boundary; below it, same-country assets always merge | `1.5` |
| `GAP_MAX_DAYS` | A gap `≥` this is **always** a hard split, regardless of country | `6` |
| `TRIP_GAP_FALLBACK_DAYS` | Split point used **only** as the deterministic fallback for an *ambiguous* boundary (no LLM / invalid verdict). Must satisfy `GAP_MIN_DAYS ≤ TRIP_GAP_FALLBACK_DAYS ≤ GAP_MAX_DAYS` | `4` |
| `OUTLIER_MAX_ASSETS` | Outlier **annotation** threshold: a cluster with `≤` this many assets at a soft boundary is flagged `outlier` as LLM context. Annotation only — never creates or overrides a boundary (§6) | `2` |
| `REVIEW_TAG` | Tag applied to no-location assets | `needs-location-review` |
| `ALBUM_PREFIX` | Namespacing prefix for trip albums | `Trip — ` |
| `ANTHROPIC_API_KEY` | Optional; enables the LLM layer | — |

**Threshold roles (authoritative).** A boundary exists (§6 step 1) when
`gap_days ≥ GAP_MIN_DAYS` **or** the country changes. A boundary is a **hard
split** when `gap_days ≥ GAP_MAX_DAYS` (always, regardless of country); otherwise
it is **soft** and escalated. So the *ambiguous* (soft) set is every boundary with
`GAP_MIN_DAYS ≤ gap_days < GAP_MAX_DAYS`, **plus** any country-change boundary with
`gap_days < GAP_MAX_DAYS` (including small-gap hops below `GAP_MIN_DAYS`).
`TRIP_GAP_FALLBACK_DAYS` is **not** a first-pass threshold — it is consulted only
when a soft boundary cannot be resolved by the LLM, where `gap_days ≥
TRIP_GAP_FALLBACK_DAYS` → split, else merge.

CLI flags: `--apply` (perform writes; default is dry-run), `--no-llm` (force
deterministic-only), `--llm-names` is implied when a key is present.

## 4. Data Fetch

Pull assets via `POST /api/search/metadata` with `withExif: true` so each asset
carries `exifInfo`. Contract details (verified against the current Immich
OpenAPI spec):

- **Asset type.** `MetadataSearchDto.type` is a **single** `AssetTypeEnum`, not a
  list. We therefore **omit `type`** (fetch all) and **filter client-side** to
  `IMAGE` and `VIDEO`, dropping `OTHER`/`AUDIO`. (Avoids two round-trips and is
  robust to enum additions.)
- **Exclusions.** Set `withDeleted: false`; constrain `visibility` to the normal
  timeline so archived / locked / hidden assets are excluded. Leave `withStacked`
  at its default (stack children are not separately albumed). These defaults can
  be overridden by config later if needed, but the spec's intent is "visible
  timeline photos and videos only."
- **Pagination.** Response is `SearchResponseDto` → `assets` is a
  `SearchAssetResponseDto` with `items`, `total`, `count`, and `nextPage`. Loop:
  send `page` (starting 1) with `size` ~1000; stop when `assets.nextPage` is
  `null`.

Accumulate a flat list of normalized records:

```
{ id, type, city, state, country, lat, lon, taken_at }
```

`taken_at` is derived from `exifInfo.dateTimeOriginal` (fallback
`fileCreatedAt`). The HTTP client sends `x-api-key` and fails loudly with a clear
message on auth failure or an unexpected response shape (so an API-version
mismatch is obvious rather than silent).

## 5. Classification

For each asset, evaluated in order:

1. **No location** — no `city`/`state` **and** no `lat/lon` → queue for the
   `REVIEW_TAG`, exclude from albums.
2. **Home (by name)** — `city` matches `HOME_CITIES` **or** `state` matches
   `HOME_STATES` (case-insensitive) → ignore. **Country guard:** if
   `HOME_COUNTRIES` is configured and the asset has a non-`None` `country`, the
   name match counts as home only when that `country` is in `HOME_COUNTRIES`
   (so `Paris, Texas` is *not* treated as home for a Paris, France resident). If
   `HOME_COUNTRIES` is unset, or the asset has no country, the name match alone
   decides (prior behavior).
3. **Coordinates-only** — has `lat/lon` but **no** `city`/`state` (a common Immich
   geocoding gap). Handled by the optional home-GPS check:
   - If `HOME_LAT/HOME_LON` are configured: haversine distance to home ≤
     `HOME_RADIUS_KM` → **home, ignore**; otherwise → **away**, feed into
     clustering with `country`/`city` = `None` (contributes `lat/lon` for
     distance but no city to the name; the country-change trigger ignores `None`).
   - If home coords are **not** configured: → queue for the `REVIEW_TAG` (do
     **not** assume away). This is the safe default that prevents un-geocoded home
     photos from becoming fake trip albums.
4. **Away** — has a `city` (or `state`) not matching home (with or without coords)
   → feed into clustering.

The four branches form a complete partition: branch 1 = no location at all;
branch 2 = name-matched home **that also passes the country guard**; branch 3 =
coords but no name; branch 4 = named and not home (this includes a name match that
*fails* the country guard, e.g. `Paris, Texas`). Every asset lands in exactly one.

Rationale: a coordinates-only asset is genuinely located but cannot be name-matched
against home, so without a GPS home reference it is ambiguous — routing it to
review (rather than to "away") avoids manufacturing home-trip albums, while the
optional home radius lets users who set it recover those real trips automatically.

## 6. Trip Clustering + Boundary Escalation

The model is **provisional cuts first, then resolve the soft ones** — so every
ambiguous boundary actually *exists* as a boundary (the previous "always-merge the
middle band" wording left middle-band gaps with no boundary to escalate).

1. **Provisional cut pass.** Sort away-assets by `taken_at`. Place a provisional
   boundary between adjacent assets `i, i+1` iff **either**:
   - `gap_days ≥ GAP_MIN_DAYS`, **or**
   - `country` changes across the pair (both non-`None`).

   Sub-`GAP_MIN`, same-country gaps never become boundaries (these are the only
   "hard merges"). This yields provisional clusters and a list of provisional
   boundaries, each of which is then classified exactly once below.
2. **Classify each provisional boundary** (this step only *classifies* boundaries
   placed in step 1 — it never creates new ones):
   - **Hard split** (no escalation) — `gap_days ≥ GAP_MAX_DAYS`, **regardless of
     country**. A gap this large is decisive on its own, and a country change only
     reinforces it; this honors the config guarantee that `≥ GAP_MAX_DAYS` always
     splits.
   - **Soft boundary → escalate** — every boundary with `gap_days < GAP_MAX_DAYS`.
     By construction (step 1) this is exactly:
     - **Middle-band gap** — `GAP_MIN_DAYS ≤ gap_days < GAP_MAX_DAYS`; and/or
     - **Country change** — a country hop with `gap_days < GAP_MAX_DAYS`,
       *including* one with a small gap below `GAP_MIN_DAYS` (it became a boundary
       in step 1, so it is reviewed rather than force-merged).

   **Sparse outlier is an annotation, not a trigger.** For each soft boundary, if
   either adjacent cluster has `≤ OUTLIER_MAX_ASSETS` assets (default `2`), set an
   `outlier` flag in the escalation payload as *context* for the LLM (e.g. "the
   right side is a single layover shot — likely merge"). It does **not** create a
   boundary (a sub-`GAP_MIN`, same-country single shot stays merged, which is the
   desired behavior — one stray photo within a trip is part of that trip) and does
   **not** override a hard split. It only enriches boundaries that are already
   soft. (Chosen over a boundary-creating rule per YAGNI: a same-country photo
   inside the merge window is virtually always part of the surrounding trip.)

   `approx_distance_km` for a soft boundary is the great-circle (haversine)
   distance between the two clusters' centroids (mean of available `lat/lon`). If
   either cluster has no coordinates, it is `null` and omitted from the LLM's
   reasoning.
3. **Batch escalate `resolve_boundary`.** Pack all soft boundaries into one (or a
   few) Claude API call(s). Each boundary payload:
   `{ left: {cities, dates, count}, right: {cities, dates, count}, gap_days,
   approx_distance_km, cause: "middle_band" | "country_change" | "both",
   outlier: bool }`. (`cause` is which step-1 rule(s) placed the boundary —
   `"both"` when a middle-band gap *and* a country change coincide; `outlier` is
   the annotation from step 2.) Response per boundary:
   `{ decision: "merge" | "split", reason }`. Schema-invalid or no key →
   fallback to the `TRIP_GAP_FALLBACK_DAYS` rule (`gap_days ≥` → split, else
   merge; note this defaults small-gap country hops to *merge* unless the LLM
   splits them).
4. Apply hard splits + merge/split verdicts to produce final trips.

## 7. Naming (enrichment)

Each final trip has a stable identity `trip_key` = the immutable Immich **asset
id of its earliest asset** (see §9). `name_trip` is **cached by `trip_key`**, not
by mutable trip contents — so adding photos to an existing trip later does **not**
re-roll the title.

`name_trip` payload `{ cities_in_order, date_range, count }`, response
`{ title, confidence }`. Fallback title = `"<top city/cities>, <Mon Year>"`
(multi-city → `"Lisbon & Porto"`). `ALBUM_PREFIX` is prepended in all cases, e.g.
`Trip — Lisbon long weekend` or `Trip — Lisbon & Porto, Apr 2025`. The title is
**display metadata only**; album identity is the `trip_key` marker, never the title.

## 8. Shared Escalation Seam

A single function:

```
escalate(kind, payload, response_schema, fallback_fn) -> verdict
```

Responsibilities: prompt assembly, Claude API call, schema validation, caching,
audit logging, and fallback on any failure. The caller supplies an explicit
**cache key** chosen to reuse a verdict exactly when it is still valid:
- `resolve_boundary` keys on a **composite** of *boundary identity* **and**
  *decision-relevant facts*:
  - **Identity** — the stable endpoint ids of the boundary: the earliest-asset id
    of the left cluster and of the right cluster. This pins the key to *this*
    boundary so two unrelated boundaries can never collide on coincidentally-equal
    facts.
  - **Facts** — bucketed `gap_days`, both `country` values, `cause`, the `outlier`
    flag, and bucketed `approx_distance_km`. This invalidates the cache when the
    inputs that drove the verdict materially change.
  Both are required. Identity alone would freeze a stale verdict when new photos
  move the gap/countries/distance; facts alone would let distinct boundaries reuse
  each other's verdict. With the composite, adding photos *inside* a trip (neither
  endpoint nor facts move) still hits the cache, while a material change to the
  boundary re-adjudicates, and unrelated boundaries are always distinct. `count`
  is excluded; bucketing keeps trivial jitter (a few hours, a few km) from forcing
  re-adjudication.
- `name_trip` keys on `trip_key` (§7) — titles are display-only and must stay
  stable as a trip grows, so identity (not facts) is the right key there.

Two call sites: `resolve_boundary` and `name_trip`. With no key or `--no-llm`,
every call routes straight to `fallback_fn`, so the pipeline behaves as a pure
deterministic version and remains idempotent.

## 9. Apply (idempotent, dry-run by default)

Default run **prints the plan only** and changes nothing: trip list with names,
date ranges, asset counts, the review-tag count, and — for each ambiguous
boundary — the merge/split decision + reason and whether each title is LLM or
fallback.

With `--apply`:

- **Albums (identity by marker, not title).** Each trip has a stable `trip_key`
  (earliest asset id). Every album this tool creates stores a machine marker in
  its **description**: `[immich-trip-albummer] key=<trip_key>`. On apply:
  `GET /api/albums`, parse markers, and index by `trip_key`.
  - **Match found** → reuse that album. Add new assets via
    `PUT /api/albums/{id}/assets` (Immich skips assets already present, so re-adds
    are safe). If the freshly computed title differs, **`PATCH /api/albums/{id}`
    to rename in place** — never create a second album.
  - **No match** → `POST /api/albums` with the title and the marker description.
  This makes re-runs idempotent under content growth: adding photos to a trip
  updates the existing album rather than spawning a duplicate, because identity is
  the `trip_key` marker, not the (mutable, possibly LLM-generated) title.
- **Tag (rerun-safe).** `GET /api/tags`, exact-name (case-insensitive) lookup for
  `REVIEW_TAG` → reuse its id; else `POST /api/tags`. Then bulk-attach the
  review assets via `PUT /api/tags/assets` (`{ tagIds, assetIds }`). Re-attaching
  an already-tagged asset is a no-op.

### Idempotency limits (known, surfaced in the plan)

`trip_key` = earliest-asset id is stable under the common case (incremental
forward imports). Two cases are best-effort and explicitly reported in the
dry-run plan rather than silently "handled":

- **Earlier asset imported into an existing trip** (e.g. back-filling old photos)
  can shift a trip's earliest asset, changing its `trip_key`. The plan flags any
  trip whose `trip_key` has no matching album marker but which overlaps an
  existing tool-made album, so the user can reconcile instead of getting a quiet
  duplicate.
- **Re-clustering merges/splits a previously albumed trip differently** (new data
  changed a boundary verdict). The tool never deletes or rewrites old albums
  (per §13); it reports the divergence (which existing album(s) the new trip
  overlaps) and leaves reconciliation to the user.

## 10. Auditability

`escalations.jsonl` records every escalation: `kind`, cache key, full payload,
verdict, reason, and whether the verdict or the fallback was applied. This answers
"why was this trip split / named this way?" after the fact.

## 11. Error Handling

- Auth failure or unexpected API response shape → fail loudly with a message
  naming the endpoint and the assumed Immich API version.
- LLM failure (no key, timeout, malformed/invalid verdict) → silent, logged
  fallback. Never aborts the pipeline.

## 12. Testing

- **Pure functions** → unit-tested with fixture assets, no network/LLM:
  - classification, incl. the four branches, the home-GPS radius edge (coords
    inside radius = home, outside = away, no-home-coords = review), and the
    `HOME_COUNTRIES` guard (same-named foreign city like `Paris, Texas` is **not**
    home; unset guard or `None` country falls back to name-only);
  - provisional-cut pass (cut at `≥ GAP_MIN` **or** country change; sub-`GAP_MIN`
    same-country stays merged);
  - boundary classification (hard-split vs soft/escalate), incl.: a small-gap
    country hop landing in the escalate set; a `gap ≥ GAP_MAX` country-change
    boundary classified as a **hard split** (never soft); and a sub-`GAP_MIN`
    same-country single shot creating **no** boundary (outlier is annotation only);
  - haversine/centroid distance, incl. `null` when coords absent;
  - fallback naming and `trip_key` derivation.
- **`escalate`** → injected fake adjudicator. Assert: a valid verdict is adopted;
  an invalid verdict triggers the fallback; a repeated cache key does not
  re-invoke the adjudicator; `--no-llm` always routes to fallback. Plus
  `resolve_boundary` composite cache-key behavior: adding photos *inside* a trip
  (endpoints + facts unchanged) hits the cache; a change to gap-bucket/country/
  distance re-adjudicates; and two boundaries with identical fact-buckets but
  different endpoint ids get **distinct** keys (no cross-boundary collision).
- **Idempotency** → given recorded album/tag responses, assert: marker parsing
  finds the right album by `trip_key`; a changed title triggers `PATCH` (not a new
  album); growing a trip re-uses the album; the re-clustering/earlier-import edge
  cases are reported in the plan rather than duplicating.
- **API client** → thin layer exercised via the dry-run plan output against
  recorded/fake responses pinned to the target API version.

## 13. Out of Scope (YAGNI)

- No external reverse-geocoder — rely on Immich's stored geocoding.
- Home is matched primarily by city/state name; GPS radius is an **optional,
  narrow** fallback used *only* for coordinates-only assets (§5), not a general
  home-zone mechanism.
- No generalized escalation framework — only the single-file seam above.
- No automatic album deletion or re-clustering of previously created albums (see
  Idempotency limits in §9).

## 14. Assumptions / Version Risk

Endpoints/fields below were **verified against the current Immich OpenAPI spec**
(`open-api/immich-openapi-specs.json`): `POST /search/metadata` (singular `type`,
`visibility`, `withDeleted`, `withStacked`, paginated `assets.items`/`nextPage`);
`GET/POST /albums`, `PUT /albums/{id}/assets`, `PATCH /albums/{id}`; `GET/POST
/tags`, `PUT /tags/assets` (`{tagIds, assetIds}`); API-key auth via `x-api-key`;
`exifInfo` carrying `city/state/country/dateTimeOriginal/latitude/longitude`.

Immich's published API docs are generated from this OpenAPI source on `main`,
which moves. **Tests and the client must be pinned to the target server's API
version**, not to `main`; the client fails loudly on any auth failure or
unexpected response shape so a version drift is visible and fixable rather than
silent.
