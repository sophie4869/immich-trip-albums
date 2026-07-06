# Immich Trip Albummer

Scans an [Immich](https://immich.app) library, finds photos and videos taken
**away from home**, clusters them into **trips**, and creates **one album per
trip**. Screenshots and assets without any location data are silently skipped.
**Dry-run by default**, idempotent on re-runs.

## How it works

```
fetch assets ─▶ classify ─▶ cluster into trips ─▶ name ─▶ (dry-run plan │ apply)
                   │             │                  │
              home/away/      gap + country      mechanical
              skip            boundaries         fallback title
```

- **Classify** — each asset is exactly one of: *skip* (no location data, or a
  screenshot without location), *home* (city/state name match, optionally guarded
  by `HOME_COUNTRIES`, plus an optional home-GPS radius for coordinates-only shots),
  or *away*.
- **Cluster** — away-assets are cut into provisional clusters at every gap ≥
  `GAP_MIN_DAYS` or country change; a gap ≥ `GAP_MAX_DAYS` is always a separate
  trip, and anything in between is decided by a deterministic
  `TRIP_GAP_FALLBACK_DAYS` rule.
- **Name** — each trip gets a mechanical `City, Mon Year` title based on its
  assets' location metadata.
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

Use the interactive setup script to generate a `.env` file:

```bash
bash setup-env.sh
```

Or copy `.env.example` and fill it in manually:

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
| `OUTLIER_MAX_ASSETS` | Cluster size that flags a boundary as an outlier (annotation only) |
| `ALBUM_PREFIX` | Prefix for trip album names (default: `Trip — `) |

## Run

Dry run (default — prints the plan, changes nothing):

```bash
trip-albums --env .env
```

Apply (creates albums):

```bash
trip-albums --env .env --apply
```

Scope to a date range — a safe first pass, an incremental/cron run, or
reprocessing one window:

```bash
trip-albums --env .env --since 2025-01-01            # everything from Jan 1
trip-albums --env .env --since 2025-06-01 --apply    # e.g. nightly "new photos" run
trip-albums --env .env --since 2025-04-01 --until 2025-04-30
```

`--since` / `--until` filter **server-side** (`takenAfter`/`takenBefore`), so a
big library isn't fetched whole. A `GAP_MAX_DAYS` buffer is fetched on each side
of the window so a trip straddling an edge still clusters correctly; only trips
with at least one photo inside the window are albumed.

## Idempotency notes

- Album identity is the description marker, **not** the title — so you can
  **rename an album freely in Immich** and re-runs still recognize it and leave
  your name untouched (already-albumed trips are detected by marker and skipped).
- Auto-generated names are just `City1 & City2, Mon Year`. Rename in the Immich
  UI whenever you like, or — if you drive this tool through the `trip-albums`
  Claude skill — ask the agent to suggest better trip names (e.g. *Côte d'Azur*
  instead of *Cassis & Marseille 02*) before or after creating albums.
- Two best-effort cases are **reported in the plan** rather than silently
  duplicated: back-filling an *earlier* photo into an existing trip (which shifts
  the trip's earliest-asset key), and re-clustering that merges/splits a
  previously-albumed trip differently. The tool never deletes or rewrites albums
  it made; reconcile those manually.

## Screenshot filtering

Assets whose `originalPath` contains `screenshot`, `screen shot`, `screen_shot`,
or `screens/` and have no location data are automatically skipped and not counted
toward trips.

## Immich API version

Endpoints and fields target a recent Immich API (`/api/search/metadata`,
`/api/albums`, with `exifInfo` carrying
`city/state/country/dateTimeOriginal/latitude/longitude`). If your instance
differs, the client fails loudly naming the endpoint. **Pin and test against your
own server version** rather than assuming `main`.

## Tests

```bash
pytest -q
```

The deterministic core (classification, clustering, naming, idempotency) is fully
unit-tested with no network calls.
