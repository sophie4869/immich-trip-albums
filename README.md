# Immich Trip Albummer

Scans an [Immich](https://immich.app) library, finds photos and videos taken
**away from home**, clusters them into **trips**, and creates **one album per
trip**. Assets with no usable location are tagged for manual review instead of
being albumed. **Dry-run by default**, idempotent on re-runs.

A thin, optional LLM layer (Claude) adjudicates ambiguous trip boundaries and
writes nicer album titles. With no `ANTHROPIC_API_KEY` (or `--no-llm`) the whole
tool runs as a pure deterministic pipeline and still produces correct results.

## How it works

```
fetch assets ─▶ classify ─▶ cluster into trips ─▶ name ─▶ (dry-run plan │ apply)
                   │             │                  │
              home/away/      gap + country      LLM or
              review          boundaries         fallback
```

- **Classify** — each asset is exactly one of: *no-location* (→ review tag),
  *home* (city/state name match, optionally guarded by `HOME_COUNTRIES`, plus an
  optional home-GPS radius for coordinates-only shots), or *away*.
- **Cluster** — away-assets are cut into provisional clusters at every gap ≥
  `GAP_MIN_DAYS` or country change; a gap ≥ `GAP_MAX_DAYS` is always a separate
  trip, and anything in between is adjudicated (LLM, or a deterministic
  `TRIP_GAP_FALLBACK_DAYS` rule).
- **Name** — each trip gets an LLM title (e.g. *Portugal road trip*) or a
  mechanical `City, Mon Year` fallback.
- **Apply** — albums are identified by a marker stored in the album description
  (`[immich-trip-albummer] key=<earliest-asset-id>`), so re-runs reuse and update
  albums instead of duplicating them.

## Install

Requires Python 3.11+.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Configure

Copy `.env.example` to `.env` and fill it in:

```bash
cp .env.example .env
```

| Key | Meaning |
|-----|---------|
| `IMMICH_URL` | Base URL of your Immich instance |
| `IMMICH_API_KEY` | Immich API key (Account Settings → API Keys); sent as `x-api-key` |
| `HOME_CITIES` | Comma-separated city names that count as home (e.g. `Paris`) |
| `HOME_STATES` | Optional broader home match (e.g. `Île-de-France`) |
| `HOME_COUNTRIES` | Optional guard so `Paris, Texas` isn't treated as home |
| `HOME_LAT` / `HOME_LON` / `HOME_RADIUS_KM` | Optional home GPS radius, used only for coordinates-only assets |
| `GAP_MIN_DAYS` / `GAP_MAX_DAYS` / `TRIP_GAP_FALLBACK_DAYS` | Trip-splitting thresholds |
| `OUTLIER_MAX_ASSETS` | Cluster size that flags a boundary as an outlier (LLM context only) |
| `REVIEW_TAG` | Tag applied to no-location assets |
| `ALBUM_PREFIX` | Prefix for trip album names |
| `ANTHROPIC_API_KEY` | Optional; enables the LLM layer |

## Run

Dry run (default — prints the plan, changes nothing):

```bash
trip-albums --env .env
```

Apply (creates albums and tags):

```bash
trip-albums --env .env --apply
```

Deterministic only (skip the LLM even if a key is set):

```bash
trip-albums --env .env --no-llm
```

Every LLM decision (and its deterministic fallback) is logged to
`escalations.jsonl` so you can see why a trip was split or named the way it was.

## Idempotency notes

- Album identity is the description marker, **not** the title — re-runs add new
  photos to the existing album and rename it in place if the title changed.
- Two best-effort cases are **reported in the plan** rather than silently
  duplicated: back-filling an *earlier* photo into an existing trip (which shifts
  the trip's earliest-asset key), and re-clustering that merges/splits a
  previously-albumed trip differently. The tool never deletes or rewrites albums
  it made; reconcile those manually.

## Immich API version

Endpoints and fields target a recent Immich API (`/api/search/metadata`,
`/api/albums`, `/api/tags`, with `exifInfo` carrying
`city/state/country/dateTimeOriginal/latitude/longitude`). If your instance
differs, the client fails loudly naming the endpoint. **Pin and test against your
own server version** rather than assuming `main`.

## Tests

```bash
pytest -q
```

The deterministic core (classification, clustering, naming, idempotency) is fully
unit-tested with no network and no LLM calls.
