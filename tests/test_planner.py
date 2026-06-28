from trip_albums.planner import build_plan
from trip_albums.config import load_config
from tests.fixtures import asset
from tests.test_config import base_env


def cfg(**o):
    return load_config(base_env(**o))


def day(n):
    return f"2025-04-{n:02d}T12:00:00Z"


def test_two_separated_trips_produce_two_albums():
    assets = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Rome", country="Italy", taken=day(20)),  # huge gap -> hard split
    ]
    plan = build_plan(assets, cfg())
    assert len(plan.trips) == 2


def test_ambiguous_boundary_merges_below_fallback():
    # 3-day gap < TRIP_GAP_FALLBACK_DAYS(4) -> fallback merges to one trip.
    assets = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Porto", country="Portugal", taken=day(4)),
    ]
    plan = build_plan(assets, cfg())
    assert len(plan.trips) == 1


def test_ambiguous_boundary_splits_above_fallback():
    # 5-day gap > TRIP_GAP_FALLBACK_DAYS(4) -> fallback splits to two trips.
    assets = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Porto", country="Portugal", taken=day(6)),
    ]
    plan = build_plan(assets, cfg())
    assert len(plan.trips) == 2


def test_no_location_assets_counted_near_trips():
    assets = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="noloc", city=None, lat=None, lon=None, taken=day(2)),
    ]
    plan = build_plan(assets, cfg())
    assert plan.review_count == 1


def test_title_prefixed():
    assets = [asset(id="a", city="Lisbon", country="Portugal", taken=day(1))]
    plan = build_plan(assets, cfg())
    assert plan.trips[0].title.startswith("Trip — ")


def _dt(s):
    from datetime import datetime, timezone
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_window_drops_trips_entirely_outside_range():
    assets = [
        asset(id="old", city="Lisbon", country="Portugal", taken=day(1)),   # buffer trip
        asset(id="new", city="Rome", country="Italy", taken=day(25)),       # in-window trip
    ]
    window = (_dt(day(20)), _dt(day(30)))
    plan = build_plan(assets, cfg(), window=window)
    assert [t.key for t in plan.trips] == ["new"]


def test_window_keeps_trip_straddling_the_edge():
    assets = [
        asset(id="s1", city="Lisbon", country="Portugal", taken=day(19)),
        asset(id="s2", city="Lisbon", country="Portugal", taken=f"2025-04-19T18:00:00Z"),
        asset(id="s3", city="Lisbon", country="Portugal", taken=f"2025-04-20T18:00:00Z"),
    ]
    window = (_dt(day(20)), _dt(day(30)))
    plan = build_plan(assets, cfg(), window=window)
    assert len(plan.trips) == 1
    assert "s3" in plan.trips[0].asset_ids


def test_window_filters_review_count_by_trip_overlap():
    """No-location assets are only counted when they overlap a trip's date range."""
    assets = [
        asset(id="trip1", city="Lisbon", country="Portugal", taken=day(22)),
        asset(id="rev_old", city=None, lat=None, lon=None, taken=day(1)),
        asset(id="rev_near", city=None, lat=None, lon=None, taken=day(22)),
    ]
    window = (_dt(day(20)), _dt(day(30)))
    plan = build_plan(assets, cfg(), window=window)
    # rev_near overlaps the trip; rev_old does not
    assert plan.review_count == 1
