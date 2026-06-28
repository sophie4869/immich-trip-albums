from datetime import datetime, timezone

from trip_albums.models import Asset
from tests.fixtures import api_asset


def test_from_api_basic():
    a = Asset.from_api(api_asset(city="Lisbon", country="Portugal", lat=38.7, lon=-9.1))
    assert a.id == "a1"
    assert a.type == "IMAGE"
    assert a.city == "Lisbon"
    assert a.country == "Portugal"
    assert a.lat == 38.7
    assert a.lon == -9.1
    assert a.taken_at == datetime(2025, 4, 1, 12, 0, tzinfo=timezone.utc)


def test_from_api_empty_strings_become_none():
    a = Asset.from_api(api_asset(city="", state=""))
    assert a.city is None
    assert a.state is None


def test_from_api_missing_exif_location_is_none():
    a = Asset.from_api(api_asset())
    assert a.city is None and a.state is None and a.country is None
    assert a.lat is None and a.lon is None


def test_from_api_falls_back_to_file_created_at():
    raw = api_asset()
    raw["exifInfo"]["dateTimeOriginal"] = None
    a = Asset.from_api(raw)
    assert a.taken_at == datetime(2025, 4, 1, 12, 0, tzinfo=timezone.utc)


def test_from_api_handles_missing_exifinfo_entirely():
    a = Asset.from_api({"id": "x", "type": "VIDEO"})
    assert a.id == "x" and a.type == "VIDEO"
    assert a.city is None and a.lat is None and a.taken_at is None
