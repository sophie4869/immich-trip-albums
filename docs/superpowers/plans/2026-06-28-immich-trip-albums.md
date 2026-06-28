# Immich Trip Albummer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python CLI that scans an Immich library, clusters away-from-home photos/videos into trips, and creates one album per trip (dry-run by default, idempotent), tagging un-locatable assets for review.

**Architecture:** A deterministic pipeline (fetch → classify → cluster → name → apply) with a single optional LLM seam (`escalate`) that adjudicates ambiguous trip boundaries and generates album titles. The LLM is enrichment with a deterministic fallback, so the whole tool runs correctly with no API key. Pure logic (classify/cluster/naming) is separated from I/O (Immich client, Anthropic call) so the core is unit-tested without a network.

**Tech Stack:** Python 3.11+, `requests` (Immich HTTP), `anthropic` (optional LLM), `pytest` (tests). No external geocoder.

**Spec:** [docs/superpowers/specs/2026-06-28-immich-trip-albums-design.md](../specs/2026-06-28-immich-trip-albums-design.md)

---

## File Structure

```
trip_albums/
  __init__.py
  models.py       # Asset, Boundary, Trip, AlbumPlan, Plan dataclasses + Asset.from_api
  config.py       # Config dataclass + load_config() from env/.env
  geo.py          # haversine_km(), centroid()
  classify.py     # classify_assets() -> (away, review, home counts) ; 4-branch partition
  cluster.py      # provisional cuts, boundary classification, apply verdicts -> trips
  naming.py       # trip_key(), fallback_title()
  escalate.py     # escalate() seam: cache + audit log + fallback; Adjudicator protocol
  adjudicate.py   # resolve_boundary(), name_trip(): payloads, schemas, cache keys, fallbacks; AnthropicAdjudicator
  immich.py       # ImmichClient: search_assets, list/create/patch albums, add assets, tags
  planner.py      # build_plan(): orchestrate fetch->classify->cluster->escalate->name
  apply.py        # apply_plan(): idempotent album reuse/create/patch + tag ensure/attach
  render.py       # render_plan(): human dry-run text
  cli.py          # argparse, wiring, main()
tests/
  conftest.py
  fixtures.py     # asset/album/tag builders
  test_geo.py
  test_models.py
  test_config.py
  test_classify.py
  test_cluster.py
  test_naming.py
  test_escalate.py
  test_adjudicate.py
  test_immich.py
  test_planner.py
  test_apply.py
  test_cli.py
pyproject.toml
.env.example
README.md
```

**Responsibility boundaries:** `geo`/`classify`/`cluster`/`naming` are pure (no I/O). `escalate` owns caching/audit/fallback but not the actual API (injected `Adjudicator`). `adjudicate` builds payloads + the real `AnthropicAdjudicator`. `immich` is the only HTTP-to-Immich module. `planner` wires pure + escalate; `apply` is the only module that mutates Immich.

---

## Task 0: Project scaffold

**Files:**
- Create: `pyproject.toml`, `trip_albums/__init__.py`, `tests/conftest.py`, `.env.example`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "trip-albums"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["requests>=2.31", "anthropic>=0.40"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
trip-albums = "trip_albums.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty `trip_albums/__init__.py` and `tests/conftest.py`** (conftest may just add the repo root to `sys.path`; with an installed package it can be empty).

- [ ] **Step 3: Write `.env.example`**

```
IMMICH_URL=https://immich.example.com
IMMICH_API_KEY=
HOME_CITIES=Paris
HOME_STATES=
HOME_COUNTRIES=France
HOME_LAT=
HOME_LON=
HOME_RADIUS_KM=25
GAP_MIN_DAYS=1.5
GAP_MAX_DAYS=6
TRIP_GAP_FALLBACK_DAYS=4
OUTLIER_MAX_ASSETS=2
REVIEW_TAG=needs-location-review
ALBUM_PREFIX=Trip —
ANTHROPIC_API_KEY=
```

- [ ] **Step 4: Set up venv + install**

Run: `python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`
Expected: installs cleanly.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml trip_albums/__init__.py tests/conftest.py .env.example
git commit -m "chore: project scaffold"
```

---

## Task 1: Geo helpers (`geo.py`)

**Files:**
- Create: `trip_albums/geo.py`
- Test: `tests/test_geo.py`

- [ ] **Step 1: Write failing tests**

```python
import math
from trip_albums.geo import haversine_km, centroid

def test_haversine_known_distance():
    # Paris -> London ~ 343 km
    d = haversine_km(48.8566, 2.3522, 51.5074, -0.1278)
    assert 330 < d < 355

def test_haversine_zero():
    assert haversine_km(1.0, 2.0, 1.0, 2.0) == 0.0

def test_centroid_mean_of_points():
    assert centroid([(0.0, 0.0), (2.0, 4.0)]) == (1.0, 2.0)

def test_centroid_none_when_empty():
    assert centroid([]) is None
```

- [ ] **Step 2: Run to verify fail** — `pytest tests/test_geo.py -v` → FAIL (module missing)

- [ ] **Step 3: Implement `geo.py`**

```python
import math

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

def centroid(points):
    if not points:
        return None
    n = len(points)
    return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)
