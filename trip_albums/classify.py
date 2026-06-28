"""Classify each asset into exactly one of: review, home, away (spec §5)."""

from dataclasses import dataclass

from .geo import haversine_km


@dataclass
class Classified:
    away: list  # list[Asset] to feed into clustering
    review_asset_ids: list  # no-location + coords-only-without-home-coords
    home_count: int


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


def classify_one(asset, config):
    """Return "review" | "home" | "away" for a single asset (branch order = spec §5)."""
    # 1. No location at all.
    if not asset.has_name and not asset.has_coords:
        return "review"

    # 2. Home by name (guarded by country when configured).
    if _name_matches_home(asset, config) and _passes_country_guard(asset, config):
        return "home"

    # 3. Coordinates-only (coords but no usable name).
    if asset.has_coords and not asset.has_name:
        if config.has_home_coords:
            dist = haversine_km(asset.lat, asset.lon, config.home_lat, config.home_lon)
            return "home" if dist <= config.home_radius_km else "away"
        return "review"

    # 4. Named, not home.
    return "away"


def classify_assets(assets, config):
    away, review_ids, home_count = [], [], 0
    for asset in assets:
        verdict = classify_one(asset, config)
        if verdict == "away":
            away.append(asset)
        elif verdict == "review":
            review_ids.append(asset.id)
        else:
            home_count += 1
    return Classified(away=away, review_asset_ids=review_ids, home_count=home_count)
