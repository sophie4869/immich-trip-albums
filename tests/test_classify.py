from trip_albums.classify import classify_one, classify_assets
from trip_albums.config import load_config
from tests.fixtures import asset
from tests.test_config import base_env


def cfg(**overrides):
    return load_config(base_env(**overrides))


def test_no_location_is_review():
    a = asset(city=None, state=None, lat=None, lon=None)
    assert classify_one(a, cfg()) == "review"


def test_name_match_home():
    a = asset(city="Paris", country="France")
    assert classify_one(a, cfg()) == "home"


def test_state_match_home():
    a = asset(city="Versailles", state="Île-de-France", country="France")
    assert classify_one(a, cfg(HOME_STATES="Île-de-France")) == "home"


def test_country_guard_rejects_same_named_foreign_city():
    # Paris, Texas should NOT be home for a Paris, France resident.
    a = asset(city="Paris", country="United States")
    assert classify_one(a, cfg(HOME_COUNTRIES="France")) == "away"


def test_country_guard_passes_when_asset_country_none():
    a = asset(city="Paris", country=None)
    assert classify_one(a, cfg(HOME_COUNTRIES="France")) == "home"


def test_named_not_home_is_away():
    a = asset(city="Lisbon", country="Portugal")
    assert classify_one(a, cfg()) == "away"


def test_coords_only_inside_radius_is_home():
    a = asset(city=None, state=None, lat=48.86, lon=2.35)  # ~central Paris
    assert classify_one(a, cfg(HOME_LAT="48.8566", HOME_LON="2.3522", HOME_RADIUS_KM="25")) == "home"


def test_coords_only_outside_radius_is_away():
    a = asset(city=None, state=None, lat=43.30, lon=5.37)  # Marseille
    assert classify_one(a, cfg(HOME_LAT="48.8566", HOME_LON="2.3522", HOME_RADIUS_KM="25")) == "away"


def test_coords_only_without_home_coords_is_review():
    a = asset(city=None, state=None, lat=43.30, lon=5.37)
    assert classify_one(a, cfg()) == "review"


def test_classify_assets_partitions_and_counts():
    assets = [
        asset(id="home1", city="Paris", country="France"),
        asset(id="away1", city="Lisbon", country="Portugal"),
        asset(id="rev1", city=None, lat=None, lon=None),
    ]
    result = classify_assets(assets, cfg())
    assert [a.id for a in result.away] == ["away1"]
    assert result.review_asset_ids == ["rev1"]
    assert result.home_count == 1