```

- [ ] **Step 4: Run to verify pass** — `pytest tests/test_geo.py -v` → PASS
- [ ] **Step 5: Commit** — `git add trip_albums/geo.py tests/test_geo.py && git commit -m "feat: geo haversine + centroid"`

---

## Task 2: Asset model (`models.py`)

**Files:**
- Create: `trip_albums/models.py`
- Test: `tests/test_models.py`, `tests/fixtures.py`

`Asset.from_api` normalizes a raw Immich asset dict (with `exifInfo`) into
`{ id, type, city, state, country, lat, lon, taken_at }`. `taken_at` is a
timezone-aware `datetime` from `exifInfo.dateTimeOriginal` (fallback
`fileCreatedAt`). Empty strings become `None`.

- [ ] **Step 1: Write `tests/fixtures.py` helper**

```python
def api_asset(id="a1", type="IMAGE", city=None, state=None, country=None,
              lat=None, lon=None, taken="2025-04-01T12:00:00.000Z"):
    return {
        "id": id, "type": type,
        "exifInfo": {"city": city, "state": state, "country": country,
                     "latitude": lat, "longitude": lon,
                     "dateTimeOriginal": taken, "fileCreatedAt": taken},
    }
```

- [ ] **Step 2: Write failing tests**

```python
from datetime import datetime, timezone
from trip_albums.models import Asset
from tests.fixtures import api_asset

def test_from_api_basic():
    a = Asset.from_api(api_asset(city="Lisbon", country="Portugal", lat=38.7, lon=-9.1))
    assert a.id == "a1" and a.type == "IMAGE"
    assert a.city == "Lisbon" and a.country == "Portugal"
    assert a.lat == 38.7 and a.lon == -9.1
    assert a.taken_at == datetime(2025, 4, 1, 12, 0, tzinfo=timezone.utc)

def test_from_api_empty_strings_become_none():
    a = Asset.from_api(api_asset(city="", state=""))
    assert a.city is None and a.state is None

def test_from_api_falls_back_to_file_created_at():
    raw = api_asset()
    raw["exifInfo"]["dateTimeOriginal"] = None
    a = Asset.from_api(raw)
    assert a.taken_at is not None
```

- [ ] **Step 3: Run → FAIL**
- [ ] **Step 4: Implement `models.py`** (Asset dataclass + `from_api` with ISO parsing handling trailing `Z`; also stub `Boundary`, `Trip`, `AlbumPlan`, `Plan` dataclasses used later). Parse dates with `datetime.fromisoformat(s.replace("Z", "+00:00"))`.
- [ ] **Step 5: Run → PASS**
- [ ] **Step 6: Commit** — `git commit -m "feat: Asset.from_api normalization"`

---

## Task 3: Config (`config.py`)

**Files:**
- Create: `trip_albums/config.py`
- Test: `tests/test_config.py`

`load_config(env: dict) -> Config`. Parses lists from comma-separated strings,
floats/ints from strings, optional home coords (all-or-nothing). Validates
`GAP_MIN ≤ TRIP_GAP_FALLBACK ≤ GAP_MAX`. Raises `ConfigError` on missing
`IMMICH_URL`/`IMMICH_API_KEY` or bad threshold ordering.

- [ ] **Step 1: Write failing tests** — cover: list parsing (`"Paris, Lyon"` → `["paris","lyon"]` lowercased), threshold-order validation raises, missing URL raises, home coords require both lat+lon, `ANTHROPIC_API_KEY` absent ⇒ `llm_enabled=False`.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `config.py`** — `Config` dataclass with all keys from `.env.example`; `home_cities/home_states/home_countries` stored lowercased; `llm_enabled = bool(anthropic_api_key) and not no_llm`.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: config loading + validation"`

---

## Task 4: Classification (`classify.py`)

