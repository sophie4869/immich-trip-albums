"""Orchestrate the deterministic pipeline + LLM seam into a Plan (spec)."""

from .adjudicate import (
    BOUNDARY_SCHEMA,
    NAME_SCHEMA,
    boundary_cache_key,
    make_boundary_fallback,
    make_name_fallback,
)
from .classify import classify_assets
from .cluster import boundaries, provisional_cut, resolve
from .models import Plan
from .naming import fallback_title


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


def build_plan(assets, config, escalator):
    classified = classify_assets(assets, config)
    away = sorted(classified.away, key=lambda a: a.taken_at)

    clusters = provisional_cut(away, config)
    bs = boundaries(clusters, config)

    boundary_fallback = make_boundary_fallback(config.trip_gap_fallback_days)
    verdicts = {}
    decisions = []
    for b in bs:
        if b.hard:
            continue  # hard split: never escalated
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
        key = boundary_cache_key(b, left_country, right_country)
        verdict = escalator.escalate("resolve_boundary", payload, key, BOUNDARY_SCHEMA, boundary_fallback)
        verdicts[b.index] = verdict["decision"]
        decisions.append({
            "left_cities": payload["left"]["cities"],
            "right_cities": payload["right"]["cities"],
            "gap_days": b.gap_days,
            "cause": b.cause,
            "decision": verdict["decision"],
            "reason": verdict.get("reason", ""),
            "source": escalator.last["applied"] if escalator.last else "fallback",
        })

    trips = resolve(clusters, bs, verdicts)

    name_fallback = make_name_fallback()
    for trip in trips:
        bare = fallback_title(trip.assets, "")  # no prefix; planner prepends below
        payload = {
            "cities_in_order": [a.city for a in trip.assets if a.city],
            "date_range": [str(trip.start), str(trip.end)],
            "count": len(trip.assets),
            "fallback_title": bare,
        }
        verdict = escalator.escalate("name_trip", payload, trip.key, NAME_SCHEMA, name_fallback)
        trip.title = config.album_prefix + verdict["title"]
        applied = escalator.last["applied"] if escalator.last else "fallback"
        trip.title_source = {"verdict": "llm", "cache": "cache"}.get(applied, "fallback")

    return Plan(
        trips=trips,
        review_asset_ids=classified.review_asset_ids,
        home_count=classified.home_count,
        decisions=decisions,
    )
