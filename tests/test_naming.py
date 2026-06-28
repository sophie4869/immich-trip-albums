from trip_albums.naming import trip_key, fallback_title
from tests.fixtures import asset


def test_trip_key_is_earliest_asset_id_regardless_of_order():
    assets = [
        asset(id="late", taken="2025-04-05T10:00:00Z"),
        asset(id="early", taken="2025-04-01T10:00:00Z"),
        asset(id="mid", taken="2025-04-03T10:00:00Z"),
    ]
    assert trip_key(assets) == "early"


def test_fallback_title_single_city():
    assets = [asset(city="Lisbon", taken="2025-04-01T10:00:00Z")]
    assert fallback_title(assets, "Trip — ") == "Trip — Lisbon, Apr 2025"


def test_fallback_title_two_cities_joined():
    assets = [
        asset(id="a", city="Lisbon", taken="2025-04-01T10:00:00Z"),
        asset(id="b", city="Lisbon", taken="2025-04-02T10:00:00Z"),
        asset(id="c", city="Porto", taken="2025-04-03T10:00:00Z"),
    ]
    title = fallback_title(assets, "Trip — ")
    assert title == "Trip — Lisbon & Porto, Apr 2025"


def test_fallback_title_unknown_when_no_cities():
    assets = [asset(city=None, lat=1.0, lon=2.0, taken="2025-04-01T10:00:00Z")]
    assert fallback_title(assets, "Trip — ") == "Trip — Unknown area, Apr 2025"


def test_fallback_title_caps_at_two_cities_by_frequency():
    assets = [
        asset(id="a", city="Rome", taken="2025-05-01T10:00:00Z"),
        asset(id="b", city="Rome", taken="2025-05-02T10:00:00Z"),
        asset(id="c", city="Milan", taken="2025-05-03T10:00:00Z"),
        asset(id="d", city="Naples", taken="2025-05-04T10:00:00Z"),
    ]
    # Rome (x2) is most frequent; second is the next most frequent in first-seen order.
    title = fallback_title(assets, "Trip — ")
    assert title.startswith("Trip — Rome & ")
    assert "Naples" not in title or "Milan" not in title  # only two cities shown