**Files:**
- Create: `trip_albums/classify.py`
- Test: `tests/test_classify.py`

Implements spec §5 exactly. `classify_assets(assets, config) -> Classified`
where `Classified` has `.away: list[Asset]`, `.review: list[Asset]` (no-location +
coords-only-without-home-coords), `.home_count: int`. Per-asset `classify_one`
returns one of `"away" | "home" | "review"`.

Branch order (each asset lands in exactly one):
1. no `city`/`state` **and** no `lat/lon` → `review`
2. name match (`city` in `home_cities` or `state` in `home_states`), **and** country
   guard passes (`home_countries` unset, or asset `country` is None, or in list) → `home`
3. has `lat/lon`, no `city`/`state` (coords-only):
   - home coords set: haversine ≤ `home_radius_km` → `home`, else `away`
   - home coords unset → `review`
4. else (named, not home) → `away`

- [ ] **Step 1: Write failing tests** — one per branch plus edges:
  - no-loc → review; Paris/France with guard → home; **Paris/USA with `HOME_COUNTRIES=[France]` → away** (country guard); coords-only inside radius → home; coords-only outside radius → away; coords-only, no home coords → review; Lisbon/Portugal → away.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `classify.py`** following the branch order; use `geo.haversine_km`.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: 4-branch asset classification"`

---

## Task 5: Naming + trip key (`naming.py`)

**Files:**
- Create: `trip_albums/naming.py`
- Test: `tests/test_naming.py`

- `trip_key(trip_assets) -> str`: the id of the earliest asset (by `taken_at`).
- `fallback_title(trip, prefix) -> str`: `"<prefix> <top cities>, <Mon Year>"`.
  Top cities = the up-to-2 most common non-None cities in order of frequency;
  multi → `"Lisbon & Porto"`; none → `"Unknown area"`. Month/year from earliest asset.

- [ ] **Step 1: Write failing tests** — earliest-asset key stable regardless of input order; single-city title; two-city `&` title; all-None-city → "Unknown area"; prefix applied.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `naming.py`**
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: trip_key + fallback title"`

---

## Task 6: Clustering (`cluster.py`)

**Files:**
- Create: `trip_albums/cluster.py`
- Test: `tests/test_cluster.py`

Implements spec §6. Functions:
- `provisional_cut(away_sorted, config) -> list[list[Asset]]`: boundary between
  adjacent assets iff `gap_days ≥ GAP_MIN` **or** country changes (both non-None).
- `boundaries(clusters, config) -> list[Boundary]`: for each adjacent pair, build a
  `Boundary` with `gap_days`, `cause ∈ {middle_band, country_change, both}`,
  `hard: bool` (`gap_days ≥ GAP_MAX`), `outlier: bool` (either side ≤
  `OUTLIER_MAX_ASSETS`), `approx_distance_km` (haversine of centroids, or None),
  and the two endpoint ids (earliest asset id each side).
- `resolve(clusters, boundaries, verdicts) -> list[Trip]`: hard boundaries always
  split; soft boundaries split unless the verdict says merge; merge concatenates
  adjacent clusters into one `Trip`.

- [ ] **Step 1: Write failing tests** (use fixtures, fixed datetimes):
  - middle-band gap → one soft boundary, `cause=middle_band`, `hard=False`.
  - small-gap (< GAP_MIN) **country change** → soft boundary `cause=country_change`.
  - `gap ≥ GAP_MAX` with country change → `hard=True` (split regardless of country).
  - sub-GAP_MIN same country → **no** boundary (single cluster); outlier never cuts.
  - `outlier` flag set when a side has ≤ OUTLIER_MAX_ASSETS but does not create a boundary.
  - `approx_distance_km` is None when a cluster has no coords.
  - `resolve`: a soft boundary with verdict `merge` yields one trip; `split` yields two; hard always two.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `cluster.py`** (gap in days = `(b.taken_at - a.taken_at).total_seconds()/86400`).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: provisional clustering + boundary classification"`

---

## Task 7: Escalation seam (`escalate.py`)

**Files:**
- Create: `trip_albums/escalate.py`
- Test: `tests/test_escalate.py`

`escalate(kind, payload, cache_key, schema, fallback_fn, adjudicator, audit) ->
verdict`. Behavior:
- If `adjudicator is None` (no key / `--no-llm`) → return `fallback_fn(payload)`,
  audit `applied="fallback"`.
- Else check `cache[cache_key]`; on hit return it (no adjudicator call), audit
  `applied="cache"`.
