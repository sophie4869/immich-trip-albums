"""Classify each asset into exactly one of: home, away, skip (spec §5)."""

from dataclasses import dataclass

from .geo import haversine_km


@dataclass
class Classified:
    away: list  # list[Asset] to feed into clustering
    home_count: int
    skip_count: int = 0  # no-location assets and screenshots without location


def _name_matches_home(asset, config):
    city = asset.city.lower() if asset.city else None
    state = asset.state.lower() if asset.state else None
    return (city is not None and city in config.home_cities) or (
        state is not None and state in config.home_states
    )


def _passes_country_guard(asset, config):
    # Guard only applies when HOME_COUNTRIES is set AND the asset has a country.
    if not config.home_countries or asset.country is None:
        return True
    return asset.country.lower() in config.home_countries


_SCREENSHOT_MARKERS = ("screenshot", "screen shot", "screen_shot", "screens/")


def _is_screenshot(asset):
    if asset.original_path:
        lower = asset.original_path.lower()
        return any(m in lower for m in _SCREENSHOT_MARKERS)
    return False


def classify_one(asset, config):
    """Return "home" | "away" | "skip" for a single asset (branch order = spec §5).

    Assets with no usable location are silently skipped (counted in skip_count).
    """
    # 0. Screenshots without location — not useful for trip albums.
    if not asset.has_name and not asset.has_coords and _is_screenshot(asset):
        return "skip"

    # 1. No location at all — skip silently.
    if not asset.has_name and not asset.has_coords:
        return "skip"

    # 2. Home by name (guarded by country when configured).
    if _name_matches_home(asset, config) and _passes_country_guard(asset, config):
        return "home"

    # 3. Coordinates-only (coords but no usable name).
    if asset.has_coords and not asset.has_name:
        if config.has_home_coords:
            dist = haversine_km(asset.lat, asset.lon, config.home_lat, config.home_lon)
            return "home" if dist <= config.home_radius_km else "away"
        return "skip"

    # 4. Named, not home.
    return "away"


def classify_assets(assets, config):
    away, home_count, skip_count = [], 0, 0
    for asset in assets:
        verdict = classify_one(asset, config)
        if verdict == "away":
            away.append(asset)
        elif verdict == "skip":
            skip_count += 1
        else:
            home_count += 1
    return Classified(away=away, home_count=home_count, skip_count=skip_count)
