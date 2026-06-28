"""Configuration loading and validation from an environment mapping."""

from dataclasses import dataclass
from typing import Optional


class ConfigError(Exception):
    """Raised when configuration is missing or inconsistent."""


@dataclass
class Config:
    immich_url: str
    immich_api_key: str
    home_cities: list
    home_states: list
    home_countries: list
    home_lat: Optional[float]
    home_lon: Optional[float]
    home_radius_km: float
    gap_min_days: float
    gap_max_days: float
    trip_gap_fallback_days: float
    outlier_max_assets: int
    review_tag: str
    album_prefix: str
    anthropic_api_key: Optional[str]
    llm_enabled: bool

    @property
    def has_home_coords(self):
        return self.home_lat is not None and self.home_lon is not None


def _list(env, key):
    raw = env.get(key, "") or ""
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _float(env, key, default=None):
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc


def _int(env, key, default):
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


def load_config(env, no_llm=False):
    """Build a validated Config from an env-like mapping (os.environ or .env merge)."""
    url = (env.get("IMMICH_URL") or "").strip().rstrip("/")
    if not url:
        raise ConfigError("IMMICH_URL is required")
    api_key = (env.get("IMMICH_API_KEY") or "").strip()
    if not api_key:
        raise ConfigError("IMMICH_API_KEY is required")

    home_lat = _float(env, "HOME_LAT")
    home_lon = _float(env, "HOME_LON")
    if (home_lat is None) != (home_lon is None):
        raise ConfigError("HOME_LAT and HOME_LON must be set together (or both unset)")

    gap_min = _float(env, "GAP_MIN_DAYS", 1.5)
    gap_max = _float(env, "GAP_MAX_DAYS", 6.0)
    fallback = _float(env, "TRIP_GAP_FALLBACK_DAYS", 4.0)
    if not (gap_min <= fallback <= gap_max):
        raise ConfigError(
            f"Require GAP_MIN_DAYS <= TRIP_GAP_FALLBACK_DAYS <= GAP_MAX_DAYS "
            f"(got {gap_min}, {fallback}, {gap_max})"
        )

    anthropic_key = (env.get("ANTHROPIC_API_KEY") or "").strip() or None

    return Config(
        immich_url=url,
        immich_api_key=api_key,
        home_cities=_list(env, "HOME_CITIES"),
        home_states=_list(env, "HOME_STATES"),
        home_countries=_list(env, "HOME_COUNTRIES"),
        home_lat=home_lat,
        home_lon=home_lon,
        home_radius_km=_float(env, "HOME_RADIUS_KM", 25.0),
        gap_min_days=gap_min,
        gap_max_days=gap_max,
        trip_gap_fallback_days=fallback,
        outlier_max_assets=_int(env, "OUTLIER_MAX_ASSETS", 2),
        review_tag=(env.get("REVIEW_TAG") or "needs-location-review").strip(),
        album_prefix=env.get("ALBUM_PREFIX", "Trip — "),
        anthropic_api_key=anthropic_key,
        llm_enabled=bool(anthropic_key) and not no_llm,
    )