- Else call `adjudicator(kind, payload)`; validate against `schema` (minimal
  validator: required keys + enum membership). Invalid/raises → `fallback_fn`,
  audit `applied="fallback"` with the error. Valid → cache + return, audit
  `applied="verdict"`.
- `audit` is an injected callback (writes one JSON line); tests pass a list-append.

`Adjudicator` is a `typing.Protocol` (callable). Validation is a small local
function, not jsonschema (YAGNI).

- [ ] **Step 1: Write failing tests** with a fake adjudicator:
  - valid verdict adopted + cached; second identical `cache_key` does **not** call the adjudicator again.
  - invalid verdict (missing key / bad enum) → fallback used; audit records `fallback`.
  - adjudicator raising → fallback used.
  - `adjudicator=None` → fallback used, no call.
  - distinct `cache_key`s do not share results (collision guard).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `escalate.py`**
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: escalate seam with cache/fallback/audit"`

---

## Task 8: Adjudicators (`adjudicate.py`)

**Files:**
- Create: `trip_albums/adjudicate.py`
- Test: `tests/test_adjudicate.py`

**REFERENCE SKILL @claude-api** before writing the Anthropic call — confirm model
id and Messages API usage. Use a small fast model for these bounded judgments
(e.g. `claude-haiku-4-5-20251001` or `claude-sonnet-4-6`); make it a module
constant so it is easy to change.

Provides:
- `boundary_cache_key(boundary) -> str`: composite of endpoint ids **and** fact
  buckets — `f"{left_id}|{right_id}|{gap_bucket}|{lc}|{rc}|{cause}|{outlier}|{dist_bucket}"`
  (gap bucket = `round(gap_days*2)/2`; dist bucket = `round(dist/25)` or `"na"`).
- `boundary_fallback(payload) -> {"decision","reason"}`: `gap_days ≥
  TRIP_GAP_FALLBACK_DAYS` → split else merge; reason notes "fallback".
- `name_fallback(trip, prefix)`: wraps `naming.fallback_title`.
- `BOUNDARY_SCHEMA = {"required": ["decision","reason"], "enums": {"decision": ["merge","split"]}}`,
  `NAME_SCHEMA = {"required": ["title"], ...}`.
- `AnthropicAdjudicator`: callable `(kind, payload) -> dict`; builds the prompt per
  `kind`, calls Messages API, parses a strict JSON object from the response.

- [ ] **Step 1: Write failing tests** (no network):
  - `boundary_cache_key`: same boundary facts+ids → equal key; change gap bucket → different key; **same facts, different endpoint ids → different key**.
  - `boundary_fallback`: gap above fallback → split; below → merge.
  - `name_fallback` delegates to naming.
  - schema constants shape.
  (Do **not** unit-test the live Anthropic call; keep `AnthropicAdjudicator` thin and covered by a JSON-parse test with a stubbed client.)
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `adjudicate.py`** (consult @claude-api for the Messages call; inject the `anthropic.Anthropic` client so it can be stubbed).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: boundary/name adjudicators + cache keys"`

---

## Task 9: Immich client (`immich.py`)

**Files:**
- Create: `trip_albums/immich.py`
- Test: `tests/test_immich.py`

`ImmichClient(base_url, api_key, session=None)` — `session` injectable for tests.
Sends `x-api-key`. Methods (spec §4/§9), all raising a clear `ImmichError` on
non-2xx or unexpected shape:
- `search_all_assets()` → generator/list across pages: POST `/api/search/metadata`
  with `{withExif: true, withDeleted: false, page, size: 1000}` (omit `type`),
  loop on `assets.nextPage`, yield `assets.items`.
- `list_albums()` → GET `/api/albums`.
- `create_album(name, description, asset_ids)` → POST `/api/albums`.
- `rename_album(album_id, name)` → PATCH `/api/albums/{id}`.
- `add_assets(album_id, ids)` → PUT `/api/albums/{id}/assets`.
- `list_tags()` / `create_tag(name)` → GET/POST `/api/tags`.
- `tag_assets(tag_ids, asset_ids)` → PUT `/api/tags/assets`.

- [ ] **Step 1: Write failing tests** with a fake `requests.Session` (monkeypatched
  `request` returning canned `Response`-likes):
  - pagination stops at `nextPage=None` and concatenates items across 2 pages.
  - `x-api-key` header present.
  - non-2xx raises `ImmichError` naming the endpoint.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `immich.py`**
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: Immich HTTP client"`

---

## Task 10: Planner (`planner.py`)

