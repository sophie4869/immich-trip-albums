from trip_albums.cluster import provisional_cut, boundaries, resolve
from trip_albums.config import load_config
from tests.fixtures import asset
from tests.test_config import base_env


def cfg(**overrides):
    # GAP_MIN=1.5, GAP_MAX=6, FALLBACK=4, OUTLIER=2 by default.
    return load_config(base_env(**overrides))


def day(n, hour=12):
    return f"2025-04-{n:02d}T{hour:02d}:00:00Z"


# --- provisional_cut --------------------------------------------------------

def test_middle_band_gap_creates_two_clusters():
    away = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Lisbon", country="Portugal", taken=day(4)),  # 3-day gap
    ]
    clusters = provisional_cut(away, cfg())
    assert [[x.id for x in c] for c in clusters] == [["a"], ["b"]]


def test_sub_gap_min_same_country_stays_merged():
    away = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Lisbon", country="Portugal", taken=day(1, hour=18)),  # 0.25 day
    ]
    clusters = provisional_cut(away, cfg())
    assert [[x.id for x in c] for c in clusters] == [["a", "b"]]


def test_small_gap_country_change_creates_boundary():
    away = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Madrid", country="Spain", taken=day(1, hour=18)),  # 0.25 day
    ]
    clusters = provisional_cut(away, cfg())
    assert len(clusters) == 2


# --- boundaries -------------------------------------------------------------

def test_middle_band_boundary_is_soft():
    away = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Lisbon", country="Portugal", taken=day(4)),
    ]
    clusters = provisional_cut(away, cfg())
    (b,) = boundaries(clusters, cfg())
    assert b.cause == "middle_band"
    assert b.hard is False
    assert 2.9 < b.gap_days < 3.1
    assert b.left_id == "a" and b.right_id == "b"


def test_country_change_small_gap_boundary_is_soft():
    away = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Madrid", country="Spain", taken=day(1, hour=18)),
    ]
    (b,) = boundaries(provisional_cut(away, cfg()), cfg())
    assert b.cause == "country_change"
    assert b.hard is False


def test_large_gap_country_change_is_hard_split():
    away = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Madrid", country="Spain", taken=day(10)),  # 9-day gap
    ]
    (b,) = boundaries(provisional_cut(away, cfg()), cfg())
    assert b.hard is True  # >= GAP_MAX regardless of country


def test_both_cause_when_middle_band_and_country_change():
    away = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Madrid", country="Spain", taken=day(4)),  # 3-day gap + country change
    ]
    (b,) = boundaries(provisional_cut(away, cfg()), cfg())
    assert b.cause == "both"


def test_outlier_flag_is_annotation_not_a_cut():
    # A single-asset cluster across a middle-band gap: boundary exists (gap), outlier flagged.
    away = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="solo", city="Sintra", country="Portugal", taken=day(4)),
    ]
    (b,) = boundaries(provisional_cut(away, cfg()), cfg())
    assert b.outlier is True

    # But a sub-GAP_MIN same-country single shot creates NO boundary at all.
    away2 = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="solo", city="Lisbon", country="Portugal", taken=day(1, hour=18)),
    ]
    assert boundaries(provisional_cut(away2, cfg()), cfg()) == []


def test_distance_none_when_cluster_lacks_coords():
    away = [
        asset(id="a", city="Lisbon", country="Portugal", lat=None, lon=None, taken=day(1)),
        asset(id="b", city="Porto", country="Portugal", lat=41.1, lon=-8.6, taken=day(4)),
    ]
    (b,) = boundaries(provisional_cut(away, cfg()), cfg())
    assert b.approx_distance_km is None


def test_distance_computed_when_both_have_coords():
    away = [
        asset(id="a", city="Lisbon", country="Portugal", lat=38.72, lon=-9.14, taken=day(1)),
        asset(id="b", city="Porto", country="Portugal", lat=41.15, lon=-8.61, taken=day(4)),
    ]
    (b,) = boundaries(provisional_cut(away, cfg()), cfg())
    assert b.approx_distance_km is not None and b.approx_distance_km > 250


# --- resolve ----------------------------------------------------------------

def make_two_clusters():
    away = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Porto", country="Portugal", taken=day(4)),
    ]
    c = cfg()
    clusters = provisional_cut(away, c)
    bs = boundaries(clusters, c)
    return clusters, bs


def test_resolve_soft_merge_yields_one_trip():
    clusters, bs = make_two_clusters()
    trips = resolve(clusters, bs, {bs[0].index: "merge"})
    assert len(trips) == 1
    assert trips[0].asset_ids == ["a", "b"]
    assert trips[0].key == "a"


def test_resolve_soft_split_yields_two_trips():
    clusters, bs = make_two_clusters()
    trips = resolve(clusters, bs, {bs[0].index: "split"})
    assert len(trips) == 2
    assert [t.key for t in trips] == ["a", "b"]


def test_resolve_hard_always_splits_ignoring_verdict():
    away = [
        asset(id="a", city="Lisbon", country="Portugal", taken=day(1)),
        asset(id="b", city="Porto", country="Portugal", taken=day(10)),  # hard
    ]
    c = cfg()
    clusters = provisional_cut(away, c)
    bs = boundaries(clusters, c)
    trips = resolve(clusters, bs, {bs[0].index: "merge"})  # verdict ignored for hard
    assert len(trips) == 2
