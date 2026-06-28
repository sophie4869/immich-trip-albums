"""Core data structures and raw-API normalization."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


def _clean(value):
    """Normalize empty/blank strings to None; pass other values through."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _parse_dt(value):
    if not value:
        return None
    # Immich emits ISO-8601 with a trailing 'Z'; fromisoformat wants +00:00.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class Asset:
    """A normalized Immich asset with just the fields this tool cares about."""

    id: str
    type: str
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    taken_at: Optional[datetime] = None
    original_path: Optional[str] = None

    @property
    def has_coords(self):
        return self.lat is not None and self.lon is not None

    @property
    def has_name(self):
        return self.city is not None or self.state is not None

    @classmethod
    def from_api(cls, raw):
        exif = raw.get("exifInfo") or {}
        lat = exif.get("latitude")
        lon = exif.get("longitude")
        taken = exif.get("dateTimeOriginal") or exif.get("fileCreatedAt")
        return cls(
            id=raw.get("id"),
            type=raw.get("type"),
            city=_clean(exif.get("city")),
            state=_clean(exif.get("state")),
            country=_clean(exif.get("country")),
            lat=float(lat) if lat is not None else None,
            lon=float(lon) if lon is not None else None,
            taken_at=_parse_dt(taken),
            original_path=raw.get("originalPath"),
        )


@dataclass
class Boundary:
    """A provisional boundary between two adjacent clusters (cluster index .. index+1)."""

    index: int  # boundary sits between clusters[index] and clusters[index + 1]
    gap_days: float
    cause: str  # "middle_band" | "country_change" | "both"
    hard: bool  # gap_days >= GAP_MAX -> always split
    outlier: bool  # either side <= OUTLIER_MAX_ASSETS (annotation only)
    approx_distance_km: Optional[float]
    left_id: str  # earliest-asset id of the left cluster (stable identity)
    right_id: str  # earliest-asset id of the right cluster


@dataclass
class Trip:
    """A final trip: a contiguous run of away-assets that becomes one album."""

    key: str  # trip_key = earliest asset id
    assets: list  # list[Asset], chronologically sorted
    title: Optional[str] = None
    decisions: list = field(default_factory=list)  # boundary verdicts for render/audit

    @property
    def asset_ids(self):
        return [a.id for a in self.assets]

    @property
    def start(self):
        return self.assets[0].taken_at if self.assets else None

    @property
    def end(self):
        return self.assets[-1].taken_at if self.assets else None

    @property
    def cities(self):
        return [a.city for a in self.assets if a.city]


@dataclass
class Plan:
    """The full dry-run plan: trips to album."""

    trips: list = field(default_factory=list)  # list[Trip]
    existing_trips: list = field(default_factory=list)  # list[Trip] already albumed
    review_count: int = 0  # no-location assets near a trip (display only)
    home_count: int = 0
    skip_count: int = 0  # assets without location data
    decisions: list = field(default_factory=list)  # all boundary decision records
    warnings: list = field(default_factory=list)