**Files:**
- Create: `trip_albums/planner.py`
- Test: `tests/test_planner.py`

`build_plan(assets, config, adjudicator, audit) -> Plan`. Orchestrates:
fetch is done by caller; here: classify → sort away → provisional clusters →
boundaries → for each soft boundary call `escalate("resolve_boundary", payload,
boundary_cache_key, BOUNDARY_SCHEMA, boundary_fallback, adjudicator, audit)` →
`resolve` into trips → for each trip compute `trip_key` and call
`escalate("name_trip", ...)` (fallback `name_fallback`) → assemble `Plan` with
`trips` (id=trip_key, title, asset_ids, date range, city summary, per-boundary
decisions+reasons) and `review_asset_ids`.

- [ ] **Step 1: Write failing tests** using fixtures + a fake adjudicator (no network):
  - two clearly-separate trips (big gap) → 2 trips, no escalation calls.
  - one ambiguous boundary, fake verdict `merge` → 1 trip; `split` → 2 trips.
  - review assets surfaced.
  - with `adjudicator=None`, falls back deterministically (still produces a Plan).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `planner.py`**
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: build_plan orchestration"`

---

## Task 11: Apply (`apply.py`)

**Files:**
- Create: `trip_albums/apply.py`
- Test: `tests/test_apply.py`

`apply_plan(plan, client, config) -> ApplyResult`. Spec §9:
- `MARKER = "[immich-trip-albummer] key="`. Build `{trip_key: album}` index by
  parsing markers from `client.list_albums()` descriptions.
- For each trip: match by `trip_key` →
  - found: `add_assets`; if `album.name != title` → `rename_album` (PATCH).
  - missing: `create_album(title, description=f"{MARKER}{trip_key}", asset_ids)`.
  - report (don't act) the §9 idempotency-limit cases: a trip whose `trip_key` is
    unknown but whose assets overlap an existing tool-made album.
- Tag: find `REVIEW_TAG` via `list_tags()` (case-insensitive) else `create_tag`;
  `tag_assets([tag_id], review_asset_ids)`.

- [ ] **Step 1: Write failing tests** with a fake client (records calls):
  - new trip → `create_album` with marker in description.
  - existing marker → `add_assets`, no create.
  - existing marker + changed title → `rename_album` called (not a 2nd create).
  - tag reused when present; created when absent; `tag_assets` called with review ids.
  - overlap/earlier-import case is reported in `ApplyResult.warnings`, not duplicated.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `apply.py`**
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: idempotent apply (albums + tag)"`

---

## Task 12: Render + CLI (`render.py`, `cli.py`)

**Files:**
- Create: `trip_albums/render.py`, `trip_albums/cli.py`
- Test: `tests/test_cli.py`

- `render_plan(plan) -> str`: human dry-run text — trips (title, dates, count),
  per ambiguous boundary the merge/split + reason + whether title is LLM/fallback,
  review count, and any idempotency warnings.
- `cli.main(argv)`: argparse `--apply`, `--no-llm`, `--env PATH`. Loads `.env`
  (simple `KEY=VALUE` parser merged over `os.environ`), builds `Config`, constructs
  `ImmichClient`; constructs `AnthropicAdjudicator` only if `config.llm_enabled`
  else `None`; opens `escalations.jsonl` audit sink; fetches assets; `build_plan`;
  prints `render_plan`; if `--apply` calls `apply_plan` and prints results.

- [ ] **Step 1: Write failing tests**:
  - `render_plan` includes a trip title and the review count (string asserts on a Plan fixture).
  - `main(["--no-llm"])` with a stubbed client (monkeypatched) runs dry-run and prints a plan without calling apply.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement `render.py` + `cli.py`**
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `git commit -m "feat: dry-run renderer + CLI"`

---

## Task 13: Docs + full test run

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`** — what it does, install, `.env` setup, dry-run vs `--apply`, `--no-llm`, the review tag, idempotency notes, Immich version caveat (pin to your server version).
- [ ] **Step 2: Run the whole suite** — `pytest -q` → all PASS.
- [ ] **Step 3: Commit** — `git commit -m "docs: README"`

---

## Notes for the implementer
- **TDD throughout** (@superpowers:test-driven-development): red → green → commit per task.
- **DRY/YAGNI:** no jsonschema dep (tiny local validator); no external geocoder; LLM strictly optional.
- Keep pure modules free of `requests`/`anthropic` imports so the core suite needs no network.
- Use fixed `datetime`s in tests (no `Date.now()`); the Anthropic live call is never exercised in unit tests.
