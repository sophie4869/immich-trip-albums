"""Builders for test data: raw Immich API dicts and normalized Assets."""

from datetime import datetime, timezone

from trip_albums.models import Asset


def api_asset(id="a1", type="IMAGE", city=None, state=None, country=None,
              lat=None, lon=None, taken="2025-04-01T12:00:00.000Z"):
    """A raw Immich asset dict as returned by /search/metadata with withExif."""
    return {
        "id": id,
        "type": type,
        "exifInfo": {
            "city": city,
            "state": state,
            "country": country,
            "latitude": lat,
            "longitude": lon,
            "dateTimeOriginal": taken,
            "fileCreatedAt": taken,
        },
    }


def asset(id="a1", type="IMAGE", city=None, state=None, country=None,
          lat=None, lon=None, taken="2025-04-01T12:00:00.000Z"):
    """A normalized Asset, built directly (skips from_api parsing)."""
    return Asset(
        id=id, type=type, city=city, state=state, country=country,
        lat=lat, lon=lon, taken_at=_dt(taken),
    )


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
