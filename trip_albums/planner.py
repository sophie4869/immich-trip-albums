"""Orchestrate the deterministic pipeline into a Plan."""

from datetime import timedelta

from .classify import classify_assets
from .cluster import boundaries, provisional_cut, resolve
from .models import Plan
from .naming import fallback_title

# ---------------------------------------------------------------------------
# Schemas and cache-key helpers (previously in adjudicate.py)
# ---------------------------------------------------------------------------

BOUNDARY_SCHEMA = {"required": ["decision", "reason"], "enums": {"decision": ["merge", "split"]}}
NAME_SCHEMA = {"required": ["title"], "enums": {}}


def _boundary_cache_key(boundary, left_country, right_country):
    """Composite key: endpoint identity + decision-relevant fact buckets."""
    gap_bucket = round(boundary.gap_days * 2) / 2  # half-day buckets
    lc = (left_country or "none").lower()
    rc = (right_country or "none").lower()
    dist = boundary.approx_distance_km
    dist_bucket = "na" if dist is None else round(dist / 25)  # 25km buckets
    parts = [boundary.left_id, boundary.right_id, gap_bucket, lc, rc,
             boundary.cause, int(boundary.outlier), dist_bucket]
    return "|".join(str(p) for p in parts)


def _make_boundary_fallback(fallback_days):
    """Deterministic boundary verdict: split when gap >= TRIP_GAP_FALLBACK_DAYS."""
    def fallback(payload):
        gap = payload["gap_days"]
        decision = "split" if gap >= fallback_days else "merge"
        return {"decision": decision, "reason": f"fallback: gap {gap:.1f}d vs {fallback_days}d"}
    return fallback


def _make_name_fallback():
    """Deterministic title: use the mechanical title precomputed in the payload."""
    def fallback(payload):
        return {"title": payload["fallback_title"]}
    return fallback

# ---------------------------------------------------------------------------
# Simple in-process decision cache (previously Escalator)
# ---------------------------------------------------------------------------

class _DecisionCache:
    """Applies deterministic fallbacks and caches results for idempotent re-runs."""

    def __init__(self):
        self._cache = {}
        self.last_source = "fallback"

    def decide(self, cache_key, payload, fallback_fn):
        if cache_key in self._cache:
            self.last_source = "cache"
            return self._cache[cache_key]
        verdict = fallback_fn(payload)
        self._cache[cache_key] = verdict
        self.last_source = "fallback"
        return verdict


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def _cluster_summary(cluster):
    cities = []
    for a in cluster:
        if a.city and a.city not in cities:
            cities.append(a.city)
    return {
        "cities": cities,
        "dates": [str(cluster[0].taken_at), str(cluster[-1].taken_at)],
        "count": len(cluster),
        "country": cluster[-1].country if cluster[-1].country else cluster[0].country,
    }


def _in_window(dt, window):
    if window is None or dt is None:
        return window is None
    since, until = window
    if since is not None and dt < since:
        return False
    if until is not None and dt > until:
        return False
    return True


def build_plan(assets, config, window=None, existing_keys=None):
    """Build a dry-run Plan.

    When `window` is a (since, until) datetime pair, assets outside it may still
    be fetched (a buffer lets edge trips cluster correctly), but only trips with
    at least one in-window asset are kept.

    `existing_keys` is a set of trip keys that already have albums — these are
    separated into `plan.existing_trips` so the renderer can show them differently.
    """
    existing_keys = existing_keys or set()
    classified = classify_assets(assets, config)
    away = sorted(classified.away, key=lambda a: a.taken_at)

    clusters = provisional_cut(away, config)
    bs = boundaries(clusters, config)

    cache = _DecisionCache()
    boundary_fallback = _make_boundary_fallback(config.trip_gap_fallback_days)
    verdicts = {}
    decisions = []
    for b in bs:
        if b.hard:
            continue  # hard split: never needs adjudication
        left, right = clusters[b.index], clusters[b.index + 1]
        left_country = left[-1].country
        right_country = right[0].country
        payload = {
            "left": _cluster_summary(left),
            "right": _cluster_summary(right),
            "gap_days": b.gap_days,
            "approx_distance_km": b.approx_distance_km,
            "cause": b.cause,
            "outlier": b.outlier,
        }
        key = _boundary_cache_key(b, left_country, right_country)
        verdict = cache.decide(key, payload, boundary_fallback)
        verdicts[b.index] = verdict["decision"]
        decisions.append({
            "left_cities": payload["left"]["cities"],
            "right_cities": payload["right"]["cities"],
            "gap_days": b.gap_days,
            "cause": b.cause,
            "decision": verdict["decision"],
            "reason": verdict.get("reason", ""),
            "source": cache.last_source,
        })

    trips = resolve(clusters, bs, verdicts)

    if window is not None:
        trips = [t for t in trips if any(_in_window(a.taken_at, window) for a in t.assets)]

    name_fallback = _make_name_fallback()
    for trip in trips:
        bare = fallback_title(trip.assets, "")  # no prefix; planner prepends below
        payload = {
            "cities_in_order": [a.city for a in trip.assets if a.city],
            "date_range": [str(trip.start), str(trip.end)],
            "count": len(trip.assets),
            "fallback_title": bare,
        }
        verdict = cache.decide(trip.key, payload, name_fallback)
        trip.title = config.album_prefix + verdict["title"]

    new_trips = [t for t in trips if t.key not in existing_keys]
    existing_trips = [t for t in trips if t.key in existing_keys]

    # Count no-location assets that fall within new trip date ranges —
    # useful for display; no action is taken on them.
    _REVIEW_BUFFER = timedelta(days=1)
    review_count = 0
    if new_trips:
        no_loc = [a for a in assets if not a.has_name and not a.has_coords]
        for a in no_loc:
            if a.taken_at and any(
                t.start - _REVIEW_BUFFER <= a.taken_at <= t.end + _REVIEW_BUFFER
                for t in new_trips
            ):
                review_count += 1

    return Plan(
        trips=new_trips,
        existing_trips=existing_trips,
        review_count=review_count,
        home_count=classified.home_count,
        skip_count=classified.skip_count,
        decisions=decisions,
    )
