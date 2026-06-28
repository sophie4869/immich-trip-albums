"""Provisional-cut-then-resolve trip clustering (spec §6)."""

from .geo import centroid, haversine_km
from .models import Boundary, Trip
from .naming import trip_key


def _gap_days(left_asset, right_asset):
    return (right_asset.taken_at - left_asset.taken_at).total_seconds() / 86400.0


def _country_changed(left_asset, right_asset):
    lc, rc = left_asset.country, right_asset.country
    return lc is not None and rc is not None and lc != rc


def provisional_cut(away_sorted, config):
    """Cut between adjacent assets iff gap >= GAP_MIN or country changes (both non-None).

    `away_sorted` must be sorted by taken_at ascending.
    """
    if not away_sorted:
        return []
    clusters = [[away_sorted[0]]]
    for prev, cur in zip(away_sorted, away_sorted[1:]):
        cut = _gap_days(prev, cur) >= config.gap_min_days or _country_changed(prev, cur)
        if cut:
            clusters.append([cur])
        else:
            clusters[-1].append(cur)
    return clusters


def _cluster_centroid(cluster):
    points = [(a.lat, a.lon) for a in cluster if a.lat is not None and a.lon is not None]
    return centroid(points)


def boundaries(clusters, config):
    """Build a Boundary record for each adjacent cluster pair."""
    out = []
    for i in range(len(clusters) - 1):
        left, right = clusters[i], clusters[i + 1]
        la, ra = left[-1], right[0]  # the assets straddling the boundary
        gap = _gap_days(la, ra)
        in_band = gap >= config.gap_min_days
        changed = _country_changed(la, ra)
        if in_band and changed:
            cause = "both"
        elif changed:
            cause = "country_change"
        else:
            cause = "middle_band"

        lc, rc = _cluster_centroid(left), _cluster_centroid(right)
        dist = haversine_km(lc[0], lc[1], rc[0], rc[1]) if lc and rc else None

        out.append(Boundary(
            index=i,
            gap_days=gap,
            cause=cause,
            hard=gap >= config.gap_max_days,
            outlier=len(left) <= config.outlier_max_assets or len(right) <= config.outlier_max_assets,
            approx_distance_km=dist,
            left_id=trip_key(left),
            right_id=trip_key(right),
        ))
    return out


def resolve(clusters, boundary_list, verdicts):
    """Combine clusters into Trips.

    A boundary splits when it is hard, or when its soft verdict is "split".
    `verdicts` maps a soft boundary's index -> "merge" | "split".
    """
    by_index = {b.index: b for b in boundary_list}
    trips = []
    current = list(clusters[0]) if clusters else []
    for i in range(len(clusters) - 1):
        b = by_index[i]
        split = b.hard or verdicts.get(i) == "split"
        if split:
            trips.append(_make_trip(current))
            current = list(clusters[i + 1])
        else:
            current.extend(clusters[i + 1])
    if current:
        trips.append(_make_trip(current))
    return trips


def _make_trip(assets):
    ordered = sorted(assets, key=lambda a: a.taken_at)
    return Trip(key=trip_key(ordered), assets=ordered)
